"""受控文件清单、路径迁移和媒体验收；不扫描素材库。"""
import hashlib
import json
import math
import ntpath
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess

MEDIA = {'.mp4', '.mov', '.mkv', '.ts', '.avi', '.webm', '.mp3', '.wav', '.m4a',
         '.aac', '.flac', '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.ttf', '.otf'}
ID = re.compile(r'^[A-Za-z0-9_-]{1,100}$')


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('INVALID_ID')
    return value


def output_relative(identity):
    """新账号绑定任务使用预留草稿名；旧任务保留原导出路径。"""
    batch = identifier(identity['batch_id'])
    if not identity.get('target_account_id'):
        return batch + '/%03d.mp4' % identity['video_index']
    name = identity.get('draft_name', '')
    if not name or re.search(r'[\\/:*?"<>|\x00-\x1f]', name) or name.endswith(('.', ' ')):
        raise ValueError('UNSAFE_DRAFT_NAME')
    # LAN输出按稳定content_id分目录；旧任务仍保留原batch路径。
    if identity.get('output_layout') == 'LAN_RESIDENT_V1':
        return identifier(identity['content_id']) + '/' + name + '.mp4'
    return batch + '/' + name + '.mp4'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.new')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def below(root, relative):
    if not isinstance(relative, str) or '\\' in relative or ':' in relative:
        raise ValueError('UNSAFE_RELATIVE_PATH')
    rel = PurePosixPath(relative)
    if rel.is_absolute() or not rel.parts or any(p in ('', '.', '..') for p in relative.split('/')):
        raise ValueError('UNSAFE_RELATIVE_PATH')
    root = Path(root).resolve()
    target = root.joinpath(*rel.parts)
    if not target.resolve().is_relative_to(root):
        raise ValueError('PATH_OUTSIDE_ROOT')
    current = target
    while current != root:
        if current.is_symlink() or getattr(current, 'is_junction', lambda: False)():
            raise ValueError('LINK_NOT_ALLOWED')
        current = current.parent
    return target


def strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        if value.startswith(('{', '[')):
            try:
                yield from strings(json.loads(value))
                return
            except ValueError:
                pass
        yield value


def normalized(value):
    return ntpath.normcase(ntpath.normpath(value))


def rewrite(value, mapping):
    if isinstance(value, dict):
        return {k: rewrite(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [rewrite(v, mapping) for v in value]
    if isinstance(value, str):
        if normalized(value) in mapping:
            return mapping[normalized(value)]
        if value.startswith(('{', '[')):
            try:
                return json.dumps(rewrite(json.loads(value), mapping), ensure_ascii=False)
            except ValueError:
                pass
    return value


def package(draft, destination, identity, *, max_bytes=20 * 1024**3, max_files=3000):
    """只冻结当前草稿JSON/封面及JSON实际引用的媒体，不修改源草稿。"""
    draft = Path(draft).resolve()
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError('PACKAGE_ALREADY_EXISTS')
    if not (draft / 'draft_content.json').is_file():
        raise ValueError('DRAFT_CONTENT_MISSING')
    sources = {}
    documents = {}
    for path in draft.rglob('*'):
        if len(sources) >= max_files:
            raise ValueError('TOO_MANY_DRAFT_FILES')
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise ValueError('DRAFT_LINK_NOT_ALLOWED')
        if not path.is_file():
            continue
        relative = path.relative_to(draft).as_posix()
        if path.suffix == '.json' and (path.name.startswith('draft_') or path.name == 'template.json'):
            if path.stat().st_size > 30 * 1024**2:
                raise ValueError('DRAFT_JSON_TOO_LARGE')
            documents[path] = read(path)
            sources[path] = 'draft/' + relative
        elif path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}:
            sources[path] = 'draft/' + relative
    referenced = sorted({raw for value in documents.values() for raw in strings(value)
                         if (ntpath.isabs(raw) or Path(raw).is_absolute()) and Path(raw).suffix.lower() in MEDIA})
    save(destination.parent / (identity['job_id'] + '.source_inventory.json'),
         [{'source': raw, 'exists': Path(raw).is_file()} for raw in referenced])
    for value in documents.values():
        for raw in strings(value):
            is_absolute = ntpath.isabs(raw) or Path(raw).is_absolute()
            if not is_absolute or raw.startswith(('http:', 'https:')):
                continue
            path = Path(raw).resolve()
            if path == draft.parent:
                continue  # draft_root_path：仅改本地副本的根路径，不复制父目录。
            if path == draft or path.is_relative_to(draft):
                if path.suffix.lower() in MEDIA and not path.is_file():
                    raise ValueError('REFERENCED_MEDIA_MISSING:' + str(path))
                if path.is_file() and path not in sources:
                    if path.suffix.lower() not in MEDIA and path.suffix != '.json':
                        raise ValueError('UNSUPPORTED_INTERNAL_RESOURCE')
                    sources[path] = 'draft/' + path.relative_to(draft).as_posix()
                continue
            # 目录型特效资源需另行明确移植，不扫描任意外部目录。
            if path.suffix.lower() not in MEDIA:
                if path.is_dir():
                    raise ValueError('EXTERNAL_RESOURCE_DIRECTORY_REQUIRES_MAPPING')
                continue
            if not path.is_file() or path.is_symlink():
                raise ValueError('REFERENCED_MEDIA_MISSING:' + str(path))
            sources[path] = 'assets/' + hashlib.sha256(str(path).encode()).hexdigest()[:20] + path.suffix.lower()
    total = sum(p.stat().st_size for p in sources)
    if total > max_bytes or len(sources) > max_files:
        raise ValueError('PACKAGE_LIMIT_EXCEEDED')
    destination.mkdir(parents=True)
    entries = []
    for source, relative in sorted(sources.items(), key=lambda r: r[1]):
        before = source.stat()
        target = below(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or digest(source) != digest(target):
            raise ValueError('SOURCE_CHANGED_DURING_COPY')
        entries.append({'relative': relative, 'source': str(source), 'size': target.stat().st_size,
                        'sha256': digest(target)})
    main = documents[draft / 'draft_content.json']
    manifest = {**identity, 'draft_source': str(draft), 'files': entries, 'total_bytes': total,
                'duration_us': main.get('duration'), 'canvas': main.get('canvas_config', {}),
                'fps': main.get('fps', 30), 'publish_state': 'AWAITING_PUBLISH_PARAMETERS'}
    manifest['requires_audio'] = any(t.get('type') == 'audio' and t.get('segments') for t in main.get('tracks', []))
    manifest['material_count'] = sum(Path(e['source']).suffix.lower() in MEDIA for e in entries)
    save(destination / 'manifest.json', manifest)
    return manifest


def media_probe(binary, path, expected_seconds):
    if not math.isfinite(expected_seconds) or expected_seconds <= 0:
        raise ValueError('INVALID_EXPECTED_DURATION')
    done = subprocess.run([str(binary), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
                          capture_output=True, timeout=60, check=True,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    value = json.loads(done.stdout)
    video = next(s for s in value['streams'] if s.get('codec_type') == 'video')
    audio = [s for s in value['streams'] if s.get('codec_type') == 'audio']
    duration = float(value['format']['duration'])
    if (video.get('codec_name') != 'h264' or video.get('width', 0) <= 0 or video.get('height', 0) <= 0
            or not math.isfinite(duration) or duration <= 0 or 'mp4' not in value['format']['format_name'].split(',')
            or any(s.get('codec_name') != 'aac' for s in audio)
            or abs(duration - expected_seconds) > max(2, expected_seconds * .02)):
        raise ValueError('EXPORTED_MEDIA_VALIDATION_FAILED')
    return {'codec': video['codec_name'], 'width': video['width'], 'height': video['height'],
            'fps': video.get('avg_frame_rate'), 'duration': duration,
            'audio_codec': audio[0]['codec_name'] if audio else None,
            'size': Path(path).stat().st_size, 'sha256': digest(path)}
