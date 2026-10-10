"""从本次真实查询结果生成报告，不访问或修改正式索引。"""
from pathlib import Path
import json,csv
OUT=Path(__file__).resolve().parent
d=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
cases=d['cases']
def tm(s):
    s=round(s);return f'{s//3600:02}:{s%3600//60:02}:{s%60:02}'
def rank(m,k='best_asset'):return m[k]['rank'] if m[k] else 'NA'
def pair(m):return f'{rank(m)} / {rank(m,"best_time_2s")}'
manual={
1:('60–70%','30–40%','低','双人动作清楚，背景保留'),
2:('55–65%','35–45%','中','镜像，但保留原场景与双人姿态'),
3:('50–60%','40–50%','中','人物左右关系与GT相反，可能还包含未标注的镜像；原标签保持不变'),
4:('50–65%','35–50%','中','主体姿态有信息，但中心区域仍有较多替换背景；贴纸不在实际模型输入中'),
5:('70–80%','20–30%','低','单人近景占比高，原场景保留'),
6:('55–65%','35–45%','中','镜像及背景替换叠加；特效影响不能单独分离'),
7:('65–75%','25–35%','低','双人俯身动作；去上下区域crop有改善，但未进Top10'),
8:('65–80%','20–35%','低','放大后三人局部组合保留辨识信息；相似姿态帧优先于标注时间'),
9:('55–65%','35–45%','中','单人近景和背景替换；9号与5号都为近景，但背景/细节不同，不是控制变量实验'),
10:('45–60%','40–55%','中至高','人工对照可见主体缩放/构图变化；标准crop后query与GT可见部位不完全一致')}
for c in cases:
    a,b,level,note=manual[c['case_id']]
    c['manual_visual_review']=dict(subject_fraction_rough=a,background_fraction_rough=b,subtitle_occlusion_whole_query='高',subtitle_occlusion_actual_model_input='无黄色字幕',replacement_background_actual_input=level if '换背景' in c['transformations'] else '未换背景',notes=note,method='人工粗估，未分割测量；主体/背景是布局范围，字幕叠加另记，不作为精确可加总比例')
    c['per_candidate_original_top500']={str(v):next(({'rank':r['rank'],'similarity':r['similarity'],'timestamp':r['timestamp']} for r in json.loads((OUT/f'case_{c["case_id"]:02d}_rankings.json').read_text(encoding='utf-8'))['original'] if r['video_id']==v),None) for v in c['accepted_video_ids']}
fail=[c for c in cases if not c['user_success']]
d['failure_class_counts']={x:sum(c['category']==x for c in fail) for x in ['A','B','C','D']}
d['failure_variant_summary']={name:{criterion:{str(k):sum(c['metrics'][name][criterion] is not None and c['metrics'][name][criterion]['rank']<=k for c in fail) for k in [1,5,10,50,100,200,500]} for criterion in ['best_asset','best_time_2s']} for name in fail[0]['metrics']}
d['verification']={'status':'PASS','cases':10,'case_variant_rows':50,'top500_records':25000,'logical_usable_assets':319,'protected_file_stat_changes':0}
d['diagnosis_conclusions']={
    'gt_cases_in_corpus':10,'gt_cases_with_frame_within_2s':10,
    'original_success_cases':[1,2,3,5,8],
    'production_mirror_recommendation':'暂不直接上线；只看到Top1改善1例，Top10无新增成功，且个别排名退化',
    'production_crop_recommendation':'暂不加入默认多视图max融合；仅保留离线实验，有局部排名收益但无失败例进入Top10',
    'minimal_next_step':'独立实验中扩大候选至500，按asset和相邻时间窗去重，验证现有ORB局部匹配精排；对6/9/10保留更深候选诊断，精排无法修复未召回',
    'largest_bottleneck':'复杂二创下整图特征候选召回（3/5失败Top500外），其次排序（2/5）；镜像有个别收益；字幕不是本批首要证据；时间定位另有3/8两例',
}
(OUT/'results.json').write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# 地狱素材10例失败诊断','',
'数据源：`D:/Users/Desktop/地狱素材/1.png` 至 `10.png`；`D:/Users/Desktop/测试结果.xls`，Sheet1 A1:F11。空白=用户找到正确素材，“无”=未找到。',
'本报告只读 formal_v1_repaired；未修改 formal_v1、formal_v1_repaired、FAISS、已有embedding、Web或CLIP。仅对10张query及20张query变体做临时DINO前向，共30次。所有诊断产物保存在本目录。','',
'## 核心结论','',
'1. **10/10 GT在319个正式逻辑资产内，10/10标注时间附近有索引帧，GT_OUTSIDE_CORPUS=0。**',
'2. 原图素材级Top10成功5/10，恰好重现用户记录：1、2、3、5、8。失败5例：**A=3（6、9、10），B=2（4、7），C=0，D=0**。A表示正确素材Top500未召回，B表示已召回但不在Top10。',
'3. 原图+镜像逐帧max融合：**素材级Top1=30%、Top5=50%、Top10=50%**；原图为20%、50%、50%。5个失败案例没有一个通过镜像或crop实验进入Top10。',
'4. 严格时间±2秒：原图+镜像融合Top1=0%、Top5=30%、Top10=30%；原图为0%、20%、30%。±5秒融合为20%、30%、30%。这不同于“找到正确素材”的业务口径。',
'5. 镜像有局部收益：10号素材rank 3264→395，融合409；6号8122→541，仍在500外。crop有局部收益：4号154→64，6号8122→435，7号226→76，10号3264→151。均未解决前十命中。',
'6. **暂不直接把镜像双查询或crop多视图max融合加入生产默认路径。** 小样本里Top10没有收益；融合会抬升更多干扰候选，局部改善可能被抵消。',
'7. 更像是复杂二创下整体特征的召回不足，其次是候选排序。镜像、背景替换、主体尺度/布局变化均可能相关，现有数据不能隔离因果。3和8换背景仍成功，不能说“换背景一定失败”。',
'8. 原图预处理已去掉顶部/底部黄色字幕，4号贴纸也不在模型输入里。**本批证据不支持字幕/贴纸是主要失败原因。**',
'9. 最小下一步：先做独立Top500候选按asset/相邻时间去重和现有ORB局部精排验证，优先4、7；保留原DINO排序回退。6、9、10原图未进入Top500，单纯精排无法解决其召回问题。不要凭这10例直接上线。','',
'## 方法与口径','',
f'- 索引：`{d["index"]}`，{d["index_type"]}，{d["ntotal"]:,}帧，384维归一化向量，严格验收READY；现有DINOv2-small权重和现有预处理，设备 `{d["device"]}`。',
'- 只读SQLite URI `mode=ro`；FAISS仅read_index/search；不抽帧、不解码原视频、不训练、不重建素材embedding。GT人工核对使用已有JPEG。',
'- 对每个视图计算全库精确内积分数和排名，保存完整Top500。Top10/50/100/200/500均是其前缀；不是把500外一律记为未出现。并列按index_id升序，极少数同分候选次序可能与Web/FAISS默认tie顺序不同。',
'- 原图+镜像融合按同一FAISS row/index_id取max，覆盖整个库后重排；无Top500截断误差。没有按视频聚合或去重，保持当前逐帧检索口径。',
'- 正确asset/video：用户指定源视频对应逻辑资产；正确时间：同一可接受资产且距表中时间≤2秒，另外报告≤5秒。GT时间仅精确到整秒，不保证就是截图逐帧真值。C类仅说明检索定位偏差，不等于metadata时间轴错误。',
'- 5号出现两个同名不同SHA资产，video_id=18和185；已有GT缩略图显示同一内容、同一时间附近，按可接受GT集合处理。两者逐个Top500命中保存在results.json的per_candidate_original_top500。不可将不同SHA自动合并资产。',
'- “Top1错误分数”在本报告严格定义为排名最高的非GT资产分数。部分不同asset可能包含重叠录制内容；未对全库建立内容等价标签，不能把所有非GT判为视觉不相关。人工查看1号Top1的video_id=293缩略图，与GT=8显示相同治疗场景，疑似重叠录制。因此该例严格源文件Top1未命中不等于画面完全错误，未擅自扩充GT集合。素材级Top1是指定源文件口径，不能直接当作所有内容等价版本的业务Top1准确率。',
'- 每个variant都给出正确候选最佳分数；跨variant的similarity变化可能来自不同帧，不代表同一帧的控制变量测量。',
f'- 查询诊断主体耗时{d["elapsed_seconds"]:.2f}秒（包含模型和索引加载、30次query推理、排名和结果写盘；不包含人工核对和报告整理）。','',
'## GT覆盖核对','',
'|案例|正确视频名称|video_id|asset_id|GT时间|最近索引时间/差值|状态|',
'|---|---|---|---|---|---|---|']
for c in cases:
    nearest='；'.join(f'{a["video_id"]}: {a["nearest_frame"]["timestamp"]:.3f}s / {a["nearest_delta"]:.3f}s' for a in c['gt_candidates'])
    lines.append(f'|{c["case_id"]}|{c["gt_name"]}|{", ".join(map(str,c["accepted_video_ids"]))}|{"<br>".join(c["accepted_asset_ids"])}|{tm(c["gt_seconds"])}|{nearest}|IN_CORPUS，原路径存在|')
lines+=['','319个可用逻辑资产与正式videos表按asset_id匹配。所有GT附近±2秒存在已索引frame；详细frame_id、frame_number、timestamp和源路径见cases.json及results.json。6号“妙手陶老师2026.22”精确对应`.ts`文件；“.22”不是扩展名。','',
'GT缩略图人工对照：','![1至5号GT对照](gt_review_1_5.jpg)','![6至10号GT对照](gt_review_6_10.jpg)','',
'## 原图排名和分数','',
'素材rank表示同一GT资产任意时刻第一次出现；时间rank限定±2秒。差值为正确候选similarity减Top1分数，负值表示落后。','',
'|案例|用户结果|素材/video rank|时间±2s rank|时间±5s rank|素材分数|时间分数|最高非GT分数|素材−Top1|时间−Top1|',
'|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for c in cases:
    m=c['metrics']['original']
    lines.append(f'|{c["case_id"]}|{"成功" if c["user_success"] else "失败"}|{rank(m)}|{rank(m,"best_time_2s")}|{rank(m,"best_time_5s")}|{m["best_asset"]["similarity"]:.6f}|{m["best_time_2s"]["similarity"]:.6f}|{m["top1_wrong_asset"]["similarity"]:.6f}|{m["correct_asset_minus_top1"]:.6f}|{m["correct_time_minus_top1"]:.6f}|')
lines+=['','### 不同截断位置的命中','',
'|案例|Top10 素材/时间|Top50|Top100|Top200|Top500|','|---|---|---|---|---|---|']
for c in cases:
    hits=c['metrics']['original']['cutoffs']
    labels=[' / '.join('✓' if hits[str(k)][v] else '×' for v in ['asset','time_2s']) for k in [10,50,100,200,500]]
    lines.append('|'+str(c['case_id'])+'|'+'|'.join(labels)+'|')
lines+=['','## 失败5例分类','',
'|案例|主分类|证据|补充问题|','|---|---|---|---|',
'|4|B 排序|正确素材第154，已进入Top500|素材最佳帧在19s，GT476s；GT时间±2s排5191。即使素材排前，仍需细化时间。|',
'|6|A 特征召回|正确素材第8122|GT时间±2s排25127；镜像改善素材rank到541，尚未达到500。|',
'|7|B 排序|正确素材第226，时间±2s第257|去字幕区域crop把两者都提升到76，是最适合小范围候选精排验证的一例。|',
'|9|A 特征召回|正确素材第3755|时间±2s第5670；镜像变差，crop未带来足够rank改善。|',
'|10|A 特征召回|正确素材第3264|时间±2s第45853；镜像和中心crop改善明显，但最佳时间crop rank仍838。|','',
'分类采用D→A→B→C→HIT的互斥顺序。失败5例C=0并不表示它们没有时间定位难点，而是素材召回/排序已经先失败。用户成功的3号和8号属于“素材成功但严格时间未进Top10”：3号最佳素材时间2240s，距GT45s；8号3960.054s，距GT82.946s。它们的时间±2s rank分别2363和23。','',
'## 镜像双查询','',
'每格为“素材rank / 时间±2s rank”。','',
'|案例|原图|水平翻转|原图+镜像max|最佳素材分数变化（镜像−原图）|最佳时间分数变化|进入阈值|','|---|---|---|---|---:|---:|---|']
for c in cases:
    m=c['metrics'];tr=c['mirror_transitions']
    transitions='；'.join(f'{key}:Top{k}' for key in ['best_asset','best_time_2s'] for k in [10,100,500] if tr[key][str(k)]) or '无新增跨阈值'
    lines.append(f'|{c["case_id"]}|{pair(m["original"])}|{pair(m["mirror"])}|{pair(m["original_mirror_max"])}|{tr["best_asset"]["similarity_change"]:+.6f}|{tr["best_time_2s"]["similarity_change"]:+.6f}|{transitions}|')
lines+=['','只有10号素材从Top500外进入Top500；没有从Top100外进入Top100或从Top10外进入Top10的新增案例。4号单独镜像素材154→617，反而退出Top500。6号和10号有镜像鲁棒性相关证据，但不能概括为所有镜像截图都会失败。','',
'### 融合命中率','',
'|口径/模式|Top1|Top5|Top10|Top500|','|---|---:|---:|---:|---:|']
for criterion,label in [('best_asset','素材'),('best_time_2s','时间±2秒'),('best_time_5s','时间±5秒')]:
    for mode in ['original','mirror','original_mirror_max']:
        s=d['summary'][mode][criterion]
        lines.append(f'|{label}/{mode}|'+ '|'.join(f'{s[str(k)]}/10 ({s[str(k)]*10}%)' for k in [1,5,10,500])+'|')
lines+=['','## 失败5例区域实验','',
'- subtitle_crop：固定保留原图横向100%、纵向28%–72%，避开上下黄色字幕。不做文字检测。',
'- center75：横、纵均保留中心75%区域；之后仍使用既有DINO预处理。',
'- original_crops_max：原图、subtitle_crop、center75逐帧分数max；all_views_max再加镜像。',
'- 这些crop使用固定比例，无标签调参、无人物检测；只在失败5例做，不能据此计算全10例crop泛化率。crop后仍有中心裁切，变化不仅是去字幕，也改变主体尺度和可见上下文。','',
'|案例|原图|镜像|去上下区域crop|中心75%|原图+两crop融合|全部视图融合|','|---|---|---|---|---|---|---|']
for c in fail:
    lines.append('|'+str(c['case_id'])+'|'+'|'.join(pair(c['metrics'][name]) for name in ['original','mirror','subtitle_crop','center75','original_crops_max','all_views_max'])+'|')
lines+=['','**所有失败例的所有单视图及融合都没有素材/时间Top10命中。** 6号中心crop进Top500但时间rank17834；7号subtitle_crop素材和时间进Top100；10号中心crop素材进Top200，时间仍在Top500外。9号没有被这些简单变体救回。','',
'max融合不保证rank改善：7号中心crop把正确素材分数从0.624518升到0.752054，但rank反而从226降到519，其他候选提升更大；其subtitle_crop单独rank76，也被max融合压到519。9号中心crop分数0.571426→0.790574，但rank3755→3882。不同视图的绝对余弦分数不能直接解释为可比的命中概率。','',
'## 成功与失败的视觉差异（仅相关性）','',
'全图主体/背景比例为人工粗估范围，不是分割测量。字幕为叠加遮挡，另行记录。原图10例都有较大黄色字幕，目视遮挡等级均高；但实际模型输入没有这些字幕。','',
'|案例|用户结果|用户标注变换|主体占比粗估|背景占比粗估|实际模型输入替换背景|观察|','|---|---|---|---|---|---|---|']
for c in cases:
    v=c['manual_visual_review'];lines.append(f'|{c["case_id"]}|{"成功" if c["user_success"] else "失败"}|{c["transformations"]}|{v["subject_fraction_rough"]}|{v["background_fraction_rough"]}|{v["replacement_background_actual_input"]}|{v["notes"]}|')
lines+=['',
'- 按用户标签：换背景7例中成功2、失败5；未换背景3例成功3。镜像5例中成功1、失败4；未标镜像5例成功4、失败1。标签可能不完整，例如3号人工对照也显示左右反转，因此这些比率只能描述当前小样本。',
'- 贴纸/特效各1例均失败，但贴纸不在模型实际输入区域；特效和其他变换共现，不能单独归因。',
'- 标注放大仅8号且成功；人工对照10号也可见缩放/构图差异。主体大并不必然成功，9号单人近景仍失败。',
'- DINO现有预处理为短边256、中心224×224。所有query为320×666，实际保留约原图x=20–300、y=192.5–472.5，只有中部约42%高度（坐标为缩放近似，实际输入图按真实processor生成）。原始整张图的大字幕不等于模型实际看到的大字幕。',
'- 实际模型输入如下，黄色字幕和左下贴纸均不在内；换过的背景、人体局部、尺度和左右关系仍然在内。','',
'![10例实际模型输入](actual_model_inputs.jpg)','',
'## 下一步最小实验建议','',
'1. 保留本次10例和可接受GT集合，增加少量独立真实业务截图作为验证集；素材命中和时间命中分开验收。3号、10号变换标签和3号精确时间可再人工核准。',
'2. 先对4、7做独立候选Top500按asset/相邻时间去重，再复用现有ORB对候选已有JPEG做局部几何验证/精排；不要直接改Web。它们已有召回，是改动最小、问题最明确的验证对象。',
'3. 10号镜像/中心crop可作为候选扩展实验，6号中心crop也能带来素材候选；使用候选并集后再排序，比较rank融合或局部验证，不再默认裸max分数可靠。9号保留为未解决的强失败案例。',
'这些仅为建议，本次没有实施新的精排、阈值调优、模型切换、训练、建库或Web变更。','',
'## 文件和保护检查','',
'- `results.json`：全量GT、每种variant的指标、Top1/最高非GT详情、分数差、阈值命中、镜像阈值迁移、人工视觉观察。',
'- `results.csv`：50行case×variant长表，便于筛选对比。',
'- `case_01_rankings.json` 至 `case_10_rankings.json`：每种variant的完整Top500，含index_id、frame_id、asset_id、video_id、timestamp、路径、分数。',
'- `cases.json`：表格GT解析、所有同名资产匹配、附近frame和JPEG对应关系。',
'- `preprocessing.json`、`actual_model_inputs.jpg`：实际模型裁切参数与输入图。',
'- `protected_before.json` / `protected_after.json`：正式两库、Web非runtime文件、CLIP目录的逐文件大小与mtime_ns快照；差异为0。此为文件状态检查，未声称重算全库SHA。全部数据库用只读模式打开。',
'- 复现：指定CUDA Python运行本目录`diagnose.py --run`；GT准备不访问模型，运行`diagnose.py`。运行前后均不写正式库。','']
(OUT/'report.md').write_text('\n'.join(lines),encoding='utf-8')
with (OUT/'gt_coverage.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['case_id','gt_name','asset_id','video_id','gt_time','gt_seconds','in_corpus','nearest_index_id','nearest_frame_id','nearest_timestamp','nearest_delta','source_path'])
    for c in cases:
        for a in c['gt_candidates']:
            w.writerow([c['case_id'],c['gt_name'],a['asset_id'],a['video_id'],tm(c['gt_seconds']),c['gt_seconds'],a['in_corpus'],a['nearest_frame']['index_id'],a['nearest_frame']['frame_id'],a['nearest_frame']['timestamp'],a['nearest_delta'],a['file_path']])
print('REPORT_WRITTEN',len(lines),'lines')
