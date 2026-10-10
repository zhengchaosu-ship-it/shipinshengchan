"""官方固定revision权重分块续传；只补下载同一模型，不更换来源/模型。"""
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from prepare_model import MODEL,REVISION,MODEL_DIR,OUT,FILES
from speech_search.common import sha256,write_json


def main():
    api=f'https://huggingface.co/api/models/{MODEL}/revision/{REVISION}?blobs=true'
    with urllib.request.urlopen(api,timeout=30) as r:data=json.load(r)
    weight=next(x for x in data['siblings'] if x['rfilename']=='model.safetensors')
    size=weight['size'];expected=weight['lfs']['sha256'];target=MODEL_DIR/'model.safetensors';part=MODEL_DIR/'model.safetensors.part'
    if not target.exists():
        offset=part.stat().st_size if part.exists() else 0
        def chunk_at(start):
                end=min(size-1,start+4*1024*1024-1)
                url=f'https://huggingface.co/{MODEL}/resolve/{REVISION}/model.safetensors?download=true&chunk={start}&end={end}'
                for attempt in range(3):
                    try:
                        req=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}'})
                        with urllib.request.urlopen(req,timeout=45) as response:
                            if response.status!=206 or response.headers.get('Content-Range')!=f'bytes {start}-{end}/{size}':raise RuntimeError('Range响应不符，停止保留断点')
                            chunk=response.read()
                        if len(chunk)!=end-start+1:raise RuntimeError('分块长度不符')
                        break
                    except Exception:
                        if attempt==2:raise
                        time.sleep(2)
                return chunk
        with part.open('ab') as f,ThreadPoolExecutor(max_workers=8) as pool:
            while offset<size:
                starts=list(range(offset,min(size,offset+8*4*1024*1024),4*1024*1024))
                for chunk in pool.map(chunk_at,starts):
                    f.write(chunk);f.flush();offset+=len(chunk)
                    write_json(OUT/'download_progress.json',dict(bytes=offset,total=size,revision=REVISION))
                    print(offset,size,round(offset/size*100,1),flush=True)
        if sha256(part)!=expected:raise RuntimeError('下载权重SHA与官方LFS不符，不加载')
        part.replace(target)
    if sha256(target)!=expected:raise RuntimeError('现有权重SHA与官方不符')
    write_json(OUT/'model_manifest.json',dict(model=MODEL,revision=REVISION,weight_official_sha256=expected,
        files={n:dict(size=(MODEL_DIR/n).stat().st_size,sha256=sha256(MODEL_DIR/n)) for n in FILES}))
    print('RERANKER_MODEL_READY',flush=True)


if __name__=='__main__':main()
