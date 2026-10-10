"""受限现场验收：只提交已确认存在的同hash副本，绝不制作生产测试视频。"""
from pathlib import Path
from urllib.request import Request,urlopen
from contextlib import closing
import hashlib
import json
import sqlite3
import time
from production_materials.config import HERE,settings

def main():
    config=settings();base='http://192.168.1.126:8510'
    source=HERE/'runtime/acceptance_20261007/upload-smoke-renamed.mp4'
    expected='bf8e2e5f8924149aa02aa51ec1f9ef8bfaa33e0b93a6f4abddb713cdea2cedfd'
    with source.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==expected
    with closing(sqlite3.connect(Path(config['database']).as_uri()+'?mode=ro',uri=True)) as db:
        original=db.execute("SELECT path FROM legacy_inventory WHERE pool_id='STARTUP_TECHNIQUE' AND content_hash=? AND available=1",(expected,)).fetchone()
        assert original and Path(original[0]).is_file()
    def request(path,data=None,token=None,method=None,raw=False,extra=None):
        headers={'Origin':base};headers.update(extra or {})
        if token:headers['X-Upload-Token']=token
        if data is not None and not raw:data=json.dumps(data).encode();headers['Content-Type']='application/json'
        with urlopen(Request(base+path,data=data,headers=headers,method=method),timeout=30) as response:return json.load(response)
    before=request('/api/overview')
    batch=request('/api/batches',{'pool_id':'STARTUP_TECHNIQUE','files':[dict(filename='portal-lan-validation.mp4',size=source.stat().st_size,fingerprint=expected)]})
    upload=batch['uploads'][0];offset=0;chunks=0
    with source.open('rb') as stream:
        while block:=stream.read(batch['chunk_bytes']):
            result=request('/api/uploads/'+upload['upload_id']+'?offset='+str(offset),block,upload['token'],'PUT',True,{'X-Chunk-SHA256':hashlib.sha256(block).hexdigest()})
            offset=result['received'];chunks+=1
    request('/api/uploads/'+upload['upload_id']+'/finalize',{},upload['token'])
    for _ in range(40):
        row=request('/api/uploads/'+upload['upload_id'],token=upload['token'])
        if row['state'] in ('LIBRARY_READY','DUPLICATE_SKIPPED','QUARANTINED','ATTENTION_REQUIRED'):break
        time.sleep(.5)
    after=request('/api/overview')
    assert row['state']=='DUPLICATE_SKIPPED',row['state']
    assert [p['count'] for p in before['pools']]==[p['count'] for p in after['pools']]
    result=dict(lan_service=base,state=row['state'],bytes_received=offset,chunks=chunks,
                production_pool_counts_unchanged=True,new_production_materials=0,render_jobs_created=0,publish_calls=0)
    (HERE/'runtime/acceptance_20261007/lan-upload.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
