"""有限目录元数据清单，Shadow不读取整段视频、不扫描检索库。"""
import os
import hashlib
from pathlib import Path

from .models import digest

DEFAULT_POOLS = (
    ('引流',r'E:\备份\起号手法\引流话术'),
    ('手法',r'E:\备份\起号手法\手法绿幕'),
    ('坐诊',r'E:\备份\精简'),
    ('收尾',r'E:\备份\起号手法\收尾'),
)
VIDEO_EXTENSIONS={'.mp4','.mov','.mkv','.avi','.m4v','.webm'}


def inventory(pools=DEFAULT_POOLS, *, max_files_per_pool=64, max_entries_per_pool=4096):
    result=[]
    for module,root_value in pools:
        root=Path(root_value).resolve()
        files,issues,visited=[],[],0
        directories=[root]
        while directories and len(files)<max_files_per_pool and visited<max_entries_per_pool:
            folder=directories.pop(0)
            try:
                with os.scandir(folder) as scan:
                    entries=sorted(scan,key=lambda item:item.name.casefold())
                for entry in entries:
                    visited+=1
                    if visited>max_entries_per_pool or len(files)>=max_files_per_pool:
                        break
                    if entry.is_symlink():
                        continue
                    path=Path(entry.path)
                    if entry.is_dir(follow_symlinks=False):
                        directories.append(path)
                    elif path.suffix.lower() in VIDEO_EXTENSIONS and entry.is_file(follow_symlinks=False):
                        # Windows DirEntry.stat可能返回st_ino=0；Path.stat查询真实文件索引。
                        stat=path.stat(follow_symlinks=False)
                        if stat.st_size<=0 or not stat.st_ino:
                            issues.append({'path':str(path),'reason':'EMPTY_OR_UNSTABLE_FILE_ID'});continue
                        files.append({'material_id':'SHADOW-FILE-'+digest([stat.st_dev,stat.st_ino])[:32],
                                      'module_type':module,'path':str(path.resolve()),'filename':path.name,
                                      'size_bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns,
                                      'filesystem_identity':[stat.st_dev,stat.st_ino],
                                      'media_sha256':None,'duration_seconds':None,
                                      'identity_status':'SHADOW_FILESYSTEM_ID_MEDIA_HASH_PENDING'})
            except OSError as exc:
                issues.append({'path':str(folder),'reason':type(exc).__name__})
        # 同一NTFS对象的路径别名不增加素材数量。
        unique={item['material_id']:item for item in files}
        result.append({'module_type':module,'root':str(root),'files':list(unique.values()),
                       'issues':issues,'entries_visited':visited,'bounded':True,
                       'truncated':bool(directories) or len(files)>=max_files_per_pool or visited>=max_entries_per_pool})
    return result


def verify_material(item):
    path=Path(item['path'])
    if not path.is_file():
        raise ValueError('SHADOW_MATERIAL_MISSING')
    stat=path.stat()
    if [stat.st_dev,stat.st_ino]!=item['filesystem_identity'] or stat.st_size!=item['size_bytes'] or stat.st_mtime_ns!=item['mtime_ns']:
        raise ValueError('SHADOW_MATERIAL_CHANGED')
    return True


def content_sample(catalog, *, maximum_per_pool=5):
    """只为少量Shadow样本计算完整SHA，识别改名副本；不处理全素材库。"""
    sampled=[]
    for pool in catalog:
        by_hash={}
        chosen=sorted(pool['files'],key=lambda m:(m['size_bytes'],m['filename']))[:maximum_per_pool]
        for item in chosen:
            verify_material(item)
            with open(item['path'],'rb') as source:
                sha=hashlib.file_digest(source,'sha256').hexdigest()
            if sha in by_hash:
                by_hash[sha]['aliases'].append(item['path'])
                continue
            by_hash[sha]={**item,'material_id':'MEDIA-SHA256-'+sha,'media_sha256':sha,
                          'identity_status':'CONTENT_SHA256_VERIFIED','aliases':[item['path']]}
        sampled.append({**pool,'files':list(by_hash.values()),'metadata_file_count':len(pool['files']),
                        'content_sample_limit':maximum_per_pool,'full_pool_hashed':len(chosen)==len(pool['files'])})
    return sampled
