"""独立生产编目与目录登记；增量迁移只作用于自己的数据库。"""
from contextlib import contextmanager,closing
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import sqlite3

from .config import HERE, LABELS, STARTUP, COMMERCE, VIDEO_EXT, IMAGE_EXT, default_pools

def now():
    return datetime.now(timezone.utc).isoformat()

def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def safe_filename(name):
    if (not isinstance(name, str) or not name or len(name)>180 or name in {'.','..'} or name[-1] in '. '
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', name, re.I)):
        raise ValueError('INVALID_FILENAME')
    return name

def local_directory(value):
    path=Path(value)
    if not path.is_absolute() or str(path).startswith(('\\\\','//')) or not path.is_dir():
        raise ValueError('EXISTING_LOCAL_DIRECTORY_REQUIRED')
    for item in (path,*path.parents):
        if item.is_symlink() or (hasattr(item,'is_junction') and item.is_junction()):
            raise ValueError('LINKED_POOL_NOT_ALLOWED')
    return path.resolve(strict=True)

class Store:
    def __init__(self, config):
        self.config=config; self.path=Path(config['database'])

    @contextmanager
    def connect(self, write=False):
        db=sqlite3.connect(self.path, timeout=30)
        db.row_factory=sqlite3.Row; db.execute('PRAGMA foreign_keys=ON'); db.execute('PRAGMA busy_timeout=30000')
        try:
            if write: db.execute('BEGIN IMMEDIATE')
            yield db
            if write: db.commit()
        except BaseException:
            db.rollback(); raise
        finally:
            db.close()

    def initialize(self, pools=None):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='schema_version'").fetchone()
            if not exists:
                if self.path.stat().st_size:
                    with closing(sqlite3.connect(self.path.with_suffix('.pre-portal.bak'))) as backup: db.backup(backup)
                db.executescript((HERE/'migrations/001_portal.sql').read_text('utf-8'))
                db.execute('INSERT INTO schema_version VALUES(1,?)',(now(),));db.commit()
        with self.connect(True) as db:
            for p in pools if pools is not None else default_pools(self.config):
                db.execute('INSERT OR IGNORE INTO pools VALUES(?,?,?,?,?,?)',
                    (p['pool_id'],p['business_type'],p['module_type'],p['label'],p.get('root'),now()))
            source=Path(self.config.get('products_file',''))
            if source.is_file():
                for product in json.loads(source.read_text('utf-8'))['products']:
                    self._product(db,product['id'],product['name'])

    def _product(self, db, key, name):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',key) or not str(name).strip():
            raise ValueError('INVALID_PRODUCT')
        db.execute('INSERT INTO products VALUES(?,?,1) ON CONFLICT(product_id) DO UPDATE SET display_name=excluded.display_name', (key,str(name).strip()[:120]))

    def add_product(self,key,name):
        with self.connect(True) as db:self._product(db,key,name)

    def pools(self, private=False):
        with self.connect() as db:rows=[dict(r) for r in db.execute('SELECT * FROM pools ORDER BY rowid')]
        for row in rows:
            row['configured']=bool(row['root'] and Path(row['root']).is_dir())
            if not private:row.pop('root')
        return rows

    def products(self):
        with self.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM products WHERE enabled=1 ORDER BY display_name')]

    def configure_pool(self, pool_id, root):
        # 高级管理专用；普通HTTP上传协议没有这个入口。
        path=local_directory(root)
        if pool_id not in COMMERCE:raise ValueError('ONLY_COMMERCE_DIRECTORY_CONFIGURATION')
        protected=[Path(p).resolve() for p in self.config.get('raw_media_roots',[])]
        protected += [Path(self.config[k]).resolve() for k in ('staging_root','thumbnail_root')]
        for other in protected:
            if path.is_relative_to(other) or other.is_relative_to(path):raise ValueError('PROTECTED_DIRECTORY')
        with self.connect(True) as db:
            for row in db.execute('SELECT pool_id,root FROM pools WHERE root IS NOT NULL AND pool_id!=?',(pool_id,)):
                other=Path(row['root']).resolve()
                if path.is_relative_to(other) or other.is_relative_to(path):raise ValueError('POOL_DIRECTORIES_MUST_BE_SEPARATE')
            if db.execute('SELECT 1 FROM uploads WHERE pool_id=? LIMIT 1',(pool_id,)).fetchone():
                old=db.execute('SELECT root FROM pools WHERE pool_id=?',(pool_id,)).fetchone()
                if old and Path(old[0]).resolve()!=path:raise ValueError('CONFIGURED_POOL_IN_USE_NO_MOVE')
            db.execute('UPDATE pools SET root=?,updated_at=? WHERE pool_id=?',(str(path),now(),pool_id))

    def metadata_inventory(self):
        """只列已配置生产目录的小型清单，不解码、不读原始索引、不追随链接。"""
        rows=[]
        for pool in self.pools(True):
            if not pool['configured']:continue
            root=local_directory(pool['root']);visited=0
            for current,dirs,names in os.walk(root,followlinks=False):
                dirs[:]=[n for n in dirs if not n.startswith('.') and not Path(current,n).is_symlink()
                         and not (hasattr(Path(current,n),'is_junction') and Path(current,n).is_junction())]
                for name in names:
                    path=Path(current,name);visited+=1
                    if visited>100000:raise ValueError('PRODUCTION_POOL_INVENTORY_TOO_LARGE')
                    allowed=VIDEO_EXT|IMAGE_EXT if pool['business_type']=='VISUAL' else VIDEO_EXT
                    if path.suffix.lower() not in allowed or path.is_symlink() or not path.is_file():continue
                    st=path.stat();rows.append((str(path.resolve()),pool['pool_id'],st.st_size,st.st_mtime_ns))
        with self.connect(True) as db:
            db.execute('UPDATE legacy_inventory SET available=0')
            for row in rows:
                db.execute('''INSERT INTO legacy_inventory VALUES(?,?,?,?,NULL,1) ON CONFLICT(path) DO UPDATE SET
                    content_hash=CASE WHEN size_bytes=excluded.size_bytes AND mtime_ns=excluded.mtime_ns THEN content_hash ELSE NULL END,
                    pool_id=excluded.pool_id,size_bytes=excluded.size_bytes,mtime_ns=excluded.mtime_ns,available=1''',row)
        return len(rows)

    def event(self, db, upload_id, event, detail=None):
        db.execute('INSERT INTO events(upload_id,event,detail_json,created_at) VALUES(?,?,?,?)',(upload_id,event,json.dumps(detail or {},ensure_ascii=False),now()))

    def transition(self, upload_id, state, **fields):
        assert set(fields)<= {'received','destination','content_hash','metadata_json','material_id','duplicate_of','long_confirmed','error_code'}
        with self.connect(True) as db:
            fields.update(state=state,updated_at=now())
            db.execute('UPDATE uploads SET '+','.join(k+'=?' for k in fields)+' WHERE upload_id=?',(*fields.values(),upload_id))
            self.event(db,upload_id,state)

    def revision(self):
        with self.connect() as db:return db.execute('SELECT revision FROM catalog_state WHERE singleton=1').fetchone()[0]

    def material(self, key):
        with self.connect() as db:
            row=db.execute("SELECT * FROM materials WHERE material_id=? AND status='LIBRARY_READY'",(key,)).fetchone()
        return dict(row) if row else None

class ProductRegistry(Store):
    pass

class ProductionMaterialPoolRegistry(Store):
    def startup_defaults(self):
        """新账号只消费已登记正式池；读取清单不创建目录或修改编目。"""
        from .library import canonical_pool
        return [self.require_startup_pool(canonical_pool(module)) for module in STARTUP]

    def require_startup_pool(self, key):
        from .library import canonical_pool, pool_roots
        from startup_autopilot.material_catalog import inventory, verify_material
        path=self.path.resolve()
        if not path.is_file():raise ValueError('PRODUCTION_POOL_REGISTRY_UNAVAILABLE')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            rows=[dict(r) for r in db.execute("SELECT * FROM pools WHERE business_type='STARTUP'")]
        formal=pool_roots(self.config['production_library_root']) if self.config.get('production_library_root') else {}
        candidates=[r['pool_id'] for r in rows if r['pool_id'] in formal]
        row=next((r for r in rows if r['pool_id']==key),None)
        if not row or key not in formal or canonical_pool(row['module_type'])!=key:
            raise ValueError('PRODUCTION_POOL_NOT_REGISTERED: '+key+'; candidates='+','.join(candidates))
        # 当前Registry无enabled列；登记池默认启用，配置可显式禁用，兼容未来enabled列。
        if not row.get('enabled',True) or key in self.config.get('disabled_pool_ids',[]):
            raise ValueError('POOL_DISABLED: '+key+'; candidates='+','.join(candidates))
        if not row['root'] or Path(row['root']).resolve()!=formal[key].resolve():
            raise ValueError('PRODUCTION_POOL_ROOT_MISMATCH: '+key+'; candidates='+','.join(candidates))
        root=local_directory(row['root'])
        meta=inventory([(row['label'],root)],max_files_per_pool=1024,max_entries_per_pool=16384)[0]
        readable=[]
        for item in meta['files']:
            try:
                verify_material(item)
                with Path(item['path']).open('rb') as stream:
                    if not stream.read(1):continue
                verify_material(item);readable.append(item)
            except (OSError,ValueError):continue
        if not readable:
            raise ValueError('POOL_EMPTY: '+key+'; 正式素材池候选='+','.join(candidates))
        return {**row,'root':str(root),'enabled':True,'candidate_count':len(readable)}

class ProductionMaterialCatalog(Store):
    def query(self, *, business_type=None, module_type=None, product_id=None, exact_scope=False, limit=200):
        from .library import POOL_ALIASES
        module_type = {v:k for k,v in POOL_ALIASES.items()}.get(module_type,module_type)
        sql="SELECT * FROM materials WHERE status='LIBRARY_READY'";args=[]
        for column,value in [('business_type',business_type),('module_type',module_type)]:
            if value:sql+=' AND '+column+'=?';args.append(value)
        if product_id:
            sql+= " AND (product_scope='PRODUCT_SPECIFIC' AND product_id=?" + (')' if exact_scope else " OR product_scope='GLOBAL')")
            args.append(product_id)
        elif exact_scope:sql+=" AND product_scope='GLOBAL'"
        sql+=' ORDER BY created_at DESC,material_id LIMIT ?';args.append(min(int(limit),1000))
        with self.connect() as db:
            result=[dict(r) for r in db.execute(sql,args)]
            # 原目录文件只编目、不生成重复持久 material_id；保留上传素材优先顺序。
            remaining=max(0,min(int(limit),1000)-len(result))
            if remaining and not (exact_scope and product_id):
                legacy="SELECT l.*,p.business_type,p.module_type FROM legacy_inventory l JOIN pools p USING(pool_id) WHERE l.available=1 AND NOT EXISTS(SELECT 1 FROM materials m WHERE m.path=l.path)"
                values=[]
                for column,value in [('business_type',business_type),('module_type',module_type)]:
                    if value:legacy+=' AND p.'+column+'=?';values.append(value)
                legacy+=' ORDER BY l.path LIMIT ?';values.append(remaining)
                for row in db.execute(legacy,values):
                    item=dict(row);path=Path(item['path'])
                    item.update(material_id='LEG-'+hashlib.sha256(str(path).encode()).hexdigest(),
                        original_filename=path.name,stored_filename=path.name,product_scope='GLOBAL',product_id=None,
                        status='EXISTING',media_type='IMAGE' if path.suffix.lower() in IMAGE_EXT else 'VIDEO')
                    result.append(item)
        return result

    def for_commerce(self,product_id,module_type):
        if module_type not in COMMERCE:raise ValueError('COMMERCE_MODULE_REQUIRED')
        if not any(p['product_id']==product_id for p in self.products()):raise ValueError('UNKNOWN_PRODUCT')
        return self.query(business_type='COMMERCE',module_type=module_type,product_id=product_id,limit=1000)
