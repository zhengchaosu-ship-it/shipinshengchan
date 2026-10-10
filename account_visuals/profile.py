"""账号视觉身份契约。预留字段为NULL，继续使用成熟生成器已有视觉参数。"""
import json
from pathlib import Path
from contextlib import closing
import sqlite3

RESERVED=('subtitle_style','font','logo','stickers','subject_position','subject_scale','chroma_key')


def visual_settings(path, account):
    result={name:None for name in RESERVED}
    path=Path(path)
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='account_visual_profiles'").fetchone():
            row=db.execute('SELECT settings_json FROM account_visual_profiles WHERE business_account_id=?',(account,)).fetchone()
            if row:
                settings=json.loads(row[0])
                # 预留参数尚未接入渲染时禁止写入无效承诺。
                if set(settings)-set(RESERVED) or any(value is not None for value in settings.values()):raise ValueError('VISUAL_SETTING_NOT_IMPLEMENTED')
                result.update(settings)
    return {'business_account_id':account,'schema_version':1,'settings':result,'use_existing_generator_settings':True}
