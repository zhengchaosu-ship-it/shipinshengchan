"""统一生产目录映射；旧 module_type 保持兼容，目录由服务器解析。"""
from pathlib import Path

POOL_ALIASES = {'STARTUP_HOOK': 'STARTUP_LEAD', 'STARTUP_ENDING': 'STARTUP_CLOSE'}
DIRECTORIES = {
    'STARTUP_LEAD': '起号素材/01_引流',
    'STARTUP_TECHNIQUE': '起号素材/02_手法',
    'STARTUP_CLINIC': '起号素材/03_坐诊',
    'STARTUP_CLOSE': '起号素材/04_收尾',
    'COMMERCE_HOOK_CLINIC': '带货素材/01_引流坐诊',
    'COMMERCE_BRIDGE_CLINIC': '带货素材/02_承接坐诊',
    'COMMERCE_PRODUCT_INTRO': '带货素材/03_述品介绍',
    'COMMERCE_CALL_FEEDBACK': '带货素材/04_连麦反馈',
    'COMMERCE_SALES_CLOSE': '带货素材/05_销售逼单',
    'VISUAL_BACKGROUND': '背景素材',
}


def canonical_pool(key):
    return POOL_ALIASES.get(key, key)


def pool_roots(root):
    return {key: Path(root) / relative for key, relative in DIRECTORIES.items()}
