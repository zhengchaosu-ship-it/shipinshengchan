"""用户额度和时段规则；仅临时库/字节素材，不执行真实Render/Provider。"""
from dataclasses import replace
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

from startup_autopilot.tests import test_production as fixtures
from startup_autopilot.models import SHANGHAI
from production_autopilot.preflight import run


class SlotPolicyTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ProductionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.worker,self.cli,_=self.f.make_worker()
        self.now=self.f.now.astimezone(SHANGHAI).replace(hour=0,minute=0,second=0,microsecond=0)

    def test_low_ai_scores_change_ranking_not_user_daily_limit(self):
        f=self.f;grant=f.start();before=f.production.authorization(f.account)
        with patch('startup_autopilot.bandit_selector.BanditSelector.score',return_value=('ACCOUNT_SLOT_AFFINITY',-1000000)):
            ids=f.production.reserve_daily(grant,self.now)
        self.assertEqual(len(ids),5)
        self.assertEqual(before,f.production.authorization(f.account))
        self.assertEqual(f.production.shadows.load(f.f.actor,f.account)[1].daily_publish_limit,5)
        self.assertEqual(self.cli.submits(),[])

    def test_only_legal_partial_capacity_is_reserved_without_lowering_limit(self):
        f=self.f
        pools={p['pool_id']:p for p in f.f.catalogs}
        draft=replace(f.f.draft,slots=tuple(replace(s,selection_policy='FIXED',
            fixed_material_id=pools[s.material_pool]['files'][1 if s.slot_position=='HAND_2' else 0]['material_id']) for s in f.f.draft.slots))
        receipt=f.f.builder.preview_draft(f.f.actor,draft)
        f.f.builder.confirm(f.f.actor,draft,receipt['token'])
        grant=f.start();before=f.production.authorization(f.account)
        report=run(f.production,f.token,f.account,infra={'render_ready':True,'render_reason':'READY','publisher_ready':True})
        self.assertTrue(report['eligible'],report['blocking_reasons'])
        self.assertEqual(report['capacity']['daily'],1);self.assertEqual(report['capacity']['required'],5)
        ids=f.production.reserve_daily(grant,self.now)
        self.assertEqual(len(ids),1)
        self.assertEqual(before,f.production.authorization(f.account))
        with f.store.connect() as db:
            row=db.execute('SELECT * FROM autopilot_allocations').fetchone()
            self.assertEqual(row['scheduled_at'][11:16],'09:00')
            evidence=json.loads(db.execute("SELECT evidence_json FROM autopilot_events WHERE event='DAILY_CAPACITY_RESERVED' ORDER BY recorded_at DESC LIMIT 1").fetchone()[0])
            self.assertEqual(evidence['daily_limit'],5);self.assertEqual(len(evidence['unfilled_slots']),4)
            self.assertFalse(evidence['carry_over']);self.assertFalse(evidence['catch_up'])
        # 已用尽合法组合时自然为0；配置仍为5，不向未来插入额外slot。
        self.assertEqual(f.production.reserve_daily(grant,self.now+timedelta(days=1)),[])
        self.assertEqual(before,f.production.authorization(f.account))

    def test_midday_missing_slots_are_not_carried_to_next_day(self):
        f=self.f;grant=f.start()
        first=f.production.reserve_daily(grant,self.now.replace(hour=10,minute=1))
        second=f.production.reserve_daily(grant,self.now+timedelta(days=1))
        self.assertEqual(len(first),3);self.assertEqual(len(second),5)
        with f.store.connect() as db:
            days={d:[r[0][11:16] for r in db.execute('SELECT scheduled_at FROM autopilot_allocations WHERE local_day=? ORDER BY scheduled_at',(d,))]
                for d in (self.now.date().isoformat(),(self.now+timedelta(days=1)).date().isoformat())}
            self.assertEqual(days[self.now.date().isoformat()],['15:00','18:00','21:00'])
            self.assertEqual(days[(self.now+timedelta(days=1)).date().isoformat()],['09:00','12:00','15:00','18:00','21:00'])
            self.assertEqual(db.execute('SELECT count(*) FROM production_job_lineage').fetchone()[0],0)
        self.assertEqual(f.production.reserve_daily(grant,self.now+timedelta(days=1)),[])

    def test_user_limit_three_remains_three(self):
        f=self.f;grant=f.start(3,('09:00','15:00','21:00'))
        self.assertEqual(len(f.production.reserve_daily(grant,self.now)),3)
        self.assertEqual(len(f.production.reserve_daily(grant,self.now+timedelta(days=1))),3)
        self.assertEqual(json.loads(f.production.authorization(f.account)['config_json'])['daily_publish_limit'],3)

    def test_paused_account_cannot_reserve_or_catch_up(self):
        f=self.f;grant=f.start();f.production.control(f.token,f.account,'pause')
        with self.assertRaises(PermissionError):f.production.reserve_daily(grant,self.now)
        with f.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM autopilot_allocations').fetchone()[0],0)
        self.assertFalse(f.production.authorization(f.account)['enabled'])

    def test_explicit_replacement_cannot_link_cross_day_debt(self):
        from startup_autopilot.production import ServiceGrant
        f=self.f;worker,_,row=f.ready_job()
        with f.store.connect(write=True) as db:
            db.execute("UPDATE provider_publish_jobs SET state='FAILED',provider_task_set_id='fixture-task',submit_attempt_count=1 WHERE job_id=?",(row['job_id'],))
            db.execute("UPDATE autopilot_allocations SET state='FAILED' WHERE allocation_id=?",(row['allocation_id'],))
        grant=ServiceGrant(f.account,f.production.authorization(f.account)['config_hash'])
        child=f.production.reserve_daily(grant,self.now+timedelta(days=2))[0]
        with self.assertRaisesRegex(ValueError,'SLOT_CATCH_UP_FORBIDDEN'):
            worker.reliability.link_replacement(f.token,row['allocation_id'],child)
        with f.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM production_job_lineage').fetchone()[0],0)


if __name__=='__main__':unittest.main()
