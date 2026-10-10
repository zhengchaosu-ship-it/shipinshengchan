"""从已完成实验生成报告，不运行额外模型或更改排序。"""
import json
import re
import statistics
from prepare_model import OUT,MODEL,REVISION
from run import VARIANTS,name,hit,NEG,snapshot
from speech_search.common import read_json,write_json


def rate(x,n):return f'{x}/{n} ({x/n:.1%})'
def esc(x):return str(x).replace('|','\\|').replace('\n',' ')
def rank_text(x):return str(x) if x is not None else 'Top10外'


def main():
    r=read_json(OUT/'results.json');p=read_json(OUT/'plan.json')
    assert snapshot()==p['protected'] and r['gt_hashes_unchanged']
    selected=r['selection_before_extra20'];extra_ok=False;latency_ok=False
    if selected:
        extra=r['groups']['additional20'][selected]['metrics'];base=r['groups']['additional20']['baseline']['metrics']
        extra_ok=all(extra['asset_hits'][k]>=base['asset_hits'][k] for k in ['top1','top5','top10']) and extra['nearby_hits']['top10']>=base['nearby_hits']['top10']
        latency_ok=r['performance']['variants'][selected]['total']['p95_ms']<=2000
    old_errors={e['case']['case_id'] for e in r['availability']}
    records={x['case']['case_id']:x for x in r['records']}
    rescue_counts={}
    for k,mode in VARIANTS:
        key=name(k,mode)
        rescue_counts[key]=dict(asset_top1=[c for c in old_errors if hit(records[c]['variants'][key]['asset_rank'],1)],
            real_gt_time_top1=[c for c in old_errors if hit(records[c]['variants'][key]['nearby_rank'],1)],
            time_unrescuable=[e['case']['case_id'] for e in r['availability'] if e['gt_time_raw_rank']>k])
    truncated=[dict(case_id=x['case']['case_id'],variant=v,window_id=row['window_id'],info=row['token_info'])
        for x in r['records'] for v,d in x['variants'].items() if v!='baseline' for row in d['scored_pool'] if row['token_info']['window_truncated'] or row['token_info']['query_truncated']]
    decision=dict(selected_on_original32=selected,extra20_no_regression=extra_ok,total_p95_within_2s=latency_ok,
        support_beta=bool(selected and extra_ok and latency_ok),old_errors_rescued=rescue_counts,
        truncated_pairs=truncated,protected_files_unchanged=r['protected_files_unchanged'],gt_unchanged=r['gt_hashes_unchanged'],
        note='模型和上下文未据额外20例调整。候选方案先由32例选出，额外20例只作固定门槛检查；跨时间错误单列。')
    write_json(OUT/'decision.json',decision)
    yes='支持进入人工核对型寻帧Beta的后续接入验收，但本轮不接Web，也不代表正式准确率保证。' if decision['support_beta'] else '本轮不建议上线reranker；保留当前Semantic。Top20 window-only在32例和延迟上通过，但额外20例Top1从95%降至85%，收益没有稳定复现。'
    lines=['# 话术搜索V1 Semantic TopK精排验证','',yes,'',
        '**实测最佳折中为Top20 + window only，但未通过额外20例。** 32例素材Top1从25/32升到27/32（78.1%→84.4%），救回B_fuzzy16、C_semantic23，新增素材Top1退化0；其中真正GT时间Top1只救回B_fuzzy16，C_semantic23仍优先给出GT前15秒的另一句话。额外20例素材Top1从19/20降至17/20（95%→85%），新增NEW15、NEW16两例退化，救回0。',
        '32例正确时间Top10仍30/32，额外20例仍19/20。合计52例素材Top1为44/52→44/52，正确时间Top1为44/52→43/52；这只是描述性合计，不能抵消额外集退化。','',
        '## 模型与冻结实验','',
        f'- 唯一reranker：**{MODEL}**；revision `{REVISION}`，官方约278M参数，原权重1,112,206,140 bytes，实验独立目录加载。',
        '- 官方说明其为中英文cross-encoder、输入query/document直接输出相关性；参考[BAAI模型卡](https://huggingface.co/BAAI/bge-reranker-base)。中文与否定区分的实际表现以下方本地测试为准，不能由模型说明推定。',
        '- 使用已有CUDA Python与Transformers，不重装生产依赖。RTX3060、FP16、batch8、最大512tokens；输出原始logit，不是概率，也不与Semantic/Fuzzy分数做加权融合。同logit仅以原semantic分数及window_id确定顺序。',
        '- 只比较raw Semantic Top20、Top50、Top100。基线仍用当前Top200 + 原collapse，不增加Top500/1000模型精排。',
        '- window输入：原query + candidate.original_text。context输入：原query + 前一句最后最多40token + 原窗口 + 后一句最前最多40token，核心窗口优先。query上限128tokens，无额外检索指令。',
        '- 排序后复用现有collapse，未启用上一轮新增10秒规则，也未做新的去重实验。上下文不扩大输出窗口或GT时间判定，正确时间仍要求GT起点落在原窗口±2秒。',
        '- 52例均重新生成查询向量和FAISS召回，但没有重新编码库存向量。6种组合在每例中轮换执行顺序，模型预热后计时；额外20例不用于改模型或调参数。',
        '- 先按32例选择不降低素材Top5/Top10和时间Top10的方案，按素材Top1、时间Top1、较小K、window优先依次选择；随后额外20例检查不退化。交互延迟采用预先记录的总P95≤2秒判断，所有实测值仍完整披露。',
        f"- 模型加载{r['model_load_seconds']:.2f}秒；Torch峰值分配显存{r['peak_vram_allocated_bytes']/1024**3:.3f}GiB，保留池{r['peak_vram_reserved_bytes']/1024**3:.3f}GiB；不含其它进程占用。",
        f'- 输入实际截断query或原window的pair数：{len(truncated)}（上下文按固定上限裁剪另计）。','',
        '## 7个旧Top1错例的候选上限','',
        '| case | GT asset raw rank | 真正GT时间raw rank | 时间在Top10/20/50/100 | Top100可救状态 |','|---|---:|---:|---|---|']
    for e in r['availability']:
        flags='/'.join('是' if e['contains'][str(k)]['gt_time'] else '否' for k in [10,20,50,100])
        lines.append(f"| {e['case']['case_id']} | {e['asset_raw_rank']} | {e['gt_time_raw_rank']} | {flags} | {e['status']} |")
    lines+=['','真正GT时间口径：Top20/50/100都最多救回5/7。C_semantic20的asset虽在rank28，指定话术实际rank6827；C_semantic21的asset rank37，指定时间rank179。二者均为本轮RERANK_UNRESCUABLE，不把同asset错误时间包装为正确话术救回。', '',
        '## 固定32例与额外20例','',
        '| 集合 | 方案 | 素材Top1 | Top5 | Top10 | 时间Top1 | 时间Top10 |','|---|---|---:|---:|---:|---:|---:|']
    for group,values in r['groups'].items():
        for key,d in values.items():
            m=d['metrics'];n=m['n'];a=m['asset_hits'];t=m['nearby_hits']
            lines.append(f"| {group} | {key} | {rate(a['top1'],n)} | {rate(a['top5'],n)} | {rate(a['top10'],n)} | {rate(t['top1'],n)} | {rate(t['top10'],n)} |")
    lines+=['','## 救回与新增退化','',
        '| 集合/方案 | Top1救回case | Top1退化case | 正确时间Top1救回 | 正确时间Top1退化 |','|---|---|---|---|---|']
    for group,values in r['groups'].items():
        for key,d in values.items():
            if key=='baseline':continue
            changes=d['top1_changes'];tc=d['time_top1_changes']
            lines.append(f"| {group}/{key} | {', '.join(changes['rescued']) or '无'} | {', '.join(changes['degraded']) or '无'} | {', '.join(tc['rescued']) or '无'} | {', '.join(tc['degraded']) or '无'} |")
    lines+=['','| 方案 | 7旧错例中asset Top1救回 | 真正GT时间Top1救回 |','|---|---|---|']
    for key,x in rescue_counts.items():lines.append(f"| {key} | {len(x['asset_top1'])}：{', '.join(x['asset_top1'])} | {len(x['real_gt_time_top1'])}：{', '.join(x['real_gt_time_top1'])} |")
    lines+=['','## 旧7例逐例结果','',
        '| case | query | baseline素材/时间rank | 精排方案 | 精排素材/时间rank | Top1原文 | Top1 logit |','|---|---|---|---|---|---|']
    for e in r['availability']:
        cid=e['case']['case_id'];x=records[cid];b=x['variants']['baseline']
        for k,mode in VARIANTS:
            key=name(k,mode);d=x['variants'][key];first=d['top10'][0]
            lines.append(f"| {cid} | {esc(x['case']['query'])} | {rank_text(b['asset_rank'])}/{rank_text(b['nearby_rank'])} | {key} | {rank_text(d['asset_rank'])}/{rank_text(d['nearby_rank'])} | {esc(first['matched_text'])} | {first['rerank_score']:.4f} |")
    lines+=['','## 关键错例与上下文收益判断','',
        '- B_fuzzy16：GT完整句“但是我告诉她她回去做没效果”logit7.875，高于另一asset几乎同文候选7.6016，指定素材与时间均提升至Top1。',
        '- C_semantic23：正确asset升Top1，但首先返回9962.64秒的“按到三百次的时候”；指定GT9977.64秒的“按三百次的时候”仍排第二。不能宣称两例真正话术时点都救回。',
        '- NEW15：query“这里皮肤肌肉以及深处都会疼”，GT“这边的皮上疼,还有肌肉疼,还有里面疼”从1降至4（Top20），reranker logit3.1699；局部短句“越是這邊疼 這個肌肉”以4.8359领先。Top100时GT掉出Top10，扩池增加了其它局部短句干扰。',
        '- NEW16：简体GT“你以为我是的是推拉还是按摩”5.7617，被另一asset繁体近乎同句5.8477超过，rank1→2。两者时间也相近，可能存在同源内容/标注歧义，但未做音视频确认，不修改asset或GT，仍按固定评测计退化。',
        '- NEW13：GT时间raw rank76，Top20/50不在池；Top100已在池但GT logit2.0586，仍未进Top10。对比“腰有点酸”4.5234，说明扩大到100并没有自动解决这条模糊改写。',
        '- small context未带来整体收益：32例素材Top1为22/32，低于baseline25/32与window-only27/32；额外20例16/20，低于baseline19/20。正确时间Top1下降更明显。',
        '- 上下文可能让模型给邻句窗口高分：NEW09的query包含“就在这个中间…”，context方案首条窗口只有“腰疼了 包括流伤了”，匹配开头在前一句。返回窗口从463.8秒开始，GT460.38秒超过±2秒容差；不能通过把上下文时间算作输出时间来提高分数。本轮保持原时间判定。','',
        '## 否定表达诊断','',
        '词面筛选包括不、不是、没有、并非、不一定、不能、不要及没/未/无；含词不等于肯否反转（如有没有、不同）。不加手写规则、不修改原句。C_semantic20的真正否定GT未入池，reranker不能解决该条召回问题；其它视频的否定句也不能重新标作指定GT。','',
        '| query | 候选句 | reranker logit |','|---|---|---:|']
    for probe in r['negation_probe']:
        for c in probe['candidates']:lines.append(f"| {probe['query']} | {c['text']} | {c['score']:.4f} |")
    lines+=['','以上是用户例句的固定2×2诊断，不计入52例准确率；即使通过也不能证明复杂否定已解决。',
        '实测有局部改善：C_semantic20的Top20原来首位“一個部位疼”在reranker中仅1.9346；否定候选“这个位置 还真没有疼的地方”为7.6328并升Top1，差5.6982。该候选来自其它asset，真正GT仍在rank6827而不在精排池，素材/时间命中仍失败。2×2例句也都更偏向同含义句，但不足以断言所有否定问题解决；没有添加任何否定规则。','',
        '| 集合/case | query | 方案 | Top1原文 | GT素材/时间rank |','|---|---|---|---|---|']
    for x in r['records']:
        if not re.search(NEG,x['case']['query']) and not any(re.search(NEG,d['top10'][0]['matched_text']) for d in x['variants'].values()):continue
        for key in ['baseline',selected or 'window_20']:
            d=x['variants'][key]
            lines.append(f"| {x['group']}/{x['case']['case_id']} | {esc(x['case']['query'])} | {key} | {esc(d['top10'][0]['matched_text'])} | {rank_text(d['asset_rank'])}/{rank_text(d['nearby_rank'])} |")
    lines+=['','## 性能（52次暖查询，各组合52次）','',
        f"Semantic FAISS median/P95：{r['performance']['semantic_faiss']['median_ms']:.1f}/{r['performance']['semantic_faiss']['p95_ms']:.1f}ms；基线总计算：{r['performance']['semantic_total']['median_ms']:.1f}/{r['performance']['semantic_total']['p95_ms']:.1f}ms。",'',
        '| 方案 | 精排额外median ms | P95 ms | 总查询median ms | P95 ms |','|---|---:|---:|---:|---:|']
    for key,d in r['performance']['variants'].items():
        lines.append(f"| {key} | {d['extra']['median_ms']:.1f} | {d['extra']['p95_ms']:.1f} | {d['total']['median_ms']:.1f} | {d['total']['p95_ms']:.1f} |")
    lines+=['','额外耗时包含分词、短上下文准备对应的SQL读取、CPU/GPU传输、CUDA推理、取回分数与现有输出折叠；GPU前后同步。总耗时为本次编码+FAISS+metadata基线和对应额外计算之和，不含磁盘写实验日志、模型/索引冷加载或Web预览。没有借Top100缓存分数伪装Top20/50耗时。','',
        '## 生产判断','',f"32例上预先选出的方案：**{selected or '无方案通过32例收益/保留门槛'}**。额外20例不退化：{extra_ok}；总P95≤2秒：{latency_ok}。",'',yes,'',
        '样本是冻结开发验证集，仍不是独立听审的真实二创业务准确率；不能仅依赖小样本承诺可靠找回原视频。没有继续寻找第二个模型或调整上下文/权重。','',
        '## 保护与产物','',
        f"受保护文件集合、大小、mtime未变：{r['protected_files_unchanged']}；GT SHA未变：{r['gt_hashes_unchanged']}。FAISS/metadata额外SHA证据见index_hash_verification.json。",
        '3项分词/上下文边界测试通过；52例基线window_id与分数逐条复现历史结果。6种组合共17,680个候选句对，逐项核对全部来自相应TopK；实际最长输入236tokens，无query/原window截断。',
        '正式speech、DINO、CLIP、原字幕数据库、现有查询与Web均未修改。只新增本实验目录。results.json保留候选与所有logit、逐例指标、性能及2×2否定诊断；results.csv为全52例对比；errors.csv列出错误/退化；candidate_availability.json为候选上限。','']
    (OUT/'report.md').write_text('\n'.join(lines),encoding='utf8')
    print(json.dumps(decision,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
