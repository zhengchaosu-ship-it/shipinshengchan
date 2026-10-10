from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
import json
import hashlib
import sqlite3
import tempfile
import unittest

from startup_autopilot.affinity import build_affinities, normalized_score
from startup_autopilot.demo import fixture
from startup_autopilot.metrics import FIELDS, MetricSnapshot, PublishedWork, YixiaoerMetricsDecoder, feedback_requests, valid_public_sample_count
from startup_autopilot.models import Actor, SHANGHAI, Slot, Template, aware, digest, material_override, phase, policy, production_dispatch, transition
from startup_autopilot.planner import StartupDailyPlanner, composition_signature, counts_as_occupied, submission_budget
from startup_autopilot.storage import FoundationStore

NOW=datetime(2026,10,6,1,0,tzinfo=SHANGHAI)


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.actor,self.profile,self.template,self.now=fixture(NOW)
        self.planner=StartupDailyPlanner()
        self.day=(NOW+timedelta(days=1)).date()

    def run_shadow(self, **kwargs):
        return self.planner.shadow(self.actor,self.profile,self.template,self.day,self.now,**kwargs)

    def row(self, content, time='09:00', status='SCHEDULED_QUEUED', **extras):
        return {'account_id':self.profile.account_id,'content_id':content,'scheduled_at':f'2026-10-07T{time}:00+08:00','status':status,**extras}

    def change_template(self, template):
        self.template=template
        profile=replace(self.profile,template_hash=digest(asdict(template)),enabled=False,status='SETUP')
        self.profile=transition(profile,self.actor,'start',NOW,config_confirmed=True,config_hash=profile.config_hash())

    def test_five_unique_no_side_effects(self):
        result=self.run_shadow()
        self.assertEqual(len(result['proposals']),5)
        self.assertEqual(len({p['composition_signature'] for p in result['proposals']}),5)
        self.assertTrue(all(result[k]==0 for k in ('submit_count','render_jobs_created','publish_jobs_created')))
        used=[s['material_id'] for p in result['proposals'] for s in p['selections']]
        self.assertEqual(len(set(used)),20)

    def test_selection_idempotent(self):
        one=self.run_shadow(); self.now+=timedelta(seconds=30); two=self.run_shadow()
        self.assertEqual(one['proposals'],two['proposals'])
        self.assertNotEqual(one['input_snapshot_hash'],two['input_snapshot_hash'])

    def test_ready_render_and_queued_all_count_distinct_content(self):
        rows=[self.row('ONE',status='READY'),self.row('ONE',status='RENDERING'),self.row('TWO','12:00')]
        result=self.run_shadow(existing=rows)
        self.assertEqual(result['existing_content_count'],2)
        self.assertEqual(len(result['proposals']),3)
        self.assertEqual(result['proposals'][0]['scheduled_at'],'2026-10-07T15:00:00+08:00')

    def test_existing_eight_block_without_modification(self):
        rows=[self.row(str(i),f'{i*3:02d}:00') for i in range(8)]
        before=digest(rows); result=self.run_shadow(existing=rows)
        self.assertEqual(result['attention_reason'],'EXISTING_DAILY_LIMIT_EXCEEDED_NO_TASKS_MODIFIED')
        self.assertEqual(result['proposals'],[]); self.assertEqual(digest(rows),before)

    def test_five_reserved_nothing_to_fill(self):
        result=self.run_shadow(existing=[self.row(str(i),t) for i,t in enumerate(self.profile.publish_times)])
        self.assertEqual(result['status'],'CAPACITY_ALREADY_RESERVED')

    def test_failed_unknown_retains_capacity(self):
        self.assertTrue(counts_as_occupied(self.row('FAIL',status='FAILED',submit_attempt_count=1)))

    def test_verified_failed_without_work_can_release(self):
        row=self.row('FAIL',status='FAILED',submit_attempt_count=1,reconciled_no_public_work=True,provider_stage_status='fail')
        self.assertFalse(counts_as_occupied(row))
        row['provider_video_id']='WORK'; self.assertTrue(counts_as_occupied(row))

    def test_cancelled_consumed_intent_held(self):
        self.assertTrue(counts_as_occupied(self.row('C',status='CANCELLED',submit_attempt_count=1)))
        self.assertTrue(counts_as_occupied(self.row('C',status='CANCELLED',submit_attempt_count=0,intent_json='INTENT')))
        self.assertTrue(counts_as_occupied(self.row('C',status='CANCELLED',submit_attempt_count=0,provider_video_id='WORK')))

    def test_existing_collision_needs_reconciliation(self):
        self.assertEqual(self.run_shadow(existing=[self.row('ONE'),self.row('TWO')])['attention_reason'],'EXISTING_SCHEDULE_COLLISION_RECONCILIATION_REQUIRED')

    def test_utc_and_beijing_same_instant_collision(self):
        one=self.row('ONE'); two=self.row('TWO')
        two['scheduled_at']='2026-10-07T01:00:00+00:00'
        self.assertEqual(self.run_shadow(existing=[one,two])['attention_reason'],'EXISTING_SCHEDULE_COLLISION_RECONCILIATION_REQUIRED')

    def test_actual_duplicate_publish_jobs_not_stage_dedup(self):
        rows=[self.row('ONE',publish_job_id='JOB1'),self.row('ONE',publish_job_id='JOB2')]
        self.assertEqual(self.run_shadow(existing=rows)['attention_reason'],'EXISTING_DUPLICATE_PUBLISH_JOBS_RECONCILIATION_REQUIRED')

    def test_exhausted_submission_budget_not_mistaken_for_full_day(self):
        events=[{'account_id':self.profile.account_id,'attempt_key':str(i),'attempted_at':NOW.isoformat()} for i in range(5)]
        result=self.run_shadow(existing=[self.row('ONE')],submissions=events)
        self.assertEqual(result['attention_reason'],'SUBMISSION_BUDGET_EXHAUSTED')
        self.assertEqual(result['proposals'],[])

    def test_time_boundary_and_horizon(self):
        self.now=datetime(2026,10,7,7,tzinfo=SHANGHAI)
        self.assertIn('SCHEDULE_TOO_SOON',self.run_shadow()['attention_reason'])
        self.now=NOW; self.day=(NOW+timedelta(days=15)).date()
        self.assertEqual(self.run_shadow()['proposals'],[])

    def test_naive_date_rejected(self):
        self.now=NOW.replace(tzinfo=None)
        with self.assertRaises(ValueError): self.run_shadow()

    def test_cross_account_denied(self):
        self.actor=Actor('OTHER',frozenset({'OTHER'}))
        with self.assertRaises(PermissionError): self.run_shadow()

    def test_template_order_tamper_denied(self):
        self.template=replace(self.template,slots=tuple(reversed(self.template.slots)))
        with self.assertRaises(PermissionError): self.run_shadow()

    def test_policy_same_version_tamper_denied(self):
        self.planner=StartupDailyPlanner(dict(policy(),material_cooldown_hours=0))
        with self.assertRaises(PermissionError): self.run_shadow()

    def test_inactive_and_finished_do_not_plan(self):
        self.profile=transition(self.profile,self.actor,'pause',NOW)
        self.assertEqual(self.run_shadow()['status'],'INACTIVE')
        self.profile=transition(self.profile,self.actor,'finish',NOW,finish_choice='KEEP_SCHEDULED')
        self.assertEqual(self.run_shadow()['proposals'],[])

    def test_missing_health_and_render_offline_block(self):
        self.assertEqual(self.run_shadow(health={})['status'],'ATTENTION_REQUIRED')
        self.assertEqual(self.run_shadow(health={'render':'OFFLINE'})['attention_reason'],'RENDER_ATTENTION_REQUIRED')

    def test_block_material_respected(self):
        blocked=self.template.slots[0].material_ids[0]
        result=self.run_shadow(overrides={blocked:'BLOCK'})
        self.assertNotIn(blocked,[s['material_id'] for p in result['proposals'] for s in p['selections']])

    def test_fixed_and_daily_fatigue_conflict_not_relaxed(self):
        slot=replace(self.template.slots[0],fixed_material_id=self.template.slots[0].material_ids[0])
        self.change_template(replace(self.template,slots=(slot,*self.template.slots[1:])))
        self.assertEqual(self.run_shadow()['attention_reason'],'MATERIAL_POOL_OR_FATIGUE_CONFLICT')

    def test_lock_conflict_blocks(self):
        one,two=self.template.slots[0].material_ids[:2]
        self.assertEqual(self.run_shadow(overrides={one:'LOCK',two:'LOCK'})['attention_reason'],'MULTIPLE_LOCKS_IN_SLOT')

    def test_fatigue_history_and_future_reservation(self):
        mid=self.template.slots[0].material_ids[0]
        history=[{'account_id':self.profile.account_id,'material_id':mid,'used_at':'2026-10-07T10:00:00+08:00','content_id':'FUTURE'}]
        first=self.run_shadow(material_history=history)['proposals'][0]
        self.assertNotIn(mid,[s['material_id'] for s in first['selections']])

    def test_recent_signature_blocks(self):
        selections=[{'slot':1,'module_type':'引流','material_id':'ONE'}]
        self.assertEqual(composition_signature('A',selections),composition_signature('A',selections))
        self.assertNotEqual(composition_signature('A',selections),composition_signature('B',selections))
        # 单个固定槽位，唯一组合30天内被占用。
        self.change_template(Template(self.profile.account_id,self.template.version,(Slot('引流',('ONE',)),)))
        self.profile=replace(self.profile,daily_publish_limit=1,publish_times=('09:00',),enabled=False,status='SETUP')
        self.profile=transition(self.profile,self.actor,'start',NOW,config_confirmed=True,config_hash=self.profile.config_hash())
        history=[{'account_id':self.profile.account_id,'signature':composition_signature(self.profile.account_id,selections),'used_at':NOW.isoformat()}]
        self.assertEqual(self.run_shadow(composition_history=history)['attention_reason'],'COMPOSITION_RECENT_DUPLICATE')

    def test_pool_exhaustion_no_partial_tasks(self):
        self.change_template(Template(self.profile.account_id,self.template.version,(Slot('引流',('ONE','TWO')),)))
        self.assertEqual(self.run_shadow()['proposals'],[])

    def test_autopilot_branches_in_allowed_pool(self):
        self.profile=transition(self.profile,self.actor,'refresh_learning',NOW,valid_samples=20,coverage=.9)
        affinities={m:{'account_id':self.profile.account_id,'sample_count':20,'affinity_score':1+i/10} for i,slot in enumerate(self.template.slots) for m in slot.material_ids[:6]}
        result=self.run_shadow(valid_samples=20,affinities=affinities)
        self.assertEqual(len(result['proposals']),5)
        for proposal in result['proposals']:
            for selected,slot in zip(proposal['selections'],self.template.slots):
                self.assertIn(selected['material_id'],slot.material_ids)
                self.assertIn(selected['selection_branch'],('EXPLOIT','DIVERSITY','EXPLORE'))

    def test_cross_account_scores_denied(self):
        with self.assertRaises(PermissionError): self.run_shadow(affinities={'ONE':{'account_id':'OTHER'}})

    def test_preferred_used_in_cold_rotation(self):
        mid=self.template.slots[0].material_ids[0]
        self.assertEqual(self.run_shadow(overrides={mid:'PREFERRED'})['proposals'][0]['selections'][0]['material_id'],mid)

    def test_seven_day_usage_cap(self):
        mid=self.template.slots[0].material_ids[0]
        history=[{'account_id':self.profile.account_id,'material_id':mid,'used_at':(NOW-timedelta(days=d)).isoformat(),'content_id':str(d)} for d in (2,3,4)]
        selected=[s['material_id'] for p in self.run_shadow(material_history=history,overrides={mid:'PREFERRED'})['proposals'] for s in p['selections']]
        self.assertNotIn(mid,selected)

    def test_future_usage_budget_and_adjacent_core(self):
        mid=self.template.slots[0].material_ids[0]
        history=[{'account_id':self.profile.account_id,'material_id':mid,'used_at':f'2026-10-{day:02d}T09:00:00+08:00','content_id':str(day),'core':False} for day in (9,10,11)]
        selected=[s['material_id'] for p in self.run_shadow(material_history=history,overrides={mid:'PREFERRED'})['proposals'] for s in p['selections']]
        self.assertNotIn(mid,selected)
        history=history[:1]; history[0]['core']=True
        first=self.run_shadow(material_history=history,overrides={mid:'PREFERRED'})['proposals'][0]
        self.assertNotIn(mid,[s['material_id'] for s in first['selections']])


class AuthorizationAndBudgetTests(unittest.TestCase):
    def setUp(self): self.actor,self.profile,self.template,self.now=fixture(NOW)

    def test_second_confirmation_required(self):
        setup=replace(self.profile,enabled=False,status='SETUP')
        with self.assertRaises(PermissionError): transition(setup,self.actor,'start',NOW)

    def test_config_change_requires_new_confirmation(self):
        paused=transition(self.profile,self.actor,'pause',NOW)
        paused=replace(paused,target_follower_count=9999)
        with self.assertRaises(PermissionError): transition(paused,self.actor,'resume',NOW)

    def test_finish_requires_scheduled_choice(self):
        with self.assertRaises(ValueError): transition(self.profile,self.actor,'finish',NOW)

    def test_target_reached_does_not_finish(self):
        self.assertEqual(transition(self.profile,self.actor,'refresh_learning',NOW,valid_samples=20,coverage=1).status,'AUTOPILOT')

    def test_samples_and_missing_metrics_keep_learning(self):
        self.assertEqual(phase(19,1,policy()),'COLD_START')
        self.assertEqual(phase(20,.45,policy()),'LEARNING')

    def test_admin_override_permission(self):
        employee=replace(self.actor,role='EMPLOYEE')
        with self.assertRaises(PermissionError): material_override(employee,'DEMO_ACCOUNT','M','BLOCK',{'M'})

    def test_submission_day_dedup_poc_and_manual(self):
        events=[{'account_id':'DEMO_ACCOUNT','attempt_key':str(i),'attempted_at':NOW.isoformat(),'source':source} for i,source in enumerate(('PRODUCTION','POC','MANUAL'))]
        events.append(dict(events[0])); events.append({'account_id':'OTHER','attempt_key':'X','attempted_at':NOW.isoformat()})
        self.assertEqual(submission_budget(events,'DEMO_ACCOUNT',NOW,policy()),(2,None))

    def test_quota_error_attention_no_retry(self):
        events=[{'account_id':'DEMO_ACCOUNT','attempt_key':'X','attempted_at':NOW.isoformat(),'quota_rejected':True}]
        self.assertEqual(submission_budget(events,'DEMO_ACCOUNT',NOW,policy())[0],0)
        self.assertIsNone(policy()['official_submission_limit'])

    def test_beijing_natural_day(self):
        events=[{'account_id':'DEMO_ACCOUNT','attempt_key':'X','attempted_at':'2026-10-05T17:00:00+00:00'}]
        self.assertEqual(submission_budget(events,'DEMO_ACCOUNT',NOW,policy())[0],4)

    def test_no_live_dispatch_even_with_authorization(self):
        with self.assertRaises(PermissionError): production_dispatch(self.profile)
        with self.assertRaises(PermissionError): replace(self.profile,execution_mode='LIVE').validate()


class MetricsTests(unittest.TestCase):
    def work(self,id='W',account='A'):
        return PublishedWork(account,id,'2026-10-01T09:00:00+08:00','fixture://PUBLIC')

    def sample(self,id='W',account='A',views=100,offset=24,observed=None,full=False):
        work=self.work(id,account)
        snapshot=YixiaoerMetricsDecoder().decode(work,offset,observed or '2026-10-03T09:00:00+08:00',
                  {'viewCount':views,'greatCount':10,'commentCount':2,'shareCount':1,'collectCount':0},evidence_ref='fixture://STATS')
        if full:
            values=dict(snapshot.values,followers_delta=1,completion_rate=.5)
            snapshot=replace(snapshot,values=values,capabilities={k:'AVAILABLE' if values[k] is not None else 'NOT_SUPPORTED' for k in FIELDS},evidence_hash=digest([id,views,values,offset]))
        return snapshot

    def test_public_time_only_windows(self):
        requests=feedback_requests(self.work())
        self.assertEqual(requests[0]['due_at'],'2026-10-01T11:00:00+08:00')
        self.assertEqual(requests[2]['due_at'],'2026-10-04T09:00:00+08:00')
        with self.assertRaises(ValueError): feedback_requests(replace(self.work(),state='SCHEDULED_QUEUED'))

    def test_sample_count_dedup_and_account_isolation(self):
        works=[self.work(),self.work(),self.work('X','B'),replace(self.work('Q'),state='SCHEDULED_QUEUED')]
        self.assertEqual(valid_public_sample_count(works,'A'),1)

    def test_zero_retained_missing_null(self):
        snapshot=self.sample()
        self.assertEqual(snapshot.values['favorites'],0)
        self.assertIsNone(snapshot.values['followers_delta'])
        self.assertEqual(snapshot.capabilities['followers_delta'],'NOT_SUPPORTED')
        partial=YixiaoerMetricsDecoder().decode(self.work(),24,'2026-10-03T09:00:00+08:00',{},evidence_ref='fixture://EMPTY')
        self.assertIsNone(partial.values['views']); self.assertEqual(partial.capabilities['views'],'NOT_RETURNED')

    def test_not_due_and_invalid_metric(self):
        with self.assertRaises(ValueError): self.sample(observed='2026-10-01T10:00:00+08:00')
        raw=YixiaoerMetricsDecoder().decode(self.work(),24,'2026-10-03T09:00:00+08:00',{'viewCount':-1},evidence_ref='fixture://BAD')
        self.assertIsNone(raw.values['views']); self.assertEqual(raw.capabilities['views'],'INVALID')

    def test_relative_baseline_no_cross_account_absolute_views(self):
        baseline=self.sample('BASE',views=100,observed='2026-10-02T09:00:00+08:00',full=True)
        foreign=self.sample('FOREIGN','B',1000000,observed='2026-10-02T09:00:00+08:00',full=True)
        score=normalized_score(self.sample('NEW',views=200,full=True),[baseline,foreign])
        self.assertEqual(score['view_score'],2)
        self.assertEqual(score['baseline_work_ids'],['BASE'])

    def test_low_coverage_excludes_full_learning(self):
        base=self.sample('BASE',observed='2026-10-02T09:00:00+08:00')
        score=normalized_score(self.sample('NEXT'),[base])
        self.assertAlmostEqual(score['coverage'],.45)
        self.assertIsNone(score['learning_score'])

    def test_no_baseline_neutral_not_fabricated(self):
        score=normalized_score(self.sample(full=True),[])
        self.assertIsNone(score['view_score']); self.assertFalse(score['learning_eligible'])

    def test_single_viral_sample_shrinks(self):
        base=self.sample('BASE',views=100,observed='2026-10-02T09:00:00+08:00',full=True)
        viral=self.sample('VIRAL',views=1000000,full=True)
        rows=build_affinities('A',[base,viral],{'VIRAL':[{'material_id':'M','module_type':'引流'}]},[],NOW)
        self.assertEqual(rows[0]['sample_count'],1)
        self.assertLess(abs(rows[0]['affinity_score']-1),.1)

    def test_72h_correction_not_extra_sample(self):
        base24=self.sample('BASE',observed='2026-10-02T09:00:00+08:00',full=True)
        current24=self.sample('NEW',full=True)
        base72=self.sample('BASE',offset=72,observed='2026-10-04T09:00:00+08:00',full=True)
        current72=self.sample('NEW',offset=72,observed='2026-10-05T09:00:00+08:00',full=True)
        binding={'NEW':[{'material_id':'M','module_type':'引流'}]}
        one=build_affinities('A',[base24,current24],binding,[],NOW)[0]
        two=build_affinities('A',[base24,current24,base72,current72],binding,[],NOW)[0]
        self.assertEqual(two['sample_count'],1); self.assertNotEqual(one['version_hash'],two['version_hash'])
        self.assertIsNotNone(two['score_72h'])


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'autopilot.fixture.db'
        self.store=FoundationStore(self.path)
        with sqlite3.connect(self.path) as db:
            db.executescript('CREATE TABLE employees(employee_id TEXT PRIMARY KEY); CREATE TABLE xiaovcat_accounts(account_id TEXT PRIMARY KEY); CREATE TABLE legacy_jobs(id TEXT PRIMARY KEY,status TEXT);')
            db.execute("INSERT INTO employees VALUES('DEMO_EMPLOYEE')")
            db.execute("INSERT INTO xiaovcat_accounts VALUES('DEMO_ACCOUNT')")
            db.execute("INSERT INTO legacy_jobs VALUES('OLD','SCHEDULED_QUEUED')")
        db.close()
        self.store.migrate(isolated=True)
        self.actor,self.profile,self.template,self.now=fixture(NOW)
        self.store.save_profile(self.actor,self.profile,self.template,NOW)

    def tearDown(self):
        self.assertTrue(Path(self.temp.name).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.temp.cleanup()

    def test_migration_idempotent_and_legacy_preserved(self):
        self.assertFalse(self.store.migrate(isolated=True))
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT * FROM legacy_jobs').fetchall(),[('OLD','SCHEDULED_QUEUED')])
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertTrue(Path(str(self.path)+'.bak').exists())

    def test_production_path_denied(self):
        with self.assertRaises(PermissionError): FoundationStore('D:/video_search_tool/operations.db')
        with self.assertRaises(PermissionError): self.store.migrate()

    def test_concurrent_shadow_save_one_snapshot(self):
        decision=StartupDailyPlanner().shadow(self.actor,self.profile,self.template,'2026-10-07',NOW)
        def save(_): return self.store.save_shadow(self.actor,self.profile,decision,NOW,policy()['scoring_version'])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(save,range(8)))
        self.assertEqual(sum(r[1] for r in results),1)
        self.assertEqual(len({r[0] for r in results}),1)

    def test_immutable_shadow_evidence(self):
        decision=StartupDailyPlanner().shadow(self.actor,self.profile,self.template,'2026-10-07',NOW)
        self.store.save_shadow(self.actor,self.profile,decision,NOW,policy()['scoring_version'])
        with self.store.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError): db.execute("UPDATE sap_shadow_runs SET decision_json='{}'")

    def test_metrics_and_affinity_history_append_only(self):
        with self.store.connect() as db:
            self.assertIn('sap_metric_snapshots',{r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")})
            self.assertIn('sap_affinity_no_update',{r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")})

    def test_profile_invalid_foreign_account_denied(self):
        with self.assertRaises(PermissionError): self.store.save_profile(Actor('OTHER',frozenset()),self.profile,self.template,NOW)

    def test_same_template_version_cannot_change_content(self):
        altered=replace(self.template,slots=tuple(reversed(self.template.slots)))
        changed=replace(self.profile,template_hash=digest(asdict(altered)),enabled=False,status='SETUP')
        with self.assertRaises(ValueError): self.store.save_profile(self.actor,changed,altered,NOW)

    def test_full_existing_schema_migration_in_readonly_copy(self):
        production=Path(__file__).resolve().parents[2]/'operations.db'
        if not production.exists():
            self.skipTest('PRODUCTION_DATABASE_NOT_AVAILABLE')
        copied=Path(self.temp.name)/'legacy-copy.fixture.db'
        source=sqlite3.connect(production.as_uri()+'?mode=ro',uri=True)
        target=sqlite3.connect(copied)
        try:
            source.execute('PRAGMA query_only=ON')
            source.backup(target)
            tables=[r[0] for r in target.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            def fingerprint(connection):
                return {table:hashlib.sha256(repr(connection.execute('SELECT * FROM "'+table+'" ORDER BY rowid').fetchall()).encode()).hexdigest() for table in tables}
            before=fingerprint(target)
        finally:
            source.close(); target.close()
        FoundationStore(copied).migrate(isolated=True)
        with FoundationStore(copied).connect() as db:
            self.assertEqual(fingerprint(db),before)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sap_profiles').fetchone()[0],0)
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok')


if __name__=='__main__': unittest.main()
