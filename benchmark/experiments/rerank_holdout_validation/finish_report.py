"""从冻结候选复核指标并生成报告；不再检索或调参。"""
from pathlib import Path
import csv, io, json, hashlib
import numpy as np
from PIL import Image, ImageDraw
from prepare_dataset import ROOT, OUT, FORMAL, ro, read, write, sha
from run_validation import protected, deduplicate, metric, transitions

def main():
    r=read(OUT/'results.json');cases=r['cases'];schemes=r['protocol']['schemes'];n=len(cases)
    checks={'case_count':n,'ranking_checks':0,'fusion_checks':0,'gt_mapping_checks':0,'source_query_checks':0}
    frozen=read(OUT/'frozen_dataset.json')['cases']
    for c,f in zip(cases,frozen):
        assert c['id']==f['id'] and sha(c['query'])==f['signature']['sha256'];checks['source_query_checks']+=1
        assert all(Path(x['file_name']).stem==f['source_video_name'] for x in f['corpus']);checks['gt_mapping_checks']+=1
        cache=read(OUT/(c['id']+'_candidates.json'));raw=cache['raw_top500'];kept=deduplicate(raw)
        assert len(raw)==500 and len({x['index_id'] for x in raw})==500
        scored=cache['scored_dedup'];assert set(x['index_id'] for x in scored)==set(x['index_id'] for x in kept)
        for x in scored:
            q=max(x['orb']['original']['quality'],x['orb']['mirror']['quality'])
            assert abs(x['fused_score']-(.75*x['similarity']+.25*q))<1e-12;checks['fusion_checks']+=1
        assert scored==sorted(scored,key=lambda x:(-x['fused_score'],x['dino_rank']))
        for name,pool in zip(schemes,[raw,kept,scored]):
            m=metric(pool,set(c['gt_asset_ids']))
            assert m==c['metrics'][name];checks['ranking_checks']+=1
    for s in schemes:
        for k in ['1','5','10']:
            assert r['summary'][s]['hits'][k]==sum(c['metrics'][s]['hits'][k] for c in cases)
    assert not r['protected_changes']
    assert protected()==read(OUT/'protected_before.json')
    assert sha(OUT/'frozen_protocol.json')==r['protocol_sha256']
    assert sha(OUT/'frozen_dataset.json')==r['dataset_sha256']
    checks['protected_file_stat_unchanged']=True
    checks['independent_query_count']=len({c['query'] for c in cases})
    checks['unique_gt_assets']=len({a for c in cases for a in c['gt_asset_ids']})
    checks['gt_indexed_within_2_seconds']=sum(any(abs(v['nearest_frame']['timestamp']-f['expected_timestamp'])<=2 for v in f['corpus']) for f in frozen)
    checks['protocol_unchanged']=True
    r['production_decision']={'choice':'A','recommendation':'候选去重可以上线，ORB暂不上线；本次不修改生产',
                              'basis':'去重Top10救回1例无退化；ORB额外Top10救回0例，增加约0.41秒median等待；小样本和等价片段标签问题限制Top1解释。'}
    r['posthoc_visual_review']={'cases':['business_04','business_19'],
                               'observation':'A Top1与C Top1画面高度相似，疑似同一直播片段的不同文件；尚未核实视频片段等价性。',
                               'gt_changed':False,'metrics_changed':False,
                               'limitation':'按冻结GT计2例asset Top1回退，不直接认定为2例业务画面错误；也不擅自扩充GT抹去退化。'}
    write('results.json',r)
    write('verification.json',checks)
    # CSV每方案独立行，耗时明确对应方案，避免把C总耗时误写成A/B。
    fields=['case_id','scheme','gt_asset_ids','gt_in_top500','rank','unique_asset_rank','top1','top5','top10','candidate_frames','candidate_assets','difficulty']
    for name in ['baseline','dedup','orb','added','scheme_total']:
        fields += [name+'_median_seconds',name+'_p95_seconds']
    with (OUT/'results.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader()
        for c in cases:
            t=r['timing_by_case'][c['id']]
            for s,m in c['metrics'].items():
                row={'case_id':c['id'],'scheme':s,'gt_asset_ids':'|'.join(c['gt_asset_ids']),'gt_in_top500':c['gt_in_top500'],
                     'rank':m['first_gt_frame_rank'] if m['first_gt_frame_rank'] else '>500 / outside pool','unique_asset_rank':m['unique_asset_rank'],
                     **{f'top{k}':m['hits'][str(k)] for k in [1,5,10]},'candidate_frames':m['candidate_frames'],'candidate_assets':m['candidate_assets'],'difficulty':c['difficulty']['group']}
                for label,key in [('baseline','baseline_seconds'),('dedup','dedup_seconds'),('orb','orb_seconds'),('added','added_seconds'),
                                  ('scheme_total',{'A_DINO':'baseline_seconds','B_DEDUP':'B_total_seconds','C_DEDUP_ORB':'C_total_seconds'}[s])]:
                    for stat in ['median_seconds','p95_seconds']:row[label+'_'+stat]=t[key][stat]
                writer.writerow(row)
    # 保存GT退化案例的可复查JPEG联系图；只读现有缩略图，不seek原视频。
    examples=[]
    for cid in ['business_04','business_19']:
        c=next(c for c in cases if c['id']==cid)
        raw=read(OUT/(cid+'_candidates.json'))
        examples.append((cid+' query',Image.open(c['query']).convert('RGB')))
        for label,row in [('A top1',raw['raw_top500'][0]),('C top1',raw['scored_dedup'][0])]:
            with ro(FORMAL/row['shard']) as db:
                blob=db.execute('SELECT thumbnail FROM frames WHERE frame_number=?',(row['frame_number'],)).fetchone()[0]
            examples.append((f"{cid} {label} v{row['video_id']} t{row['timestamp']:.1f}",Image.open(io.BytesIO(blob)).convert('RGB')))
    sheet=Image.new('RGB',(900,800),'white');draw=ImageDraw.Draw(sheet)
    for i,(label,im) in enumerate(examples):
        im.thumbnail((290,360));x=(i%3)*300;y=(i//3)*400
        sheet.paste(im,(x,y+35));draw.text((x+2,y+3),label,fill='black')
    sheet.save(OUT/'top1_regression_review.jpg')
    def rank(c,s):return c['metrics'][s]['first_gt_frame_rank'] or '>500（候选池外）'
    def count(v):return f'{v}/{n}（{100*v/n:.0f}%）'
    def names(xs):return '、'.join(xs) if xs else '无'
    L=['# 寻帧排序方案独立验证：冻结参数结果','',
       '**建议选择 A：候选去重可以上线，ORB 暂不上线。这里只给建议，未修改生产。**',
       '20例中，去重使列表Top10命中由16例增至17例；ORB未进一步增加Top10，Top1改善3例、退化2例，净增1例。ORB额外成本中位数约0.41秒。单次小样本验证不足以证明稳定泛化收益。','',
       '## 1. 样本来源和独立性','',
       '反馈库共有34条图片搜索：6条correct、5条no_correct、23条无反馈。6条correct全部缺少corrected_timestamp，因此“已确认正确素材和正确时间”的反馈样本为0。未把predicted_timestamp当作GT。',
       f'使用已有business20真实业务benchmark的20例。合格独立图片20张、不同GT逻辑asset {checks["unique_gt_assets"]}个，距离目标20例还缺0例。20例GT均在formal_v1_repaired，{checks["gt_indexed_within_2_seconds"]}例GT时间±2秒内有索引帧。',
       '检索前做字节SHA-256、解码RGB哈希、原/镜像pHash近邻检查，并人工查看20例与hell10的联系图；没有重复query或同场景派生图。另检查同asset且GT相差≤10秒的重叠，未命中。两套实验GT asset集合也不重叠。hell10衍生图片及既有ORB实验图片均纳入排除比对，未使用它们补足样本。',
       '独立性边界：这20例没有参与hell10 ORB参数调整，但曾用于旧检索/模型比较。因此是相对该次rerank调参的独立验证，不是从未用于任何开发的盲测；部分案例来自同一个asset，20张图也不是20段完全独立视频。GT采用原benchmark的允许视频列表，通过production_video_id映射到逻辑asset；没有根据这次得分事后扩大GT。','',
       '## 2. 冻结方案和统计口径','',
       '- A：正式formal_v1_repaired，原图query，FAISS精确Top500。',
       '- B：在A顺序上贪心保留代表帧；每asset≤5帧，与该asset已保留帧时间差≥10秒。',
       '- C：仅对B候选读取已有JPEG；query保持比例长边256、INTER_AREA；原query及水平镜像ORB取quality较大者；score=0.75×DINO+0.25×ORB quality，同分按DINO原rank。',
       '- ORB直接复用hell10实现及生产ORB构造器：500特征、scaleFactor=1.2、8层、Hamming cross-check、distance<50；RANSAC阈值3像素、2000迭代、confidence=.995、固定seed20260928。内点≥6且内点率≥.35才给分；quality=min(inliers/15,1)×sqrt(match_ratio×inlier_rate)。',
       '- 只运行A/B/C，不搜索权重、尺度、候选数量或时间间隔。冻结协议与样本SHA在results.json，原实现SHA在frozen_protocol.json。',
       '- **主口径是素材命中**：前K条frame结果中出现任一GT asset即成功，不要求时间正确；同asset多帧仍占多个显示位置，与上一轮hell10口径一致。另给“先完全折叠为唯一asset列表”的TopK，明确区分两种口径。未优化视频内时间定位。','',
       '## 3. 三方案素材命中','', '| 方案 | Top1 | Top5 | Top10 |','|---|---:|---:|---:|']
    for s in schemes:L.append('| '+s+' | '+' | '.join(count(r['summary'][s]['hits'][str(k)]) for k in [1,5,10])+' |')
    L+=['','完全唯一asset列表口径（每个asset只出现一次，仅用于指标解释，不是第四种检索方案）：','', '| 方案 | Top1 | Top5 | Top10 |','|---|---:|---:|---:|']
    for s in schemes:L.append('| '+s+' | '+' | '.join(count(r['summary'][s]['unique_asset_hits'][str(k)]) for k in [1,5,10])+' |')
    L+=['','B不会改变asset首次出现的相对顺序，因此它的收益来自减少重复frame占位，不是新增召回或提升唯一asset排序。若未来界面本来已完全折叠为一asset一行，则本次去重没有增加唯一asset Top10命中。','',
        '## 4. 逐case排名','', '| case | A baseline | B 去重 | C 去重+ORB | Top500唯一asset | 去重帧数 | 类型 |','|---|---:|---:|---:|---:|---:|---|']
    for c in cases:L.append(f"| {c['id']} | {rank(c,schemes[0])} | {rank(c,schemes[1])} | {rank(c,schemes[2])} | {c['unique_assets']} | {c['dedup_frames']} | {c['difficulty']['group']} |")
    L+=['','business_07的正确asset不在原图Top500，三个方案均不能命中。ORB rerank cannot rescue because GT is outside candidate pool. business_01和business_06虽然保留在候选中，最终仍为37和93，未进入Top10。','',
        '## 5. 分开计算救回与退化','']
    for title,key in [('候选去重自身（A→B）','A_DINO_to_B_DEDUP'),('增加ORB的贡献（B→C）','B_DEDUP_to_C_DEDUP_ORB'),('最终方案相对baseline（A→C）','A_DINO_to_C_DEDUP_ORB')]:
        d=r['transitions'][key];L += [f'### {title}','']
        for label,name in [('Top10救回','top10_rescued'),('Top10退化','top10_regressed'),('Top1改善','top1_rescued'),('Top1退化','top1_regressed')]:L.append(f'- {label}：{len(d[name])}例；{names(d[name])}。')
        L.append('')
    L+=['具体变化：business_16为17→8→1；business_03为2→2→1，business_05为4→4→1；business_04和business_19均为1→1→2。两个Top1退化仍留在Top5/Top10。判定严格遵循检索前冻结的GT asset，不因局部相似而自动认定别的asset为正确。',
        '**Top1退化的标注限制：**人工查看top1_regression_review.jpg发现，两例的A Top1与C Top1画面高度相似，疑似同一直播片段存在于不同文件。business_04从video19的6930秒改排video187的6135秒；business_19从video238的178秒改排video27的13023秒。没有解码原视频核实片段等价性，不能将这2例asset Top1回退直接写成2例业务画面错误。所有指标继续使用检索前GT，未事后扩大允许asset集合。此问题限制对ORB“伤害”的解释，后续应补齐等价片段标注；本次不修GT、不另算一套调参结果。','',
        '## 6. 性能','',
        '本机CUDA DINO、FAISS CPU四线程、OpenCV单线程；20张图各测3轮，总计60次。三轮完整候选排序均一致。复用已加载模型和FAISS实例；固定黑图仅做CUDA算子预热；不缓存候选JPEG或ORB描述子到应用内存，允许操作系统正常文件缓存。',
        'baseline计时含图片读取/解码、query embedding、FAISS Top500、500条metadata查询。ORB额外计时含query变换/描述子、候选JPEG数据库读取/解码、描述子、双视图匹配、RANSAC与融合排序。总耗时是实际逐query阶段之和；不包含Streamlit渲染、上传、预览或并发排队。模型+FAISS加载约%.2f秒另计，不算单次搜索。'%r['startup_seconds'],'',
        '| 阶段 | median | P95 |','|---|---:|---:|']
    for title,key in [('A baseline','baseline_seconds'),('去重单独','dedup_seconds'),('ORB单独额外','orb_seconds'),('去重+ORB额外','added_seconds'),('B总计','B_total_seconds'),('C总计','C_total_seconds')]:
        t=r['timing_summary'][key];L.append(f"| {title} | {1000*t['median_seconds']:.3f} ms | {1000*t['p95_seconds']:.3f} ms |")
    L+=['','P95为60次观测的numpy线性百分位估计，不代表并发或高负载SLA。三轮不是60个独立准确率案例，准确率分母始终为20。首轮ORB额外median/P95约431/866ms；后两轮约396/807ms、395/803ms。',
        '交互判断：C端到端计算median约0.60秒、P95约1.03秒，单用户计算延迟仍可用于交互；但本轮未测试真实Web渲染和并发，不据此保证Web端延迟。去重仅约0.14ms；当前独立集上ORB的额外等待没有带来额外Top10救回。','',
        '逐query中位耗时（ms；每例三轮详细值和P95见JSON/CSV）：','',
        '| case | baseline | 去重 | ORB额外 | C总计 |','|---|---:|---:|---:|---:|']
    for c in cases:
        t=r['timing_by_case'][c['id']];L.append('| '+c['id']+' | '+' | '.join(f"{1000*t[k]['median_seconds']:.3f}" for k in ['baseline_seconds','dedup_seconds','orb_seconds','C_total_seconds'])+' |')
    L+=['','## 7. 困难类型相关性','', '| 人工可见分组 | 例数 | A Top1/5/10 | B Top1/5/10 | C Top1/5/10 |','|---|---:|---|---|---|']
    for group,g in r['difficulty_groups'].items():L.append('| '+group+f" | {g['n']} | "+' | '.join('/'.join(str(g['hits'][s][str(k)]) for k in [1,5,10]) for s in schemes)+' |')
    L+=['','上述为命中例数。全部20例都有后加文字，无纯净普通截图对照组；明显背景合成8例（其中business_06兼有大贴纸，单列复杂二创）。保留场景的12例也有字幕或小画中画。镜像、裁切/放大缺少可靠源图对照，均标unknown，不臆造分组统计。',
        '去重救回的business_16属于换背景类；该组也有本来成功和仍失败的案例，不能解释为换背景必然失败。ORB在保留场景组Top1改善2例且退化2例，在换背景组改善1例。每组样本很少，且多种干扰共存，只能描述相关现象，不能归因或据此调整参数。','',
        '## 8. 完整性和复核','',
        f'读取正式FAISS ntotal={r["faiss_ntotal"]:,}；未写正式索引、metadata、feature、模型或Web。只为20个query计算查询向量，没有重建任何素材embedding。复核{checks["ranking_checks"]}份方案指标、{checks["fusion_checks"]}个去重候选融合公式及20份GT文件名映射，全部通过。',
        'formal_v1、formal_v1_repaired、Web、CLIP目录（如存在）、旧hell10诊断和ORB实验、原查询/案例/反馈库的文件路径、大小、mtime_ns前后比对无变化。此处是文件stat检查，不冒称全库内容SHA校验。旧实验实现及生产ORB源码另做SHA核验。',
        '没有启动Web，没有新增第四个方案，没有调参、抽帧、全库扫描推理或CLIP建库。输出目录中的脚本可复查；prepare_dataset.py准备样本，run_validation.py执行冻结的三方案，finish_report.py从已保存候选复核并生成报告。','',
        '## 9. 最终生产决策','',
        '1. 独立验证集实际20例，目标缺口0；相对hell10 rerank调参独立，含14个不同GT asset。',
        '2. baseline Top1/5/10：55% / 80% / 80%。',
        '3. 仅去重 Top1/5/10：55% / 80% / 85%。',
        '4. 去重+ORB Top1/5/10：60% / 85% / 85%。',
        '5. 去重Top10救回1例：business_16。',
        '6. 去重Top10退化0例，Top1也无退化。',
        '7. ORB在去重基础上额外Top10救回0例；Top1改善3例。',
        '8. ORB额外Top10退化0例；Top1退化2例：business_04、business_19。',
        '9. 去重+ORB额外延迟median/P95：409.293 / 862.270ms；其中去重本身仅0.143 / 0.224ms。',
        '10. **选择A：候选去重可以上线，ORB暂不上线。** 去重对当前多帧结果列表复现了小幅收益，成本极低、无观察到的命中退化；ORB的Top1净收益只有1例且伴随2例Top1回退，没有额外Top10救回，暂不足以支持默认增加约0.41秒等待。建议后续若获授权，先仅上线已冻结去重并保留回退；继续收集有正确时间和等价素材标注的新反馈，再决定ORB。当前20例不足以宣称显著性或广泛泛化。本次不执行上线，也不继续调ORB。','',
        '## 文件','',
        '- results.json：协议、逐例指标、三轮耗时、救回/退化、完整性检查。',
        '- results.csv：60行（20例×3方案）逐例排名、素材命中与耗时。',
        '- business_*_candidates.json：完整Top500与去重候选ORB证据、三个方案排序。',
        '- dataset_audit.json / frozen_dataset.json / frozen_protocol.json：来源、排除核对、GT及检索前冻结参数。',
        '- independence_contact_sheet.jpg：20例与hell10独立性人工复核图。',
        '- top1_regression_review.jpg：两个Top1退化的query、A Top1、C Top1现有JPEG。',
        '- verification.json / protected_before.json / protected_after.json：可复查校验。','']
    (OUT/'report.md').write_text('\n'.join(L),encoding='utf-8')
    print(json.dumps(checks,ensure_ascii=False))

if __name__=='__main__':main()
