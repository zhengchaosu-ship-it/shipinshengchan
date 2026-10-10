"""可信局域网上传服务；请求体分片写盘，不经过Streamlit文件管理器。"""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import argparse
import hashlib
import ipaddress
import json
import logging
import mimetypes
import re
import threading
import time

from .config import HERE,STATE_LABELS,IMAGE_EXT,settings
from .store import Store,ProductionMaterialCatalog,now
from .ingest import Ingest,UploadError
from . import media

PUBLIC_MATERIAL=('material_id','business_type','module_type','pool_id','product_scope','product_id',
                 'original_filename','stored_filename','duration','width','height','fps','codec','audio_codec',
                 'media_type','status','ingest_batch_id','created_at')
PUBLIC_UPLOAD=('upload_id','ingest_batch_id','pool_id','product_scope','product_id','original_filename','expected_size',
               'received','state','material_id','duplicate_of','created_at','updated_at','error_code')

def public_upload(row):
    result={k:row[k] for k in PUBLIC_UPLOAD};result['state_label']=STATE_LABELS.get(row['state'],'待处理')
    info=json.loads(row.get('metadata_json') or '{}');result['duration']=info.get('duration')
    return result

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,engine):
        self.engine=engine;self.slots=threading.BoundedSemaphore(12)
        super().__init__(address,Handler)
    def process_request(self,request,address):
        if not self.slots.acquire(False):self.shutdown_request(request);return
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,*args):
        try:super().process_request_thread(*args)
        finally:self.slots.release()

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    server_version='XunZhenMaterials/1'
    def setup(self):
        super().setup();self.connection.settimeout(60)
    def log_message(self,fmt,*args):logging.info('%s %s',self.client_address[0],fmt%args)
    @property
    def engine(self):return self.server.engine
    def guard(self,write=False):
        config=self.engine.config
        if not any(ipaddress.ip_address(self.client_address[0]) in ipaddress.ip_network(n) for n in config['trusted_networks']):
            raise UploadError('LAN_ONLY',403)
        host=self.headers.get('Host','').lower();parsed=urlsplit('http://'+host)
        if parsed.hostname not in [h.lower() for h in config['allowed_hosts']] or parsed.port!=self.server.server_port:
            raise UploadError('INVALID_HOST',403)
        if write and self.headers.get('Origin')!='http://'+host:
            raise UploadError('SAME_ORIGIN_REQUIRED',403)
        if self.headers.get('Transfer-Encoding'):raise UploadError('USE_BOUNDED_CHUNKS',411)
    def json(self,status,value):
        body=json.dumps(value,ensure_ascii=False).encode();self.send_response(status)
        self.close_connection=True;self.send_header('Connection','close')
        self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
    def body(self):
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=256*1024:raise UploadError('REQUEST_TOO_LARGE',413)
        data=self.rfile.read(length)
        if len(data)!=length:raise UploadError('INCOMPLETE_REQUEST')
        result=json.loads(data)
        if not isinstance(result,dict):raise UploadError('JSON_OBJECT_REQUIRED')
        return result
    def dispatch(self,action):
        try:self.guard(action!='GET');getattr(self,'route_'+action)()
        except UploadError as error:self.close_connection=True;self.json(error.status,{'error':error.code})
        except (ValueError,KeyError,TypeError) as error:
            self.close_connection=True;self.json(400,{'error':'INVALID_REQUEST'})
        except (BrokenPipeError,ConnectionResetError,TimeoutError):self.close_connection=True
        except Exception:
            logging.exception('request failed');self.close_connection=True;self.json(500,{'error':'SERVICE_ERROR'})
    def do_GET(self):self.dispatch('GET')
    def do_POST(self):self.dispatch('POST')
    def do_PUT(self):self.dispatch('PUT')
    def route_POST(self):
        path=urlsplit(self.path).path
        if path=='/api/batches':return self.json(201,self.engine.create_batch(self.body()))
        match=re.fullmatch(r'/api/uploads/([a-f0-9]{32})/finalize',path)
        if match:
            data=self.body()
            if set(data)-{'confirm_long'}:raise UploadError('UNSUPPORTED_REQUEST_FIELD')
            state=self.engine.finalize(match[1],self.headers.get('X-Upload-Token',''),data.get('confirm_long') is True)
            return self.json(202,{'state':state})
        raise UploadError('NOT_FOUND',404)
    def route_PUT(self):
        parsed=urlsplit(self.path);match=re.fullmatch(r'/api/uploads/([a-f0-9]{32})',parsed.path)
        if not match:raise UploadError('NOT_FOUND',404)
        offset=int(parse_qs(parsed.query).get('offset',['-1'])[0]);length=int(self.headers.get('Content-Length','-1'))
        result=self.engine.chunk(match[1],self.headers.get('X-Upload-Token',''),offset,length,self.rfile,self.headers.get('X-Chunk-SHA256',''))
        self.json(200,result)
    def route_GET(self):
        parsed=urlsplit(self.path);path=parsed.path;query=parse_qs(parsed.query)
        if path in {'/','/portal.js','/portal.css'}:
            name={'/':'index.html','/portal.js':'portal.js','/portal.css':'portal.css'}[path]
            return self.file(HERE/'static'/name,static=True)
        if path=='/favicon.ico':
            self.send_response(204);self.send_header('Content-Length','0');self.end_headers();return
        if path=='/health':return self.json(200,{'status':'READY','service':'PRODUCTION_MATERIAL_UPLOAD','checked_at':now()})
        if path=='/api/bootstrap':
            return self.json(200,{'pools':self.engine.store.pools(),'products':self.engine.store.products(),
                'revision':self.engine.store.revision(),'chunk_bytes':self.engine.config['chunk_bytes'],
                'long_video_seconds':self.engine.config['long_video_seconds']})
        if path=='/api/overview':return self.json(200,{'pools':self.overview(query.get('product_id',[None])[0])})
        if path=='/api/records':
            with self.engine.store.connect() as db:rows=[public_upload(dict(r)) for r in db.execute('SELECT * FROM uploads ORDER BY created_at DESC LIMIT 200')]
            return self.json(200,{'records':rows})
        if path=='/api/materials':return self.json(200,self.library(query))
        match=re.fullmatch(r'/api/uploads/([a-f0-9]{32})',path)
        if match:return self.json(200,public_upload(self.engine.get(match[1],self.headers.get('X-Upload-Token',''))))
        match=re.fullmatch(r'/api/materials/((?:PM-|LEG-)[a-f0-9]{64})/(media|thumbnail|info)',path)
        if match:
            row=self.resolve_material(match[1]);source=Path(row['path'])
            if match[2]=='media':return self.file(source)
            if row['material_id'].startswith('LEG-'):
                thumb_key=match[1]+'-'+str(row['mtime_ns'])
                prior=Path(self.engine.config['thumbnail_root'])/(thumb_key+'.jpg')
                if match[2]=='thumbnail' and prior.is_file():return self.file(prior)
                info=media.inspect(self.engine.config,source,source.name)
                row.update(info,thumbnail_path=media.thumbnail(self.engine.config,source,info,thumb_key))
            if match[2]=='info':return self.json(200,{k:row.get(k) for k in PUBLIC_MATERIAL})
            return self.file(Path(row['thumbnail_path']))
        raise UploadError('NOT_FOUND',404)
    def overview(self,product):
        with self.engine.store.connect() as db:
            result=[]
            for pool in self.engine.store.pools():
                sql="SELECT count(*) FROM materials WHERE pool_id=? AND status='LIBRARY_READY'";args=[pool['pool_id']]
                if product and pool['business_type']=='COMMERCE':
                    sql+=" AND (product_id=? OR product_scope='GLOBAL')";args.append(product)
                count=db.execute(sql,args).fetchone()[0]
                legacy=0
                legacy=db.execute('SELECT count(*) FROM legacy_inventory l WHERE l.pool_id=? AND available=1 AND NOT EXISTS(SELECT 1 FROM materials m WHERE m.path=l.path)',(pool['pool_id'],)).fetchone()[0]
                result.append(dict(pool,count=count+legacy,uploaded=count,existing=legacy))
        return result
    def library(self,query):
        pool_id=query.get('pool_id',[None])[0];product=query.get('product_id',[None])[0]
        offset=max(0,int(query.get('offset',['0'])[0]));limit=min(40,max(1,int(query.get('limit',['12'])[0])))
        with self.engine.store.connect() as db:
            scope="m.status='LIBRARY_READY'";args=[]
            if pool_id:scope+=' AND m.pool_id=?';args.append(pool_id)
            if product:scope+=" AND (m.product_id=? OR m.product_scope='GLOBAL')";args.append(product)
            legacy="l.available=1 AND NOT EXISTS(SELECT 1 FROM materials m WHERE m.path=l.path)"
            old_args=[]
            if pool_id:legacy+=' AND l.pool_id=?';old_args.append(pool_id)
            # 元数据分页，不扫描或解码整库；原有文件只在预览时提取媒体信息。
            sql=("SELECT m.path,m.material_id,m.created_at,0 AS old FROM materials m WHERE "+scope+
                 " UNION ALL SELECT l.path,NULL,NULL,1 FROM legacy_inventory l JOIN pools p USING(pool_id) WHERE "+legacy)
            params=args+old_args
            total=db.execute('SELECT count(*) FROM ('+sql+')',params).fetchone()[0]
            page=db.execute(sql+' ORDER BY old,created_at DESC,path LIMIT ? OFFSET ?',(*params,limit,offset)).fetchall()
            result=[]
            for item in page:
                if not item['old']:
                    material=dict(db.execute('SELECT * FROM materials WHERE material_id=?',(item['material_id'],)).fetchone())
                    result.append({k:material.get(k) for k in PUBLIC_MATERIAL});continue
                row=db.execute('SELECT l.*,p.business_type,p.module_type FROM legacy_inventory l JOIN pools p USING(pool_id) WHERE l.path=?',(item['path'],)).fetchone()
                path=Path(row['path'])
                result.append(dict(material_id='LEG-'+hashlib.sha256(str(path).encode()).hexdigest(),business_type=row['business_type'],
                    module_type=row['module_type'],pool_id=row['pool_id'],product_scope='GLOBAL',product_id=None,
                    original_filename=path.name,stored_filename=path.name,duration=None,
                    media_type='IMAGE' if path.suffix.lower() in IMAGE_EXT else 'VIDEO',status='EXISTING',created_at=None))
        return {'materials':result,'total':total,'offset':offset,'limit':limit}
    def resolve_material(self,key):
        catalog=ProductionMaterialCatalog(self.engine.config)
        if key.startswith('PM-'):row=catalog.material(key)
        else:
            row=None
            with self.engine.store.connect() as db:
                for item in db.execute('SELECT * FROM legacy_inventory WHERE available=1'):
                    if 'LEG-'+hashlib.sha256(item['path'].encode()).hexdigest()==key:
                        row=dict(item,material_id=key,original_filename=Path(item['path']).name);break
        if not row:raise UploadError('MATERIAL_NOT_FOUND',404)
        with self.engine.store.connect() as db:pool=db.execute('SELECT root FROM pools WHERE pool_id=?',(row['pool_id'],)).fetchone()
        path=Path(row['path'])
        if not pool or not path.is_file() or not path.resolve().is_relative_to(Path(pool['root']).resolve()):raise UploadError('MATERIAL_UNAVAILABLE',404)
        if path.stat().st_size!=row['size_bytes'] or path.stat().st_mtime_ns!=row['mtime_ns']:raise UploadError('MATERIAL_CHANGED',409)
        return row
    def file(self,path,static=False):
        if not path.is_file():raise UploadError('FILE_NOT_FOUND',404)
        size=path.stat().st_size;start=0;end=size-1;status=200
        value=self.headers.get('Range')
        if value:
            match=re.fullmatch(r'bytes=(\d+)-(\d*)',value)
            if not match:raise UploadError('INVALID_RANGE',416)
            start=int(match[1]);end=min(int(match[2]) if match[2] else end,end)
            if start>end:raise UploadError('INVALID_RANGE',416)
            status=206
        self.send_response(status);self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.close_connection=True;self.send_header('Connection','close')
        self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-cache' if static else 'private, max-age=60')
        if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        if static:
            hosts=' '.join('http://'+h+':8502' for h in self.engine.config['allowed_hosts'])
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; object-src 'none'; frame-ancestors "+hosts)
        self.end_headers()
        with path.open('rb') as source:
            source.seek(start);remaining=end-start+1
            while remaining:
                block=source.read(min(1024**2,remaining))
                if not block:break
                self.wfile.write(block);remaining-=len(block)

def serve(config):
    for address in config['bind_addresses']:
        parsed=ipaddress.ip_address(address)
        if parsed.is_unspecified or not (parsed.is_private or parsed.is_loopback):raise ValueError('TRUSTED_LAN_BIND_REQUIRED')
    store=Store(config);store.initialize();store.metadata_inventory()
    engine=Ingest(store)
    servers=[Server((host,config['port']),engine) for host in config['bind_addresses']]
    worker=threading.Thread(target=engine.run,daemon=True,name='material-ingest');worker.start()
    for server in servers:threading.Thread(target=server.serve_forever,daemon=True).start()
    logging.info('material upload service ready on configured LAN addresses')
    try:
        while True:
            time.sleep(10)
            if not worker.is_alive():raise RuntimeError('MATERIAL_INGEST_WORKER_STOPPED')
    finally:
        engine.stop.set();engine.wake.set()
        for server in servers:server.shutdown();server.server_close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config');args=parser.parse_args()
    config=settings(args.config);log=Path(config['database']).parent/'service.log';log.parent.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=log,encoding='utf-8',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    serve(config)
