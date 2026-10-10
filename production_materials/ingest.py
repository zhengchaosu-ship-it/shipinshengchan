"""有界分片写盘、校验、去重、原子入库与崩溃恢复。"""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import hashlib
import hmac
import json
import os
import secrets
import shutil
import threading
import time

from .config import VIDEO_EXT,IMAGE_EXT,TERMINAL
from .store import Store,now,sha256,safe_filename,local_directory
from . import media,consumers

class UploadError(ValueError):
    def __init__(self,code,status=400):self.code,self.status=code,status;super().__init__(code)

class Ingest:
    def __init__(self,store):
        self.store,self.config=store,store.config
        self.root=Path(self.config['staging_root']);self.root.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.stop=threading.Event();self.wake=threading.Event()
        self.upload_locks={}

    def get(self,key,token=None):
        with self.store.connect() as db:row=db.execute('SELECT * FROM uploads WHERE upload_id=?',(key,)).fetchone()
        if not row:raise UploadError('UPLOAD_NOT_FOUND',404)
        value=dict(row)
        if token is not None and not hmac.compare_digest(value['token_hash'],hashlib.sha256(token.encode()).hexdigest()):
            raise UploadError('UPLOAD_TOKEN_INVALID',403)
        return value

    def _space(self,db,additional=()):
        """预留剩余暂存及最终提交副本；按实际卷合并，防并发超卖。"""
        need={};locations={};reserve=int(self.config.get('min_free_bytes',5*1024**3))
        def add(path,size):
            path=Path(path);volume=path.stat().st_dev;locations[volume]=path;need[volume]=need.get(volume,0)+max(0,size)
        for row in db.execute("SELECT * FROM uploads WHERE state NOT IN ('LIBRARY_READY','DUPLICATE_SKIPPED','QUARANTINED')"):
            add(self.root,row['expected_size']-row['received']);add(row['target_root'],row['expected_size'])
        for target,size in additional:add(self.root,size);add(target,size)
        for volume,amount in need.items():
            if shutil.disk_usage(locations[volume]).free<amount+reserve:raise UploadError('DISK_SPACE_INSUFFICIENT',507)

    def create_batch(self,data):
        if set(data)-{'pool_id','product_id','files'}:raise UploadError('UNSUPPORTED_REQUEST_FIELD')
        files=data.get('files');pool_id=data.get('pool_id');product=data.get('product_id') or None
        # 迁移后旧浏览器仍可提交历史池名；测试/旧配置也保持可用。
        from .library import canonical_pool
        known = {p['pool_id'] for p in self.store.pools()}
        if pool_id not in known:pool_id=canonical_pool(pool_id)
        if not isinstance(files,list) or not 1<=len(files)<=100:raise UploadError('BATCH_FILE_LIMIT')
        with self.lock,self.store.connect(True) as db:
            pool=db.execute('SELECT * FROM pools WHERE pool_id=?',(pool_id,)).fetchone()
            if not pool or not pool['root']:raise UploadError('POOL_NOT_CONFIGURED')
            target=local_directory(pool['root'])
            if product and (pool['business_type']!='COMMERCE' or not db.execute('SELECT 1 FROM products WHERE product_id=? AND enabled=1',(product,)).fetchone()):
                raise UploadError('INVALID_PRODUCT_SCOPE')
            allowed=VIDEO_EXT|IMAGE_EXT if pool['business_type']=='VISUAL' else VIDEO_EXT
            checked=[]
            for f in files:
                if set(f)-{'filename','size','fingerprint'}:raise UploadError('UNSUPPORTED_REQUEST_FIELD')
                name=safe_filename(f.get('filename'));size=f.get('size');fingerprint=f.get('fingerprint','')
                if Path(name).suffix.lower() not in allowed:raise UploadError('UNSUPPORTED_FILE_TYPE')
                if not isinstance(size,int) or isinstance(size,bool) or not 0<size<=int(self.config.get('max_file_bytes',50*1024**3)):
                    raise UploadError('INVALID_FILE_SIZE')
                if not isinstance(fingerprint,str) or not 8<=len(fingerprint)<=160:raise UploadError('INVALID_FINGERPRINT')
                checked.append((name,size,fingerprint))
            if db.execute("SELECT count(*) FROM uploads WHERE state='UPLOADING'").fetchone()[0]+len(checked)>300:
                raise UploadError('TOO_MANY_PENDING_UPLOADS',429)
            self._space(db,[(target,size) for _,size,_ in checked])
            # 用服务自身身份确认可写；拒绝传完大文件后才发现目录没有权限。
            probe=target/('.pm-writecheck-'+secrets.token_hex(12)+'.tmp')
            try:
                with probe.open('xb') as stream:stream.write(b'local production upload access check')
            except OSError:raise UploadError('POOL_NOT_WRITABLE',503)
            finally:
                try:probe.unlink(missing_ok=True)
                except OSError:pass
            batch='INGEST-'+secrets.token_hex(12);stamp=now();db.execute('INSERT INTO batches VALUES(?,?)',(batch,stamp))
            result=[]
            for name,size,fingerprint in checked:
                key=secrets.token_hex(16);token=secrets.token_urlsafe(32);staged=self.root/(key+'.uploadpart')
                staged.touch(exist_ok=False)
                db.execute('''INSERT INTO uploads(upload_id,token_hash,ingest_batch_id,pool_id,product_scope,product_id,
                    original_filename,expected_size,fingerprint,state,staged_path,target_root,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,'UPLOADING',?,?,?,?)''',
                    (key,hashlib.sha256(token.encode()).hexdigest(),batch,pool_id,'PRODUCT_SPECIFIC' if product else 'GLOBAL',product,name,size,fingerprint,str(staged),str(target),stamp,stamp))
                self.store.event(db,key,'UPLOADING');result.append({'upload_id':key,'token':token,'filename':name,'received':0,'state':'UPLOADING'})
        return {'ingest_batch_id':batch,'uploads':result,'chunk_bytes':self.config.get('chunk_bytes',4*1024**2)}

    def chunk(self,key,token,offset,length,stream,expected_hash):
        lock=self.upload_locks.setdefault(key,threading.Lock())
        with lock:
            row=self.get(key,token)
            if row['state']!='UPLOADING':raise UploadError('UPLOAD_ALREADY_FINALIZED',409)
            if offset!=row['received']:raise UploadError('OFFSET_MISMATCH',409)
            if length<=0 or length>self.config.get('chunk_bytes',4*1024**2) or offset+length>row['expected_size']:
                raise UploadError('CHUNK_LIMIT')
            with self.lock,self.store.connect() as db:self._space(db)
            hasher=hashlib.sha256();remaining=length
            with open(row['staged_path'],'r+b') as output:
                output.truncate(offset);output.seek(offset)
                try:
                    while remaining:
                        block=stream.read(min(1024**2,remaining))
                        if not block:raise UploadError('INCOMPLETE_CHUNK')
                        output.write(block);hasher.update(block);remaining-=len(block)
                    if not hmac.compare_digest(hasher.hexdigest(),expected_hash):raise UploadError('CHUNK_HASH_MISMATCH')
                    output.flush();os.fsync(output.fileno())
                except BaseException:
                    output.truncate(offset);output.flush();raise
            with self.store.connect(True) as db:
                db.execute('UPDATE uploads SET received=?,updated_at=? WHERE upload_id=?',(offset+length,now(),key))
            return {'received':offset+length}

    def finalize(self,key,token,confirm_long=False):
        with self.upload_locks.setdefault(key,threading.Lock()):
            row=self.get(key,token)
            if row['state'] in TERMINAL:return row['state']
            if row['state']=='NEEDS_CONFIRMATION' and confirm_long:
                self.store.transition(key,'STAGED',long_confirmed=1)
            elif row['state']=='UPLOADING':
                if row['received']!=row['expected_size']:raise UploadError('UPLOAD_INCOMPLETE',409)
                self.store.transition(key,'STAGED')
            elif row['state'] not in {'STAGED','VALIDATING','DEDUPLICATING','COMMITTING'}:
                raise UploadError('UPLOAD_NOT_READY',409)
            self.wake.set();return 'STAGED'

    def cleanup_staging(self,row):
        # 只回收已成功或已跳过的上传副本；损坏/长视频保留，正式素材永不删除。
        path=Path(row['staged_path'])
        if path.parent.resolve()!=self.root.resolve() or path.name!=row['upload_id']+'.uploadpart':
            raise UploadError('INVALID_STAGING_PATH')
        try:path.unlink(missing_ok=True)
        except OSError:
            import logging
            logging.warning('Terminal staging cleanup deferred: %s',row['upload_id'])

    def find_duplicate(self,row,content_hash):
        with self.store.connect() as db:
            material=db.execute("SELECT * FROM materials WHERE content_hash=? AND status='LIBRARY_READY'",(content_hash,)).fetchone()
            candidates=[dict(r) for r in db.execute('SELECT * FROM legacy_inventory WHERE available=1 AND size_bytes=?',(row['expected_size'],))]
        if material and Path(material['path']).is_file() and sha256(material['path'])==content_hash:return dict(material)
        for candidate in candidates:
            path=Path(candidate['path'])
            if not path.is_file():continue
            stat=path.stat()
            if stat.st_size!=row['expected_size']:continue
            value=candidate['content_hash'] if stat.st_mtime_ns==candidate['mtime_ns'] else None
            value=value or sha256(path)
            with self.store.connect(True) as db:db.execute('UPDATE legacy_inventory SET content_hash=?,mtime_ns=? WHERE path=?',(value,stat.st_mtime_ns,str(path)))
            if value==content_hash:return dict(path=str(path),content_hash=value,material_id='LEGACY-'+value,pool_id=candidate['pool_id'])
        return None

    def process(self,key):
        row=self.get(key)
        if row['state']=='COMMITTING':return self.commit(row)
        self.store.transition(key,'VALIDATING',error_code=None)
        try:
            if Path(row['staged_path']).stat().st_size!=row['expected_size']:raise ValueError('STAGED_SIZE_CHANGED')
            info=media.inspect(self.config,row['staged_path'],row['original_filename'])
        except (ValueError,OSError,StopIteration,KeyError,ZeroDivisionError) as error:
            self.store.transition(key,'QUARANTINED',error_code='MEDIA_INVALID');return
        except Exception as error:
            import subprocess
            if isinstance(error,(subprocess.CalledProcessError,subprocess.TimeoutExpired)):
                self.store.transition(key,'QUARANTINED',error_code='MEDIA_INVALID');return
            raise
        if info['duration']>self.config.get('long_video_seconds',1200) and not row['long_confirmed']:
            self.store.transition(key,'NEEDS_CONFIRMATION',metadata_json=json.dumps(info));return
        self.store.transition(key,'DEDUPLICATING',metadata_json=json.dumps(info))
        content_hash=sha256(row['staged_path'])
        duplicate=self.find_duplicate(row,content_hash)
        if duplicate:
            self.store.transition(key,'DUPLICATE_SKIPPED',content_hash=content_hash,duplicate_of=duplicate['material_id'])
            self.cleanup_staging(row)
            return
        with self.store.connect() as db:pool=dict(db.execute('SELECT * FROM pools WHERE pool_id=?',(row['pool_id'],)).fetchone())
        root=local_directory(row['target_root'])
        if Path(pool['root']).resolve()!=root:raise UploadError('POOL_CONFIGURATION_CHANGED')
        if pool['business_type']=='COMMERCE':
            root=root/(row['product_id'] if row['product_id'] else '_global');root.mkdir(exist_ok=True)
            if root.is_symlink() or (hasattr(root,'is_junction') and root.is_junction()):raise UploadError('LINKED_POOL_NOT_ALLOWED')
        name=Path(row['original_filename']);destination=root/name.name
        counter=1
        while destination.exists():
            suffix='__'+content_hash[:10]+('' if counter==1 else '_'+str(counter))
            destination=root/(name.stem[:120]+suffix+name.suffix.lower());counter+=1
        self.store.transition(key,'COMMITTING',destination=str(destination),content_hash=content_hash,metadata_json=json.dumps(info))
        self.commit(self.get(key))

    def commit(self,row):
        destination=Path(row['destination']);staged=Path(row['staged_path'])
        root=local_directory(row['target_root'])
        if not destination.resolve().is_relative_to(root):raise UploadError('DESTINATION_OUTSIDE_POOL')
        temp=destination.parent/('.pm-'+row['upload_id']+'.part')
        if not destination.exists():
            # 临时文件不带视频扩展名，既有生成器无法读取半成品。
            with staged.open('rb') as source,temp.open('wb') as target:
                shutil.copyfileobj(source,target,1024**2);target.flush();os.fsync(target.fileno())
            if sha256(temp)!=row['content_hash']:raise UploadError('COMMIT_HASH_MISMATCH')
            if os.name=='nt':os.rename(temp,destination)  # Windows rename原子且拒绝覆盖。
            else:os.link(temp,destination);temp.unlink()
        if sha256(destination)!=row['content_hash'] or destination.stat().st_size!=row['expected_size']:
            raise UploadError('DESTINATION_CONFLICT_NO_OVERWRITE')
        info=json.loads(row['metadata_json']);thumb=media.thumbnail(self.config,destination,info,row['content_hash'])
        with self.store.connect() as db:pool=dict(db.execute('SELECT * FROM pools WHERE pool_id=?',(row['pool_id'],)).fetchone())
        value=dict(material_id='PM-'+row['content_hash'],business_type=pool['business_type'],module_type=pool['module_type'],
            pool_id=row['pool_id'],product_scope=row['product_scope'],product_id=row['product_id'],original_filename=row['original_filename'],
            stored_filename=destination.name,path=str(destination),content_hash=row['content_hash'],size_bytes=row['expected_size'],
            mtime_ns=destination.stat().st_mtime_ns,**info,thumbnail_path=thumb,status='COMMITTING',ingest_batch_id=row['ingest_batch_id'],created_at=now())
        with self.store.connect(True) as db:
            db.execute('INSERT INTO materials('+','.join(value)+') VALUES('+','.join('?' for _ in value)+') ON CONFLICT(content_hash) DO NOTHING',tuple(value.values()))
        consumers.deliver(self.config,value)
        with self.store.connect(True) as db:
            db.execute("UPDATE materials SET status='LIBRARY_READY' WHERE material_id=?",(value['material_id'],))
            db.execute("UPDATE uploads SET state='LIBRARY_READY',material_id=?,updated_at=? WHERE upload_id=?",(value['material_id'],now(),row['upload_id']))
            db.execute('UPDATE catalog_state SET revision=revision+1,updated_at=? WHERE singleton=1',(now(),))
            self.store.event(db,row['upload_id'],'LIBRARY_READY',{'material_id':value['material_id']})
        self.cleanup_staging(row)

    def recover(self):
        with self.store.connect(True) as db:
            db.execute("UPDATE uploads SET state='STAGED' WHERE state IN ('VALIDATING','DEDUPLICATING')")
            for row in db.execute("SELECT * FROM uploads WHERE state='UPLOADING'").fetchall():
                path=Path(row['staged_path'])
                if path.exists() and path.stat().st_size>=row['received']:
                    with path.open('r+b') as f:f.truncate(row['received'])
                else:db.execute("UPDATE uploads SET state='ATTENTION_REQUIRED',error_code='STAGING_FILE_MISSING' WHERE upload_id=?",(row['upload_id'],))
        with self.store.connect() as db:
            terminal=[dict(r) for r in db.execute("SELECT * FROM uploads WHERE state IN ('LIBRARY_READY','DUPLICATE_SKIPPED')")]
        for row in terminal:self.cleanup_staging(row)

    def run(self):
        self.recover()
        while not self.stop.is_set():
            with self.store.connect() as db:rows=db.execute("SELECT upload_id FROM uploads WHERE state IN ('STAGED','COMMITTING') ORDER BY created_at LIMIT 1").fetchall()
            if not rows:self.wake.wait(1);self.wake.clear();continue
            try:self.process(rows[0]['upload_id'])
            except Exception as error:
                import logging
                logging.exception('material commit stopped: %s',rows[0]['upload_id'])
                self.store.transition(rows[0]['upload_id'],'ATTENTION_REQUIRED',error_code=getattr(error,'code','INGEST_ERROR'))
