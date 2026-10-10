"""正式池初始化与共享池片内身份约束；不调用任何发布/渲染入口。"""
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import tempfile
import unittest

from production_materials.library import DIRECTORIES
from production_materials.store import ProductionMaterialPoolRegistry
from startup_autopilot.composition import CompositionSlot, StartupCompositionTemplateVersion
from startup_autopilot.composition_planner import preview
from startup_autopilot.employee_ui import ensure_account
from startup_autopilot.models import Actor
from startup_autopilot.shadow_store import ShadowStore
from startup_autopilot.template_store import TemplateBuilderStore
from startup_autopilot.tests.test_foundation import NOW


class ProductionPoolBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.formal=self.root/'formal';self.formal.mkdir()
        modules=[('STARTUP_LEAD','STARTUP_HOOK','引流'),('STARTUP_TECHNIQUE','STARTUP_TECHNIQUE','手法'),
                 ('STARTUP_CLINIC','STARTUP_CLINIC','坐诊'),('STARTUP_CLOSE','STARTUP_ENDING','收尾')]
        rows=[]
        for key,module,label in modules:
            folder=self.formal/DIRECTORIES[key];folder.mkdir(parents=True)
            for i in range(3):(folder/f'{i}.mp4').write_bytes(f'fixture {key} {i}'.encode())
            rows.append(dict(pool_id=key,business_type='STARTUP',module_type=module,label=label,root=str(folder)))
        self.config={'database':str(self.root/'registry.sqlite'),'production_library_root':str(self.formal)}
        self.registry=ProductionMaterialPoolRegistry(self.config);self.registry.initialize(rows)
        self.shadows=ShadowStore(self.root/'shadow.sqlite');self.shadows.initialize()
        self.builder=TemplateBuilderStore(self.shadows);self.builder.initialize()
        self.service=SimpleNamespace(shadows=self.shadows,builder=self.builder)
        self.actor=Actor('STUDIO_CONSOLE',frozenset({'A','B'}))
        self.account=dict(account_id='A',display_name='独立夹具',provider_account_id='provider-A',last_synced_at=NOW.isoformat())
        with patch('production_materials.config.settings',return_value=self.config):
            ensure_account(self.service,self.actor,self.account)
        self.draft=StartupCompositionTemplateVersion('A',0,tuple(
            CompositionSlot(position,position,kind,pool,'LEARNABLE',max_uses_7d=None)
            for position,kind,pool in [('HAND_1','手法','STARTUP_TECHNIQUE'),('HAND_2','手法','STARTUP_TECHNIQUE'),
                                       ('TAIL_1','收尾','STARTUP_CLOSE'),('TAIL_2','收尾','STARTUP_CLOSE')]))

    def tearDown(self):self.temp.cleanup()

    def catalogs(self):return self.builder.catalog.refresh(self.actor,'A',hash_budget=10)

    def test_old_empty_directory_never_selected_and_formal_ids_used(self):
        old=self.root/'old_backup';old.mkdir()
        with self.registry.connect(True) as db:
            db.execute('INSERT INTO pools VALUES(?,?,?,?,?,?)',('OLD_HAND','STARTUP','HISTORICAL_HAND','旧手法',str(old),NOW.isoformat()))
        with patch('production_materials.config.settings',return_value=self.config):
            ensure_account(self.service,self.actor,{**self.account,'account_id':'B','provider_account_id':'provider-B'})
        with self.shadows.connect(readonly=True) as db:
            pools=[dict(r) for r in db.execute("SELECT * FROM composition_material_pools WHERE account_id='B'")]
        self.assertEqual({r['pool_id'] for r in pools},{'STARTUP_LEAD','STARTUP_TECHNIQUE','STARTUP_CLINIC','STARTUP_CLOSE'})
        self.assertTrue(all(Path(r['root']).is_relative_to(self.formal) for r in pools))
        self.assertTrue(old.is_dir())

    def test_new_entry_upgrades_cached_old_registry_class_without_background_actions(self):
        import production_materials.store as module
        class OldRegistry(module.Store):
            pass
        with patch.object(module,'ProductionMaterialPoolRegistry',OldRegistry), \
                patch('production_materials.config.settings',return_value=self.config):
            ensure_account(self.service,self.actor,{**self.account,'account_id':'B','provider_account_id':'provider-B'})
            self.assertTrue(callable(getattr(module.ProductionMaterialPoolRegistry,'startup_defaults',None)))
        with self.shadows.connect(readonly=True) as db:
            pools=[dict(r) for r in db.execute("SELECT * FROM composition_material_pools WHERE account_id='B'")]
            self.assertEqual({p['pool_id'] for p in pools},{'STARTUP_LEAD','STARTUP_TECHNIQUE','STARTUP_CLINIC','STARTUP_CLOSE'})
            self.assertEqual(db.execute('SELECT COUNT(*) FROM composition_template_versions').fetchone()[0],0)
        self.assertFalse(self.shadows.load(self.actor,'B')[1].enabled)

    def test_empty_registered_pool_rejected_before_new_profile_save(self):
        folder=self.formal/DIRECTORIES['STARTUP_TECHNIQUE']
        # 测试目录改名保留夹具，正式池路径现在存在但为空。
        folder.rename(folder.with_name('retained_fixture'));folder.mkdir()
        with patch('production_materials.config.settings',return_value=self.config):
            with self.assertRaisesRegex(ValueError,'POOL_EMPTY.*正式素材池候选'):
                ensure_account(self.service,self.actor,{**self.account,'account_id':'B','provider_account_id':'provider-B'})
        with self.shadows.connect(readonly=True) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM shadow_profiles WHERE business_account_id='B'").fetchone())

    def test_disabled_unregistered_and_historical_root_are_rejected(self):
        self.registry.config={**self.config,'disabled_pool_ids':['STARTUP_TECHNIQUE']}
        with self.assertRaisesRegex(ValueError,'POOL_DISABLED'):self.registry.require_startup_pool('STARTUP_TECHNIQUE')
        self.registry.config=self.config
        with self.assertRaisesRegex(ValueError,'NOT_REGISTERED'):self.registry.require_startup_pool('UNKNOWN')
        old=self.root/'empty_old';old.mkdir()
        with self.registry.connect(True) as db:db.execute('UPDATE pools SET root=? WHERE pool_id=?',(str(old),'STARTUP_TECHNIQUE'))
        with self.assertRaisesRegex(ValueError,'ROOT_MISMATCH'):self.registry.require_startup_pool('STARTUP_TECHNIQUE')

    def test_shared_hand_and_tail_distinct_35_unique_and_reuse_unchanged(self):
        before=asdict(self.draft)
        result=preview(self.actor,self.draft,self.catalogs(),NOW)
        self.assertEqual(result['daily_counts'],[5]*7);self.assertEqual(result['weekly_capacity'],35)
        self.assertEqual(result['duplicate_count'],0)
        proposals=[p for day in result['days'] for p in day['proposals']]
        self.assertEqual(len({p['composition_signature'] for p in proposals}),35)
        for p in proposals:
            a,b,c,d=p['selections'];self.assertNotEqual(a['material_id'],b['material_id']);self.assertNotEqual(c['media_sha256'],d['media_sha256'])
        self.assertLess(len({p['selections'][0]['material_id'] for p in proposals}),35)
        self.assertEqual(asdict(self.draft),before)
        for key in ('render_jobs_created','publish_jobs_created','provider_tasks_created','upload_count','publish_count'):
            self.assertEqual(result[key],0)

    def test_content_identity_blocks_aliases_with_different_names_and_ids(self):
        catalogs=self.catalogs();hand=next(p for p in catalogs if p['pool_id']=='STARTUP_TECHNIQUE')
        first=hand['files'][0];second=hand['files'][1]
        alias={**first,'material_id':'DIFFERENT-ID-SAME-SHA','filename':'renamed.mp4'}
        hand['files']=[first,alias,second]
        slots=(replace(self.draft.slots[0],selection_policy='FIXED',fixed_material_id=first['material_id']),self.draft.slots[1])
        result=preview(self.actor,replace(self.draft,slots=slots),catalogs,NOW,days=1)
        self.assertEqual(result['total_suggestions'],1)
        self.assertEqual(result['days'][0]['proposals'][0]['selections'][1]['material_id'],second['material_id'])

    def test_fixed_same_content_cannot_bypass_constraint(self):
        catalogs=self.catalogs();mid=next(p for p in catalogs if p['pool_id']=='STARTUP_TECHNIQUE')['files'][0]['material_id']
        slots=tuple(replace(s,selection_policy='FIXED',fixed_material_id=mid) for s in self.draft.slots[:2])
        result=preview(self.actor,replace(self.draft,slots=slots),catalogs,NOW)
        self.assertEqual(result['total_suggestions'],0)

    def prepare_repair(self):
        with patch('production_materials.config.settings',return_value=self.config):
            ensure_account(self.service,self.actor,{**self.account,'account_id':'B','provider_account_id':'provider-B'})
        old=self.root/'old_empty';old.mkdir()
        with self.shadows.connect() as db:
            for key in ('OLD_HAND','OLD_TAIL'):db.execute('INSERT INTO composition_material_pools VALUES(?,?,?,?)',('A',key,key,str(old)))
        draft=replace(self.draft,slots=tuple(replace(s,material_pool='OLD_HAND' if s.module_type=='手法' else 'OLD_TAIL') for s in self.draft.slots))
        self.builder.preview_draft(self.actor,draft,NOW)
        mapping={s.slot_position:'STARTUP_TECHNIQUE' if s.module_type=='手法' else 'STARTUP_CLOSE' for s in draft.slots}
        return draft,mapping

    def test_repair_keeps_draft_all_other_fields_and_other_account_unchanged(self):
        draft,mapping=self.prepare_repair()
        with self.shadows.connect(readonly=True) as db:
            before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t+' WHERE '+('business_account_id' if t=='shadow_profiles' else 'account_id')+"='B'")]
                    for t in ('shadow_profiles','composition_material_pools','composition_catalog_cache','composition_template_states')}
        receipt=self.builder.rebind_unconfirmed_pools(self.actor,'A',mapping,self.registry,NOW)
        self.assertEqual(receipt['result']['daily_counts'],[5]*7)
        restored=self.builder.latest_draft(self.actor,'A')['draft']
        for original,actual in zip(json.loads(json.dumps(asdict(draft)))['slots'],restored['slots']):
            self.assertEqual({k:v for k,v in original.items() if k!='material_pool'},
                             {k:v for k,v in actual.items() if k!='material_pool'})
        self.assertEqual(self.builder.state(self.actor,'A')['status'],'UNCONFIRMED_DEFAULT')
        self.assertFalse(self.shadows.load(self.actor,'A')[1].enabled)
        with self.shadows.connect(readonly=True) as db:
            for t,rows in before.items():
                self.assertEqual(rows,[tuple(r) for r in db.execute('SELECT * FROM '+t+' WHERE '+('business_account_id' if t=='shadow_profiles' else 'account_id')+"='B'")])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM composition_template_versions').fetchone()[0],0)

    def test_live_editor_applies_only_pool_repair_preserving_unsaved_edits(self):
        from streamlit.testing.v1 import AppTest
        draft,mapping=self.prepare_repair();self.builder.rebind_unconfirmed_pools(self.actor,'A',mapping,self.registry,NOW)
        script='\n'.join(['import streamlit as st','from startup_autopilot.models import Actor',
            'from startup_autopilot.shadow_store import ShadowStore','from startup_autopilot.template_store import TemplateBuilderStore',
            'from startup_autopilot.template_ui import render_editor',f'builder=TemplateBuilderStore(ShadowStore({str(self.shadows.path)!r}))',
            "actor=Actor('STUDIO_CONSOLE',frozenset({'A'}))","render_editor(st,builder,actor,'A',catalogs=builder.catalog.refresh(actor,'A'))"])
        app=AppTest.from_string(script,default_timeout=20)
        rows=asdict(draft)['slots'];rows[0]['exploration_ratio']=.55
        app.session_state['composition:A:draft']=rows
        app.session_state['composition:A:count']=4
        app.run();self.assertFalse(app.exception)
        actual=app.session_state['composition:A:draft']
        self.assertEqual(actual[0]['exploration_ratio'],.55)
        self.assertEqual([s['material_pool'] for s in actual],[mapping[s['slot_position']] for s in rows])


if __name__=='__main__':unittest.main()
