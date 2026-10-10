"""低频健康快照与跨库本地备份；不调用生成或发布。"""
from contextlib import ExitStack, closing
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import urllib.request

from startup_autopilot.production import utcnow
from startup_autopilot.models import aware
from yixiaoer_adapter.worker import write_json


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def verify_backup(folder):
    folder=Path(folder).resolve();manifest=json.loads((folder/'manifest.json').read_text('utf-8'))
    if manifest.get('state')!='COMPLETE':raise ValueError('BACKUP_INCOMPLETE')
    if {item['file'] for item in manifest['databases']}!={'operations.db','account_assets.db','render_jobs.db'}:raise ValueError('BACKUP_REQUIRED_DATABASE_MISSING')
    for item in manifest['databases']:
        # 清单不能将恢复工具引向备份目录外。
        path=folder/item['file']
        if path.resolve().parent!=folder.resolve() or sha(path)!=item['sha256']:raise ValueError('BACKUP_HASH_MISMATCH')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('BACKUP_DATABASE_CORRUPT')
    from .backup_safety import profile_compatibility
    profile_compatibility(folder)
    return manifest


class Operations:
    def __init__(self, production, config, render_path):
        self.production=production;self.config=config;self.render_path=Path(render_path)
        self.root=Path(config.get('consolidation_runtime',Path(config['runtime_dir'])/'consolidation'))

    def backup(self, *, force=False, now=None):
        from .backup_safety import guarded_backup
        return guarded_backup(self,force=force,now=now or utcnow(),verify=verify_backup)

    def _backup_snapshot(self, *, now):
        sources=[('operations.db',self.production.planner.path),('account_assets.db',self.production.shadows.path),('render_jobs.db',self.render_path)]
        sources=[(name,Path(path).resolve()) for name,path in sources if Path(path).is_file()]
        if len(sources)!=3:raise ValueError('BACKUP_REQUIRED_DATABASE_MISSING')
        # 全量副本创建之前检查；force也不能绕过磁盘保护。不更改原Backup退避闩锁。
        from server_maintenance.storage import require_copy_space, GIB
        evidence_roots=[Path(self.config['runtime_dir'])/'metrics',Path(self.config['runtime_dir'])/'jobs',Path(self.config['runtime_dir'])/'compositions',Path(self.config.get('publisher_evidence_dir',Path(__file__).resolve().parents[1]/'yixiaoer_adapter/runtime/jobs'))]
        source_size=sum(path.stat().st_size for _,path in sources)
        source_size+=sum(p.stat().st_size for root in evidence_roots if root.is_dir() for p in root.rglob('*.json'))
        space=require_copy_space(self.root,source_size,expected_temp_space=source_size,
                                 safety_margin=self.config.get('backup_safety_margin_bytes',20*GIB))
        write_json(self.root/'backup.space_precheck.json',dict(space,checked_at=now.isoformat()))
        folder=self.root/'backups'/now.strftime('%Y%m%dT%H%M%S%fZ');folder.mkdir(parents=True)
        manifest={'state':'CREATING','created_at':now.isoformat(),'databases':[],'render_publish_calls':0}
        write_json(folder/'manifest.json',manifest)
        # 同时持有各源库的只读快照，再使用同一读连接backup。
        # 不持有BEGIN IMMEDIATE：SQLite backup遇到另一个写事务会持续BUSY。
        with ExitStack() as stack:
            connections={}
            for _,path in sorted(sources,key=lambda item:str(item[1])):
                source=stack.enter_context(closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10)))
                source.execute('BEGIN');source.execute('SELECT count(*) FROM sqlite_master').fetchone()
                connections[path]=source
            for name,path in sources:
                destination=folder/name
                with closing(sqlite3.connect(destination)) as out:connections[path].backup(out)
                manifest['databases'].append({'file':name,'source':str(path),'sha256':sha(destination),'size':destination.stat().st_size})
        # 指标及Publish request/intent审计保留在DB，同时保存小型本地JSON证据。
        artifact_count=0
        for index,source_root in enumerate(evidence_roots):
            if source_root.is_dir():
                for source in source_root.rglob('*.json'):
                    destination=folder/'evidence'/str(index)/source.relative_to(source_root)
                    destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination);artifact_count+=1
        from .backup_safety import profile_compatibility
        manifest.update(state='COMPLETE',artifact_count=artifact_count,profile_compatibility=profile_compatibility(folder))
        write_json(folder/'manifest.json',manifest);verify_backup(folder)
        result={'created_at':now.isoformat(),'folder':str(folder),'verified':True}
        return result

    def health(self, render_online, *, now=None):
        now=now or utcnow();result={}
        def record(name,state,**details):result[name]={'state':state,'details':details}
        try:
            with self.production.planner.connect() as db:
                record('数据库','OK' if db.execute('PRAGMA quick_check').fetchone()[0]=='ok' else 'ERROR')
        except Exception as error:record('数据库','ERROR',reason=type(error).__name__)
        root=Path(__file__).resolve().parents[1]
        workers=[('托管Worker',Path(self.config['runtime_dir'])/'heartbeat.json',180)]
        for name,config_file,age in [('Account Sync','account_sync.config.json',660),('Publisher Worker','worker.config.json',180)]:
            try:
                conf=json.loads((root/'yixiaoer_adapter'/config_file).read_text('utf-8-sig'))
                workers.append((name,Path(conf['runtime_dir'])/'heartbeat.json',age))
            except Exception:record(name,'UNKNOWN')
        for name,path,age in workers:
            try:
                data=json.loads(path.read_text('utf-8'));fresh=now-aware(data['last_heartbeat'])<timedelta(seconds=age)
                complete=data.get('state') in ('PRODUCTION_PROVIDER_QUEUED','CANARY_PROVIDER_QUEUED')
                record(name,'OK' if fresh or complete else 'STALE',worker_state=data.get('state'))
            except Exception:record(name,'UNKNOWN')
        try:
            with urllib.request.urlopen('http://127.0.0.1:8502/_stcore/health',timeout=3) as response:record('8502','OK' if response.status==200 else 'ERROR')
        except Exception:record('8502','OFFLINE')
        try:
            if render_online():record('Render Worker','OK')
            elif self.config.get('render_config'):
                from .preflight import infrastructure
                probe=infrastructure(self.config)
                halted=any(w['status']=='HALTED_NEEDS_MANUAL' for w in probe['workers'])
                record('Render Worker','HALTED_NEEDS_MANUAL' if halted else 'OFFLINE',reason=probe['render_reason'])
            else:record('Render Worker','OFFLINE')
        except Exception:record('Render Worker','UNKNOWN')
        for name,path in [('磁盘空间',self.production.planner.path.parent),('备份磁盘',self.root)]:
            try:
                parent=path
                while not parent.exists():parent=parent.parent
                free=shutil.disk_usage(parent).free
                record(name,'OK' if free>=self.config.get('minimum_free_bytes',5*1024**3) else 'LOW',free_bytes=free)
            except Exception:record(name,'UNKNOWN')
        try:
            config=json.loads((root/'jianying_auto/config.json').read_text('utf-8'))
            for key,label in [('green_dir','主体素材'),('pull_dir','引流素材'),('shouwei_dir','收尾素材'),('bg_dir','背景素材')]:
                record(label,'OK' if Path(config[key]).is_dir() else 'MISSING')
            render_config=json.loads((root/'startup_render/server.example.json').read_text('utf-8'))
            record('Render输出目录','OK' if Path(render_config['result_root']).is_dir() else 'MISSING')
        except Exception:record('素材路径','UNKNOWN')
        from yixiaoer_adapter.cli_runner import run_hidden
        try:
            check=run_hidden(['powershell.exe','-NoProfile','-Command',"@(Get-Process -Name '蚁小二4.0' -ErrorAction SilentlyContinue).Count"],timeout=10)
            record('Yixiaoer Client','OK' if check.returncode==0 and int(check.stdout.decode().strip())>0 else 'OFFLINE')
        except Exception:record('Yixiaoer Client','UNKNOWN')
        write_json(self.root/'health.json',{'checked_at':now.isoformat(),'components':result})
        try:
            with self.production.planner.connect(write=True) as db:
                for name,value in result.items():
                    db.execute('''INSERT INTO production_health_snapshots VALUES(?,?,?,?) ON CONFLICT(component)
                        DO UPDATE SET state=excluded.state,checked_at=excluded.checked_at,details_json=excluded.details_json''',
                        (name,value['state'],now.isoformat(),json.dumps(value['details'],ensure_ascii=False)))
        except sqlite3.DatabaseError:
            # DB损坏时独立文件仍可诊断，不让健康监控跟随业务DB一起消失。
            pass
        return result

    def tick(self, render_online):
        now=utcnow();path=self.root/'health.json'
        attempt=self.root/'operations.attempt.json'
        if attempt.exists() and now-aware(json.loads(attempt.read_text('utf-8'))['started_at'])<timedelta(seconds=300):return None
        write_json(attempt,{'started_at':now.isoformat()})
        from .reliability import ReliabilityStore
        reliability=ReliabilityStore(self.production)
        if not path.exists() or now-aware(json.loads(path.read_text('utf-8'))['checked_at'])>=timedelta(seconds=300):
            health=self.health(render_online,now=now)
            for component,value in health.items():
                if value['state']!='OK':reliability.incident('__SYSTEM__',component+'：'+value['state'],'HEALTH:'+component,category='SYSTEM')
                else:
                    with self.production.planner.connect(write=True) as db:db.execute("UPDATE production_incidents SET state='RESOLVED',resolved_at=? WHERE account_id='__SYSTEM__' AND source_key=?",(now.isoformat(),'HEALTH:'+component))
        result=self.backup(now=now)
        if result.get('state') in ('BACKUP_FAILED','BACKUP_PAUSED','BACKUP_BUSY'):
            return result  # 独立备份告警，不影响下一次Planner/Render/对账循环。
        with self.production.planner.connect(write=True) as db:db.execute("UPDATE production_incidents SET state='RESOLVED',resolved_at=? WHERE account_id='__SYSTEM__' AND source_key='OPERATIONS'",(now.isoformat(),))
        return result
