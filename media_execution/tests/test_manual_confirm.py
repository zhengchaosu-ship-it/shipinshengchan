"""8502原Prepare/Preview/Confirm支持仅存在2060的已验证MP4及封面。"""
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from yixiaoer_adapter.tests import test_production as fixtures
from media_execution.production import ProductionControlPlane


class ManualConfirmTests(unittest.TestCase):
    def test_original_preview_and_confirm_without_server_media(self):
        self.check_original_preview_and_confirm(False)

    def test_local_operator_preview_and_confirm_without_enabling_employee_login(self):
        self.check_original_preview_and_confirm(True)

    def check_original_preview_and_confirm(self, local_operator):
        fixture=fixtures.ProductionTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        f=fixture.f
        control=ProductionControlPlane({'operations_db':str(f.store.path),'worker_ids':['WORKER-2060S-01']},SimpleNamespace(db_path=f.root/'render.db'))
        control.migrate()
        with f.store.connect(write=True) as db:
            for cid,path in zip(f.ids,f.paths):
                row=db.execute('SELECT * FROM startup_contents WHERE content_id=?',(cid,)).fetchone()
                media={'size':row['size_bytes'],'mtime_ns':row['mtime_ns'],'duration':8,'cover_path':str(Path(path).with_suffix('.jpg')),'cover_sha256':'b'*64}
                db.execute('INSERT INTO media_execution_outputs(content_id,render_job_id,worker_id,local_output_path,output_sha256,media_json,render_completed_at) VALUES(?,?,?,?,?,?,?)',
                    (cid,cid,'WORKER-2060S-01',str(path),'a'*64,json.dumps(media),control.clock()))
                Path(path).rename(Path(path).with_suffix('.worker-only'))
        if local_operator:
            from startup_autopilot.single_studio import StudioPlannerStore,LocalOperator,ACTOR_ID
            from startup_pipeline.service import StartupPipeline
            studio=StudioPlannerStore(f.store.path,studio_enabled=True)
            studio.initialize_operator()
            with studio.connect(write=True) as db:
                db.execute('UPDATE startup_batches SET employee_id=?',(ACTOR_ID,))
            f.store=studio;f.employee=ACTOR_ID;f.token=LocalOperator()
            f.pipeline=StartupPipeline(studio,probe=f.pipeline.probe)
        plan=replace(fixture.base.plan,plan_id='REMOTE-MANUAL-INPUT')
        source={'selected_content_ids':list(f.ids),'employee_id':f.employee,'payload_json':plan.payload()}
        from yixiaoer_adapter.production import prepare_production_preview
        from startup_pipeline.plan_confirmation import load_plan
        with patch('yixiaoer_adapter.production.subprocess.run',side_effect=AssertionError('SERVER_FFMPEG_FORBIDDEN')):
            preview=prepare_production_preview(f.store,source,f.profile,fixture.config,probe=lambda path:(_ for _ in ()).throw(AssertionError('SERVER_MEDIA_PROBE_FORBIDDEN')))
        selected=load_plan(preview['payload_json'])
        _,receipt=f.pipeline.preview_receipt(f.token,selected,list(f.ids),f.profile)
        result=f.pipeline.confirm_plan(f.token,selected,list(f.ids),f.profile,expected_preview=receipt)
        self.assertEqual(result['created'],3)
        self.assertTrue(f.pipeline.confirm_plan(f.token,selected,list(f.ids),f.profile,expected_preview=receipt)['idempotent'])
        with f.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM media_execution_jobs WHERE job_type='PUBLISH'").fetchone()[0],3)
            self.assertEqual(db.execute('SELECT sum(submit_attempt_count) FROM provider_publish_jobs').fetchone()[0],0)
