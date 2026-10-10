"""原32例与20个新asset的字幕小样本复测；不评估/调整融合。"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from speech_search.common import HERE,read_json,write_json,sha256,RULES
from speech_search.build_formal import OUTPUT
from speech_search.formal_query import FormalSearch
from speech_search.evaluate import measure,summarize


def main():
    original=read_json(HERE/'validation/cases.json')
    if original['rules_frozen_before_evaluation']!=RULES:raise RuntimeError('冻结规则变化')
    groups={'original32':original['cases'],'additional20':read_json(OUTPUT/'additional_cases.json')['cases']}
    t=time.perf_counter();engine=FormalSearch();startup=time.perf_counter()-t
    warm=engine.search('患者的腰部问题');report=dict(index_load_seconds=startup,model_load_seconds=engine.model_load_seconds,
        first_query_ms=warm['timings']['total_ms'],original_cases_sha256=sha256(HERE/'validation/cases.json'),
        additional_cases_sha256=sha256(OUTPUT/'additional_cases.json'),rules=RULES,device='cpu',evaluations={})
    for name,cases in groups.items():
        report['evaluations'][name]={}
        for mode in ['exact','fuzzy','semantic']:
            records=[]
            for case in cases:
                response=engine.search(case['query'],mode=mode);records.append(measure(case,response))
                print(name,mode,case['case_id'],records[-1]['asset_rank'],records[-1]['local_rank'],round(response['timings']['total_ms'],1),flush=True)
            report['evaluations'][name][mode]=dict(summary=summarize(records),records=records)
            write_json(OUTPUT/'query_tests.json',report)
    old=read_json(HERE/'validation/results.json')['evaluations']['paired_pilot']['semantic']['summary']
    new=report['evaluations']['original32']['semantic']['summary']
    report['semantic_change_vs_pilot']=dict(asset_hit_delta={k:new['asset_hits'][k]-old['asset_hits'][k] for k in old['asset_hits']},
        nearby_top10_delta=new['local_hits']['top10']-old['local_hits']['top10'],
        note='同一32例，候选由8个asset增加至318个；不改模型、不调候选数、不调重叠折叠规则。')
    write_json(OUTPUT/'query_tests.json',report)
    print(json.dumps({g:{m:d['summary'] for m,d in modes.items()} for g,modes in report['evaluations'].items()},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
