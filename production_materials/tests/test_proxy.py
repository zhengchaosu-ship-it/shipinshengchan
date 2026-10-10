"""同源代理真实HTTP分片、隔离入库、续传及路径权限回归。"""
import hashlib
import json
import threading
import unittest

import httpx
from starlette.applications import Starlette
from starlette.routing import Mount

from production_materials.proxy import MaterialProxy, PREFIX
from production_materials.service import Server
from production_materials.tests import test_portal as portal_fixture


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        portal_fixture.PortalTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        portal_fixture.PortalTests.tearDownClass()

    async def asyncSetUp(self):
        self.fixture = portal_fixture.PortalTests('test_B_hash_dedup_renamed_file')
        self.fixture.setUp()
        self.server = Server(('127.0.0.1',0),self.fixture.engine)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        config = dict(self.fixture.config,port=self.server.server_port)
        self.app = Starlette(routes=[Mount(PREFIX,app=MaterialProxy(config))])
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app,client=('127.0.0.1',53000)),
                                       base_url='http://127.0.0.1:8502',headers={'Origin':'http://127.0.0.1:8502'})

    async def asyncTearDown(self):
        await self.client.aclose()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.fixture.tearDown()

    async def create(self, name='proxy-test.mp4'):
        data = (self.fixture.sources/'0.mp4').read_bytes()
        response = await self.client.post(PREFIX+'/api/batches',json={
            'pool_id':'STARTUP_TECHNIQUE','files':[{'filename':name,'size':len(data),'fingerprint':hashlib.sha256(data).hexdigest()}]})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()['uploads'][0],data

    async def put(self, row, data, offset=0, digest=None):
        return await self.client.put(PREFIX+'/api/uploads/'+row['upload_id']+'?offset='+str(offset),content=data,
                                     headers={'X-Upload-Token':row['token'],'X-Chunk-SHA256':digest or hashlib.sha256(data).hexdigest()})

    async def complete(self,row,data,offset=0):
        for start in range(offset,len(data),1024):
            response = await self.put(row,data[start:start+1024],start)
            self.assertEqual(response.status_code,200,response.text)
        response = await self.client.post(PREFIX+'/api/uploads/'+row['upload_id']+'/finalize',json={},headers={'X-Upload-Token':row['token']})
        self.assertEqual(response.status_code,202,response.text)
        self.fixture.engine.process(row['upload_id'])
        return self.fixture.engine.get(row['upload_id'])

    async def test_portal_assets_bootstrap_and_embed_policy_same_origin(self):
        for path in ('/','/portal.js','/portal.css','/api/bootstrap','/health'):
            response = await self.client.get(PREFIX+path)
            self.assertEqual(response.status_code,200,response.text)
        response = await self.client.get(PREFIX+'/')
        self.assertIn('href="./portal.css"',response.text)
        self.assertIn('src="./portal.js"',response.text)
        self.assertNotIn(':8510',response.text)
        self.assertIn('http://127.0.0.1:8502',response.headers['content-security-policy'])

    async def test_actual_chunks_progress_commit_and_dedup(self):
        row,data = await self.create()
        stored = await self.complete(row,data)
        self.assertEqual(stored['state'],'LIBRARY_READY')
        second,_ = await self.create('renamed.mp4')
        duplicate = await self.complete(second,data)
        self.assertEqual(duplicate['state'],'DUPLICATE_SKIPPED')
        self.assertEqual(len(list((self.fixture.root/'STARTUP_TECHNIQUE').glob('*.mp4'))),1)

    async def test_retry_queries_existing_offset_and_wrong_hash_safe(self):
        row,data = await self.create()
        self.assertEqual((await self.put(row,data[:1024])).status_code,200)
        response = await self.put(row,data[1024:2048],1024,'0'*64)
        self.assertEqual(response.status_code,400)
        current = await self.client.get(PREFIX+'/api/uploads/'+row['upload_id'],headers={'X-Upload-Token':row['token']})
        self.assertEqual(current.json()['received'],1024)
        self.assertEqual((await self.complete(row,data,1024))['state'],'LIBRARY_READY')

    async def test_cross_origin_host_and_outside_lan_rejected(self):
        self.assertEqual((await self.client.post(PREFIX+'/api/batches',json={},headers={'Origin':'http://evil.invalid'})).status_code,403)
        self.assertEqual((await self.client.get(PREFIX+'/health',headers={'Host':'evil.invalid:8502'})).status_code,403)
        self.assertEqual((await self.client.get(PREFIX+'/health',headers={'X-Forwarded-For':'192.168.1.2'})).status_code,403)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app,client=('8.8.8.8',53000)),base_url='http://127.0.0.1:8502') as outside:
            self.assertEqual((await outside.get(PREFIX+'/health')).status_code,403)

    async def test_paths_tokens_size_and_methods_rejected(self):
        response = await self.client.post(PREFIX+'/api/batches',json={'pool_id':'STARTUP_TECHNIQUE','root':'C:/Windows','files':[]})
        self.assertEqual(response.status_code,400)
        response = await self.client.post(PREFIX+'/api/batches',json={'pool_id':'STARTUP_TECHNIQUE','files':[{'filename':'../bad.mp4','size':10}]})
        self.assertEqual(response.status_code,400)
        row,data = await self.create()
        response = await self.client.get(PREFIX+'/api/uploads/'+row['upload_id'],
                                        headers={'X-Upload-Token':'incorrect'})
        self.assertEqual(response.status_code,403)
        response = await self.client.put(PREFIX+'/api/uploads/'+row['upload_id']+'?offset=0',content=b'x',headers={'Content-Length':'5000000'})
        self.assertEqual(response.status_code,413)
        self.assertEqual((await self.client.delete(PREFIX+'/api/uploads/'+row['upload_id'])).status_code,405)

    async def test_media_range_streams_without_whole_file(self):
        row,data = await self.create()
        stored = await self.complete(row,data)
        response = await self.client.get(PREFIX+'/api/materials/'+stored['material_id']+'/media',headers={'Range':'bytes=0-99'})
        self.assertEqual(response.status_code,206)
        self.assertEqual(response.content,data[:100])
        self.assertEqual(response.headers['content-length'],'100')

    async def test_backend_down_reports_recoverable_service_error(self):
        config = dict(self.fixture.config,port=1)
        app = Starlette(routes=[Mount(PREFIX,app=MaterialProxy(config))])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',53000)),base_url='http://127.0.0.1:8502') as client:
            response = await client.get(PREFIX+'/health')
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json()['error'],'MATERIAL_SERVICE_UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
