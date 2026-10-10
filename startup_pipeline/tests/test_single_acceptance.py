from datetime import date,time,timedelta
from pathlib import Path
import tempfile
import unittest
import json
from dataclasses import replace
from publish_planner.storage import PlannerStore
from publish_planner.models import Plan
from startup_pipeline.service import StartupPipeline
from startup_pipeline.single_acceptance import migrate,create_single_ready_job,ReadyScope,CONFIRMATION
from startup_pipeline.account_binding import reserve
from startup_render.common import save,digest
from xiaovcat_adapter.storage import OperationsStore
from xiaovcat_adapter.desktop_worker.v04_submit import reserve_once


class SingleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=PlannerStore(self.root/'operations.db');self.store.migrate()
        password='isolated-fixture-password';self.store.bootstrap_admin('admin',password)
        admin=self.store.login('admin',password)
        self.store.sync_snapshot({'run_id':'fixture','complete':True,
            'groups':[{'group_id':'339642','group_name':'renameable','identity_status':'SOURCE_ID'}],
            'accounts':[{'account_id':'1621131832863931','group_id':'339642','display_name':'丙曜','platform':'抖音',
             'online_status':'ONLINE','is_available':True,'identity_evidence':'ISOLATED_FIXTURE'}]},session_token=admin)
        self.employee=self.store.save_employee(admin,employee_name='fixture',login_name='employee',password=password,
            group_bindings=[{'group_id':'339642','group_role':'STARTUP'}])
        self.token=self.store.login('employee',password)
        self.output=self.root/'丙曜起号.mp4';self.output.write_bytes(b'isolated mock media, NOT REAL MP4')
        self.pipeline=StartupPipeline(self.store,batch_root=self.root/'batches',probe=self.probe);self.pipeline.migrate()
        path=self.root/'batches/fixture/batch_manifest.json'
        save(path,{'batch_id':'fixture','created_at':'2026-10-04T00:00:00+08:00','videos':[
            {'video_index':1,'status':'success','composition_signature':'fixture-signature','selected_materials':[]}]})
        self.pipeline.import_batch(admin,path,self.employee)
        self.content=self.pipeline.contents(self.token)[0]['content_id']
        self.pipeline.register_export(self.token,self.content,self.output)
        context=reserve(self.store,self.token,'1621131832863931',1)
        with self.store.connect(write=True) as db:
            db.execute('INSERT INTO startup_content_bindings VALUES(?,?,?,?,?,NULL)',
               (self.content,context['generation_id'],'1621131832863931','丙曜',context['draft_names'][0]))
        self.run=self.root/'single-run'
        save(self.run/'single_run.json',{'run_id':'fixture-single-run','max_jobs':1})
        save(self.run/'GENERATION_RESULT.json',{'registered':[{'content_id':self.content}]})
        save(self.run/'server/receipts'/(self.content+'.json'),{'status':'COMPLETED','content_status':'READY_TO_PUBLISH',
             'target_account_id':'1621131832863931','media':{'sha256':digest(self.output)}})
        tomorrow=date.today()+timedelta(days=1)
        self.plan=Plan('fixture-single',tomorrow,tomorrow,time(9),('1621131832863931',),(str(self.output),),daily_count=1)

    def probe(self,path):
        p=Path(path);s=p.stat()
        return {'video_path':str(p),'size_bytes':s.st_size,'mtime_ns':s.st_mtime_ns,'duration_seconds':1,'media':{'fixture':True}}

    def create(self,plan=None,confirmation=CONFIRMATION):
        plan=plan or self.plan
        _,preview=self.pipeline.preview_receipt(self.token,plan,[self.content],'startup-default')
        return create_single_ready_job(self.pipeline,self.token,plan,self.content,'startup-default',self.run,
                     expected_preview=preview,confirmation=confirmation)

    def test_create_one_real_scoped_job_uses_ready_binding(self):
        result=self.create();job=OperationsStore(self.store.path).get_job(result['job_id'])
        self.assertEqual(job.content_id,self.content);self.assertEqual(job.title,'');self.assertEqual(job.description,'')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT dispatch_mode FROM startup_job_metadata').fetchone()[0],'SINGLE_ACCEPTANCE')
            self.assertEqual(db.execute('SELECT test_only FROM publish_plan_items').fetchone()[0],0)
        ReadyScope(OperationsStore(self.store.path),job.job_id,self.root).check(result['policy'])

    def test_missing_explicit_confirmation_creates_nothing(self):
        with self.assertRaises(PermissionError):self.create(confirmation='')
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],0)

    def test_duplicate_content_denied(self):
        self.create()
        with self.assertRaises(PermissionError):self.create(replace(self.plan,plan_id='other'))

    def test_non_ready_denied(self):
        with self.store.connect(write=True) as db:db.execute("UPDATE startup_contents SET production_status='GENERATING'")
        with self.assertRaises(ValueError):self.create()

    def test_other_account_denied(self):
        with self.assertRaises(PermissionError):self.create(replace(self.plan,account_ids=('other',)))

    def test_media_changed_after_ready_denied(self):
        self.output.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.create()

    def test_scope_policy_change_denied(self):
        result=self.create();scope=ReadyScope(OperationsStore(self.store.path),result['job_id'],self.root)
        with self.assertRaises(PermissionError):scope.check(dict(result['policy'],description='other'))

    def test_real_reservation_is_durable_once(self):
        result=self.create();store=OperationsStore(self.store.path);scope=ReadyScope(store,result['job_id'],self.root)
        reserve_once(store,result['job_id'],scope)
        with self.assertRaises(PermissionError):reserve_once(store,result['job_id'],scope)

    def test_migration_preserves_old_simulation_and_ids(self):
        _,preview=self.pipeline.preview_receipt(self.token,self.plan,[self.content],'startup-default')
        self.pipeline.confirm(self.token,self.plan,[self.content],'startup-default',expected_preview=preview)
        with self.store.connect() as db:
            before=[tuple(r) for r in db.execute('SELECT * FROM startup_job_metadata')]
            jobs=[tuple(r) for r in db.execute('SELECT * FROM publish_jobs')]
        result=migrate(self.store.path);self.assertTrue(result['old_rows_unchanged'])
        with self.store.connect() as db:
            self.assertEqual(before,[tuple(r) for r in db.execute('SELECT * FROM startup_job_metadata')])
            self.assertEqual(jobs,[tuple(r) for r in db.execute('SELECT * FROM publish_jobs')])
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())

    def test_old_worker_refuses_new_job_without_scope(self):
        result=self.create()
        with self.assertRaises(PermissionError):reserve_once(OperationsStore(self.store.path),result['job_id'])
