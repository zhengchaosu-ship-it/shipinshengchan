from contextlib import contextmanager,closing
from pathlib import Path
from unittest.mock import patch
import hashlib
import io
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
import urllib.error

from production_materials.config import settings,STARTUP,COMMERCE,VISUAL,ROOT
from production_materials.store import Store,ProductionMaterialCatalog,sha256,safe_filename
from production_materials.ingest import Ingest,UploadError
from production_materials.service import Server
from production_materials import media

class PortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=tempfile.TemporaryDirectory(prefix='material-fixtures-')
        cls.sources=Path(cls.fixture.name);cls.base=settings()
        for number,color in enumerate(('red','blue','green')):
            media.hidden([cls.base['ffmpeg'],'-nostdin','-v','error','-f','lavfi','-i',f'color=c={color}:s=108x192:r=10',
                          '-t','0.5','-c:v','libx264','-pix_fmt','yuv420p',cls.sources/f'{number}.mp4'])
        from PIL import Image
        Image.new('RGB',(108,192),'orange').save(cls.sources/'background.png')
    @classmethod
    def tearDownClass(cls):cls.fixture.cleanup()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='portal-test-');self.root=Path(self.temp.name)
        self.config=dict(self.base,database=str(self.root/'catalog.db'),staging_root=str(self.root/'staging'),
            thumbnail_root=str(self.root/'thumbs'),products_file='',min_free_bytes=0,chunk_bytes=1024,
            operations_db=str(self.root/'operations.db'),shadow_db=str(self.root/'shadow.db'),raw_media_roots=[str(self.root/'raw')])
        pools=[]
        for business,values in [('STARTUP',STARTUP),('COMMERCE',COMMERCE),('VISUAL',VISUAL)]:
            for key,label in values.items():
                target=self.root/key;target.mkdir()
                pools.append(dict(pool_id=key,module_type=key,business_type=business,label=label,root=str(target)))
        self.store=Store(self.config);self.store.initialize(pools)
        self.store.add_product('product_a','产品A');self.store.add_product('product_b','产品B')
        self.engine=Ingest(self.store)
        with closing(sqlite3.connect(self.config['operations_db'])) as db, db:
            db.executescript((ROOT/'account_visuals/migrations/001_background.sql').read_text('utf-8'))
        with closing(sqlite3.connect(self.config['shadow_db'])) as db, db:
            db.executescript('''CREATE TABLE composition_material_pools(account_id,pool_id,label,root);
                CREATE TABLE composition_catalog_cache(account_id,pool_id,file_key,path,size_bytes,mtime_ns,media_sha256,
                PRIMARY KEY(account_id,pool_id,file_key));''')
            db.execute('INSERT INTO composition_material_pools VALUES(?,?,?,?)',('account_a','pool_hand','手法',str(self.root/'STARTUP_TECHNIQUE')))
    def tearDown(self):self.temp.cleanup()
    def create(self,file,filename=None,pool='STARTUP_TECHNIQUE',product=None):
        data=file.read_bytes() if isinstance(file,Path) else file
        result=self.engine.create_batch({'pool_id':pool,'product_id':product,
            'files':[{'filename':filename or file.name,'size':len(data),'fingerprint':hashlib.sha256(data).hexdigest()}]})
        return result['uploads'][0],data
    def upload(self,file,filename=None,pool='STARTUP_TECHNIQUE',product=None):
        row,data=self.create(file,filename,pool,product)
        for offset in range(0,len(data),1024):
            chunk=data[offset:offset+1024]
            self.engine.chunk(row['upload_id'],row['token'],offset,len(chunk),io.BytesIO(chunk),hashlib.sha256(chunk).hexdigest())
        self.engine.finalize(row['upload_id'],row['token']);self.engine.process(row['upload_id'])
        return self.engine.get(row['upload_id'])

    def test_A_startup_immediately_visible_to_existing_consumers(self):
        row=self.upload(self.sources/'0.mp4');self.assertEqual(row['state'],'LIBRARY_READY')
        from jianying_auto.source_catalog import scan_videos
        self.assertTrue(scan_videos(self.root/'STARTUP_TECHNIQUE'))
        from startup_autopilot.composition_catalog import CompositionCatalog
        outer=self
        class ShadowFixture:
            def load(self,*args):return None
            @contextmanager
            def connect(self,**kwargs):
                with closing(sqlite3.connect(outer.config['shadow_db'])) as db, db:
                    db.row_factory=sqlite3.Row;yield db
        observed=CompositionCatalog(ShadowFixture()).refresh(None,'account_a',hash_budget=0)
        self.assertEqual(observed[0]['verified_unique_count'],1)
        self.assertEqual(observed[0]['files'][0]['media_sha256'],row['content_hash'])
    def test_B_hash_dedup_renamed_file(self):
        self.upload(self.sources/'0.mp4')
        self.assertEqual(self.upload(self.sources/'0.mp4','renamed.mp4')['state'],'DUPLICATE_SKIPPED')
        self.assertEqual(len(list((self.root/'STARTUP_TECHNIQUE').glob('*.mp4'))),1)
    def test_C_same_filename_no_overwrite(self):
        a=self.upload(self.sources/'0.mp4','same.mp4');b=self.upload(self.sources/'1.mp4','same.mp4')
        self.assertNotEqual(a['destination'],b['destination'])
        self.assertEqual(sha256(a['destination']),sha256(self.sources/'0.mp4'))
        self.assertEqual(sha256(b['destination']),sha256(self.sources/'1.mp4'))
    def test_D_broken_mp4_quarantined(self):
        row=self.upload(b'broken container','broken.mp4')
        self.assertEqual(row['state'],'QUARANTINED');self.assertFalse(list((self.root/'STARTUP_TECHNIQUE').iterdir()))
        self.assertTrue(Path(row['staged_path']).exists())
    def test_E_F_commerce_product_and_business_isolation(self):
        row=self.upload(self.sources/'1.mp4',pool='COMMERCE_PRODUCT_INTRO',product='product_a')
        catalog=ProductionMaterialCatalog(self.config)
        self.assertEqual(len(catalog.for_commerce('product_a','COMMERCE_PRODUCT_INTRO')),1)
        self.assertEqual(catalog.for_commerce('product_b','COMMERCE_PRODUCT_INTRO'),[])
        self.assertEqual(catalog.query(business_type='STARTUP'),[])
        self.assertFalse(list((self.root/'STARTUP_TECHNIQUE').iterdir()))
        self.assertTrue(Path(row['destination']).is_relative_to(self.root/'COMMERCE_PRODUCT_INTRO'/'product_a'))
        self.upload(self.sources/'2.mp4',pool='COMMERCE_PRODUCT_INTRO')
        self.assertEqual(len(catalog.for_commerce('product_a','COMMERCE_PRODUCT_INTRO')),2)
        self.assertEqual(len(catalog.for_commerce('product_b','COMMERCE_PRODUCT_INTRO')),1)
    def test_G_no_raw_index_changes(self):
        raw=self.root/'raw';raw.mkdir();p=raw/'video_index_fixed.db';p.write_bytes(b'untouched raw index fixture')
        before=(p.stat().st_mtime_ns,sha256(p));self.upload(self.sources/'0.mp4')
        self.assertEqual(before,(p.stat().st_mtime_ns,sha256(p)))
        with self.assertRaisesRegex(ValueError,'PROTECTED_DIRECTORY'):self.store.configure_pool('COMMERCE_HOOK_CLINIC',str(raw))
    def test_H_background_binding_catalog_immediately_visible(self):
        row=self.upload(self.sources/'background.png',pool='VISUAL_BACKGROUND')
        self.assertEqual(row['state'],'LIBRARY_READY')
        from account_visuals.storage import AccountBackgroundStore
        records=AccountBackgroundStore(self.config['operations_db']).catalog()
        self.assertEqual(len(records),1);self.assertEqual(records[0]['hash'],row['content_hash'])
        self.assertEqual(ProductionMaterialCatalog(self.config).query(business_type='STARTUP'),[])
        with closing(sqlite3.connect(self.config['operations_db'])) as db, db:self.assertEqual(db.execute('SELECT count(*) FROM account_background_bindings').fetchone()[0],0)
    def test_resume_and_wrong_chunk_hash(self):
        row,data=self.create(self.sources/'0.mp4');key,token=row['upload_id'],row['token'];block=data[:1024]
        with self.assertRaisesRegex(UploadError,'CHUNK_HASH_MISMATCH'):
            self.engine.chunk(key,token,0,len(block),io.BytesIO(block),'0'*64)
        self.assertEqual(Path(self.engine.get(key)['staged_path']).stat().st_size,0)
        self.engine.chunk(key,token,0,len(block),io.BytesIO(block),hashlib.sha256(block).hexdigest())
        with open(self.engine.get(key)['staged_path'],'ab') as f:f.write(b'uncommitted')
        resumed=Ingest(self.store);resumed.recover()
        self.assertEqual(Path(resumed.get(key)['staged_path']).stat().st_size,1024)
        for offset in range(1024,len(data),1024):
            part=data[offset:offset+1024];resumed.chunk(key,token,offset,len(part),io.BytesIO(part),hashlib.sha256(part).hexdigest())
        resumed.finalize(key,token);resumed.process(key);self.assertEqual(resumed.get(key)['state'],'LIBRARY_READY')
    def test_long_video_requires_explicit_confirmation(self):
        self.engine.config['long_video_seconds']=0.1
        row=self.upload(self.sources/'0.mp4');self.assertEqual(row['state'],'NEEDS_CONFIRMATION')
        self.assertFalse(list((self.root/'STARTUP_TECHNIQUE').iterdir()))
        # 长文件仍保留，确认后才正式入库。
        with self.store.connect() as db:token_hash=db.execute('SELECT token_hash FROM uploads').fetchone()[0]
        self.store.transition(row['upload_id'],'STAGED',long_confirmed=1)
        self.engine.process(row['upload_id']);self.assertEqual(self.engine.get(row['upload_id'])['state'],'LIBRARY_READY')
    def test_disk_reservations_and_path_traversal(self):
        for name in ('../bad.mp4','C:\\bad.mp4','CON.mp4','trailing.mp4 ','evil:stream.mp4'):
            with self.assertRaises(ValueError):safe_filename(name)
        with patch('production_materials.ingest.shutil.disk_usage') as usage:
            usage.return_value.free=10
            with self.assertRaisesRegex(UploadError,'DISK_SPACE_INSUFFICIENT'):self.create(self.sources/'0.mp4')
        with self.assertRaisesRegex(UploadError,'INVALID_PRODUCT_SCOPE'):
            self.create(self.sources/'0.mp4',product='product_a')
    def test_commit_restart_no_second_material(self):
        row=self.upload(self.sources/'0.mp4');destination=Path(row['destination']);mtime=destination.stat().st_mtime_ns
        self.store.transition(row['upload_id'],'COMMITTING');self.engine.process(row['upload_id'])
        self.assertEqual(destination.stat().st_mtime_ns,mtime)
        self.assertEqual(len(ProductionMaterialCatalog(self.config).query()),1)
    def test_existing_material_dedup_without_full_library_hash(self):
        source=self.sources/'0.mp4';target=self.root/'STARTUP_TECHNIQUE'/'existing.mp4';target.write_bytes(source.read_bytes())
        self.store.metadata_inventory()
        self.assertEqual(self.upload(source,'renamed.mp4')['state'],'DUPLICATE_SKIPPED')
    def test_batch_accepts_multiple_files_and_preserves_one_batch(self):
        values=[(self.sources/f'{i}.mp4').read_bytes() for i in range(3)]
        batch=self.engine.create_batch({'pool_id':'STARTUP_TECHNIQUE','files':[
            dict(filename=f'batch-{i}.mp4',size=len(data),fingerprint=hashlib.sha256(data).hexdigest()) for i,data in enumerate(values)]})
        for upload,data in zip(batch['uploads'],values):
            for offset in range(0,len(data),1024):
                part=data[offset:offset+1024]
                self.engine.chunk(upload['upload_id'],upload['token'],offset,len(part),io.BytesIO(part),hashlib.sha256(part).hexdigest())
            self.engine.finalize(upload['upload_id'],upload['token']);self.engine.process(upload['upload_id'])
        materials=ProductionMaterialCatalog(self.config).query()
        self.assertEqual(len(materials),3)
        self.assertEqual({m['ingest_batch_id'] for m in materials},{batch['ingest_batch_id']})
    def test_revision_clears_only_material_views(self):
        from types import SimpleNamespace
        from production_materials.ui import refresh_catalog_views
        session={'production_material_revision':0,'studio_generation_sources':'cached',
            'startup_snapshot:db:user:account:catalog':'cached',
            'startup_snapshot:db:user:account:profile':'unchanged','selected_account':'account_a'}
        self.upload(self.sources/'0.mp4')
        fake=SimpleNamespace(session_state=session,markdown=lambda *a,**kw:None)
        with patch('production_materials.ui.settings',return_value=self.config):refresh_catalog_views(fake)
        self.assertNotIn('studio_generation_sources',session);self.assertNotIn('startup_snapshot:db:user:account:catalog',session)
        self.assertEqual(session['startup_snapshot:db:user:account:profile'],'unchanged');self.assertEqual(session['selected_account'],'account_a')
    def test_commerce_directory_configuration_isolated_and_not_moved(self):
        target=self.root/'new-commerce';target.mkdir()
        self.store.configure_pool('COMMERCE_HOOK_CLINIC',str(target))
        row=self.upload(self.sources/'0.mp4',pool='COMMERCE_HOOK_CLINIC',product='product_a')
        self.assertTrue(Path(row['destination']).is_relative_to(target))
        other=self.root/'other';other.mkdir()
        with self.assertRaisesRegex(ValueError,'CONFIGURED_POOL_IN_USE_NO_MOVE'):
            self.store.configure_pool('COMMERCE_HOOK_CLINIC',str(other))
    def test_http_guards_bounded_upload_and_preview_range(self):
        server=Server(('127.0.0.1',0),self.engine);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        def request(path,body=None,headers=None,method=None):
            req=urllib.request.Request(base+path,data=body,headers=headers or {},method=method)
            return urllib.request.urlopen(req,timeout=5)
        try:
            with request('/api/bootstrap') as response:self.assertNotIn('root',json.load(response)['pools'][0])
            with self.assertRaises(urllib.error.HTTPError) as rejected:request('/api/batches',b'{}')
            self.assertEqual(rejected.exception.code,403)
            rejected.exception.close()
            data=(self.sources/'0.mp4').read_bytes()
            payload=json.dumps({'pool_id':'STARTUP_TECHNIQUE','files':[{'filename':'http.mp4','size':len(data),'fingerprint':hashlib.sha256(data).hexdigest()}]}).encode()
            with request('/api/batches',payload,{'Origin':base}) as response:row=json.load(response)['uploads'][0]
            for offset in range(0,len(data),1024):
                block=data[offset:offset+1024]
                with request('/api/uploads/'+row['upload_id']+'?offset='+str(offset),block,
                        {'Origin':base,'X-Upload-Token':row['token'],'X-Chunk-SHA256':hashlib.sha256(block).hexdigest()},'PUT') as response:
                    self.assertEqual(json.load(response)['received'],offset+len(block))
            with request('/api/uploads/'+row['upload_id']+'/finalize',b'{}',{'Origin':base,'X-Upload-Token':row['token']}) as response:response.read()
            self.engine.process(row['upload_id']);material=self.engine.get(row['upload_id'])['material_id']
            with request('/api/materials?pool_id=STARTUP_TECHNIQUE&limit=1') as response:
                page=json.load(response);self.assertEqual(page['total'],1);self.assertEqual(len(page['materials']),1)
            with request('/api/materials?pool_id=STARTUP_TECHNIQUE&limit=1&offset=1') as response:
                self.assertEqual(json.load(response)['materials'],[])
            with request('/api/materials/'+material+'/media',headers={'Range':'bytes=0-31'}) as response:
                self.assertEqual(response.status,206);self.assertEqual(response.read(),data[:32])
        finally:server.shutdown();server.server_close();thread.join(5)

if __name__=='__main__':unittest.main(verbosity=2)
