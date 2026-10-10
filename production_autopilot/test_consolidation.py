"""临时库验收生产收敛；Provider/Render均为fixture，禁止真实外部写入。"""
from contextlib import closing
from dataclasses import replace, asdict
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from startup_autopilot.tests import test_production as fixtures
from startup_autopilot.production import ServiceGrant, utcnow
from startup_autopilot.models import SHANGHAI, aware
from startup_autopilot.composition import from_dict
from production_autopilot.reliability import ReliabilityStore
from production_autopilot.learning import valid_sample_count
from production_autopilot.operations import Operations, verify_backup
from production_autopilot.restore import restore
from yixiaoer_adapter.account_registry import BusinessAccountRegistry


class ConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.ProductionTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.production=self.base.production;self.store=self.base.store;self.shadows=self.base.shadows
        self.account=self.base.account;self.token=self.base.token

    def provider_rows(self):return [{'id':'PROVIDER-FIXTURE-NEW','status':1,'platformName':'抖音','platformAccountName':'fixture','fansTotal':12}]

    def test_auth_recovery_cycle_is_read_only_and_keeps_original_grant(self):
        grant=self.base.start();worker,cli,_=self.base.make_worker()
        self.production.attention(self.account,'YIXIAOER_ACCOUNT_NOT_VALID_OR_STALE')
        reliability=worker.reliability;registry=BusinessAccountRegistry(self.store.path);registry.migrate()
        first=reliability.request(self.token,self.account);self.assertEqual(reliability.request(self.token,self.account),first)
        with patch.object(worker.adapter,'list_accounts',return_value=self.provider_rows()),patch.object(worker.adapter,'create_publish_job',side_effect=AssertionError('publish forbidden')):
            result=worker.cycle()
        self.assertEqual(result['state'],'READ_ONLY_RECOVERY_ONLY');self.assertEqual(result['publish_calls'],0)
        self.assertTrue(self.production.authorization(self.account)['enabled'])
        with self.store.connect() as db:self.production.verify(db,grant)
        self.assertEqual(cli.submits(),[])
        self.assertEqual(reliability.rows({self.account}),[])

    def test_provider_failure_preserves_snapshot_and_does_not_resume(self):
        self.base.start();worker,_,_=self.base.make_worker()
        registry=BusinessAccountRegistry(self.store.path);registry.migrate();registry.apply(self.provider_rows())
        before=registry.snapshot();self.production.attention(self.account,'YIXIAOER_ACCOUNT_NOT_VALID_OR_STALE')
        worker.reliability.request(self.token,self.account)
        with patch.object(worker.adapter,'list_accounts',side_effect=RuntimeError('QUERY_UNAVAILABLE')):result=worker.cycle()
        self.assertEqual(registry.snapshot(),before);self.assertFalse(self.production.authorization(self.account)['enabled'])
        self.assertEqual(result['publish_calls'],0)

    def test_pause_or_finish_during_auth_request_never_reenabled(self):
        self.base.start();worker,_,_=self.base.make_worker()
        registry=BusinessAccountRegistry(self.store.path);registry.migrate()
        self.production.attention(self.account,'YIXIAOER_ACCOUNT_NOT_VALID_OR_STALE')
        worker.reliability.request(self.token,self.account);self.production.control(self.token,self.account,'finish')
        with patch.object(worker.adapter,'list_accounts',return_value=self.provider_rows()):worker.cycle()
        self.assertEqual(self.production.authorization(self.account)['status'],'FINISHED')

    def test_auth_failed_job_acknowledged_without_retry_and_not_reblocking(self):
        worker,cli,row=self.base.ready_job()
        claim=worker.provider_store.claim('ISOLATED_AUTOPILOT',[row['plan_id']]);worker.adapter.create_publish_job(*claim)
        original=worker.adapter.get_publish_status(row['job_id']);original['tasks'][0].update(stageStatus='failed',stages='publish',errorMessage='请在创作者中心完成短信验证')
        with patch.object(worker.adapter,'get_publish_status',return_value=original):worker.reconcile(row)
        self.assertFalse(self.production.authorization(self.account)['enabled'])
        registry=BusinessAccountRegistry(self.store.path);registry.migrate();worker.reliability.request(self.token,self.account)
        with patch.object(worker.adapter,'list_accounts',return_value=self.provider_rows()),patch.object(worker.adapter,'get_publish_status',return_value=original):result=worker.cycle()
        self.assertEqual(result['publish_calls'],0);self.assertTrue(self.production.authorization(self.account)['enabled'])
        worker.reconcile(row)
        self.assertTrue(self.production.authorization(self.account)['enabled'])
        self.assertEqual(worker.provider_store.row(row['job_id'])['state'],'FAILED')
        self.assertEqual(len(cli.submits()),1)

    def test_reconcile_rejects_other_provider_account_even_matching_title_and_time(self):
        worker,cli,row=self.base.ready_job()
        claim=worker.provider_store.claim('ISOLATED_AUTOPILOT',[row['plan_id']]);worker.adapter.create_publish_job(*claim)
        data=worker.adapter.get_publish_status(row['job_id']);data['tasks'][0]['platformAccountId']='ANOTHER_ACCOUNT'
        with patch.object(worker.adapter,'get_publish_status',return_value=data):
            with self.assertRaisesRegex(Exception,'ACCOUNT_IDENTITY_MISMATCH'):worker.adapter.reconcile_publish_result(row['job_id'])
        self.assertEqual(len(cli.submits()),1)

    def test_null_account_field_requires_original_payload_hash_not_nickname(self):
        worker,cli,row=self.base.ready_job()
        claim=worker.provider_store.claim('ISOLATED_AUTOPILOT',[row['plan_id']]);worker.adapter.create_publish_job(*claim)
        data=worker.adapter.get_publish_status(row['job_id']);data['tasks'][0]['platformAccountId']=None
        with patch.object(worker.adapter,'get_publish_status',return_value=data):worker.adapter.reconcile_publish_result(row['job_id'])
        self.assertEqual(len(cli.submits()),1)
        payload=worker.adapter.runtime/'jobs'/row['job_id']/'payload.json';payload.write_text('{}')
        with patch.object(worker.adapter,'get_publish_status',return_value=data):
            with self.assertRaisesRegex(Exception,'ACCOUNT_EVIDENCE_UNAVAILABLE'):worker.adapter.reconcile_publish_result(row['job_id'])

    def test_submitted_work_is_confirmed_by_real_public_list_before_learning(self):
        from startup_autopilot.production_metrics import collect_account
        worker,cli,row=self.base.ready_job();cli.mode='success_push'
        claim=worker.provider_store.claim('ISOLATED_AUTOPILOT',[row['plan_id']]);worker.adapter.create_publish_job(*claim);worker.reconcile(row)
        job=worker.provider_store.row(row['job_id']);self.assertEqual(job['state'],'SUBMITTED')
        published=aware(row['scheduled_at']);now=published+timedelta(hours=2,minutes=1)
        source={'platformAccountId':job['provider_account_id'],'updatedAt':int(now.timestamp()*1000),'contentData':{'id':job['provider_video_id'],'date':published.astimezone(SHANGHAI).strftime('%Y-%m-%d %H:%M:%S'),'play':100}}
        with patch.object(worker.adapter,'call',return_value={'data':{'data':[source]}}):collect_account(self.production,worker.adapter,self.account,now)
        self.assertEqual(worker.provider_store.row(row['job_id'])['state'],'PUBLISHED')
        self.assertEqual(len(cli.submits()),1)

    def test_metrics_queue_does_not_block_and_forbids_nonmetrics_calls(self):
        from threading import Event
        from production_autopilot.metrics_queue import MetricsQueue, ReadOnlyMetricsAdapter
        worker,cli,_=self.base.make_worker();started=Event();finish=Event()
        def collect(*args):started.set();finish.wait(5)
        queue=MetricsQueue(self.production,worker.adapter,worker.reliability)
        try:
            with patch('production_autopilot.metrics_queue.collect_account',collect):
                queue.submit(self.account);self.assertTrue(started.wait(2));queue.submit(self.account)
                self.assertEqual(len(queue.pending),1)
            restricted=ReadOnlyMetricsAdapter(worker.adapter)
            for command in (['publish'],['upload'],['query','records']):
                with self.assertRaisesRegex(PermissionError,'QUERY_ONLY'):restricted.call(command)
            self.assertEqual(cli.submits(),[])
        finally:finish.set();queue.executor.shutdown(wait=True)

    def test_metrics_unknown_snapshot_can_recover_and_unlinked_public_is_not_sample(self):
        from startup_autopilot.production_metrics import collect_account
        worker,_,row=self.base.ready_job();now=utcnow();published=now-timedelta(hours=24,minutes=10)
        work='fixture-work'
        with self.store.connect(write=True) as db:
            db.execute("UPDATE autopilot_allocations SET scheduled_at=? WHERE allocation_id=?",(published.isoformat(),row['allocation_id']))
            db.execute("UPDATE provider_publish_jobs SET state='PUBLISHED',provider_video_id=?,submit_attempt_count=1 WHERE job_id=?",(work,row['job_id']))
            # 正式Job的冻结排期是公开对账依据；fixture的allocation和Job必须一致。
            db.execute("UPDATE publish_jobs SET status='PUBLISHED',scheduled_at=? WHERE job_id=?",(published.isoformat(),row['job_id']))
        source={'platformAccountId':'PROVIDER-FIXTURE-NEW','contentData':{'id':work,'date':published.astimezone(SHANGHAI).strftime('%Y-%m-%d %H:%M:%S')}}
        with patch.object(worker.adapter,'call',return_value={'data':{'data':[source]}}):collect_account(self.production,worker.adapter,self.account,now)
        with self.shadows.connect() as db:
            for i in range(20):
                db.execute('INSERT INTO composition_public_samples VALUES(?,?,?,?)',(self.account,'unlinked-'+str(i),published.isoformat(),json.dumps({'public_visibility_confirmed':True,'work_id':'unlinked-'+str(i)})))
        self.assertEqual(valid_sample_count(self.store,self.shadows,self.account),0)
        source['updatedAt']=int((now+timedelta(minutes=6)).timestamp()*1000);source['contentData']['play']=500
        with patch.object(worker.adapter,'call',return_value={'data':{'data':[source]}}):collect_account(self.production,worker.adapter,self.account,now+timedelta(minutes=6))
        self.assertEqual(valid_sample_count(self.store,self.shadows,self.account),1)
        self.assertEqual(self.production.builder.context(self.base.f.actor,self.account)[0],1)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM autopilot_metrics').fetchone()[0],2)
            values=json.loads(db.execute('SELECT snapshot_json FROM autopilot_metrics LIMIT 1').fetchone()[0])['values']
            self.assertIsNone(values['completion_rate']);self.assertIsNone(values['followers_delta'])

    def test_allocation_migration_preserves_every_existing_field_and_ids(self):
        grant=self.base.start();now=utcnow().astimezone(SHANGHAI).replace(hour=22)
        self.production.reserve_daily(grant,now)
        with self.store.connect() as db:before=[tuple(r) for r in db.execute('SELECT * FROM autopilot_allocations ORDER BY allocation_id')]
        reliability=ReliabilityStore(self.production);reliability.migrate();reliability.migrate()
        with self.store.connect() as db:
            self.assertEqual(before,[tuple(r) for r in db.execute('SELECT * FROM autopilot_allocations ORDER BY allocation_id')])
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
            schema=db.execute("SELECT sql FROM sqlite_master WHERE name='autopilot_allocations'").fetchone()[0]
            self.assertNotIn('UNIQUE(account_id,composition_signature)',schema)

    def test_backup_restore_preserves_submit_latch_and_detects_corruption(self):
        worker,cli,row=self.base.ready_job()
        claim=worker.provider_store.claim('ISOLATED_AUTOPILOT',[row['plan_id']]);worker.adapter.create_publish_job(*claim)
        operations=Operations(self.production,worker.config,worker.registration.queue.path)
        backup=operations.backup(force=True)
        report=restore(backup['folder'],self.base.root/'restored')
        restored=next(j for j in report['provider_jobs'] if j['job_id']==row['job_id'])
        self.assertEqual(restored['submit_attempt_count'],1);self.assertTrue(restored['provider_task_set_id'])
        self.assertEqual(report['autopilot_states'][0]['config_hash'],self.production.authorization(self.account)['config_hash'])
        self.assertFalse(report['workers_started']);self.assertEqual(len(cli.submits()),1)
        self.assertEqual(report['dispatch_guard'],'HOLD_RECONCILIATION_REQUIRED')
        from production_autopilot.restore_guard import assert_dispatch_allowed
        with closing(sqlite3.connect(self.base.root/'restored/operations.db')) as db:
            db.row_factory=sqlite3.Row
            with self.assertRaisesRegex(PermissionError,'RESTORE_RECONCILIATION_REQUIRED'):assert_dispatch_allowed(db)
        Path(backup['folder']).joinpath('operations.db').write_bytes(b'CORRUPT_FIXTURE')
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):verify_backup(backup['folder'])

    def test_restore_review_requires_admin_and_keeps_old_jobs_held(self):
        from production_autopilot.restore_guard import confirm_review, assert_dispatch_allowed
        from publish_planner.storage import PlannerStore
        worker,_,row=self.base.ready_job();operations=Operations(self.production,worker.config,worker.registration.queue.path)
        saved=operations.backup(force=True);destination=self.base.root/'reviewed'
        restore(saved['folder'],destination);restored=PlannerStore(destination/'operations.db')
        with self.assertRaisesRegex(PermissionError,'PERMISSION_REQUIRED'):confirm_review(restored,self.token,destination/'render_jobs.db')
        admin_token=self.base.f.fixture.fixture.token
        confirm_review(restored,admin_token,destination/'render_jobs.db')
        with restored.connect() as db:
            assert_dispatch_allowed(db)
            job=db.execute('SELECT * FROM provider_publish_jobs WHERE job_id=?',(row['job_id'],)).fetchone()
            self.assertEqual(job['state'],'ATTENTION_REQUIRED');self.assertEqual(job['submit_attempt_count'],0)
        with closing(sqlite3.connect(destination/'render_jobs.db')) as db:self.assertEqual(db.execute('SELECT status FROM jobs').fetchone()[0],'NEEDS_MANUAL')

    def test_transient_provider_recovery_has_backoff_and_no_publish(self):
        self.base.start();worker,cli,_=self.base.make_worker();registry=BusinessAccountRegistry(self.store.path);registry.migrate()
        self.production.attention(self.account,'NETWORK_TIMEOUT')
        worker.reliability.queue_transient_recovery();worker.reliability.queue_transient_recovery()
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM production_recovery_requests').fetchone()[0],1)
        with patch.object(worker.adapter,'list_accounts',return_value=self.provider_rows()):result=worker.cycle()
        self.assertEqual(result['publish_calls'],0);self.assertTrue(self.production.authorization(self.account)['enabled']);self.assertEqual(cli.submits(),[])

    def test_explicit_resume_does_not_carry_failed_debt_into_next_day(self):
        worker,_,row=self.base.ready_job();old_at=(utcnow()-timedelta(minutes=10)).isoformat()
        with self.store.connect(write=True) as db:
            db.execute("UPDATE provider_publish_jobs SET state='FAILED',provider_task_set_id='fixture-task',provider_stage_status='failed',submit_attempt_count=1,updated_at=? WHERE job_id=?",(old_at,row['job_id']))
            db.execute("UPDATE autopilot_allocations SET state='FAILED' WHERE allocation_id=?",(row['allocation_id'],))
        self.production.attention(self.account,'发布需要处理：FAILED')
        before=worker.provider_store.row(row['job_id'])
        profile=self.production.start(self.token,self.account,daily_limit=1,publish_times=('21:00',),target_follower_count=1000)
        self.production.reserve_daily(ServiceGrant(self.account,profile.config_hash()),utcnow().astimezone(SHANGHAI).replace(hour=22)+timedelta(days=1))
        self.assertEqual(before,worker.provider_store.row(row['job_id']))
        with self.store.connect() as db:
            lineage=db.execute('SELECT * FROM production_job_lineage').fetchone()
            self.assertIsNone(lineage)

    def test_fifty_accounts_daily_budget_and_reservation_idempotency(self):
        # 复用真实Planner/Template/Profile/Registry数据库，不启动Provider或Render。
        source=self.account
        with self.store.connect() as db:business=dict(db.execute('SELECT * FROM xiaovcat_accounts WHERE account_id=?',(source,)).fetchone())
        with self.shadows.connect(readonly=True) as db:
            profile=dict(db.execute('SELECT * FROM shadow_profiles WHERE business_account_id=?',(source,)).fetchone())
            versions=[dict(r) for r in db.execute('SELECT * FROM composition_template_versions WHERE account_id=?',(source,))]
            state=dict(db.execute('SELECT * FROM composition_template_states WHERE account_id=?',(source,)).fetchone())
            pools=[dict(r) for r in db.execute('SELECT * FROM composition_material_pools WHERE account_id=?',(source,))]
            cache=[dict(r) for r in db.execute('SELECT * FROM composition_catalog_cache WHERE account_id=?',(source,))]
        def insert(db,table,value):db.execute('INSERT INTO '+table+'('+','.join(value)+') VALUES('+','.join('?' for _ in value)+')',tuple(value.values()))
        from yixiaoer_adapter.storage import ProviderStore
        provider=ProviderStore(self.store)
        for i in range(50):
            account='SCALE-'+str(i).zfill(2);pid='FIXTURE-PROVIDER-'+str(i)
            with self.store.connect(write=True) as db:insert(db,'xiaovcat_accounts',dict(business,account_id=account))
            provider.bind(account,{'id':pid,'status':1},source='SCALE_FIXTURE')
            with self.shadows.connect() as db:
                cloned=dict(profile,business_account_id=account,provider_account_id=pid)
                for field in ('payload_json','template_json'):
                    raw=json.loads(cloned[field]);raw['account_id']=account;cloned[field]=json.dumps(raw,ensure_ascii=False)
                insert(db,'shadow_profiles',cloned)
                insert(db,'composition_template_states',dict(state,account_id=account))
                for v in versions:
                    raw=json.loads(v['payload_json']);raw['account_id']=account
                    insert(db,'composition_template_versions',dict(v,account_id=account,config_hash=from_dict(raw).config_hash(),payload_json=json.dumps(raw),preview_token='SCALE-'+str(i)+'-'+str(v['version'])))
                for p in pools:insert(db,'composition_material_pools',dict(p,account_id=account))
                for c in cache:insert(db,'composition_catalog_cache',dict(c,account_id=account))
        now=utcnow().astimezone(SHANGHAI).replace(hour=22)
        for i in range(50):
            account='SCALE-'+str(i).zfill(2)
            p=self.production.start(self.token,account,daily_limit=5,publish_times=('09:00','12:00','15:00','18:00','21:00'),target_follower_count=1000)
            grant=ServiceGrant(account,p.config_hash())
            self.assertEqual(len(self.production.reserve_daily(grant,now)),5)
            self.assertEqual(self.production.reserve_daily(grant,now),[])
        with self.store.connect() as db:
            rows=db.execute('SELECT account_id,count(*) FROM autopilot_allocations GROUP BY account_id').fetchall()
            self.assertEqual(len(rows),50);self.assertTrue(all(r[1]==5 for r in rows))
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],0)


if __name__=='__main__':unittest.main()
