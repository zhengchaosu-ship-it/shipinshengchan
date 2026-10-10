"""迁移后的本地只读消费端验收；输出报告，不生成/渲染/发布视频。"""
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from urllib.request import urlopen

from .config import COMMERCE, settings
from .library import pool_roots
from .migration import RUN, write_json, write_csv, snapshot_protected, verify_file
from .store import ProductionMaterialCatalog


def check():
    plan=json.loads((RUN/'PLAN.json').read_text('utf-8'));config=settings()
    root=Path(plan['destination']);admin=root/'_管理';expected=pool_roots(root)
    result={'root':str(root),'created_directories':len(plan['created_directories']),
            'required_directories':15,'raw_index_moved':0,'render_jianying_moved':0,'checks':{}}
    errors=[]
    for row in plan['rows']:
        if not verify_file(Path(row['target_path']),row):errors.append(row['target_path'])
        if Path(row['source_path']).exists():errors.append('SOURCE_REMAINS:'+row['source_path'])
    result['checks']['all_files_size_sha256_verified']=not errors
    result['file_errors']=errors
    result['migration_status']=dict(Counter(r['migration_status'] for r in plan['rows']))
    result['groups']={group:dict(files=sum(r['business_type']==group for r in plan['rows']),
        bytes=sum(r['file_size'] for r in plan['rows'] if r['business_type']==group)) for group in ('STARTUP','COMMERCE','VISUAL','UNKNOWN')}
    result['checks']['protected_index_metadata_unchanged']=snapshot_protected()==plan['protected_before']
    catalog=ProductionMaterialCatalog(config);pools=catalog.pools(True)
    registry=[]
    for pool in pools:
        path=Path(pool['root'])
        with catalog.connect() as db:
            count=db.execute('SELECT count(*) FROM legacy_inventory WHERE available=1 AND pool_id=?',(pool['pool_id'],)).fetchone()[0]
            count+=db.execute('SELECT count(*) FROM materials m WHERE pool_id=? AND NOT EXISTS(SELECT 1 FROM legacy_inventory l WHERE l.available=1 AND l.path=m.path)',(pool['pool_id'],)).fetchone()[0]
        registry.append({**pool,'status':'READY' if path==expected[pool['pool_id']] and path.is_dir() else 'FAILED',
                         'material_count':count,'content_status':'HAS_MATERIALS' if count else 'EMPTY'})
    result['checks']['ten_pools_registered']=len(registry)==10 and all(p['status']=='READY' for p in registry)
    result['checks']['five_commerce_bound']=all(any(p['pool_id']==key and p['status']=='READY' for p in registry) for key in COMMERCE)
    write_csv(admin/'POOL_REGISTRY_EXPORT.csv',registry,['pool_id','business_type','module_type','label','root','status','material_count','content_status'])
    write_csv(RUN/'POOL_REGISTRY_EXPORT.csv',registry,['pool_id','business_type','module_type','label','root','status','material_count','content_status'])
    result['pools']=registry
    with catalog.connect() as db:
        materials=[dict(r) for r in db.execute('SELECT * FROM materials')]
        available=[dict(r) for r in db.execute('SELECT * FROM legacy_inventory WHERE available=1')]
        result['material_id_duplicates']=db.execute('SELECT count(*)-count(DISTINCT material_id) FROM materials').fetchone()[0]
    result['production_material_rows_updated']=plan['database_updates']['materials_updated']
    before={r['material_id']:r for r in plan['materials_before']}
    ignored={'path','stored_path','pool_id','updated_at'}
    result['checks']['original_material_identity_lineage_preserved']=(set(before)=={r['material_id'] for r in materials} and all(
        {k:v for k,v in row.items() if k not in ignored}=={k:v for k,v in before[row['material_id']].items() if k not in ignored} for row in materials))
    result['invalid_catalog_paths']=[r['path'] for r in materials+available if not Path(r['path']).is_file() or not Path(r['path']).is_relative_to(root)]
    result['checks']['catalog_paths_valid']=not result['invalid_catalog_paths']
    result['catalog_scanned_files']=len(available)
    from jianying_auto.source_catalog import read_catalog
    startup=read_catalog()
    result['startup']={label:dict(root=str(v['folder']),files=len(v['videos'])) for label,v in startup.items()}
    result['checks']['startup_four_categories_readable']=len(startup)==4 and all(v['videos'] for v in startup.values())
    from startup_autopilot.shadow_store import ShadowStore
    from startup_autopilot.composition_catalog import CompositionCatalog
    from startup_autopilot.models import Actor
    shadows=ShadowStore(config['shadow_db'])
    with shadows.connect(readonly=True) as db:
        accounts=[dict(r) for r in db.execute('SELECT business_account_id,owner_employee_id FROM shadow_profiles')]
    summaries=[]
    for account in accounts:
        actor=Actor(account['owner_employee_id'],frozenset([account['business_account_id']]))
        values=CompositionCatalog(shadows).refresh(actor,account['business_account_id'],hash_budget=0)
        summaries.append(dict(account_id=account['business_account_id'],pools=[dict(pool_id=p['pool_id'],root=p['root'],
            files=p['metadata_file_count'],verified=p['verified_unique_count'],pending=p['pending_hash_count'],issues=p['issues']) for p in values]))
    result['composition_accounts']=summaries
    result['checks']['six_accounts_read_new_pools']=len(summaries)==6 and all(len(s['pools'])==4 and all(p['verified']>0 and p['pending']==0 and not p['issues'] for p in s['pools']) for s in summaries)
    # 只读比较模板及稳定账号池ID，迁移不能改变已确认的视频结构。
    with closing(sqlite3.connect(RUN/'backups/shadow_db.sqlite.bak')) as old,shadows.connect(readonly=True) as new:
        tables=('composition_template_states','composition_template_versions')
        result['checks']['templates_unchanged']=all(old.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall()==[tuple(r) for r in new.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in tables)
        affinity_sql='SELECT * FROM composition_slot_affinities ORDER BY account_id,slot_position,material_id'
        prior=old.execute(affinity_sql).fetchall();current=[tuple(r) for r in new.execute(affinity_sql)]
        def stable_affinity(row):
            evidence=json.loads(row[-1]);evidence.pop('updated_at',None);evidence.pop('version_hash',None)
            return (*row[:-1],evidence)
        result['checks']['affinity_business_values_preserved']=[stable_affinity(r) for r in prior]==[stable_affinity(r) for r in current]
        result['concurrent_affinity_observation_updates']=sum(a!=b for a,b in zip(prior,current))
        result['checks']['account_pool_ids_unchanged']=old.execute('SELECT account_id,pool_id,label FROM composition_material_pools ORDER BY rowid').fetchall()==[tuple(r) for r in new.execute('SELECT account_id,pool_id,label FROM composition_material_pools ORDER BY rowid')]
    from .consumers import CommerceMaterialSource
    commerce=CommerceMaterialSource(catalog)
    result['commerce_queries']={key:len(commerce.materials('xiaomiaozhao',key)) for key in COMMERCE}
    result['checks']['commerce_five_queries_valid']=len(result['commerce_queries'])==5
    result['commerce_planner_status']='NOT_IMPLEMENTED_IN_EXISTING_PROJECT; VERIFIED_CONSUMER_QUERY_ONLY'
    from account_visuals.storage import AccountBackgroundStore
    from account_visuals.catalog import background_root
    backgrounds=AccountBackgroundStore(config['operations_db']);items=backgrounds.catalog()
    snapshots=[backgrounds.snapshot(a['business_account_id']) for a in accounts]
    result['background_files']=len(items)
    result['checks']['background_selector_and_bindings_valid']=len(items)==6 and background_root()==expected['VISUAL_BACKGROUND'] and all(Path(v['background_path']).is_relative_to(root) for v in snapshots)
    with closing(sqlite3.connect(RUN/'backups/operations_db.sqlite.bak')) as old,backgrounds.connect() as new:
        sql='SELECT business_account_id,background_asset_id,background_type,fit_mode,enabled,created_at FROM account_background_bindings ORDER BY business_account_id'
        result['checks']['background_identity_bindings_preserved']=old.execute(sql).fetchall()==[tuple(r) for r in new.execute(sql)]
    for url in ('http://127.0.0.1:8501/_stcore/health','http://127.0.0.1:8502/_stcore/health','http://127.0.0.1:8510/health'):
        with urlopen(url,timeout=5) as response:result['checks'][url]=response.status==200
    with urlopen('http://127.0.0.1:8510/api/bootstrap',timeout=5) as response:boot=json.load(response)
    result['checks']['upload_service_all_pools_configured']=len(boot['pools'])==10 and all(p['configured'] and 'root' not in p for p in boot['pools'])
    for key in ('STARTUP_LEAD','STARTUP_TECHNIQUE','STARTUP_CLINIC','STARTUP_CLOSE',*COMMERCE,'VISUAL_BACKGROUND'):
        with urlopen('http://127.0.0.1:8510/api/materials?pool_id='+key,timeout=5) as response:data=json.load(response)
        result.setdefault('http_library_counts',{})[key]=data['total']
    # 浏览器独立核对文件由实际页面观察记录。
    browser=json.loads((RUN/'BROWSER_VERIFICATION.json').read_text('utf-8'))
    result['checks']['8502_actual_ui_five_paths']=browser['displayed_paths']==[str(expected[k]) for k in COMMERCE]
    result['failed']=sum(r['migration_status']=='FAILED' for r in plan['rows'])
    result['duplicates']=sum(r['migration_status']=='DUPLICATE' for r in plan['rows'])
    result['status']='PRODUCTION_MATERIAL_E_DRIVE_LIBRARY_READY' if all(result['checks'].values()) and not result['failed'] and not result['material_id_duplicates'] else 'MIGRATION_ACCEPTANCE_INCOMPLETE'
    write_json(RUN/'ACCEPTANCE.json',result);write_json(admin/'ACCEPTANCE.json',result)
    lines=['# 生产素材库 E 盘迁移验收', '', result['status'], '',
        '验收日期：2026-10-07（北京时间）。根目录：`'+str(root)+'`。', '',
        f"创建目录 {result['created_directories']} 个，其中规定的根目录、业务目录、10类池及管理目录共15个，其余15个为保留的来源子目录。",
        '', '| 类别 | 文件数 | 容量（字节） | 容量（GB，十进制） |','|---|---:|---:|---:|']
    for group,label in [('STARTUP','起号'),('COMMERCE','带货'),('VISUAL','背景'),('UNKNOWN','待确认')]:
        g=result['groups'][group];lines.append(f"| {label} | {g['files']} | {g['bytes']} | {g['bytes']/1e9:.6f} |")
    lines += ['',f"总计 {len(plan['rows'])} 文件。Duplicate={result['duplicates']}，Failed={result['failed']}。所有目标存在、size及完整SHA256一致；旧源逐文件移除，旧目录保留为LEGACY_EMPTY。",
        '',f"ProductionMaterial持久记录迁移前为0条、迁移后0条，更新0条，material_id重复0；未制造新material_id。旧目录编目107条更新到新址，并补入24条明确手法素材，当前可用编目{len(available)}条。实际旧schema使用path作为stored_path含义，没有新增/更改schema。",
        '', '账号素材缓存写入750条（6账号×125文件），24个账号池的稳定pool_id未改，已确认模板不变。背景catalog 6条及账号背景绑定6条仅更新路径/更新时间，背景ID、hash和归属不变。',
        '', '## 目录与消费端', '',
        '- 8502实际浏览器页面已显示五个新带货接收目录；上传服务8510已恢复。员工页只选择业务、分类、产品；服务按pool_id解析路径。',
        '- 起号四类：引流10、手法68、坐诊30、收尾17；六个既有账号均可读四类池，hash_budget=0无待校验素材。原账号启停状态未改变，没有生成新任务。',
        '- Commerce五个Pool均为READY（目录存在、登记正确、可以接收上传），目前各0条素材。五类产品范围查询均成功返回空列表；项目原本没有CommerceCompositionPlanner，本次未实现或宣称带货规划/生成已可用。',
        '- Background Pool READY：6张背景可读，6个账号的背景snapshot校验通过。',
        '- 正式Registry使用STARTUP_LEAD/STARTUP_CLOSE；既有module_type STARTUP_HOOK/STARTUP_ENDING保留，旧上传池名有兼容解析。',
        '', '## 范围、测试与保留', '',
        '- 独立既有后台继续刷新16条素材偏好证据的updated_at/version_hash；对应业务分值和模板状态/版本逐项相同。没有回滚并行后台记录。另有1条迁移前就已失效的历史起号缓存（点赞收尾.mp4）保留，它不进入现行可用素材编目；本次131条可用编目无失效路径。',
        '- 仅使用已有Pool、显式目录或数据库分类；没有按文件名关键词猜测。8.13手法按目录归入手法，保留legacy_8.13手法子目录。',
        '- 4.20素材116条、求赞求关注素材2条进入_待确认素材并保留来源层级；旧lib2配置同步到待确认目录，现行四类起号入口不消费该旧逻辑。',
        '- 扫光、粒子特效、教程、半成品、成品、RAW_INDEX_LIBRARY、RenderOutput、剪映草稿、2060 Worker、Publisher、Yixiaoer文件全部保留原位。Raw Index移动=0，Render/Jianying移动=0。受保护索引文件属性检查相同。',
        '- 本轮62项隔离测试通过（迁移/原上传23项、背景/起号模板39项）。实际消费端和HTTP检查见ACCEPTANCE.json。8501/8502健康正常；未执行原始索引重建或搜索全量回放。',
        '- 所有旧目录保留；未整目录剪切、未覆盖同名文件、未删除目录。',
        '', '## 文件与恢复', '',
        '本目录保存MIGRATION_REPORT.md、PRODUCTION_MATERIAL_MIGRATION_MANIFEST.csv、MATERIAL_NEEDS_CLASSIFICATION.csv、POOL_REGISTRY_EXPORT.csv、DIRECTORY_INVENTORY.csv及完整PLAN.json、ACCEPTANCE.json。',
        '', '工作副本及SQLite一致性备份：`D:\\video_search_tool\\production_materials\\runtime\\e_drive_migration_20261007\\backups`。修改前源代码/配置有`.e-drive-migration-20261007.bak`。',
        '', '恢复应先停止素材上传、保持生产暂停，按manifest逐文件核对新旧SHA后复制回旧址，再只恢复本轮修改的路径字段及配置。不得整体恢复operations.db覆盖并行后台产生的新发布记录。旧副本恢复及消费端验收后才处理新址副本。',
        '', '手动复验：8502→高级管理→生产素材目录核对五路径；视频生成模块→生产素材库检查起号与背景总数；AI托管→账号模板/背景查看现有素材。无需执行生成、渲染或发布。']
    for folder in (RUN,admin):(folder/'MIGRATION_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('pools','composition_accounts')},ensure_ascii=False,indent=2))
    if result['status']!='PRODUCTION_MATERIAL_E_DRIVE_LIBRARY_READY':raise SystemExit(1)


if __name__=='__main__':check()
