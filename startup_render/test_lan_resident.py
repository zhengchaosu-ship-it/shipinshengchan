"""LAN通信/归属/租约/缓存隔离回归，不启动剪映或发布。"""
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from .common import digest, output_relative, save
from .lan_protocol import LanRegistry
from .lan_server import Handler
from .lan_transport import Transport
from .server import Broker


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.batches=self.root/'batches'; self.batches.mkdir()
        self.assets=self.root/'assets'; self.assets.mkdir()
        self.control=self.root/'control.json'
        save(self.control,{'enabled':True})
        self.config={'state_root':str(self.root/'server'),'batch_root':str(self.batches),
            'startup_assets_root':str(self.assets),'startup_assets_unc':r'\\host\StartupAssets',
            'task_files_unc':r'\\host\StartupTaskFiles','result_root':str(self.root/'outputs'),
            'worker_ids':['WORKER-A','WORKER-B'],'claim_control_file':str(self.control),'allowed_clients':['127.0.0.1']}
        self.broker=Broker(self.config)
        self.now=1000
        self.registry=LanRegistry(self.broker,clock=lambda:self.now)
        for w in ('WORKER-A','WORKER-B'):
            self.registry.register({'worker_id':w,'status':'IDLE'})
        self.identity={'job_id':'CONTENT-ONE','content_id':'CONTENT-ONE','batch_id':'BATCH-ONE',
                       'video_index':1,'business_type':'STARTUP','draft_name':'丙曜起号10月4日-1',
                       'target_account_id':'1621131832863931','files':[]}
        with self.broker.connect() as db:
            db.execute("INSERT INTO jobs(job_id,batch_id,video_index,status,payload) VALUES(?,?,1,'QUEUED',?)",
                       ('CONTENT-ONE','BATCH-ONE',json.dumps(self.identity)))

    def tearDown(self):
        self.temp.cleanup()

    def claim(self,w='WORKER-A'):
        return self.registry.claim({'worker_id':w})

    def test_atomic_two_worker_claim(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(self.claim,('WORKER-A','WORKER-B')))
        self.assertEqual(sum(r is not None for r in results),1)
        with self.broker.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lan_leases').fetchone()[0],1)

    def test_repeat_claim_same_owner_same_token(self):
        one,two=self.claim(),self.claim()
        self.assertEqual(one,two)

    def test_configured_two_workers_claim_distinct_jobs_and_keep_owner(self):
        self.config['max_parallel_jobs']=2
        second=dict(self.identity,job_id='CONTENT-TWO',content_id='CONTENT-TWO',video_index=2)
        with self.broker.connect() as db:
            db.execute("INSERT INTO jobs(job_id,batch_id,video_index,status,payload) VALUES(?,?,2,'QUEUED',?)",('CONTENT-TWO','BATCH-ONE',json.dumps(second)))
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(self.claim,('WORKER-A','WORKER-B')))
        self.assertTrue(all(results));self.assertEqual(len({r['manifest']['job_id'] for r in results}),2)
        self.assertEqual(self.claim('WORKER-A')['claim'],results[0]['claim'])
        self.assertEqual(self.claim('WORKER-B')['claim'],results[1]['claim'])

    def test_other_worker_cannot_receive_active_job(self):
        self.claim()
        self.assertIsNone(self.claim('WORKER-B'))

    def test_lease_expiry_does_not_repeat_export(self):
        first=self.claim(); self.now+=121
        self.assertIsNone(self.claim('WORKER-B'))
        with self.broker.connect() as db:
            self.assertEqual(db.execute('SELECT stage FROM lan_leases').fetchone()[0],
                             'LEASE_EXPIRED_NEEDS_RECONCILIATION')
        self.assertEqual(self.claim()['claim'],first['claim'])

    def test_worker_offline_retained(self):
        self.now+=100
        self.assertEqual(len(self.registry.workers()),2)
        self.assertEqual(self.registry.workers()[0]['status'],'OFFLINE')

    def test_heartbeat_idempotent_and_renews_owned_lease(self):
        self.claim(); self.now+=30
        value={'worker_id':'WORKER-A','status':'BUSY','current_job_id':'CONTENT-ONE'}
        self.registry.register(value); self.registry.register(value)
        with self.broker.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lan_workers').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT expires_at FROM lan_leases').fetchone()[0],1150)

    def test_foreign_status_denied(self):
        claimed=self.claim()
        with self.assertRaisesRegex(PermissionError,'WORKER_CLAIM_MISMATCH'):
            self.registry.status('CONTENT-ONE',{'worker_id':'WORKER-B','claim':claimed['claim'],'stage':'DRAFT_READY'})

    def test_halted_worker_not_claiming(self):
        self.registry.register({'worker_id':'WORKER-A','status':'HALTED_NEEDS_MANUAL'})
        with self.assertRaises(PermissionError): self.claim()

    def test_control_prevents_second_batch(self):
        save(self.control,{'enabled':True,'allowed_batch_ids':['OTHER-BATCH']})
        self.assertIsNone(self.claim())
        save(self.control,{'enabled':False})
        self.assertIsNone(self.claim())

    def test_unknown_worker_denied(self):
        with self.assertRaises(PermissionError):
            self.registry.register({'worker_id':'INTRUDER'})

    def test_repeat_failure_saved_once_and_changed_failure_denied(self):
        claimed=self.claim()
        receipt={'claim':claimed['claim'],'status':'NEEDS_MANUAL','error':'SMOKE_ONLY','real_publish_attempts':0}
        value={'worker_id':'WORKER-A','claim':claimed['claim'],'receipt':receipt}
        self.assertTrue(self.registry.finish('CONTENT-ONE',value,complete=False)['saved'])
        self.assertTrue(self.registry.finish('CONTENT-ONE',value,complete=False)['saved'])
        value['receipt']=dict(receipt,error='CHANGED')
        with self.assertRaisesRegex(ValueError,'RESULT_IMMUTABLE'):
            self.registry.finish('CONTENT-ONE',value,complete=False)

    def test_complete_without_real_output_denied(self):
        claimed=self.claim()
        with self.assertRaisesRegex(ValueError,'SERVER_OUTPUT_HASH_MISMATCH'):
            self.registry.finish('CONTENT-ONE',{'worker_id':'WORKER-A','claim':claimed['claim'],
                'receipt':{'claim':claimed['claim'],'status':'COMPLETED','media':{'sha256':'0'*64}}},complete=True)

    def test_repeat_success_ack_does_not_run_ready_twice(self):
        claimed=self.claim()
        identity=claimed['manifest']
        target=Path(self.config['result_root'])/output_relative(identity)
        target.parent.mkdir(parents=True); target.write_bytes(b'isolated-not-video')
        receipt={'claim':claimed['claim'],'status':'COMPLETED','media':{'sha256':digest(target)}}
        value={'worker_id':'WORKER-A','claim':claimed['claim'],'receipt':receipt}
        with patch.object(self.broker,'receipt') as callback:
            self.registry.finish('CONTENT-ONE',value,complete=True)
            self.registry.finish('CONTENT-ONE',value,complete=True)
            callback.assert_called_once()

    def test_repeated_heartbeat_timestamp_no_duplicate_history(self):
        value={'worker_id':'WORKER-A','status':'IDLE','timestamp':'2026-10-04T09:00:00Z'}
        self.registry.register(value); self.registry.register(value)
        with self.broker.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM lan_heartbeat_history WHERE timestamp=?',
                (value['timestamp'],)).fetchone()[0],1)

    def test_auth_required_json_only(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        server.broker=self.broker; server.registry=self.registry; server.token='x'*44
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with self.assertRaises(urllib.error.HTTPError) as error:
                opener.open(base+'/health')
            self.assertEqual(error.exception.code,403)
            error.exception.close()
            request=urllib.request.Request(base+'/health',headers={'Authorization':'Bearer '+'x'*44})
            with opener.open(request) as response:
                self.assertEqual(json.load(response)['transport'],'LAN_RESIDENT_V1')
            with self.assertRaises(urllib.error.HTTPError) as error:
                opener.open(urllib.request.Request(base+'/result/CONTENT-ONE',data=b'video',method='PUT'))
            self.assertEqual(error.exception.code,405)
            error.exception.close()
        finally:
            server.shutdown(); server.server_close()

    def test_direct_asset_and_frozen_template_paths(self):
        path=self.assets/'main.mp4'
        self.assertEqual(self.registry.source_unc('CONTENT-ONE',{'source':str(path),'relative':'assets/a.mp4'}),
                         str(Path(r'\\host\StartupAssets')/'main.mp4'))
        self.assertEqual(self.registry.source_unc('CONTENT-ONE',{'source':str(self.root/'template.json'),'relative':'draft/template.json'}),
                         str(Path(r'\\host\StartupTaskFiles')/'CONTENT-ONE'/'draft/template.json'))


class TransportTests(unittest.TestCase):
    def test_http_transient_retries_without_new_job(self):
        import io
        with patch.dict(os.environ,{'XUNZHEN_RENDER_TOKEN':'x'*44}):
            transport=Transport({'worker_id':'WORKER-A','server_url':'http://127.0.0.1:1'},sleeper=lambda _:None)
        with patch.object(transport.opener,'open',side_effect=[urllib.error.URLError('offline'),
             urllib.error.URLError('offline'),io.BytesIO(b'{"ok":true}')]) as opener:
            self.assertEqual(transport.call('/health'),{'ok':True})
            self.assertEqual(opener.call_count,3)

    def test_smb_transient_retries_without_rendering(self):
        import shutil
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'XUNZHEN_RENDER_TOKEN':'x'*44}):
            root=Path(temp); source=root/'tiny'; source.write_bytes(b'smoke')
            target=root/'received'/'tiny'
            t=Transport({'worker_id':'WORKER-A','server_url':'http://127.0.0.1:1'},sleeper=lambda _:None)
            original=shutil.copyfile
            tries=[]
            def flaky(a,b):
                tries.append(1)
                if len(tries)==1: raise OSError('storage offline')
                return original(a,b)
            with patch('startup_render.lan_transport.shutil.copyfile',side_effect=flaky):
                self.assertEqual(t.copy_verified(source,target,digest(source),5),'COPIED')
            self.assertEqual(len(tries),2)
            self.assertEqual(digest(source),digest(target))

    def test_cache_hash_and_output_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'XUNZHEN_RENDER_TOKEN':'x'*44}):
            root=Path(temp); source=root/'tiny.txt'; source.write_bytes(b'LAN non-production smoke')
            target=root/'cache'/'tiny.txt'
            transport=Transport({'worker_id':'WORKER-A','server_url':'http://127.0.0.1:1'})
            self.assertEqual(transport.copy_verified(source,target,digest(source),source.stat().st_size),'COPIED')
            self.assertEqual(transport.copy_verified(source,target,digest(source),source.stat().st_size),'CACHE_HIT')
            with self.assertRaisesRegex(ValueError,'TARGET_EXISTS_HASH_MISMATCH'):
                transport.copy_verified(source,target,'0'*64,source.stat().st_size)

    def test_local_and_server_names_use_stable_id(self):
        item={'content_id':'CONTENT-ONE','job_id':'CONTENT-ONE','batch_id':'BATCH-ONE','video_index':1,
              'target_account_id':'1621131832863931','draft_name':'丙曜起号10月4日-1','output_layout':'LAN_RESIDENT_V1'}
        self.assertEqual(output_relative(item),'CONTENT-ONE/丙曜起号10月4日-1.mp4')
        with patch.dict(os.environ,{'XUNZHEN_RENDER_TOKEN':'x'*44}):
            t=Transport({'worker_id':'WORKER-A','server_url':'http://127.0.0.1:1','local_jobs_root':'D:/JianyingRenderWorker/Jobs'})
            self.assertEqual(t.output_path(item),Path('D:/JianyingRenderWorker/Jobs/CONTENT-ONE/output/丙曜起号10月4日-1.mp4'))
        del item['output_layout']
        self.assertEqual(output_relative(item),'BATCH-ONE/丙曜起号10月4日-1.mp4')


if __name__=='__main__': unittest.main()
