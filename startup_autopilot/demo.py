"""显式运行一次的合成Shadow样本，无后台循环。"""
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta
import json
from pathlib import Path

from .models import Actor, Profile, SHANGHAI, Slot, Template, digest, policy, transition
from .planner import StartupDailyPlanner


def fixture(now=None):
    now=now or datetime.now(SHANGHAI)
    actor=Actor('DEMO_EMPLOYEE',frozenset({'DEMO_ACCOUNT'}),'ADMIN')
    template=Template('DEMO_ACCOUNT','demo-template-v1',tuple(
        Slot(name,tuple(f'DEMO-{i}-{j:02d}' for j in range(12)),2,6) for i,name in enumerate(('引流','手法','坐诊','收尾'),1)))
    profile=Profile('DEMO_ACCOUNT',5000,template.version,template_hash=digest(asdict(template)),policy_hash=digest(policy()))
    profile=transition(profile,actor,'start',now,config_confirmed=True,config_hash=profile.config_hash())
    return actor,profile,template,now


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    actor,profile,template,now=fixture()
    planner=StartupDailyPlanner()
    day=(now+timedelta(days=1)).date()
    decision=planner.shadow(actor,profile,template,day,now)
    assert len(decision['proposals'])==5 and decision['submit_count']==0
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'synthetic_fixture':True,'profile':asdict(profile),'template':asdict(template),
                                     'decision':decision,'production_dispatch_enabled':False},ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'status':decision['status'],'proposals':len(decision['proposals']),
                      'duplicate':5-len({p['composition_signature'] for p in decision['proposals']}),
                      'render_created':0,'publish_created':0,'submit_count':0,'output':str(args.output.resolve())},ensure_ascii=False))


if __name__=='__main__':
    main()
