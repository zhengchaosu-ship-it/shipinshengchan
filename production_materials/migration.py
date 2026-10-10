"""E盘生产素材迁移：先清单，后逐文件校验复制，再切换引用并清理已验证源文件。

不接受任意目录剪切，不覆盖文件，不删除目录。失败保留源文件。
仅使用显式生产目录/数据库分类，不使用文件名分类。
"""
import argparse
from contextlib import closing
import csv
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3

from .config import ROOT, VIDEO_EXT, IMAGE_EXT, settings
from .library import POOL_ALIASES, canonical_pool, pool_roots
from .store import now, sha256, local_directory

DESTINATION = Path('E:/寻帧生产素材库')
RUN = ROOT / 'production_materials/runtime/e_drive_migration_20261007'
MANIFEST_FIELDS = ['source_path','target_path','filename','original_filename','file_size','sha256',
                   'business_type','module_type','pool_id','material_id','migration_status','evidence','error']
INVENTORY_FIELDS = ['OLD_PATH','CURRENT_CATEGORY','FILE_COUNT','TOTAL_SIZE','TARGET_PATH','CONFIDENCE','STATUS','REASON']


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


def write_csv(path, rows, fields):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader(); writer.writerows(rows)
        stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


def readonly(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return db


def safe_path(path, roots, excluded=()):
    path = Path(path)
    if not path.is_absolute() or str(path).startswith(('\\\\','//')):
        raise ValueError('LOCAL_ABSOLUTE_PATH_REQUIRED')
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part,'is_junction') and part.is_junction()):
            raise ValueError('LINKED_PATH_EXCLUDED')
    resolved = path.resolve()
    if not any(resolved.is_relative_to(Path(root).resolve()) for root in roots):
        raise ValueError('OUTSIDE_APPROVED_ROOTS')
    if any(resolved.is_relative_to(Path(root).resolve()) for root in excluded):
        raise ValueError('PROTECTED_SOURCE')
    return resolved


def files_under(root):
    root = local_directory(root)
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not Path(current,d).is_symlink()
                         and not Path(current,d).is_junction())
        for name in sorted(names):
            path = Path(current,name)
            if path.is_file() and not path.is_symlink():
                yield path


def choose_target(path, digest, reserved):
    """同名同hash合并；同名不同hash使用序号且永不覆盖。"""
    original = path
    number = 0
    while True:
        known = reserved.get(str(path).casefold())
        if known == digest or (not known and path.is_file() and sha256(path) == digest):
            return path, True
        if not known and not path.exists():
            reserved[str(path).casefold()] = digest
            return path, False
        number += 1
        path = original.with_name(f'{original.stem}__{number:03d}{original.suffix}')


def snapshot_protected():
    # 只读取受保护文件属性，不打开大数据库或模型，也不扫描帧缓存。
    candidates = [ROOT/'video_index_fixed.db',ROOT/'faiss_index.bin',ROOT/'faiss_meta.pkl']
    for folder in ('dino_index','clip_index','speech_search','raw_assets'):
        candidates += [p for p in (ROOT/folder).glob('*') if p.is_file() and p.suffix in {'.db','.sqlite','.bin','.pkl','.index'}]
    return {str(p): [p.stat().st_size,p.stat().st_mtime_ns] for p in candidates if p.is_file()}


def create_plan(config, run=RUN, destination=DESTINATION):
    run = Path(run); run.mkdir(parents=True, exist_ok=True)
    if (run/'PLAN.json').exists():
        raise ValueError('PLAN_ALREADY_EXISTS_USE_SAVED_PLAN')
    targets = pool_roots(destination)
    with closing(readonly(config['database'])) as db:
        pools = [dict(r) for r in db.execute('SELECT * FROM pools')]
        materials = [dict(r) for r in db.execute('SELECT * FROM materials')]
    registered = {str(Path(m['path']).resolve()).casefold(): m for m in materials}
    sources = []
    for pool in pools:
        if pool['root']:
            sources.append(dict(root=str(Path(pool['root']).resolve()),target=str(targets[canonical_pool(pool['pool_id'])]),
                business=pool['business_type'],module=pool['module_type'],pool=canonical_pool(pool['pool_id']),
                evidence='EXISTING_POOL_REGISTRY'))
    # 这三个目录在盘点中独立确认；不根据任何文件名分流。
    sources += [dict(root='E:\\备份\\起号手法\\8.13手法',target=str(targets['STARTUP_TECHNIQUE']/'legacy_8.13手法'),
                     business='STARTUP',module='STARTUP_TECHNIQUE',pool='STARTUP_TECHNIQUE',evidence='EXPLICIT_TECHNIQUE_DIRECTORY'),
                dict(root='E:\\备份\\起号手法\\4.20素材',target=str(destination/'_待确认素材/legacy_起号手法/4.20素材'),
                     business='UNKNOWN',module='',pool='',evidence='LEGACY_LIB2_MIXED_DIRECTORY'),
                dict(root='E:\\备份\\起号手法\\求赞求关注素材',target=str(destination/'_待确认素材/legacy_起号手法/求赞求关注素材'),
                     business='UNKNOWN',module='',pool='',evidence='NO_CONFIRMED_MODULE_MAPPING'),
                dict(root='E:\\备份\\带货素材',target=str(destination/'_待确认素材/legacy_带货素材'),
                     business='UNKNOWN',module='',pool='',evidence='EMPTY_UNCLASSIFIED_COMMERCE_ROOT')]
    excluded = list(config['raw_media_roots']) + [str(ROOT/p) for p in ('outputs','startup_render','publisher_poc','yixiaoer_adapter')]
    plan = dict(version=1,created_at=now(),destination=str(destination),sources=sources,excluded=excluded,
                pools_before=pools,materials_before=materials,protected_before=snapshot_protected(),
                config=config,rows=[],inventory=[],bindings_complete=False,created_directories=[])
    reserved = {}; seen = set()
    for source in sources:
        root = safe_path(source['root'],[s['root'] for s in sources],excluded)
        selected = list(files_under(root)) if root.is_dir() else []
        rows = []
        for path in selected:
            if path.suffix.lower() not in VIDEO_EXT | IMAGE_EXT:
                continue
            path = safe_path(path,[root],excluded)
            if str(path).casefold() in seen:raise ValueError('OVERLAPPING_SOURCE_DIRECTORIES')
            seen.add(str(path).casefold())
            item = registered.get(str(path).casefold())
            business, module, pool = source['business'],source['module'],source['pool']
            target = Path(source['target'])/path.relative_to(root)
            evidence = source['evidence']
            if item:
                if canonical_pool(item['module_type']) not in targets:
                    raise ValueError('UNKNOWN_REGISTERED_MODULE_REQUIRES_REVIEW')
                business,module,pool = item['business_type'],item['module_type'],canonical_pool(item['module_type'])
                target = targets[pool]/path.relative_to(root)
                evidence = 'DATABASE_MODULE_TYPE'
            before = path.stat(); digest = sha256(path); after = path.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('SOURCE_CHANGED_DURING_PLAN')
            target, duplicate = choose_target(target,digest,reserved)
            safe_path(target,[destination],excluded)
            row = dict(source_path=str(path),target_path=str(target),filename=path.name,
                original_filename=item['original_filename'] if item else path.name,file_size=before.st_size,
                mtime_ns=before.st_mtime_ns,sha256=digest,business_type=business,module_type=module,pool_id=pool,
                material_id=item['material_id'] if item else '',migration_status='PLANNED',
                evidence=evidence,error='',duplicate=duplicate)
            rows.append(row);plan['rows'].append(row)
        plan['inventory'].append(dict(OLD_PATH=str(root),CURRENT_CATEGORY=source['module'] or 'NEEDS_CLASSIFICATION',
            FILE_COUNT=len(rows),TOTAL_SIZE=sum(r['file_size'] for r in rows),TARGET_PATH=source['target'],
            CONFIDENCE='CONFIRMED' if source['module'] else 'UNCONFIRMED',STATUS='PLANNED',REASON=source['evidence']))
        print(json.dumps(plan['inventory'][-1],ensure_ascii=False),flush=True)
    missing = set(registered)-seen
    if missing:raise ValueError('REGISTERED_MATERIAL_OUTSIDE_DISCOVERED_SOURCES: '+str(len(missing)))
    for name,reason in [('半成品','OUTPUT_OR_INTERMEDIATE_EXCLUDED'),('成品','RENDER_OUTPUT_EXCLUDED'),
                        ('Y148-抖音快手扫光棒消重短视频去重素材粒子剪辑防搬运教程过原创方法','EFFECTS_AND_TUTORIALS_NOT_BACKGROUND'),
                        ('陶老师直播录制','RAW_INDEX_LIBRARY_EXCLUDED')]:
        plan['inventory'].append(dict(OLD_PATH=str(Path('E:/备份')/name),CURRENT_CATEGORY='EXCLUDED',FILE_COUNT='',TOTAL_SIZE='',
            TARGET_PATH='',CONFIDENCE='EXCLUDED',STATUS='UNCHANGED',REASON=reason))
    save_plan(plan,run)
    return plan


def save_plan(plan, run):
    write_json(Path(run)/'PLAN.json',plan)
    write_csv(Path(run)/'PRODUCTION_MATERIAL_MIGRATION_MANIFEST.csv',plan['rows'],MANIFEST_FIELDS)
    write_csv(Path(run)/'DIRECTORY_INVENTORY.csv',plan['inventory'],INVENTORY_FIELDS)
    write_csv(Path(run)/'MATERIAL_NEEDS_CLASSIFICATION.csv',
              [r for r in plan['rows'] if r['business_type']=='UNKNOWN'],MANIFEST_FIELDS)


def verify_file(path,row):
    return path.is_file() and path.stat().st_size==row['file_size'] and sha256(path)==row['sha256']


def stage_file(row, roots, destination, excluded=()):
    source=safe_path(row['source_path'],roots,excluded)
    target=safe_path(row['target_path'],[destination],excluded)
    if source == target:raise ValueError('SOURCE_EQUALS_DESTINATION')
    if not verify_file(source,row):raise ValueError('SOURCE_CHANGED_BEFORE_MIGRATION')
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if not verify_file(target,row):raise ValueError('TARGET_COLLISION_NO_OVERWRITE')
        return
    # 保留原文件至目录和数据库全部切换成功。临时文件没有媒体扩展名。
    temporary=target.with_name(target.name+'.migrationpart')
    with source.open('rb') as src, temporary.open('xb') as dst:
        shutil.copyfileobj(src,dst,1024*1024)
        dst.flush();os.fsync(dst.fileno())
    shutil.copystat(source,temporary)
    if not verify_file(temporary,row):raise ValueError('COPY_HASH_MISMATCH_SOURCE_RETAINED')
    # Windows rename 拒绝覆盖；其他系统用排他硬链接提交，同样不覆盖。
    if os.name=='nt':os.rename(temporary,target)
    else:os.link(temporary,target);temporary.unlink()
    if not verify_file(target,row):raise ValueError('TARGET_VERIFICATION_FAILED_SOURCE_RETAINED')


def remove_verified_source(row, roots, destination, excluded=()):
    source=safe_path(row['source_path'],roots,excluded)
    target=safe_path(row['target_path'],[destination],excluded)
    if source==target:raise ValueError('SOURCE_EQUALS_DESTINATION')
    if not verify_file(target,row):raise ValueError('TARGET_CHANGED_SOURCE_RETAINED')
    if source.exists():
        if not verify_file(source,row):raise ValueError('SOURCE_CHANGED_SOURCE_RETAINED')
        source.unlink()  # 仅删除清单内已完成双重SHA校验的单个源文件。


def replace_exact(value,mapping):
    if isinstance(value,str):return mapping.get(value,value)
    if isinstance(value,list):return [replace_exact(v,mapping) for v in value]
    if isinstance(value,dict):return {k:replace_exact(v,mapping) for k,v in value.items()}
    return value


def backup_inputs(plan,run):
    backup=Path(run)/'backups';backup.mkdir(exist_ok=True)
    for key in ('database','shadow_db','operations_db'):
        target=backup/(key+'.sqlite.bak')
        if target.exists():continue
        with closing(readonly(plan['config'][key])) as src, closing(sqlite3.connect(target)) as dst:src.backup(dst)
    for relative in ('jianying_auto/config.json','jianying_auto/jianying_source_folders.json','production_materials/service.config.json'):
        target=backup/(relative.replace('/','__')+'.bak')
        if not target.exists():shutil.copy2(ROOT/relative,target)


def bind_references(plan):
    config=plan['config'];roots=pool_roots(plan['destination']);stamp=now()
    mapping={r['source_path']:r['target_path'] for r in plan['rows']}
    root_map={s['root']:s['target'] for s in plan['sources']}
    full_map={**root_map,**mapping}
    from startup_autopilot.models import digest
    counts={}
    # 三个小型业务数据库位于D盘，使用同一回滚日志事务；不连接原始索引库。
    with closing(sqlite3.connect(config['database'],timeout=30)) as db:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('ATTACH DATABASE ? AS shadow',(config['shadow_db'],))
        db.execute('ATTACH DATABASE ? AS ops',(config['operations_db'],))
        db.execute('BEGIN IMMEDIATE');db.execute('PRAGMA defer_foreign_keys=ON')
        try:
            if db.execute('SELECT count(*) FROM ops.autopilot_authorizations WHERE enabled=1').fetchone()[0]:
                raise ValueError('AUTOPILOT_ACTIVE_CANNOT_SWITCH_PATHS')
            if db.execute("SELECT count(*) FROM uploads WHERE state NOT IN ('LIBRARY_READY','DUPLICATE_SKIPPED','QUARANTINED')").fetchone()[0]:
                raise ValueError('PENDING_UPLOADS_CANNOT_SWITCH_PATHS')
            for old,new in POOL_ALIASES.items():
                db.execute('UPDATE pools SET pool_id=? WHERE pool_id=?',(new,old))
                for table in ('materials','uploads','legacy_inventory'):
                    db.execute('UPDATE '+table+' SET pool_id=? WHERE pool_id=?',(new,old))
            for key,root in roots.items():
                db.execute('UPDATE pools SET root=?,updated_at=? WHERE pool_id=?',(str(root),stamp,key))
            counts['materials_updated']=0
            for row in plan['rows']:
                if row['material_id']:
                    counts['materials_updated']+=db.execute('UPDATE materials SET path=?,pool_id=? WHERE material_id=? AND path=?',
                        (row['target_path'],row['pool_id'],row['material_id'],row['source_path'])).rowcount
                db.execute('UPDATE uploads SET destination=? WHERE destination=?',(row['target_path'],row['source_path']))
                db.execute('UPDATE legacy_inventory SET path=? WHERE path=?',(row['target_path'],row['source_path']))
            for old,new in root_map.items():
                db.execute('UPDATE uploads SET target_root=? WHERE target_root=?',(new,old))
                db.execute('UPDATE shadow.composition_material_pools SET root=? WHERE root=?',(new,old))
            counts['composition_cache_updated']=0
            for row in plan['rows']:
                if row['business_type']!='STARTUP':continue
                target=Path(row['target_path']);stat=target.stat()
                for pool in db.execute('SELECT * FROM shadow.composition_material_pools').fetchall():
                    if not target.is_relative_to(Path(pool['root'])):continue
                    db.execute('DELETE FROM shadow.composition_catalog_cache WHERE account_id=? AND pool_id=? AND path=?',
                        (pool['account_id'],pool['pool_id'],row['source_path']))
                    db.execute('''INSERT INTO shadow.composition_catalog_cache VALUES(?,?,?,?,?,?,?)
                        ON CONFLICT(account_id,pool_id,file_key) DO UPDATE SET path=excluded.path,
                        size_bytes=excluded.size_bytes,mtime_ns=excluded.mtime_ns,media_sha256=excluded.media_sha256''',
                        (pool['account_id'],pool['pool_id'],digest([stat.st_dev,stat.st_ino]),str(target),stat.st_size,stat.st_mtime_ns,row['sha256']))
                    counts['composition_cache_updated']+=1
            for profile in db.execute('SELECT business_account_id,catalog_json FROM shadow.shadow_profiles').fetchall():
                catalog=replace_exact(json.loads(profile['catalog_json']),full_map)
                for pool in catalog:
                    for item in pool.get('files',[]):
                        p=Path(item['path'])
                        if p.is_file():s=p.stat();item['filesystem_identity']=[s.st_dev,s.st_ino]
                db.execute('UPDATE shadow.shadow_profiles SET catalog_json=? WHERE business_account_id=?',
                    (json.dumps(catalog,ensure_ascii=False),profile['business_account_id']))
            counts['background_catalog_updated']=0;counts['background_bindings_updated']=0
            for old,new in mapping.items():
                counts['background_catalog_updated']+=db.execute('UPDATE ops.background_material_catalog SET path=?,updated_at=? WHERE path=?',(new,stamp,old)).rowcount
                db.execute('UPDATE ops.background_material_aliases SET path=? WHERE path=?',(new,old))
                counts['background_bindings_updated']+=db.execute('UPDATE ops.account_background_bindings SET background_path=?,updated_at=? WHERE background_path=?',(new,stamp,old)).rowcount
            for state in db.execute('SELECT * FROM ops.background_catalog_state').fetchall():
                db.execute('UPDATE ops.background_catalog_state SET root=?,result_json=? WHERE singleton=?',
                    (full_map.get(state['root'],state['root']),json.dumps(replace_exact(json.loads(state['result_json']),full_map),ensure_ascii=False),state['singleton']))
            db.execute('UPDATE catalog_state SET revision=revision+1,updated_at=? WHERE singleton=1',(stamp,))
            for schema in ('main','shadow','ops'):
                if db.execute('PRAGMA '+schema+'.foreign_key_check').fetchall():raise ValueError('FOREIGN_KEY_CHECK_FAILED')
            db.commit()
        except BaseException:db.rollback();raise
    for relative in ('jianying_auto/config.json','jianying_auto/jianying_source_folders.json'):
        path=ROOT/relative;write_json(path,replace_exact(json.loads(path.read_text('utf-8-sig')),full_map))
    path=ROOT/'production_materials/service.config.json'
    value=json.loads(path.read_text('utf-8-sig'));value['production_library_root']=plan['destination'];write_json(path,value)
    plan['bindings_complete']=True;plan['database_updates']=counts


def apply_plan(run=RUN):
    run=Path(run);plan=json.loads((run/'PLAN.json').read_text('utf-8'))
    destination=Path(plan['destination'])
    if destination.resolve()!=DESTINATION.resolve():raise ValueError('FORMAL_DESTINATION_MISMATCH')
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',int(plan['config']['port'])))==0:raise ValueError('STOP_MATERIAL_SERVICE_BEFORE_APPLY')
    roots=[s['root'] for s in plan['sources']]
    for row in plan['rows']:
        safe_path(row['source_path'],roots,plan['excluded']);safe_path(row['target_path'],[destination],plan['excluded'])
    backup_inputs(plan,run)
    dirs={destination,destination/'带货素材',destination/'起号素材',destination/'背景素材',destination/'_待确认素材',destination/'_管理',*pool_roots(destination).values()}
    for row in plan['rows']:
        p=Path(row['target_path']).parent
        while p.is_relative_to(destination):dirs.add(p);p=p.parent
    for path in sorted(dirs,key=lambda p:(len(p.parts),str(p))):
        safe_path(path,[destination])
        if not path.exists():path.mkdir();plan['created_directories'].append(str(path))
    admin=destination/'_管理'
    save_plan(plan,run);save_plan(plan,admin)  # 第一个文件复制前落盘正式清单。
    if not plan['bindings_complete']:
        for index,row in enumerate(plan['rows']):
            try:
                stage_file(row,roots,destination,plan['excluded'])
                row['migration_status']='VERIFIED';row['error']=''
            except Exception as error:
                row['migration_status']='FAILED';row['error']=repr(error)
            save_plan(plan,run);save_plan(plan,admin)
            if index%10==0:print(f"Verified {index+1}/{len(plan['rows'])}",flush=True)
        if any(r['migration_status']=='FAILED' for r in plan['rows']):raise ValueError('COPY_FAILURE_SOURCES_RETAINED_NO_BINDING_SWITCH')
        bind_references(plan);save_plan(plan,run);save_plan(plan,admin)
    for index,row in enumerate(plan['rows']):
        try:
            remove_verified_source(row,roots,destination,plan['excluded'])
            row['migration_status']='DUPLICATE' if row['duplicate'] else 'MIGRATED';row['error']=''
        except Exception as error:row['migration_status']='FAILED';row['error']=repr(error)
        save_plan(plan,run);save_plan(plan,admin)
        if index%10==0:print(f"Migrated {index+1}/{len(plan['rows'])}",flush=True)
    for item in plan['inventory']:
        if item['STATUS']=='UNCHANGED':continue
        remaining=list(files_under(item['OLD_PATH'])) if Path(item['OLD_PATH']).is_dir() else []
        item['STATUS']='LEGACY_EMPTY' if not remaining else 'LEGACY_RETAINED'
    from .store import Store
    store=Store(settings());store.metadata_inventory()
    # 恢复已验证hash，目录扫描不需要重新读取视频内容。
    with store.connect(True) as db:
        for row in plan['rows']:
            if row['pool_id'] and row['migration_status'] in ('MIGRATED','DUPLICATE'):
                db.execute('UPDATE legacy_inventory SET content_hash=? WHERE path=?',(row['sha256'],row['target_path']))
    plan['completed_at']=now();save_plan(plan,run);save_plan(plan,admin)
    print(json.dumps(dict(rows=len(plan['rows']),updates=plan.get('database_updates'),failed=sum(r['migration_status']=='FAILED' for r in plan['rows'])),ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('plan','apply'));parser.add_argument('--run',type=Path,default=RUN)
    args=parser.parse_args()
    if args.action=='plan':create_plan(settings(),args.run)
    else:apply_plan(args.run)
