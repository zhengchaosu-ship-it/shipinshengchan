"""只验证草稿安装，不写全局索引、不操作UI。5.9实际目录由现有配置提供。"""
from pathlib import Path
import json
import re
import uuid

from .common import read


def actual_draft_root(config):
    settings = Path(config['jianying_settings'])
    lines = re.findall(r'^currentCustomDraftPath=(.+)$', settings.read_text(encoding='utf-8-sig'), re.M)
    if len(lines) != 1:
        raise RuntimeError('DRAFT_ROOT_NOT_VERIFIED')
    value = lines[0].strip().replace('\\\\', '\\')
    root = Path(value)
    if not root.is_absolute() or not root.is_dir() or root.resolve() != Path(config['draft_root']).resolve():
        raise RuntimeError('DRAFT_ROOT_MISMATCH')
    return root.resolve()


def resource_paths(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {'path', 'file_path', 'font_path', 'draft_file_path', 'draft_config_path', 'audio_path'} and isinstance(item, str) and re.match(r'^[A-Za-z]:[\\/]', item):
                yield Path(item)
            else:
                yield from resource_paths(item)
    elif isinstance(value, list):
        for item in value:
            yield from resource_paths(item)


def install_check(config, folder, expected_name, *, peers=None):
    root = actual_draft_root(config)
    folder = Path(folder).resolve()
    if folder.parent != root:
        raise RuntimeError('DRAFT_STAGED_BUT_NOT_INSTALLED')
    for name in ('draft_content.json', 'draft_meta_info.json'):
        if not (folder / name).is_file() or not (folder / name).stat().st_size:
            raise RuntimeError('DRAFT_REQUIRED_FILE_MISSING:' + name)
    meta, content = read(folder / 'draft_meta_info.json'), read(folder / 'draft_content.json')
    if (folder.name != expected_name or meta.get('draft_name') != expected_name
            or Path(meta.get('draft_root_path', '')).resolve() != root
            or Path(meta.get('draft_fold_path', '')).resolve() != folder):
        raise RuntimeError('DRAFT_NAME_MISMATCH')
    try:
        uuid.UUID(meta['draft_id']); uuid.UUID(content['id'])
    except (KeyError, ValueError, TypeError, AttributeError) as error:
        raise RuntimeError('INVALID_INTERNAL_DRAFT_ID') from error
    if not isinstance(content.get('duration'), (int, float)) or content['duration'] <= 0:
        raise RuntimeError('INVALID_DRAFT_DURATION')
    canvas = content.get('canvas_config', {})
    if canvas.get('width', 0) <= 0 or canvas.get('height', 0) <= 0:
        raise RuntimeError('INVALID_DRAFT_CANVAS')
    # 5.9已打开的GOOD/TEST均生成零字节draft_biz_config.json。
    # 仅允许根目录这个已核实的辅助占位文件为空；核心/其它JSON仍严格解析。
    resources = []
    empty_optional = []
    for path in folder.rglob('*.json'):
        if path == folder / 'draft_biz_config.json' and path.stat().st_size == 0:
            empty_optional.append(str(path))
            continue
        value = read(path)
        for resource in resource_paths(value):
            if not resource.exists():
                raise RuntimeError('FAILED_MISSING_SOURCE:' + str(resource))
            resources.append(str(resource))
    unreadable_peers = []
    if peers is None:
        peers = list(root.iterdir())
        index = read(config['jianying_index'])
        if any(str(v.get('draft_id')).lower() == meta['draft_id'].lower() and Path(v.get('draft_fold_path', '')).resolve() != folder for v in index.get('all_draft_store', [])):
            raise RuntimeError('DUPLICATE_INTERNAL_DRAFT_ID:INDEX')
        peers += [Path(v['draft_fold_path']) for v in index.get('all_draft_store', []) if v.get('draft_fold_path')]
    for peer in peers:
        peer = Path(peer).resolve()
        if peer == folder or not (peer / 'draft_meta_info.json').is_file():
            continue
        try:
            other = read(peer / 'draft_meta_info.json')
            if str(other.get('draft_id')).lower() == meta['draft_id'].lower():
                raise RuntimeError('DUPLICATE_INTERNAL_DRAFT_ID:' + str(peer))
            other_content = read(peer / 'draft_content.json')
        except (ValueError, OSError):
            # 历史普通草稿可为空/非JSON；不解密、不修改。索引metadata ID已检查，
            # 仅声明可解析内容ID的审计范围；新生产UUID必须由生成器独立生成。
            unreadable_peers.append(str(peer))
            continue
        if str(other_content.get('id')).lower() == content['id'].lower():
            raise RuntimeError('DUPLICATE_INTERNAL_DRAFT_ID:' + str(peer))
    return {'draft_path': str(folder), 'actual_draft_root': str(root),
            'draft_name': expected_name, 'draft_id': meta['draft_id'],
            'content_internal_id': content['id'], 'resource_references_checked': len(resources),
            'skipped_empty_optional_files': empty_optional,
            'unreadable_legacy_peers': sorted(set(unreadable_peers)),
            'identity_audit_scope': 'INDEX_METADATA_AND_PARSEABLE_CONTENT_IDS'}
