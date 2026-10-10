"""汇总正式完整性、冻结测试与性能；不更改检索结果或参数。"""
import datetime
import statistics
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from speech_search.common import HERE,read_json,write_json
from speech_search.build_formal import OUTPUT,protected
from speech_search.evaluate import percentile


def main():
    manifest=read_json(OUTPUT/'manifest.json');validation=read_json(OUTPUT/'report.json')
    tests=read_json(OUTPUT/'query_tests.json');assembly=read_json(OUTPUT/'assembly.json');sessions=read_json(OUTPUT/'sessions.json')
    ram=read_json(OUTPUT/'ram_monitor.json');c=validation['checks']
    wall=(OUTPUT/'text.faiss').stat().st_mtime-datetime.datetime.fromisoformat(manifest['created_at']).timestamp()
    active=sum(s['session_seconds'] for s in sessions)+assembly['assembly_seconds']
    ram_peak=max(ram['peak_ram_bytes'],assembly['peak_ram_bytes'],*(s['peak_ram_bytes'] for s in sessions))
    vram=max(s['peak_vram_allocated_bytes'] for s in sessions);reserved=max(s['peak_vram_reserved_bytes'] for s in sessions)
    sem_records=[r for group in tests['evaluations'].values() for r in group['semantic']['records']]
    times=[r['response']['timings']['total_ms'] for r in sem_records]
    old=read_json(HERE/'validation/results.json')['evaluations']['paired_pilot']['semantic']
    new=tests['evaluations']['original32']['semantic'];old_by={x['case_id']:x for x in old['records']}
    lost_asset=[x['case_id'] for x in new['records'] if old_by[x['case_id']]['asset_rank'] and not x['asset_rank']]
    lost_time=[x['case_id'] for x in new['records'] if old_by[x['case_id']]['local_rank'] and not x['local_rank']]
    top1_delta=new['summary']['asset_hits']['top1']-old['summary']['asset_hits']['top1']
    # 不把完整性READY偷换为检索效果通过；未设新排名或更改测试GT。
    quality_note=('全库候选扩展后出现GT素材/时间Top10丢失或Top1明显下降；索引可查询，但不建议直接接入Web作为已验收能力。'
        if lost_asset or lost_time or top1_delta<=-4 else '未见明显退化，可进入下一任务的Web接入功能验收；不代表独立业务准确率达标。')
    summary=dict(index_status=validation['status'],assets=c['asset_count'],window_counts=c['window_counts'],vectors=c['faiss_ntotal'],
        faiss_bytes=assembly['faiss_bytes'],metadata_bytes=assembly['metadata_bytes'],wall_build_seconds=wall,active_build_seconds=active,
        encoding_call_seconds=assembly['encode_seconds'],gpu_event_seconds=assembly['gpu_event_seconds'],
        peak_process_ram_bytes=ram_peak,peak_torch_vram_bytes=vram,peak_torch_reserved_bytes=reserved,
        failures=c['failed'],timestamp_warning_windows=c['timestamp_warning_windows'],
        warm_semantic_median_ms=statistics.median(times),warm_semantic_p95_ms=percentile(times,.95),
        index_load_seconds=tests['index_load_seconds'],model_load_seconds=tests['model_load_seconds'],
        original32={m:d['summary'] for m,d in tests['evaluations']['original32'].items()},
        additional20={m:d['summary'] for m,d in tests['evaluations']['additional20'].items()},
        lost_top10_assets_vs_pilot=lost_asset,lost_top10_times_vs_pilot=lost_time,quality_note=quality_note,
        protected_files_unchanged=protected()==manifest['protected'],web_modified=False,whisper_started=False)
    write_json(OUTPUT/'final_summary.json',summary)
    lines=['# 话术搜索全库语义formal_v1验收','',f"完整性状态：**{validation['status']}**。{quality_note}",'',
        '## 实际产物','',f"- {c['asset_count']}个有字幕asset，{c['faiss_ntotal']:,}个向量；embedding=metadata=FAISS ntotal，window_id唯一。",
        f"- 1/2/3段窗口：{c['window_counts']}。缺字幕的约0.048秒asset没有伪造向量。",
        f"- FAISS：{assembly['faiss_bytes']:,} bytes（{assembly['faiss_bytes']/1024**3:.3f}GiB）；metadata：{assembly['metadata_bytes']:,} bytes（{assembly['metadata_bytes']/1024**2:.1f}MiB）。",
        '- 使用IndexFlatIP，不压缩、不与DINO/CLIP混合。vectors.f32保存512维FP32原向量；metadata独立保存全部窗口字段及主路径，原字幕ID可经既有segment_sources/window_sources追溯所有来源。',
        '- BGE-small-zh-v1.5 revision 7999e1d3359715c523056ef9478215996d62a620，直接复用pilot Encoder：同tokenizer、CLS、L2、256 token上限、查询指令和FP32。16个已编码pilot样本数值与正式结果完全一致。',
        f"- 失败{c['failed']}；原44个asset/1,060条字幕异常原值保留，扩展为{c['timestamp_warning_windows']:,}个warning窗口，没有修时间或重新转写。",'',
        '## 断点与严格验收','',
        '- 前2批共128向量停止并重启；原批次提交记录和向量SHA前后相同，续跑复用。先fsync向量，再SQLite FULL提交；未提交batch可重算，已提交batch跳过。',
        '- 单条文本ValueError/编码格式异常递归隔离写failures，系统性CUDA故障停止保留checkpoint；合成故障测试通过。',
        '- 318个asset集合、路径、start非负/start<=end、window_size、ID唯一、字段完整全部检查。全部metadata与原窗口逐行对比，全部FAISS向量与磁盘向量逐行比对、有限数/L2检查；32条自查询检查。',
        f"- 校验耗时{validation['validation_seconds']:.1f}s；报告errors={validation['errors']}。受保护文件集合/大小/mtime一致：{summary['protected_files_unchanged']}（轻量状态校验，不是生产全库逐字节hash）。",
        f"- 组装报告恢复标记：{assembly.get('report_recovered',False)}。构建期间发现组装计时字段SQL取值问题，已在向量/FAISS原子发布后仅补写报告，没有重新编码任何已完成向量。",
        '- 13项测试通过，包括坏文本隔离、系统故障保留断点、正式与pilot复用同一个Encoder，以及既有话术功能测试。', '',
        '## 固定32例全库复测','',
        '沿用原32例与GT，不调参数。原32例为从旧转写构造的开发验证，并非独立听审的真实二创holdout。原pilot候选只有8个asset；本次318个。未运行或调整融合。', '',
        '| 层 | 素材Top1 | Top5 | Top10 | 正确时间附近Top10 | median ms | P95 ms |','|---|---:|---:|---:|---:|---:|---:|']
    for m,d in tests['evaluations']['original32'].items():
        s=d['summary'];h=s['asset_hits'];lines.append(f"| {m} | {h['top1']}/32 ({h['top1']/32:.1%}) | {h['top5']}/32 ({h['top5']/32:.1%}) | {h['top10']}/32 ({h['top10']/32:.1%}) | {s['local_hits']['top10']}/32 ({s['local_hits']['top10']/32:.1%}) | {s['median_ms']:.1f} | {s['p95_ms']:.1f} |")
    lines += ['',f"相对pilot Semantic：Top1变化{top1_delta}例，素材Top10丢失{lost_asset}；时间附近Top10丢失{lost_time}。",'',
        '时间附近定义保持GT起点落在结果窗口内±2秒；素材命中不代表口播时点正确。GT使用旧Whisper时间，不能代表真实听审时间误差。字幕里同句话可出现在多个视频/多个位置；本次严格沿用单一GT，不为了提高分数事后补标其它结果。','',
        '## 已保存结果的退化核对（未再调参）','',
        '- 原32例Semantic Top1从31/32降至25/32，Top10从32/32降至30/32。原句、删字/错字、跨段各8例的素材Top10仍为8/8；同义改写为6/8。',
        '- C_semantic20：query“这个部位完全没有疼痛感”，GT“但是一点都不疼这个地方”掉出Top10，Top1却是“一個部位疼”（0.7289）。这暴露了否定含义区分问题，不能把语义相关视为同一句话。',
        '- C_semantic21：query“我的工作就是做这个”，GT“我就是干这个活的”掉出Top10；其它asset的“我做的工作 就是这个”（0.7742）等同义句领先。单一GT的素材命中失败仍照实计分，没有事后把其它视频改标为正确。',
        '- C_semantic19的“身体各个部位都是互相连通的”由rank1到6；其它素材“人身体所有的东西都相通”排前。B_fuzzy16也遇到另一asset几乎同文且相近时点的候选；仅凭字幕不能确定两个asset是否为不同编码的同一直播，不修改资产映射。',
        '- 新20例中NEW13“你的腰有没有酸痛的感觉”的指定GT未进Top10，前排为其它asset的腰酸/腰疼短句。其余19例都在Top1；这不能抵消固定32例的退化。',
        '- 观察指向全库相似话术竞争，以及通用短句、否定句区分不足；不是向量丢失或metadata错位。本轮没有修改query、GT、模型、候选数、折叠或融合参数。', '',
        '## 额外20个asset的真实字幕','',
        '原句、删字、错字、同义改写、跨段各4例，20个asset均不在原8个pilot asset内。评测前冻结，不选结果后修改query或模型。', '',
        '| 层 | 素材Top1/5/10 | 附近Top10 |','|---|---|---:|']
    for m,d in tests['evaluations']['additional20'].items():
        s=d['summary'];h=s['asset_hits'];lines.append(f"| {m} | {h['top1']}/20 · {h['top5']}/20 · {h['top10']}/20 | {s['local_hits']['top10']}/20 |")
    lines+=['','## 逐例semantic排名','', '| 集合/案例 | query | 素材rank | 时间附近rank |','|---|---|---:|---:|']
    for name,group in tests['evaluations'].items():
        for r in group['semantic']['records']:lines.append(f"| {name}/{r['case_id']} | {r['response']['query']} | {r['asset_rank'] or 'Top10外'} | {r['local_rank'] or 'Top10外'} |")
    lines+=['','## 性能与范围','',
        f"- 建库自然耗时{wall/60:.2f}分钟（含真实停止/重启间隔）；活跃构建累计{active/60:.2f}分钟，验收/查询评估另计。",
        f"- CUDA Encoder调用累计{assembly['encode_seconds']:.2f}s；CUDA事件包围encode累计{assembly['gpu_event_seconds']:.2f}s。前者包含分词/CPU-GPU拷贝，事件包围段也包含排队/空闲，不冒称纯kernel计时。",
        f"- 峰值构建进程RAM {ram_peak/1024**3:.3f}GiB；Torch分配VRAM {vram/1024**2:.1f}MiB，保留池{reserved/1024**2:.1f}MiB，不是整机或Web占用。RAM由外部进程PeakWorkingSet监控补齐早期计数器兼容性问题。",
        f"- CPU暖语义查询52例 median {statistics.median(times):.1f}ms / P95 {percentile(times,.95):.1f}ms；模型首次加载{tests['model_load_seconds']:.2f}s；索引加载{tests['index_load_seconds']:.2f}s。不含Web或预览。",'',
        '## 使用与接入判断','',quality_note,'',
        'CLI：`.\\.venv-cuda-test\\Scripts\\python.exe -X utf8 -B speech_search/formal_query.py "话术" --mode semantic`。Exact/Fuzzy独立可用，原pilot query.py保持原样；正式入口不提供hybrid。',
        '未修改Web、DINO/CLIP、图片候选去重、ORB、原字幕；原验证数据与模型流程不变。完整规则及断点用法见speech_search/FORMAL_README.md。完成本阶段后停止，没有进行Web接入。']
    (OUTPUT/'final_report.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(summary)


if __name__=='__main__':main()
