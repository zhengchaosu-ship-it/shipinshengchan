"""只分析已冻结查询结果；不查询模型，不修改GT或任何正式文件。"""
import csv
import re
import statistics
from pathlib import Path
from run import OUT,INDEX,PARAMS,snapshot
from speech_search.common import read_json,write_json
from speech_search.query import clock


NOTES={
 'B_fuzzy10':dict(category=['B','D'],primary='跨asset局部词句竞争，叠加错字/旧ASR噪声',
    similarity='局部近似；“段/短”错字与Top1的“不一段”接近，Top1语句不完整，不能断定完整语义相同。',
    negation='query、GT、Top1均含否定字；未确认肯否反转。',highly_similar=False,polarity_reversal=False),
 'B_fuzzy16':dict(category=['B','D'],primary='不同asset的近乎同文话术竞争',
    similarity='近乎同文，分差只有0.002637。文件名为同日14:29:11与14:29:14，口播位置仅差约1.12秒，疑似同源不同录制；没有音视频核实，保留原asset和单一GT。',
    negation='双方都表示没效果，非肯否反转。',highly_similar=True,polarity_reversal=False),
 'C_semantic19':dict(category=['B','D'],primary='不同asset的高度同义通用话术竞争',
    similarity='Top1“人身体所有的东西都相通”与GT“人体是相通的”高度同义，但不是指定原视频。',
    negation='不涉及否定。',highly_similar=True,polarity_reversal=False),
 'C_semantic20':dict(category=['C','E'],primary='否定含义反转，真正GT时间窗口在Top200外',
    similarity='Top1是疼，query/GT是不疼；仅有部位/疼痛词汇相似，命题相反。同asset首次出现的另一个窗口并不是GT原句。',
    negation='明确肯否反转：没有疼痛感 → 一個部位疼。',highly_similar=False,polarity_reversal=True),
 'C_semantic21':dict(category=['B'],primary='跨asset高度同义通用短句竞争；正确时间已召回但排序靠后',
    similarity='Top1“我做的工作 就是这个”和GT“我就是干这个活的”同义。指定GT时间raw rank179，现有折叠105，新时间折叠103；不是Top200召回失败。',
    negation='不涉及否定。',highly_similar=True,polarity_reversal=False),
 'C_semantic22':dict(category=['B','D'],primary='跨asset局部主题词竞争，遗漏动作含义',
    similarity='Top1只有“老人在家裡”，与GT共享老人/在家，但没有“自己可以做”的动作含义；不是完整同义句。',
    negation='不涉及否定。',highly_similar=False,polarity_reversal=False),
 'C_semantic23':dict(category=['B','D'],primary='跨asset数字/局部话术竞争，另有同asset不同位置',
    similarity='Top1“两百下三百下”共享三百下，但缺少按到的含义。正确asset有两个位置相隔约15秒；只留一条会删掉GT时间。',
    negation='不涉及否定。',highly_similar=False,polarity_reversal=False),
}


def txt(value):return str(value).replace('|','\\|').replace('\n',' ')
def rk(value):return str(value) if value is not None else '候选外/被折叠'
def interval(r):return f"{clock(r['start_time'])}–{clock(r['end_time'])}"


def main():
    r=read_json(OUT/'results.json');plan=read_json(OUT/'plan.json')
    assert r['params']==PARAMS and snapshot()==plan['protected']
    r['diagnosis_annotations']=NOTES
    r['diagnosis_counts']=dict(top1_errors=7,top1_caused_by_duplicate_windows=0,
        cross_asset_similar_or_partial_competition=6,highly_similar_or_same_wording=3,partial_topic_competition=3,
        negation_token_present_among_errors=3,confirmed_polarity_reversal=1,
        gt_asset_current_top2_to_top10=5,gt_asset_outside_top200=0,gt_time_outside_top200=1,
        gt_rank_penalized_by_raw_overlap=3,extra_time_dedup_asset_rank_improved_among_errors=0)
    r['index_hash_verification']=read_json(OUT/'index_hash_verification.json')
    write_json(OUT/'results.json',r)
    lines=['# 全库Semantic候选去重与32例错例诊断','',
        '**结论：不建议把本次新增10秒时间去重作为准确率优化上线；保留现有折叠即可。每asset只留一条会损伤时间定位，不建议采用。暂不建议据本实验确认寻帧Beta的检索质量已通过。**','',
        '正式索引完整性READY状态未变。本轮只写本实验目录；没有改索引、模型、原字幕、GT、Web，也没有启动Whisper。','',
        '## 口径与冻结规则','',
        '- 查询复用BGE-small-zh-v1.5正式Encoder与原Top200候选，所有方案共享同一批query embedding与FAISS候选；没有重建库存embedding。原始similarity和排序键保持不变。',
        '- A：当前formal_query.py方案，本来已有collapse：同asset起点相差≤2秒，或交集≥较短区间50%时保留最高分。当前25/32基线不是未去重的raw window排名。',
        '- B：每asset只保留最高分候选，作为对照，不推荐生产使用。',
        '- C：保留A条件，再增加同asset时间中心差<10秒；分数从高到低选择代表。只与已保留代表比较，不做链式传递聚类，不限制每asset不同位置的数量。',
        '- raw_windows另列为诊断口径，不是第四套调参方案。冻结计划在52例运行前保存于plan.json，之后没有测试10/12/15秒等多套阈值。',
        '- 正确时间沿用GT起点在结果区间±2秒，未改变时间判定或GT。32例及额外20例均是此前从旧转写选句/改写的固定集合，未独立听审，不能当成业务上线准确率保证。',
        '- 52例当前Top10的window_id与历史结果逐条一致，分数差<1e-6。对候选外GT只额外计算诊断排名，不将其补入Top200，不用于新的去重/排序。','',
        '## 三方案效果','',
        '| 集合 | 方案 | 素材Top1 | Top5 | Top10 | 正确时间附近Top10 |',
        '|---|---|---:|---:|---:|---:|']
    names={'raw_windows':'未折叠window（诊断）','A_current':'A 当前Semantic','B_asset':'B 每asset一条','C_time':'C 同asset时间去重'}
    for group,g in r['groups'].items():
        for mode,s in g['metrics'].items():
            n=s['n'];hits=s['asset_hits'];v=[f"{hits[f'top{k}']}/{n} ({hits[f'top{k}']/n:.1%})" for k in [1,5,10]]
            lines.append(f"| {group} | {names[mode]} | {' | '.join(v)} | {s['nearby_hits']['top10']}/{n} ({s['nearby_hits']['top10']/n:.1%}) |")
    lines+=['','- C相对A：32例和额外20例的Top1/5/10救回均为0、退化均为0；正确时间Top10也无变化。',
        '- B相对A：素材指标不变，但C_semantic23的正确时间掉出Top10，32例时间命中从30/32降到29/32。GT前约15秒有另一句更高分话术，资产级去重将真正GT删掉。',
        '- 只删除较低分重复项且保留最高分，数学上不会改变Top1；本次52例也逐条验证Top1未变。不能把Top1错误归因为“低分重叠window挤占”。','',
        '## 7个Top1错误汇总','',
        '| case | 当前asset rank | 新时间去重asset rank | raw asset rank | raw正确时间rank | 主要原因 |',
        '|---|---:|---:|---:|---:|---|']
    for e in r['errors']:
        cid=e['case']['case_id'];g=e['gt']
        lines.append(f"| {cid} | {rk(e['ranks']['A_current']['asset'])} | {rk(e['ranks']['C_time']['asset'])} | {g['asset_raw_rank']} | {g['nearby_raw_rank']} | {NOTES[cid]['primary']} |")
    lines+=['','分类统计（有交叉，不应相加）：','',
        '- A：重叠window直接造成Top1错误 **0/7**。原始GT之前确有重复窗口的3例为C_semantic19/20/21，既有折叠已将其asset rank从7→6、28→13、37→27；新增10秒规则未再改善这7例的asset rank。',
        '- B：跨asset相似/局部话术竞争 **6/7**。其中高度同义或近乎同文3例（B_fuzzy16、C_semantic19、C_semantic21）；局部关键词/错字竞争3例（B_fuzzy10、C_semantic22、C_semantic23），后3例不能称为完整语义等价。',
        '- C：query含否定字的Top1错误3例，但确认肯否反转只有 **1例C_semantic20**；另外2例双方均含否定，不能算否定错误。',
        '- D：正确asset已经在当前Top2–Top10 **5/7**；另外2例为rank13和27。',
        '- E：7例的正确asset都在raw Top200内，资产级完全漏召回为0；但C_semantic20的真正GT时间raw rank **6827**，属于话术/时间级候选召回失败。C_semantic21真正GT raw rank179，仍在候选内，折叠后105→103仍很靠后。','']
    for e in r['errors']:
        case=e['case'];cid=case['case_id'];top=e['top1'];gt=e['gt'];a=gt['asset_result'];t=gt['nearby_result'];note=NOTES[cid]
        lines += [f"### {cid}",'',f"- query：{case['query']}",
            f"- GT：{case['asset_id']}，video_id={case['video_id']}，{interval(case)}；原文：{case['expected_text']}",
            f"- 当前Top1：{top['asset_id']}，video_id={top['video_id']}，source_video_id={top['source_video_id']}，{interval(top)}，score={top['semantic_score']:.6f}",
            f"- Top1 matched_text：{top['matched_text']}",
            f"- GT asset首次窗口：当前rank {rk(e['ranks']['A_current']['asset'])} / raw rank {gt['asset_raw_rank']}；{interval(a)}；{a['matched_text']}；score={a['semantic_score']:.6f}；Top1减它的分差={e['top1_minus_gt_score']:.6f}。",
            f"- GT正确时间窗口：当前rank {rk(e['ranks']['A_current']['nearby'])} / raw rank {gt['nearby_raw_rank']}；{interval(t)}；{t['matched_text']}；score={t['semantic_score']:.6f}；Top1减它的分差={e['top1_minus_gt_nearby_score']:.6f}。",
            f"- 话术关系：{note['similarity']}",f"- 否定表达：{note['negation']}",
            f"- 重复占位：raw Top10有{e['raw_top10_unique_assets']}个asset/{e['raw_top10_time_clusters']}个时间簇；GT asset之前raw窗口{e['preceding_raw_windows']}个，现有折叠后{e['preceding_after_current']}个，新增时间去重后{e['preceding_after_time']}个。重复项确实存在，但不能改变该例Top1。",
            f"- 类型：{' + '.join(note['category'])}；{note['primary']}。",'']
    lines+=['## 否定表达单独统计','',
        '按不/不是/没有/并非/不一定/不要及没/未/无进行词面筛选，32例命中13例，额外20例命中10例。该集合包含“不平衡”“要不要”“有没有”“没多久”等，不能把所有词面命中当作肯否对立。','',
        '| 集合/case | query | 当前asset rank | Top1原文 | 人工判断 |','|---|---|---:|---|---|']
    for x in r['negation_cases']:
        note='指定GT Top1，无明确反转' if x['asset_rank']==1 else '指定GT未Top1，不能仅凭否定词判反转'
        if x['case_id']=='C_semantic20':note='明确肯否反转'
        if x['case_id'] in ['B_fuzzy10','B_fuzzy16']:note='双方含否定；不是已证实反转'
        if x['case_id']=='NEW13':note='有没有/酸不酸是疑问，未确认肯否反转'
        lines.append(f"| {x['group']}/{x['case_id']} | {txt(x['query'])} | {x['asset_rank']} | {txt(x['top10'][0]['matched_text'])} | {note} |")
    lines+=['','- C_semantic20：肯定句“一個部位疼”0.728884领先否定句“这个位置 还真没有疼的地方”0.707352，差0.021531；指定GT“不疼这个地方”只有0.610076，差0.118807。存在区分不足的直接例证。',
        '- NEW14：“我没说按摩一定很舒服”的正确否定候选0.803649，肯定短句“按摩舒服”0.785518，差0.018131。当前正确，但两者相近。',
        '- 这些是既有候选中的观察，不是语义完全匹配的最小肯否对照集。不能据1个明确错误认定否定是7例的主要成因；本轮没有加否定过滤、降权或rerank，也没有编码新的肯否改写query。','',
        '## 去重耗时与展示变化','',
        '| 操作 | median ms | P95 ms |','|---|---:|---:|']
    for m,p in r['performance'].items():lines.append(f"| {names.get(m,'C相对A额外耗时')} | {p['median_ms']:.6f} | {p['p95_ms']:.6f} |")
    changed=[x['case']['case_id'] for x in r['records'] if [v['window_id'] for v in x['modes']['A_current']['top10']]!=[v['window_id'] for v in x['modes']['C_time']['top10']]]
    lines += ['',
        '每例后处理重复21次取中位数，再对52例中位数计算median/P95；计时不含编码、FAISS或metadata读取。不是把1092次重复当独立测试案例。数量很小的CPU操作，测量有微秒级噪声，没有明显查询延迟。',
        f"新增时间去重改变了{len(changed)}/52例的Top10窗口组成（{', '.join(changed)}），但未改变素材或时间Top10命中。它提高部分结果间的时间间隔，不能据此宣称准确率提高。",'',
        '## 生产与Beta判断','',
        '1. 保留当前已有的同asset重叠折叠。新增10秒规则没有复现准确率收益，不建议为了本轮7个Top1错例将其接入生产。',
        '2. 不采用每asset仅1条：已实测损伤C_semantic23时间命中。',
        '3. 本轮未解决跨视频同义竞争与否定反转；不能把索引READY或轻量去重当作检索质量达标。暂不建议据本次结果确认寻帧Beta已具备质量验收条件；人工候选辅助检索在技术上可用，但是否接受该能力边界需另行决定，本轮不接Web。',
        '4. 未继续参数搜索、融合、negation rerank或模型实验。','',
        '## 文件与保护证据','',
        f"- 52例当前基线逐条复现：{r['baseline_reproduced_all']}；GT文件SHA未改变：{r['gt_hashes_unchanged']}。",
        f"- 全部正式speech目录及其它受保护文件集合/大小/mtime未变：{r['protected_files_unchanged']}；FAISS和metadata SHA-256与原严格验收报告一致：{r['index_hash_verification']}。",
        '- 4项边界单测通过：保最高分、不同asset、同asset独立时间点、10秒边界、非传递链、长窗口包含关系。',
        '- results.json保存52例原Top200、三方案与raw诊断结果、7个错例、否定筛选及人工分类；results.csv为逐例指标；errors.csv为7例详细诊断。',
        '- 本轮只新增speech_search/experiments/formal_dedup_validation内文件。正式query.py/formal_query.py和Web均未修改。','']
    (OUT/'report.md').write_text('\n'.join(lines),encoding='utf8')
    with (OUT/'errors.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['case_id','query','gt_asset','gt_start','gt_end','gt_original_text','top1_asset','top1_text','top1_score','current_asset_rank','raw_asset_rank','first_asset_text','first_asset_score','asset_score_gap','current_time_rank','raw_time_rank','gt_time_text','gt_time_score','gt_time_score_gap','category','reason','negation','similarity']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for e in r['errors']:
            c=e['case'];cid=c['case_id'];g=e['gt'];n=NOTES[cid]
            w.writerow(dict(case_id=cid,query=c['query'],gt_asset=c['asset_id'],gt_start=c['start_time'],gt_end=c['end_time'],gt_original_text=c['expected_text'],
                top1_asset=e['top1']['asset_id'],top1_text=e['top1']['matched_text'],top1_score=e['top1']['semantic_score'],current_asset_rank=e['ranks']['A_current']['asset'],raw_asset_rank=g['asset_raw_rank'],
                first_asset_text=g['asset_result']['matched_text'],first_asset_score=g['asset_result']['semantic_score'],asset_score_gap=e['top1_minus_gt_score'],
                current_time_rank=e['ranks']['A_current']['nearby'],raw_time_rank=g['nearby_raw_rank'],gt_time_text=g['nearby_result']['matched_text'],gt_time_score=g['nearby_result']['semantic_score'],gt_time_score_gap=e['top1_minus_gt_nearby_score'],category='+'.join(n['category']),reason=n['primary'],negation=n['negation'],similarity=n['similarity']))
    print('report.md / results.json / results.csv / errors.csv complete; no production changes')


if __name__=='__main__':main()
