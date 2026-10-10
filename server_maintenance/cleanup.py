"""只清理明确登记的SAFE_TEMP/CACHE文件；默认清单为空。"""
import hashlib
import json
from pathlib import Path
import time

from .precheck import ROOT

PROTECTED = {'video_index_fixed.db','video_index.db','operations.db','faiss_index.bin','faiss_meta.pkl'}


def clean_entries(manifest, *, root=ROOT, now=None, record=None):
    now=time.time() if now is None else now; root=Path(root).resolve(); results=[]
    for entry in manifest.get('files',[]):
        try:
            if entry.get('classification') not in ('SAFE_TEMP','CACHE') or not entry.get('approved'):
                continue
            original=root/entry['path']; path=original.resolve()
            if not path.is_relative_to(root) or path.name in PROTECTED:
                raise ValueError('PROTECTED_OR_OUTSIDE_WORKSPACE')
            # 任一祖先为junction/reparse都拒绝，防止借TTL清单间接删除生产素材。
            if any(p.is_symlink() or p.is_junction() for p in (original,*original.parents)):
                raise ValueError('REPARSE_PATH_REFUSED')
            protected_roots=('dino_index','clip_index','speech_search','models','raw_assets','production_materials','production_materials','startup_render/runtime','yixiaoer_adapter/runtime/jobs')
            relative=path.relative_to(root).as_posix()
            if any(relative==p or relative.startswith(p+'/') for p in protected_roots):
                raise ValueError('PRODUCTION_ROOT_REFUSED')
            if not path.is_file(): continue
            ttl=float(entry['ttl_seconds'])
            if ttl<=0 or now-path.stat().st_mtime<ttl: continue
            size=path.stat().st_size
            if size!=entry['size_bytes'] or size>1024**3: raise ValueError('FILE_CHANGED_OR_LARGE')
            checksum=hashlib.sha256(path.read_bytes()).hexdigest()
            if checksum!=entry['sha256']:raise ValueError('FILE_CHANGED')
            proof={'path':str(path),'size_bytes':size,'sha256':checksum,'classification':entry['classification'],'ttl_seconds':ttl}
            if record: record('EXPIRED_SAFE_TEMP',proof,'DELETE_APPROVED_TTL_FILE',proof,None,'INTENT')
            path.unlink()
            if record: record('EXPIRED_SAFE_TEMP',proof,'DELETE_APPROVED_TTL_FILE',proof,{'exists':False},'COMPLETE')
            results.append(dict(proof,result='DELETED'))
        except (OSError,ValueError,KeyError,TypeError) as error:
            results.append({'path':entry.get('path'),'result':'REFUSED','reason':str(error)})
    return results
