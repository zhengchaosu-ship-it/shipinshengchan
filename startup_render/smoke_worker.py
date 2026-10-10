"""本机隔离API/SMB smoke；绝不进入Agent.tick/剪映。"""
import argparse
from pathlib import Path
import json
from .common import digest,read,save
from .lan_transport import Transport


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--manifest',required=True)
    args=parser.parse_args()
    config=read(args.config); transport=Transport(config)
    health=transport.call('/health')
    registration=transport.call('/worker/register',transport.worker_details())
    heartbeat=transport.call('/worker/heartbeat',dict(transport.worker_details(),status='IDLE'))
    claimed=transport.call('/render-jobs/claim',{'worker_id':config['worker_id']})
    assert claimed and claimed['manifest']['job_id']=='LAN_SMOKE_V1'
    assert transport.call('/render-jobs/claim',{'worker_id':config['worker_id']})==claimed
    transport.current=claimed
    transport.stage_status('STAGING_FILES')
    manifest=read(args.manifest)
    local=Path(config['local_jobs_root'])/'LAN_SMOKE_V1'/'source'/'tiny.txt'
    one=transport.copy_verified(manifest['source_unc_path'],local,manifest['sha256'],manifest['size'])
    returned=Path(manifest['output_unc_path'])
    two=transport.copy_verified(local,returned,manifest['sha256'],manifest['size'])
    assert digest(local)==digest(returned)==manifest['sha256']
    # synthetic smoke没有业务content，明确终止，不能伪造生产COMPLETED/READY。
    receipt={'claim':claimed['claim'],'status':'NEEDS_MANUAL','error':'ISOLATED_SMOKE_FINISHED_NO_RENDER',
             'real_publish_attempts':0}
    value={'worker_id':config['worker_id'],'claim':claimed['claim'],'receipt':receipt}
    transport.call('/render-jobs/LAN_SMOKE_V1/failed',value)
    transport.call('/render-jobs/LAN_SMOKE_V1/failed',value)
    transport.call('/worker/heartbeat',dict(transport.worker_details(),status='IDLE',current_job_id=None))
    result={'status':'LAN_API_AND_SMB_SMOKE_PASS','registered':registration,'heartbeat':heartbeat,
            'claim_idempotent':True,'failure_receipt_idempotent':True,'source_unc_path':manifest['source_unc_path'],
            'worker_path':str(local),'output_unc_path':str(returned),'sha256':digest(returned),
            'copy_results':[one,two],'jianying_started':False,'publish_jobs_created':0}
    save(Path(config['state_root'])/'SMOKE_RESULT.json',result)
    # 同时由本机自动写回专用输出共享，服务器不依赖远程管理读取验收。
    save(Path(config['render_output_unc'])/'LAN_SMOKE_V1'/'SMOKE_RESULT.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
