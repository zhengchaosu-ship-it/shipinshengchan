"""维护层自己的原子文件写入，有限重试Windows短暂共享占用。"""
import json
import os
from pathlib import Path
import time
import uuid


def atomic_text(path,text):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('w',encoding='utf-8') as target:
            target.write(text); target.flush(); os.fsync(target.fileno())
        for attempt in range(6):
            try:
                os.replace(temp,path); return
            except PermissionError:
                if attempt==5:raise
                time.sleep(.1*(attempt+1))
    finally:
        if temp.exists():temp.unlink()


def write_json(path,value):
    atomic_text(path,json.dumps(value,ensure_ascii=False,indent=2))
