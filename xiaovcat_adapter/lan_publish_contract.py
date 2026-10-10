"""唯一Job3迁移范围；只包含公开任务身份，不含凭证或业务库副本。"""
from pathlib import Path

PLAN_ID='52e11ba8-fe9b-47f4-ae1f-74ed593712a9'
JOB_ID='af6c16d3-2912-4390-88c7-4584b3e4feea'
CONTENT_ID='STARTUP-a16c1f3b-2dbc-41ca-9c9d-8eb157a3e73e'
ACCOUNT_ID='1621131832863931'
GROUP_ID='339642'
ACCOUNT_IDS={'1621131832863931','3031801633454512'}
WORKER_ID='XIAOVCAT-WORKER-2060S-01'
HOSTNAME='DESKTOP-9VQ76D3'
WINDOWS_SID='S-1-5-21-1134442622-1985318965-2583428394-1001'
SCHEDULED_AT='2026-10-05T15:00:00+08:00'
VIDEO_NAME='丙曜起号10月4日-6.mp4'
VIDEO_SHA256='8e6d565018aca1d2770ad8c38e4efdd27db2aac4e4a84b36cd5a6fa0fbefc256'
USER_CONFIRMATION='USER_EXECUTED_JOB3_FIRST_REAL_ACCEPTANCE_ON_2060S'
DESKTOP_UI_LANE='Local\\XiaovcatDesktopWorkerV03'


def check_policy(policy):
    expected=dict(plan_id=PLAN_ID,job_id=JOB_ID,content_id=CONTENT_ID,account_id=ACCOUNT_ID,
                  account_name='丙曜',platform='抖音',title='',description='陶老师小妙招',
                  topics=['#健康','#健康科普','#养生'],scheduled_at=SCHEDULED_AT,business_type='STARTUP')
    for key,value in expected.items():
        if policy.get(key)!=value:raise PermissionError('LOCKED_JOB3_CONTEXT_MISMATCH:'+key)
    if Path(policy['video_path']).name!=VIDEO_NAME:raise PermissionError('LOCKED_VIDEO_MISMATCH')
    if policy.get('video_sha256',VIDEO_SHA256)!=VIDEO_SHA256:raise PermissionError('LOCKED_SHA256_MISMATCH')
    return policy
