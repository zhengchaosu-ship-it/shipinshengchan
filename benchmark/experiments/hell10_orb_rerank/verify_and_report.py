from pathlib import Path
import csv,json,statistics,time,sqlite3
import cv2,numpy as np
from run_experiment import OUT,ROOT,FORMAL,SOURCE,CONFIG,FINAL,production_orb,snapshot,write,sha

d=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
s=json.loads((OUT/'scale_control.json').read_text(encoding='utf-8'))
rf=json.loads((OUT/'scale_control_raw_focus.json').read_text(encoding='utf-8'))
sm={c['case_id']:c for c in s['cases']};rm={c['case_id']:c for c in rf['cases']}
baseline=json.loads((SOURCE/'results.json').read_text(encoding='utf-8'))

# 核对候选子集、去重约束、评分和最终统计；不读取任何源视频。
checks=0
for c in d['cases']:
    cid=c['case_id'];rows=json.loads((OUT/f'case_{cid:02d}_candidates.json').read_text(encoding='utf-8'))
    order=json.loads((OUT/f'case_{cid:02d}_rankings.json').read_text(encoding='utf-8'))
    byid={r['index_id']:r for r in rows};assert len(byid)==500
    pool=[byid[ix] for ix in order['dedup_dino']];assert len({r['asset_id'] for r in pool})==c['unique_assets_before']
    for aid in {r['asset_id'] for r in pool}:
        ts=[r['timestamp'] for r in pool if r['asset_id']==aid];assert len(ts)<=5
        assert all(abs(a-b)>=10 for i,a in enumerate(ts) for b in ts[i+1:])
    norm=json.loads((OUT/f'case_{cid:02d}_scale_control.json').read_text(encoding='utf-8'))
    assert {r['index_id'] for r in norm['candidates']}==set(order['dedup_dino'])
    nby={r['index_id']:r for r in norm['candidates']}
    assert norm['rankings']['dual_w025']==[r['index_id'] for r in sorted(norm['candidates'],key=lambda r:(-(.75*r['similarity']+.25*r['dual_quality']),r['dino_rank']))]
    if not c['gt_in_top500']:
        assert all(m['first_gt_frame_rank'] is None for m in sm[cid]['metrics'].values())
    for r in norm['candidates']:
        for v,m in r['orb'].items():
            assert 0<=m['inliers']<=m['good_matches']<=m['cross_matches']
            assert 0<=m['quality']<=1
    checks+=1

# 把关键成功的镜像几何匹配保存为可复核图片。
prod=production_orb();cv2.setNumThreads(1)
for cid in [7,8]:
    target=sm[cid]['metrics']['dual_w025']['first_gt'];view=max(target['orb'],key=lambda v:target['orb'][v]['quality'])
    qpath=Path(baseline['cases'][cid-1]['query']);query=cv2.imdecode(np.frombuffer(qpath.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    h,w=query.shape[:2];query=cv2.resize(query,(round(w*256/max(w,h)),round(h*256/max(w,h))),interpolation=cv2.INTER_AREA)
    if view=='mirror':query=cv2.flip(query,1)
    original=json.loads((OUT/f'case_{cid:02d}_candidates.json').read_text(encoding='utf-8'))
    row=next(r for r in original if r['index_id']==target['index_id'])
    db=sqlite3.connect((FORMAL/row['shard']).resolve().as_uri()+'?mode=ro',uri=True)
    try:blob=db.execute('select thumbnail from frames where frame_number=?',(row['frame_number'],)).fetchone()[0]
    finally:db.close()
    frame=cv2.imdecode(np.frombuffer(blob,np.uint8),cv2.IMREAD_COLOR)
    kq,dq=prod['orb'].detectAndCompute(query,None);kc,dc=prod['orb'].detectAndCompute(frame,None)
    matches=sorted(prod['bf_matcher'].match(dq,dc),key=lambda m:m.distance);good=[m for m in matches if m.distance<50]
    cv2.setRNGSeed(20260928)
    H,mask=cv2.findHomography(np.float32([kq[m.queryIdx].pt for m in good]).reshape(-1,1,2),np.float32([kc[m.trainIdx].pt for m in good]).reshape(-1,1,2),cv2.RANSAC,3,maxIters=2000,confidence=.995)
    assert int(mask.sum())==target['orb'][view]['inliers']
    canvas=cv2.drawMatches(query,kq,frame,kc,good,None,matchesMask=mask.ravel().tolist(),flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS)
    cv2.imencode('.png',canvas)[1].tofile(str(OUT/f'case_{cid}_inlier_matches.png'))

after=snapshot();before=json.loads((OUT/'protected_before.json').read_text(encoding='utf-8'))
changes={p:{'before':before.get(p),'after':after.get(p)} for p in before.keys()|after.keys() if before.get(p)!=after.get(p)}
assert not changes
for path,digest in d['source_sha256'].items():assert sha(Path(path))==digest
write('protected_after.json',after)
d.update(scale_control=s,scale_control_raw_focus=rf,final_evaluated_scheme='scale_control/dedup_dual_w025',
         final_scheme_note='初始预声明主方案保留；单次固定尺度核对后作为最终评估候选方案，属于探索性结果，未使用GT参与评分；需独立验证集确认',
         protected_changes=changes,validation={'status':'PASS','cases_checked':checks,'production_good_count_checks':d['production_raw_match_parity_checks'],'jpeg_identity_checks':12,'source_sha256_unchanged':True,'protected_file_stat_changes':0},
         candidate_comparisons_total=5000+sum(c['candidate_count'] for c in s['cases'])+1000)
write('results.json',d)

fields=['stage','case_id','scheme','original_global_rank','candidate_frames','candidate_assets','gt_frame_rank','unique_asset_rank','top1','top5','top10','top20','top50']
with (OUT/'results.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
    for stage,cc in [('native_query',d['cases']),('scale_control_dedup',s['cases']),('scale_control_raw_focus',rf['cases'])]:
        for c in cc:
            for name,m in c['metrics'].items():
                writer.writerow(dict(stage=stage,case_id=c['case_id'],scheme=name,original_global_rank=d['cases'][c['case_id']-1]['original_global_rank'],candidate_frames=m['candidate_frames'],candidate_assets=m['candidate_assets'],gt_frame_rank=m['first_gt_frame_rank'],unique_asset_rank=m['unique_asset_rank'],**{f'top{k}':m['hits'][str(k)] for k in [1,5,10,20,50]}))

def rank(v):return str(v) if v is not None else '>500（池外）'
def r(c,name):return rank(c['metrics'][name]['first_gt_frame_rank'])
raw_times=[c['timing']['raw500_orb_added_seconds'] for c in d['cases']]
times=[c['measured_added_seconds'] for c in s['cases']]
L=['# 地狱素材10例：Top500去重与ORB局部精排','',
'## 结论','',
'**case 4 最终第7，case 7 最终第1，两例均进入Top10。收益来源不同：4号由候选去重救回，7号由尺度对齐后的镜像ORB几何验证救回。**','',
'- 原始DINO：素材Top1=2/10（20%）、Top5=5/10（50%）、Top10=5/10（50%）。',
'- 仅去重：Top1=2/10、Top5=5/10、Top10=6/10。',
'- 最终评估方案（去重、query长边256、原图/镜像ORB取优、ORB权重0.25）：**Top1=4/10（40%）、Top5=6/10（60%）、Top10=7/10（70%）**。',
'- 原成功1、2、3、5、8全部仍在Top10，0例退化；8号进一步到第1。',
'- 6、9、10仍为池外对照：**ORB rerank cannot rescue because GT is outside candidate pool.** 未扩大召回到Top10000。',
f'- 原尺寸query对原始500帧双视图ORB，新增耗时中位数{statistics.median(raw_times):.3f}秒；最终固定尺度去重方案实测中位数{statistics.median(times):.3f}秒、平均{statistics.mean(times):.3f}秒，4号{sm[4]["measured_added_seconds"]:.3f}秒、7号{sm[7]["measured_added_seconds"]:.3f}秒。',
'- 值得作为“寻帧”的可选实验模式继续验证，**不建议凭这10例立即替换生产默认排序**。其中尺度处理是在第一轮失败后补充的探索性控制，7号只有7个几何内点、0.25融合的领先分差很小，须检查独立样本中的误匹配。',
'- 若后续上线：建议DINO仍取Top500，先按asset/时间去重，再对最多Top200代表帧做ORB；这10例去重后最多162帧，Top200不丢失本批任何已验证候选。不要直接只对原始Top100帧精排，4/7会被漏掉。',
'- 本轮不再继续调ORB。两例已进入Top10，但4号的ORB仍无有效证据，不能把去重收益归给ORB。时间定位只作记录，不设优化目标。','',
'## 边界、输入与可复现性','',
'复用`hell10_diagnosis/case_01_rankings.json`至`case_10_rankings.json`中的original Top500。之前的正式库文件size/mtime_ns与本次快照逐文件核对一致；本次未重做DINO query推理、未读写FAISS、未构建embedding。所有候选均来自原图正式DINO Top500，没有把GT帧额外塞入池中。每例每轮最多500帧。',
'GT集合与上一阶段一致，包括5号的两个可接受同内容源资产。统计的是**候选帧列表中正确asset第一次出现的位置**，因此可与154/226直接比较。另记unique_asset_rank，但不把它当成原frame列表rank冒充提升。1号其它asset可能有重叠录制，仍沿用严格指定源文件口径，不临时扩充GT。',
'所有新脚本、匹配证据、报告仅写此目录；原formal_v1、formal_v1_repaired、已有DINO embedding、FAISS、Web、CLIP及hell10_diagnosis结果未修改。原视频不解码、不扫描、不抽帧。所有shard以SQLite mode=ro读已有JPEG。','',
'## 预先固定的实验与有限追加控制','',
'1. A：原始frame Top500，DINO排序。',
'2. B：按DINO顺序贪心保留每asset最多5帧，同asset代表帧时间间隔至少10秒（时间邻域抑制，不做长时间链式聚类）；保留全体原有asset，不从库外补候选。',
'3. C：原始Top500做ORB；D：去重池做ORB。分别看原query、水平翻转query和二者quality取max。',
'4. 仅比较0.25、0.50两个融合权重，另列纯ORB质量排序作为诊断。初始主方案预声明为去重+双视图+0.25，未根据GT逐例选权重。',
'5. 初轮全部几何质量为0；查看候选尺寸后，仅追加一次固定query长边256尺度控制，用INTER_AREA保持比例缩小query，不放大低分辨率JPEG、不改变ORB参数。对10例去重池共639帧统一执行，再对4/7各原始Top500执行同尺度控制，以分离去重和ORB的贡献。没有尺度网格或继续调参。',
'6. 最终候选方案统一使用固定尺度+去重+双视图+0.25；探索性追加过程完整保留。结果不能当作独立测试集上已验证的泛化提升。','',
'## ORB复用与几何评分','',
'从video_search.py通过AST仅加载原orb、bf_matcher及match_orb_features，避免执行Streamlit页面或生产维护逻辑。保持ORB_create(nfeatures=500, scaleFactor=1.2, nlevels=8)、NORM_HAMMING、crossCheck=True和distance<50。生产函数只返回good数量，无RANSAC，也未实际使用min_good参数；本实验不修改该函数或生产权重。',
'为避免同一query重复提取500次描述子，实验缓存描述子，按相同筛选规则计算匹配。30组实际调用原函数的good数量核对全部一致；12个JPEG自身匹配检查通过，证明管线并非整体失效。',
'- match_ratio = good_matches / 全部crossCheck匹配数；另存good/min(query特征数,candidate特征数)。',
'- 使用同一组good匹配计算findHomography：RANSAC，候选坐标阈值3px，最大2000次，confidence=0.995，固定RNG种子。',
'- 内点数≥6、内点率≥0.35时：Q=min(inliers/15,1) × sqrt(match_ratio × inlier_rate)，否则Q=0。保留raw good、ratio、内点数/率、描述子数供复核。',
'- 融合 F=(1−w)×DINO_similarity+w×Q，w仅0.25/0.50。双视图取Q较大者，同分回退DINO原rank。没有用GT标签参与任何评分。',
'- 这不是纯raw match count。若所有候选Q=0，纯ORB和融合排序都回退原DINO顺序；不能声称此时ORB提升了排序。','',
'## 候选去重统计','',
'|case|原500唯一asset|去重后asset|去重后frame|GT frame前/后|原frame列表GT rank|去重GT rank|原唯一asset ordinal|',
'|---|---:|---:|---:|---:|---:|---:|---:|']
for c in d['cases']:
    L.append(f'|{c["case_id"]}|{c["unique_assets_before"]}|{c["candidate_assets_after"]}|{c["frames_after"]}|{c["gt_frames_before"]}/{c["gt_frames_after"]}|{c["original_global_rank"]}|{r(c,"dedup_dino")}|{rank(c["metrics"]["raw_dino"]["unique_asset_rank"])}|')
L+=['','原500帧里只有1–69个asset，确实存在大量重复候选。4号GT本来是第3个出现的asset，但在frame列表排154；去重压缩后进入第7。7号GT是第39个出现的asset，单靠去重仍排86，需另有局部证据。','',
'## 4/7重点结果：分离去重与ORB','',
'|方案|case 4|case 7|','|---|---:|---:|',
'|A 原DINO Top500|154|226|',
'|B 去重+DINO|7|86|',
'|C 原尺寸query，原500+原/镜像ORB/融合|154|226|',
'|D 原尺寸query，去重+原/镜像ORB/融合|7|86|',
'|尺度对齐，原500+原query ORB|154|226|',
'|尺度对齐，原500+镜像或双视图ORB|154|1|',
'|尺度对齐，原500+双视图融合0.25/0.50|154|1|',
'|尺度对齐，去重+原query ORB|7|86|',
'|尺度对齐，去重+镜像或双视图ORB|7|1|',
'|最终：尺度对齐，去重+双视图融合0.25|7|1|',
'|敏感性：相同方案融合0.50|7|1|','',
'|最终case|Top50|Top20|Top10|Top5|Top1|','|---|---|---|---|---|---|',
'|4，第7|是|是|是|否|否|',
'|7，第1|是|是|是|是|是|','',
'### 7号的几何证据','',
'最终胜出候选index_id=1455655，video_id=346，原DINO第257帧（正确asset首次出现是第226）。原query仅2个good；尺度对齐的镜像query有72个crossCheck匹配、8个good、7个RANSAC内点，内点率87.5%，match_ratio=11.11%，Q=0.145509。',
'相同0.25融合下，该候选分数约0.503694，原DINO第1候选Q=0后分数约0.503489，领先仅约0.000205。0.50权重下也为第1，但这不能代替独立样本验证。',
'![case7 镜像query与候选的7个几何内点](case_7_inlier_matches.png)','',
'### 4号仍没有ORB证据','',
'去重保留的正确asset最佳帧为index_id=50229、video_id=83、timestamp=19s，原DINO第154。其good=0、Q=0；去重后第7完全来自候选压缩。GT标注476s，本次未解决视频内时间定位。','',
'## 全10例最终结果与成功例保护','',
'|case|用户原结果|DINO原rank|仅去重rank|最终rank|最终unique asset ordinal|是否保住/救回Top10|','|---|---|---:|---:|---:|---:|---|']
for c in d['cases']:
    m=sm[c['case_id']]['metrics']['dual_w025']
    L.append(f'|{c["case_id"]}|{"成功" if c["user_success"] else "失败"}|{c["original_global_rank"]}|{r(c,"dedup_dino")}|{rank(m["first_gt_frame_rank"])}|{rank(m["unique_asset_rank"])}|{"是" if m["hits"]["10"] else "否，池外"}|')
L+=['','|模式|Top1|Top5|Top10|原成功5例跌出Top10|','|---|---:|---:|---:|---:|']
for label,hits,lost in [('原DINO',d['summary']['raw_dino']['frame_list_hits'],[]),('仅去重',d['summary']['dedup_dino']['frame_list_hits'],[]),('原尺寸query+去重+双ORB 0.25',d['summary'][FINAL]['frame_list_hits'],[]),('尺度对齐+去重+原query ORB 0.25',s['summary']['original_w025']['hits'],s['summary']['original_w025']['lost_success_top10']),('尺度对齐+去重+镜像query ORB 0.25',s['summary']['mirror_w025']['hits'],s['summary']['mirror_w025']['lost_success_top10']),('最终尺度对齐+去重+双ORB 0.25',s['summary']['dual_w025']['hits'],s['summary']['dual_w025']['lost_success_top10']),('同方案权重0.50',s['summary']['dual_w050']['hits'],s['summary']['dual_w050']['lost_success_top10'])]:
    L.append('|'+label+'|'+'|'.join(f'{hits[str(k)]}/10 ({hits[str(k)]*10}%)' for k in [1,5,10])+'|'+str(len(lost))+'|')
L+=['','6/9/10在所有方案都没有候选池内GT；它们只做同一Top500范围的负面对照，未增加搜索深度。原全库rank8122/3755/3264保留；池内无排名用null表示，不能写成501或声称ORB能救回。',
'3/8的±2秒问题仅沿用上一阶段记录，本次没有以时间命中率选参数、扩大视频内搜索或修改timestamp。8号最终胜出帧恰为4044.072s，但不据此宣称本次已解决时间定位。','',
'## 耗时与执行规模','',
'计时为本机单线程OpenCV的新增本地工作，不含DINO检索、网络和页面渲染。最终方案计时包含加载冻结候选JSON、query解码/缩放、ORB、只读JPEG读取与解码；结束于评分完成，未含后续JSON报告落盘。文件可能已在操作系统缓存中；首例含部分首次调用开销。每例只计一次，不是稳定P95 benchmark。','',
'|case|原500双视图ORB增加秒|最终处理帧数|最终方案实测增加秒|','|---|---:|---:|---:|']
for c in d['cases']:
    sc=sm[c['case_id']];L.append(f'|{c["case_id"]}|{c["timing"]["raw500_orb_added_seconds"]:.3f}|{sc["candidate_count"]}|{sc["measured_added_seconds"]:.3f}|')
L += ['',f'原500路径中位数{statistics.median(raw_times):.3f}s；最终去重路径中位数{statistics.median(times):.3f}s，范围{min(times):.3f}–{max(times):.3f}s。相同尺度原500对照：4号{rm[4]["measured_added_seconds"]:.3f}s，7号{rm[7]["measured_added_seconds"]:.3f}s。',
'主实验5000个候选配对；尺度核对639个；4/7原池同尺度对照1000个，共6639个候选配对，每个做原/镜像两个ORB方向。最大每次候选深度仍为500。没有读取Top10000、进行全库特征扫描或生成新embedding。','',
'## 上线判断与停止条件','',
'去重本身有明确小样本收益，且更省JPEG和ORB处理开销，值得优先做可回退的试用。ORB仅在尺度对齐后对7、8出现有效增益，推荐先做独立业务验证集，增加视觉相似但非GT的困难负例，确认少量内点不会带来误排，再决定是否作为可选精排加入“寻帧”。本次不修改Web。',
'建议参数起点：DINO Top500 → 每asset最多5帧、时间间隔10秒 → 按DINO保留最多200代表帧 → query固定长边256 → 原/镜像ORB几何验证 → 0.25融合。Top200是成本上限建议，仅因为本批最大162可完整覆盖，不代表对其它素材已验证足够。评分证据不足时保持DINO顺序。',
'本次两例进入Top10，故不满足“两例仍无法进入Top10”的失败停止条件；但也不继续搜权重或放宽RANSAC门槛。4号无几何证据，不再为它调ORB。后续若独立样本无法复现收益，应停止继续调ORB，而非扩大到Top10000。','',
'## 输出和校验','',
'- results.json：初始主实验、固定尺度控制、4/7原池控制、汇总指标与参数、来源SHA256和保护检查。',
'- results.csv：308行case×方案长表，stage列分清原尺寸与尺度控制，空rank表示候选池外。',
'- case_XX_candidates.json：原500候选的DINO排名、双方向good/ratio/内点及耗时；case_XX_rankings.json保存每种方案的index_id排序。',
'- case_XX_scale_control.json：最终尺度控制的评分及排序；case_04/07_scale_control_raw.json是同尺度原池对照。',
'- experiment_config.json：运行前固定的去重、RANSAC和融合参数。',
'- protected_before/after.json：正式两库、Web非runtime文件、CLIP、原诊断目录及video_search.py的逐文件大小/mtime_ns快照；差异0。冻结排名和query源文件的SHA256再次核对一致。没有声称重算整个FAISS的SHA。',
'- 10例候选子集、每asset上限、10秒间隔、融合排序公式、池外对照、原函数匹配数、自匹配管线全部校验通过。','']
(OUT/'report.md').write_text('\n'.join(L),encoding='utf-8')
assert len(list(csv.DictReader((OUT/'results.csv').open(encoding='utf-8-sig'))))==308
print(json.dumps({'status':'PASS','final_summary':s['summary']['dual_w025'],'protected_changes':changes,'report_lines':len(L)}))
