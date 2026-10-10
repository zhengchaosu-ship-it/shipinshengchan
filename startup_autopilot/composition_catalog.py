"""元数据自动刷新与有限增量SHA缓存；无常驻扫描、无上传、无媒体处理。"""
import hashlib
from pathlib import Path

from .material_catalog import inventory,verify_material
from .models import digest


def pool_id(root):return 'POOL-'+digest(str(Path(root).resolve()))[:24]


class CompositionCatalog:
    def __init__(self,shadows):self.shadows=shadows

    def register_production(self,actor,account_id,key,registry):
        """使用Registry稳定pool_id；不把路径写入Slot，不修改其他账号。"""
        self.shadows.load(actor,account_id)
        pool=registry.require_startup_pool(key)
        with self.shadows.connect() as db:
            db.execute('INSERT INTO composition_material_pools VALUES(?,?,?,?) '
                       'ON CONFLICT(account_id,pool_id) DO UPDATE SET label=excluded.label,root=excluded.root',
                       (account_id,pool['pool_id'],pool['label']+'素材池',pool['root']))
        return pool['pool_id']

    def register(self,actor,account_id,label,root):
        self.shadows.load(actor,account_id)
        path=Path(root)
        if not path.is_absolute() or str(path).startswith('\\\\') or not path.is_dir():
            raise ValueError('EXISTING_LOCAL_MATERIAL_POOL_REQUIRED')
        key=pool_id(path)
        with self.shadows.connect() as db:
            db.execute('INSERT OR IGNORE INTO composition_material_pools VALUES(?,?,?,?)',(account_id,key,label or path.name,str(path.resolve())))
        return key

    def seed(self,actor,account_id,catalog):
        for pool in catalog:
            key=self.register(actor,account_id,pool['module_type']+'素材池',pool['root'])
            for item in pool['files']:
                if not item.get('media_sha256'):continue
                try:verify_material(item)
                except ValueError:continue
                with self.shadows.connect() as db:
                    db.execute('INSERT OR IGNORE INTO composition_catalog_cache VALUES(?,?,?,?,?,?,?)',
                        (account_id,key,digest(item['filesystem_identity']),item['path'],item['size_bytes'],item['mtime_ns'],item['media_sha256']))

    def refresh(self,actor,account_id,*,hash_budget=0,max_bytes=256*1024*1024,pool_ids=None):
        self.shadows.load(actor,account_id)
        with self.shadows.connect(readonly=True) as db:
            pools=[dict(r) for r in db.execute('SELECT * FROM composition_material_pools WHERE account_id=? ORDER BY pool_id',(account_id,))]
            cached={(r['pool_id'],r['file_key']):dict(r) for r in db.execute('SELECT * FROM composition_catalog_cache WHERE account_id=?',(account_id,))}
        if pool_ids is not None:pools=[p for p in pools if p['pool_id'] in pool_ids]
        result=[];bytes_read=0
        for pool in pools:
            meta=inventory([(pool['label'],pool['root'])],max_files_per_pool=1024,max_entries_per_pool=16384)[0]
            verified={};manifest=[];pending=0;remaining=hash_budget
            for item in sorted(meta['files'],key=lambda r:(r['size_bytes'],r['filename'])):
                file_key=digest(item['filesystem_identity'])
                prior=cached.get((pool['pool_id'],file_key))
                sha=prior['media_sha256'] if prior and prior['size_bytes']==item['size_bytes'] and prior['mtime_ns']==item['mtime_ns'] and prior['path']==item['path'] else None
                if sha is None and remaining>0 and bytes_read+item['size_bytes']<=max_bytes:
                    verify_material(item)
                    with open(item['path'],'rb') as source:sha=hashlib.file_digest(source,'sha256').hexdigest()
                    verify_material(item)
                    bytes_read+=item['size_bytes'];remaining-=1
                    with self.shadows.connect() as db:
                        db.execute('INSERT INTO composition_catalog_cache VALUES(?,?,?,?,?,?,?) ON CONFLICT(account_id,pool_id,file_key) DO UPDATE SET path=excluded.path,size_bytes=excluded.size_bytes,mtime_ns=excluded.mtime_ns,media_sha256=excluded.media_sha256',
                            (account_id,pool['pool_id'],file_key,item['path'],item['size_bytes'],item['mtime_ns'],sha))
                manifest.append([file_key,item['path'],item['size_bytes'],item['mtime_ns'],sha])
                if not sha:pending+=1;continue
                if sha in verified:
                    verified[sha]['aliases'].append(item['path']);continue
                verified[sha]={**item,'material_id':'MEDIA-SHA256-'+sha,'media_sha256':sha,
                              'identity_status':'CONTENT_SHA256_VERIFIED','aliases':[item['path']]}
            result.append({**pool,'files':list(verified.values()),'metadata_file_count':len(meta['files']),
                'verified_unique_count':len(verified),'pending_hash_count':pending,'truncated':meta['truncated'],
                'issues':meta['issues'],'manifest':manifest})
        return result


def catalog_hash(catalogs):
    return digest([{k:p[k] for k in ('pool_id','root','manifest','truncated','issues')} for p in catalogs])
