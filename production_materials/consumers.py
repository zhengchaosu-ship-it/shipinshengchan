"""入库回执：只更新既有素材编目缓存，不改模板、账号设置或生产任务。"""
from pathlib import Path
from contextlib import closing
import json
import sqlite3

from .store import now

def deliver(config,material):
    path=Path(material['path']);stat=path.stat()
    if material['business_type']=='STARTUP' and config.get('shadow_db'):
        from startup_autopilot.models import digest
        target=Path(config['shadow_db'])
        if target.is_file():
            with closing(sqlite3.connect(target,timeout=30)) as db, db:
                exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='composition_catalog_cache'").fetchone()
                if exists:
                    pools=db.execute('SELECT account_id,pool_id,root FROM composition_material_pools').fetchall()
                    for account_id,pool_id,root in pools:
                        # 只登记恰好包含此素材的原账号素材池；不新建或重绑账号池。
                        if path.resolve().is_relative_to(Path(root).resolve()):
                            db.execute('''INSERT INTO composition_catalog_cache VALUES(?,?,?,?,?,?,?)
                                ON CONFLICT(account_id,pool_id,file_key) DO UPDATE SET path=excluded.path,
                                size_bytes=excluded.size_bytes,mtime_ns=excluded.mtime_ns,media_sha256=excluded.media_sha256''',
                                (account_id,pool_id,digest([stat.st_dev,stat.st_ino]),str(path),stat.st_size,stat.st_mtime_ns,material['content_hash']))
    elif material['business_type']=='VISUAL' and config.get('operations_db'):
        target=Path(config['operations_db'])
        if not target.is_file():raise ValueError('BACKGROUND_CATALOG_UNAVAILABLE')
        with closing(sqlite3.connect(target,timeout=30)) as db, db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='background_material_catalog'").fetchone():
                raise ValueError('BACKGROUND_CATALOG_UNAVAILABLE')
            key='BG-'+material['content_hash'];stamp=now()
            db.execute('''INSERT INTO background_material_catalog VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(hash)
                DO UPDATE SET available=1,updated_at=excluded.updated_at''',
                (key,str(path),path.name,material['content_hash'],material['width'],material['height'],material['duration'],
                 material['media_type'],material['thumbnail_path'],1,stamp,stamp))
            db.execute('INSERT INTO background_material_aliases VALUES(?,?) ON CONFLICT(path) DO NOTHING',(str(path),key))

class CommerceMaterialSource:
    """供未来CommerceCompositionPlanner读取；本模块不实现组合或派发。"""
    def __init__(self,catalog):self.catalog=catalog
    def materials(self,product_id,module_type):return self.catalog.for_commerce(product_id,module_type)
