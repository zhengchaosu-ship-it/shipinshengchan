"""只收集本次隔离验收的非凭据证据；不复制配置/私钥/认证令牌。"""
import json,socket,shutil,time
from pathlib import Path
from collections import Counter
from startup_render.common import read,save


def main():
    assert socket.gethostname()=='DESKTOP-9VQ76D3'
    root=Path('D:/JianyingRenderWorker/Resident/media_execution/real_acceptance_v2')
    target=Path(r'\\PC-20260617GEOP\RenderOutput\2060_acceptance_20261007_v2\worker-evidence');target.mkdir(exist_ok=True)
    result=read(root/'result.json');assert result['result']=='PASS'
    posts=[json.loads(line) for line in (root/'mock_posts.jsonl').read_text('utf-8').splitlines()]
    counts=Counter(p['job_id'] for p in posts);assert len(counts)==5 and set(counts.values())=={1}
    exports=[]
    for folder in (root/'Jobs').iterdir():
        if not folder.is_dir():continue
        latch=read(folder/'export_submit_once.json')
        state=read(folder/'state.json');receipt=state['receipt']
        assert latch['export_submit_attempts']==1 and receipt['status']=='COMPLETED'
        exports.append({'job_id':folder.name,'draft_name':latch['draft_name'],'export_attempts':1,
            'worker_output_path':receipt['worker_output_path'],'media':receipt['media']})
        save(target/(folder.name+'-events.json'),read(folder/'events.json'))
    assert len(exports)==10 and all(e['media']['full_decode_verified'] for e in exports)
    for name in ('result.json','progress.json','render_crash.json','publish_crash.json','mock_posts.jsonl','archive_result.json','pre_export_retry.json'):
        if (root/name).is_file():shutil.copy2(root/name,target/name)
    save(target/'verified_summary.json',{'collected_at':time.time(),'result':'PASS','real_render_count':10,'render_export_actions':10,
        'mock_post_count':len(posts),'mock_post_counts':dict(counts),'real_provider_calls':0,'exports':exports,
        'maximum_heavy':result['maximum_heavy'],'overlap_claims':result['overlap_claims']})
    print('TEN_REAL_EXPORTS_FIVE_SINGLE_POSTS_EVIDENCE_SAVED')


if __name__=='__main__':main()
