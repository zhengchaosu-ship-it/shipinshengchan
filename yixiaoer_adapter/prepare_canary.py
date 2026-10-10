"""本机管理员准备3条纯测试成片及灰度Preview；不创建Job、不调用供应商。"""
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import subprocess
import uuid

from PIL import Image, ImageDraw, ImageFont
from publish_planner.models import Plan
from .storage import ProviderStore, file_sha, cached_binding, audit
from .worker import interactive_identity

TITLE='蚁小二8502灰度测试'
DESCRIPTION='自动发布技术测试，无业务内容'


def prepare(store, config, owner_employee_id, *, clock=None):
    interactive_identity(config)
    now=clock or datetime.now(timezone(timedelta(hours=8)))
    root=Path(config['canary_dir']).resolve(); root.mkdir(parents=True,exist_ok=True)
    output=root/'prepared.json'
    if output.exists():
        return json.loads(output.read_text('utf-8'))
    account_id=config['test_business_account_id']
    with store.connect() as db:
        actor=db.execute('SELECT * FROM employees WHERE employee_id=? AND enabled=1',(owner_employee_id,)).fetchone()
        if not actor:
            raise PermissionError('CANARY_OWNER_REQUIRED')
        visible={a['account_id']:a for a in store._generation_accounts(db,actor,'STARTUP')}
        if account_id not in visible:
            raise PermissionError('CANARY_OWNER_ACCOUNT_PERMISSION_DENIED')
        binding=cached_binding(db,account_id,required=True)
        if binding['provider_account_id']!=config['test_provider_account_id']:
            raise PermissionError('CANARY_PROVIDER_ACCOUNT_MISMATCH')
        name=visible[account_id]['display_name']
    files=[]
    colors=['#253357','#254b3a','#4a3053']
    for index,color in enumerate(colors,1):
        frame=Image.new('RGB',(720,1280),color); draw=ImageDraw.Draw(frame)
        font=ImageFont.truetype(config['font'],46)
        draw.multiline_text((55,400),f'蚁小二8502灰度测试\n视频 {index} / 3\n纯测试，无业务素材',font=font,fill='white',spacing=35)
        cover=root/f'canary_{index}.jpg'; frame.save(cover,quality=95)
        video=root/f'canary_{index}.mp4'
        subprocess.run([config['ffmpeg'],'-hide_banner','-loglevel','error','-loop','1','-i',str(cover),'-f','lavfi','-i','anullsrc=r=44100:cl=stereo','-t','8','-c:v','libx264','-pix_fmt','yuv420p','-r','25','-c:a','aac','-shortest','-movflags','+faststart','-y',str(video)],check=True,capture_output=True,timeout=60)
        files.append({'index':index,'video_path':str(video),'cover_path':str(cover),'sha256':file_sha(video),'cover_sha256':file_sha(cover),'size':video.stat().st_size})
    from startup_pipeline.service import StartupPipeline
    pipeline=StartupPipeline(store)
    media=[pipeline.probe(f['video_path']) for f in files]
    generation=str(uuid.uuid4()); batch='YIXIAOER_CANARY_'+generation.replace('-',''); plan_id='YIXIAOER-CANARY-'+str(uuid.uuid4())
    content_ids=[]
    with store.connect(write=True) as db:
        # 只插入这3条新测试内容；不改任一历史内容、渲染任务或既有Plan。
        started=now.astimezone(timezone.utc).isoformat()
        db.execute('INSERT INTO startup_generation_runs VALUES(?,?,?,NULL)',(generation,owner_employee_id,started))
        db.execute('INSERT INTO startup_generation_bindings VALUES(?,?,?,?,?,?,?)',(generation,owner_employee_id,'STARTUP',account_id,name,batch,now.date().isoformat()))
        manifest=root/'batch_manifest.json'
        manifest.write_text(json.dumps({'batch_id':batch,'created_at':started,'videos':[{'video_index':f['index'],'status':'success','composition_signature':f['sha256'],'selected_materials':[]} for f in files]},ensure_ascii=False,indent=2),encoding='utf-8')
        db.execute('INSERT INTO startup_batches VALUES(?,?,?,?,?)',(batch,owner_employee_id,str(manifest),started,'[]'))
        for f,probe in zip(files,media):
            key='STARTUP-'+str(uuid.uuid4()); content_ids.append(key)
            db.execute("INSERT INTO startup_contents(content_id,batch_id,video_index,composition_signature,video_path,created_at,business_type,production_status,publish_status,materials_json,duration_seconds,size_bytes,mtime_ns,media_json) VALUES(?,?,?,?,?,?,'STARTUP','READY','NOT_SCHEDULED','[]',?,?,?,?)",(key,batch,f['index'],f['sha256'],f['video_path'],started,probe['duration_seconds'],probe['size_bytes'],probe['mtime_ns'],json.dumps(probe['media'],ensure_ascii=False)))
            db.execute('INSERT INTO startup_content_bindings VALUES(?,?,?,?,?,NULL)',(key,generation,account_id,name,TITLE+' '+str(f['index'])))
            audit(db,'CANARY_TEST_CONTENT_PREPARED',account_id=account_id,evidence={'content_id':key,'synthetic_only':True,'video_sha256':f['sha256'],'owner_employee_id':owner_employee_id})
        target=datetime.fromtimestamp(math.ceil((now.timestamp()+4*3600)/300)*300,now.tzinfo)
        if target.hour==23:
            target=(target+timedelta(days=1)).replace(hour=9,minute=0,second=0,microsecond=0)
        plan=Plan(plan_id,target.date(),target.date(),target.time().replace(tzinfo=None),(account_id,),tuple(f['video_path'] for f in files),daily_count=3,interval_minutes=15,title=TITLE,description=DESCRIPTION)
        db.execute('INSERT INTO yixiaoer_canary_plans VALUES(?,?,?,?,?)',(plan_id,owner_employee_id,json.dumps(content_ids),plan.payload(),started))
        db.execute("INSERT INTO startup_publish_profiles VALUES('startup-yixiaoer-canary','蚁小二灰度纯测试',?,?, '[]','DEFAULT',?) ON CONFLICT(profile_id) DO NOTHING",(TITLE,DESCRIPTION,started))
        db.execute('UPDATE startup_generation_runs SET batch_id=? WHERE generation_id=?',(batch,generation))
        value={'plan_id':plan_id,'employee_id':owner_employee_id,'business_account_id':account_id,'provider_account_id':binding['provider_account_id'],'content_ids':content_ids,'files':files,'plan_payload':json.loads(plan.payload()),'created_at':started,'status':'PREVIEW_ONLY','publish_jobs_created':0,'submit_attempt_count':0}
        db.execute("INSERT INTO yixiaoer_settings VALUES('canary_preparation',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(value,ensure_ascii=False),))
    output.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    return value
