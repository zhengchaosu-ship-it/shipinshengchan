"""寻帧到独立剪映自动合成脚本的薄适配层。"""
from contextlib import contextmanager
from pathlib import Path
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
import random
import re
import subprocess
import time

from jianying_auto.source_catalog import CATEGORIES, read_catalog


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[2]
MODULE_DIR = PROJECT_ROOT / "jianying_auto"
SCRIPT = MODULE_DIR / "jianying_auto.py"
PROJECT_CONFIG = PROJECT_ROOT / "config.json"
MODULE_CONFIG = MODULE_DIR / "config.json"
SOURCE_CONFIG = MODULE_DIR / "jianying_source_folders.json"
WEB_CONFIG = HERE / "search_config.json"
LOCK_FILE = MODULE_DIR / "runtime" / "generation.lock"
BATCH_ROOT = MODULE_DIR / "runtime" / "batches"
FIXED_MODES = ("坐诊", "手法", "流量手法")
SOURCE_CATEGORIES = CATEGORIES
TOKEN = r"(?:流量|引流|手法|坐诊|收尾)(?:[1-9]\d*)?"
INDEXED_TOKEN = r"(?:流量|引流|手法|坐诊|收尾)[1-9]\d*"
COMBINATION = re.compile(rf"^(?:{INDEXED_TOKEN}|{TOKEN}(?:\+{TOKEN})+)$")
SUCCESS_NAME = re.compile(r"草稿名:\s*(.+?)\s*$", re.MULTILINE)
SELECTED_JSON = re.compile(r"^\[选中素材JSON\]\s*(\[.*\])\s*$", re.MULTILINE)


class GenerationBusy(RuntimeError):
    pass


def enabled():
    try:
        return bool(_read_json(WEB_CONFIG).get("jianying_auto_enabled", False))
    except (OSError, ValueError, TypeError):
        return False


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def validate_mode(value):
    mode = str(value or "").strip().replace("＋", "+")
    if mode in FIXED_MODES or COMBINATION.fullmatch(mode):
        return mode
    raise ValueError(
        "模式格式不正确。请选择坐诊、手法、流量手法，或输入例如“引流1+手法2+收尾1”。")


def validate_generation_count(value):
    """生成数量只接受1～10的整数。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("生成数量必须是1～10的整数。")
    count = value
    if not 1 <= count <= 10:
        raise ValueError("生成数量必须是1～10的整数。")
    return count


def source_summary():
    """只扫描配置中的4个目录，返回网页显示所需的路径和数量。"""
    catalog = read_catalog(SOURCE_CONFIG)
    return {
        category: {
            "folder": str(catalog[category]["folder"]),
            "count": len(catalog[category]["videos"]),
        }
        for category in SOURCE_CATEGORIES
    }


def parse_slots(slots):
    """把5个UI Slot压缩为连续的1～5段，并拒绝中间断层。"""
    values = [str(value or "无").strip() for value in slots]
    if len(values) != 5:
        raise ValueError("起号自动合成页面必须提供5个选择框。")
    if values[0] not in SOURCE_CATEGORIES:
        raise ValueError("第1段必须选择素材类型。")
    sequence = []
    reached_empty = False
    empty_index = None
    for index, value in enumerate(values, 1):
        if value == "无":
            reached_empty = True
            if empty_index is None:
                empty_index = index
            continue
        if value not in SOURCE_CATEGORIES:
            raise ValueError("第%d段包含未知素材分类：%s" % (index, value))
        if reached_empty:
            raise ValueError("请按顺序选择片段，第%d段为空时，后续片段不能再选择。" % empty_index)
        sequence.append(value)
    return sequence


def plan_sequence(categories, rng=None):
    """为1～5个连续位置选择具体文件；同类先无放回，素材不足才重复。"""
    sequence = [str(category).strip() for category in categories]
    if not 1 <= len(sequence) <= 5:
        raise ValueError("起号自动合成必须选择1～5个片段。")
    invalid = [category for category in sequence if category not in SOURCE_CATEGORIES]
    if invalid:
        raise ValueError("未知素材分类：%s" % "、".join(invalid))

    randomizer = rng or random.SystemRandom()
    catalog = read_catalog(SOURCE_CONFIG)
    requested = Counter(sequence)
    warnings = []
    queues = {}
    for category in SOURCE_CATEGORIES:
        pool = list(catalog[category]["videos"])
        if requested[category] and not pool:
            raise RuntimeError("%s 素材目录没有可用视频：%s" % (
                category, catalog[category]["folder"]))
        queues[category] = list(pool)
        randomizer.shuffle(queues[category])
        if requested[category] > len(pool):
            warnings.append(
                "%s 选择了%d次，但目录只有%d个视频；不足部分将允许重复。" %
                (category, requested[category], len(pool)))

    selected = []
    for index, category in enumerate(sequence, 1):
        pool = catalog[category]["videos"]
        chosen = queues[category].pop() if queues[category] else randomizer.choice(pool)
        selected.append({
            "index": index,
            "category": category,
            "file_name": chosen.name,
            "path": str(chosen),
        })

    tokens = []
    for item in selected:
        pool = catalog[item["category"]]["videos"]
        source_index = pool.index(Path(item["path"])) + 1
        tokens.append("%s%d" % (item["category"], source_index))
    return selected, warnings, "+".join(tokens)


def composition_signature(categories, selected_materials):
    """根据Slot类型和源文件绝对路径生成稳定的组合签名。"""
    payload = []
    for index, (category, item) in enumerate(zip(categories, selected_materials), 1):
        payload.append({
            "index": index,
            "category": str(category),
            "path": os.path.normcase(os.path.abspath(str(item.get("path") or ""))),
        })
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _new_batch_directory(root=None):
    batch_root = Path(root or BATCH_ROOT)
    batch_root.mkdir(parents=True, exist_ok=True)
    base = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = batch_root / base
    suffix = 2
    while candidate.exists():
        candidate = batch_root / ("%s_%02d" % (base, suffix))
        suffix += 1
    candidate.mkdir()
    return candidate


def _verified_materials(planned, generated):
    actual = generated.get("selected_materials") or []
    expected_paths = [os.path.normcase(os.path.abspath(item["path"])) for item in planned]
    actual_paths = [os.path.normcase(os.path.abspath(str(item.get("path") or "")))
                    for item in actual]
    if actual_paths and actual_paths != expected_paths:
        raise RuntimeError("草稿实际素材顺序与网页选择计划不一致，已停止结果确认。")
    return actual or planned


def _notify_progress(callback, current, total, state):
    if callback is None:
        return
    try:
        callback(current, total, state)
    except Exception:
        # 页面进度组件异常不能影响草稿生成与批次记录。
        pass


def _python_executable():
    settings = _read_json(PROJECT_CONFIG)
    value = settings.get("paths", {}).get("python_executable")
    if not value:
        raise RuntimeError("项目 config.json 未配置 paths.python_executable")
    path = Path(value)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    if not path.is_file():
        raise RuntimeError("剪映合成解释器不存在：%s" % path)
    return path


def _draft_root():
    configured = str(_read_json(MODULE_CONFIG).get("jianying_draft_dir") or "").strip()
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = (MODULE_DIR / path).resolve()
        return path
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("LOCALAPPDATA 不可用，无法定位剪映草稿目录")
    for relative in (
        Path("JianyingPro/User Data/Projects/com.lveditor.draft"),
        Path("CapCut/User Data/Projects/com.lveditor.draft"),
    ):
        candidate = Path(local) / relative
        if candidate.is_dir():
            return candidate
    raise RuntimeError("未找到剪映草稿目录，请在 jianying_auto/config.json 中配置")


def _ensure_draft_writable(draft_root):
    """真实写入探针，提前识别继承受限沙箱的Web服务进程。"""
    root = Path(draft_root)
    if not root.is_dir():
        raise RuntimeError("剪映草稿目录不存在：%s" % root)
    probe = root / (".xunframe-write-probe-%d-%d.tmp" % (os.getpid(), time.time_ns()))
    try:
        with open(probe, "x", encoding="ascii") as handle:
            handle.write("xunframe")
        probe.unlink()
    except PermissionError as error:
        try:
            if probe.exists():
                probe.unlink()
        except OSError:
            pass
        raise RuntimeError(
            "当前寻帧服务没有写入剪映草稿目录的权限。请关闭当前8502服务，"
            "再双击项目根目录“启动寻帧.bat”重启后重试。草稿目录：%s" % root) from error
    except OSError as error:
        try:
            if probe.exists():
                probe.unlink()
        except OSError:
            pass
        raise RuntimeError("剪映草稿目录写入检查失败：%s（%s）" % (root, error)) from error


@contextmanager
def _generation_lock():
    """使用Windows文件区域锁，进程异常退出时由系统自动释放。"""
    if os.name != "nt":
        raise RuntimeError("剪映自动合成只支持本地Windows")
    import msvcrt

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise GenerationBusy("已有剪映自动合成任务正在运行，请等待它完成。") from error
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _draft_summary(draft_path):
    meta_path = draft_path / "draft_meta_info.json"
    if not meta_path.is_file():
        raise RuntimeError("草稿已创建，但缺少 draft_meta_info.json：%s" % draft_path)
    meta = _read_json(meta_path)
    return {
        "draft_name": str(meta.get("draft_name") or draft_path.name),
        "draft_path": str(draft_path),
        "duration_seconds": round(float(meta.get("tm_duration") or 0) / 1_000_000, 3),
    }


def _selected_materials(log):
    match = SELECTED_JSON.search(log or "")
    if not match:
        return []
    try:
        value = json.loads(match.group(1))
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def generate_draft(mode, timeout=1800, *, draft_name=None, selection_manifest=None,
                   business_account_id=None, background_snapshot=None, operations_db=None):
    """串行运行独立脚本，返回可直接展示的草稿摘要。"""
    clean_mode = validate_mode(mode)
    if background_snapshot is not None and not business_account_id:
        raise ValueError('ACCOUNT_BACKGROUND_SCOPE_REQUIRED')
    if business_account_id:
        from account_visuals.storage import AccountBackgroundStore, validate_snapshot
        background_snapshot = (AccountBackgroundStore(operations_db).snapshot(business_account_id)
                               if background_snapshot is None else validate_snapshot(background_snapshot, business_account_id))
    if not SCRIPT.is_file() or not MODULE_CONFIG.is_file():
        raise RuntimeError("剪映自动合成模块不完整：%s" % MODULE_DIR)
    python = _python_executable()
    draft_root = _draft_root()
    _ensure_draft_writable(draft_root)
    expected_name = draft_name
    before = {item.name for item in draft_root.iterdir() if item.is_dir()} if not expected_name else set()
    env = os.environ.copy()
    from jianying_auto.memory_safety import bounded_environment
    env = bounded_environment(env)
    # 不继承外部进程残留的其它账号视觉层。
    env.pop('XUNFRAME_ACCOUNT_BACKGROUND', None)
    env.pop('XUNFRAME_BUSINESS_ACCOUNT_ID', None)
    if business_account_id:
        env['XUNFRAME_BUSINESS_ACCOUNT_ID'] = business_account_id
        env['XUNFRAME_ACCOUNT_BACKGROUND'] = json.dumps(background_snapshot, ensure_ascii=False)
    env.update({
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    command = [str(python), "-X", "utf8", "-B", str(SCRIPT), clean_mode]
    if selection_manifest:
        manifest = Path(selection_manifest).resolve(strict=True)
        env['XUNFRAME_COMPOSITION_MANIFEST'] = str(manifest)
    if expected_name:
        if re.search(r'[\\/:*?"<>|\x00-\x1f]', expected_name) or expected_name.endswith(('.', ' ')):
            raise ValueError('UNSAFE_DRAFT_NAME')
        if (draft_root / expected_name).exists():
            raise FileExistsError('DRAFT_ALREADY_EXISTS_NO_OVERWRITE')
        env['XUNZHEN_RESERVED_DRAFT_NAME'] = expected_name
    started = time.perf_counter()
    with _generation_lock():
        from jianying_auto.memory_safety import require_draft_budget
        memory_before = require_draft_budget()
        try:
            completed = subprocess.run(
                command,
                cwd=str(MODULE_DIR),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            evidence = MODULE_DIR / 'runtime' / 'generation_logs' / ('%d-%d' % (os.getpid(), time.time_ns()))
            evidence.mkdir(parents=True, exist_ok=True)
            for name, output in (('stdout', error.stdout), ('stderr', error.stderr)):
                (evidence / (name + '.log')).write_text(output.decode('utf-8', 'replace') if isinstance(output, bytes) else output or '', encoding='utf-8')
            raise RuntimeError("剪映草稿生成超过%d秒，任务已停止。" % timeout) from error
        evidence = MODULE_DIR / 'runtime' / 'generation_logs' / ('%d-%d' % (os.getpid(), time.time_ns()))
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / 'stdout.log').write_text(completed.stdout or '', encoding='utf-8')
        (evidence / 'stderr.log').write_text(completed.stderr or '', encoding='utf-8')
        _write_json(evidence / 'metadata.json', {'draft_name': expected_name,
                    'returncode': completed.returncode, 'memory_before': memory_before,
                    'threads': {key: env[key] for key in ('MKL_NUM_THREADS','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS')}})
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "无错误输出").strip()
        raise RuntimeError("剪映草稿生成失败：%s\n完整日志: %s" % (detail[-3000:], evidence))

    match = SUCCESS_NAME.search(completed.stdout or "")
    draft_name = match.group(1).strip() if match else ""
    if expected_name and draft_name != expected_name:
        raise RuntimeError('DRAFT_NAME_RESERVATION_MISMATCH')
    draft_path = draft_root / draft_name if draft_name else None
    if expected_name and not draft_path.is_dir():
        raise RuntimeError('RESERVED_DRAFT_DIRECTORY_MISSING')
    if draft_path is None or not draft_path.is_dir():
        created = [item for item in draft_root.iterdir()
                   if item.is_dir() and item.name not in before]
        if len(created) != 1:
            raise RuntimeError("脚本已结束，但无法唯一确认新草稿目录。")
        draft_path = created[0]

    result = _draft_summary(draft_path)
    result.update({
        "mode": clean_mode,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "log": (completed.stdout or "").strip(),
        "selected_materials": _selected_materials(completed.stdout),
    })
    if business_account_id:
        audit_path = draft_path / 'account_visual_layer.json'
        if not audit_path.is_file():
            raise RuntimeError('ACCOUNT_BACKGROUND_DRAFT_AUDIT_MISSING')
        result['account_visual_layer'] = json.loads(audit_path.read_text('utf-8'))
        if result['account_visual_layer']['business_account_id'] != business_account_id:
            raise RuntimeError('ACCOUNT_BACKGROUND_DRAFT_SCOPE_MISMATCH')
    return result


def generate_sequence(categories, timeout=1800, rng=None):
    """按网页实际选择的1～5段顺序生成，并校验子进程素材。"""
    selected, warnings, command_mode = plan_sequence(categories, rng=rng)
    result = generate_draft(command_mode, timeout=timeout)
    result.update({
        "mode": " → ".join(categories),
        "command_mode": command_mode,
        "selected_materials": _verified_materials(selected, result),
        "selection_warnings": warnings,
    })
    return result


def generate_batch(categories, count=1, timeout=1800, rng=None,
                   progress_callback=None, batch_root=None, max_unique_attempts=50, generation_context=None,
                   background_snapshot=None, operations_db=None):
    """生成1～10条独立草稿；逐条失败隔离并持续保存批次Manifest。"""
    sequence = [str(category).strip() for category in categories]
    if not 1 <= len(sequence) <= 5:
        raise ValueError("起号自动合成必须选择1～5个片段。")
    invalid = [category for category in sequence if category not in SOURCE_CATEGORIES]
    if invalid:
        raise ValueError("未知素材分类：%s" % "、".join(invalid))
    requested_count = validate_generation_count(count)
    if generation_context:
        from account_visuals.storage import AccountBackgroundStore, validate_snapshot
        account_id = generation_context['target_account_id']
        background_snapshot = (AccountBackgroundStore(operations_db).snapshot(account_id)
                               if background_snapshot is None else validate_snapshot(background_snapshot, account_id))
    if not isinstance(max_unique_attempts, int) or max_unique_attempts < 1:
        raise ValueError("组合去重重试次数必须是正整数。")

    if generation_context:
        from startup_render.common import below, identifier
        if len(generation_context['draft_names']) != requested_count:
            raise ValueError('GENERATION_COUNT_MISMATCH')
        batch_directory = below(batch_root or BATCH_ROOT, identifier(generation_context['batch_id']))
        batch_directory.mkdir(parents=True, exist_ok=False)
    else:
        batch_directory = _new_batch_directory(batch_root)
    batch_id = batch_directory.name
    manifest_path = batch_directory / "batch_manifest.json"
    manifest = {
        "batch_id": batch_id,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "requested_count": requested_count,
        "success_count": 0,
        "failed_count": 0,
        "slot_sequence": sequence,
        "warnings": [],
        "videos": [],
    }
    if generation_context:
        manifest['generation_context'] = {k: generation_context[k] for k in
            ('generation_id', 'employee_id', 'business_type', 'target_account_id',
             'target_account_name_snapshot', 'batch_id')}
    _write_json(manifest_path, manifest)

    randomizer = rng or random.SystemRandom()
    used_signatures = set()
    duplicate_warning = "当前素材数量不足，部分生成结果可能使用重复组合。"
    for video_index in range(1, requested_count + 1):
        _notify_progress(progress_callback, video_index, requested_count, "running")
        record = {
            "video_index": video_index,
            "status": "failed",
            "slot_sequence": sequence,
            "composition_signature": "",
            "command_mode": "",
            "selected_materials": [],
            "selection_warnings": [],
            "draft_name": "",
            "draft_path": "",
            "duration_seconds": 0,
            "elapsed_seconds": 0,
            "error": "",
        }
        try:
            planned = warnings = command_mode = signature = None
            unique_found = False
            for _ in range(max_unique_attempts):
                planned, warnings, command_mode = plan_sequence(sequence, rng=randomizer)
                signature = composition_signature(sequence, planned)
                if signature not in used_signatures:
                    unique_found = True
                    break
            if not unique_found and duplicate_warning not in manifest["warnings"]:
                manifest["warnings"].append(duplicate_warning)

            record.update({
                "composition_signature": signature,
                "command_mode": command_mode,
                "selected_materials": planned,
                "selection_warnings": warnings,
            })
            generated = generate_draft(command_mode, timeout=timeout,
                **({'draft_name': generation_context['draft_names'][video_index - 1],
                    'business_account_id': account_id, 'background_snapshot': background_snapshot} if generation_context else {}))
            materials = _verified_materials(planned, generated)
            record.update({
                "status": "success",
                "selected_materials": materials,
                "draft_name": generated.get("draft_name", ""),
                "draft_path": generated.get("draft_path", ""),
                "duration_seconds": generated.get("duration_seconds", 0),
                "elapsed_seconds": generated.get("elapsed_seconds", 0),
                "account_visual_layer": generated.get('account_visual_layer'),
            })
            used_signatures.add(signature)
            manifest["success_count"] += 1
        except Exception as error:
            record["error"] = str(error)
            manifest["failed_count"] += 1

        manifest["videos"].append(record)
        _write_json(batch_directory / ("video_%02d.json" % video_index), record)
        _write_json(manifest_path, manifest)
        _notify_progress(progress_callback, video_index, requested_count, "complete")

    manifest["completed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    _write_json(manifest_path, manifest)
    manifest["manifest_path"] = str(manifest_path)
    return manifest
