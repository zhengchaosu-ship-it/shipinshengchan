"""服务器侧配置，路径永远不由上传请求决定。"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).parent
STARTUP = {'STARTUP_HOOK': '引流', 'STARTUP_TECHNIQUE': '手法', 'STARTUP_CLINIC': '坐诊', 'STARTUP_ENDING': '收尾'}
COMMERCE = {'COMMERCE_HOOK_CLINIC': '引流坐诊', 'COMMERCE_BRIDGE_CLINIC': '承接坐诊',
            'COMMERCE_PRODUCT_INTRO': '述品介绍', 'COMMERCE_CALL_FEEDBACK': '连麦反馈', 'COMMERCE_SALES_CLOSE': '销售逼单'}
VISUAL = {'VISUAL_BACKGROUND': '账号背景'}
LABELS = {**STARTUP, **COMMERCE, **VISUAL}
VIDEO_EXT = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v', '.ts', '.flv'}
IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
TERMINAL = {'LIBRARY_READY', 'DUPLICATE_SKIPPED', 'QUARANTINED'}
STATE_LABELS = {'UPLOADING':'上传中', 'STAGED':'等待校验', 'VALIDATING':'校验中', 'DEDUPLICATING':'检查重复',
                'COMMITTING':'正在入库', 'LIBRARY_READY':'可以使用', 'DUPLICATE_SKIPPED':'重复，已跳过',
                'QUARANTINED':'损坏，已隔离', 'NEEDS_CONFIRMATION':'待确认长视频', 'ATTENTION_REQUIRED':'入库需要处理'}

def settings(path=None):
    source = Path(path or HERE / 'service.config.json')
    value = json.loads(source.read_text('utf-8-sig'))
    for key in ('database', 'staging_root', 'thumbnail_root', 'operations_db', 'shadow_db', 'products_file', 'ffprobe', 'ffmpeg'):
        if value.get(key):
            p = Path(value[key]); value[key] = str(p if p.is_absolute() else ROOT / p)
    value['_config_path'] = str(source.resolve())
    return value

def default_pools(config=None):
    from jianying_auto.source_catalog import load_source_folders
    folders = load_source_folders()
    background = json.loads((ROOT/'jianying_auto/config.json').read_text('utf-8'))['bg_dir']
    result = []
    from .library import canonical_pool, pool_roots
    formal = pool_roots(config['production_library_root']) if config and config.get('production_library_root') else {}
    for module, label in LABELS.items():
        business = 'STARTUP' if module in STARTUP else 'COMMERCE' if module in COMMERCE else 'VISUAL'
        root = str(folders[label]) if business == 'STARTUP' else background if business == 'VISUAL' else None
        pool_id = canonical_pool(module) if formal else module
        root = str(formal[pool_id]) if formal else root
        result.append(dict(pool_id=pool_id, module_type=module, label=label, business_type=business, root=root))
    return result
