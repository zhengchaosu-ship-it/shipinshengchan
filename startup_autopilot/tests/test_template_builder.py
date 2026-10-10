"""只用临时数据库和少量字节夹具验证Slot配置，绝不调用发布/渲染。"""
from contextlib import closing
from dataclasses import asdict,replace
from pathlib import Path
import json
import sqlite3
import unittest

from startup_autopilot.tests import test_shadow_ui as fixtures
from startup_autopilot.tests.test_foundation import NOW
from startup_autopilot.composition import CompositionSlot,StartupCompositionTemplateVersion,composition_signature,reorder
from startup_autopilot.composition_planner import preview
from startup_autopilot.template_store import TemplateBuilderStore
from startup_autopilot.composition_catalog import pool_id
from startup_autopilot.models import Actor


class TemplateBuilderTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ShadowIntegrationTests();self.fixture.setUp()
        self.actor=self.fixture.actor;self.shadows=self.fixture.shadows;self.account='account-A'
        self.builder=TemplateBuilderStore(self.shadows);self.builder.initialize();self.builder.setup_account(self.actor,self.account)
        self.catalogs=self.builder.catalog.refresh(self.actor,self.account,hash_budget=5)
        pools={Path(p['root']).name:p for p in self.catalogs}
        self.flow=pools['0'];self.hand=pools['1'];self.tail=pools['3']
        self.draft=StartupCompositionTemplateVersion(self.account,0,(
            CompositionSlot('flow','FLOW_1','引流',self.flow['pool_id'],'ROTATING'),
            CompositionSlot('hand1','HAND_1','手法',self.hand['pool_id'],'LEARNABLE'),
            CompositionSlot('hand2','HAND_2','手法',self.hand['pool_id'],'ROTATING'),
            CompositionSlot('tail','TAIL_1','收尾',self.tail['pool_id'],'FIXED',fixed_material_id=self.tail['files'][0]['material_id'])))

    def tearDown(self):self.fixture.tearDown()

    def plan(self,draft=None,**kwargs):return preview(self.actor,draft or self.draft,self.catalogs,NOW,**kwargs)

    def test_old_default_unconfirmed_and_formal_gate(self):
        self.assertEqual(self.builder.state(self.actor,self.account)['status'],'UNCONFIRMED_DEFAULT')
        with self.assertRaises(PermissionError):self.builder.active(self.actor,self.account)
        with self.assertRaises(PermissionError):self.builder.confirmed_shadow(self.actor,self.account,NOW)
        self.assertIsNone(self.shadows.latest(self.actor,self.account))
        with self.assertRaises(PermissionError):self.shadows.save_decision(self.actor,self.account,self.fixture.decision)

    def test_fixed_tail_not_a_global_capacity_bottleneck(self):
        # 此用例只验证固定收尾；双手法另受片内身份约束，不用疲劳预算限制容量。
        draft=replace(self.draft,slots=tuple(replace(s,max_uses_7d=None) if s.module_type=='手法' else s for s in self.draft.slots))
        result=self.plan(draft)
        self.assertEqual(result['total_suggestions'],35)
        self.assertEqual(result['stable_daily_capacity'],5)
        self.assertEqual(result['duplicate_count'],0)
        tails=[p['selections'][-1]['material_id'] for day in result['days'] for p in day['proposals']]
        self.assertEqual(len(set(tails)),1)

    def test_duplicate_hand_slots_never_merge(self):
        result=self.plan(days=1)
        first=result['days'][0]['proposals'][0]
        self.assertEqual([m['slot_position'] for m in first['selections']],['FLOW_1','HAND_1','HAND_2','TAIL_1'])
        self.assertEqual([m['module_type'] for m in first['selections']],['引流','手法','手法','收尾'])

    def test_slot_fatigue_limits_are_independent(self):
        first=replace(self.draft.slots[0],max_uses_7d=1)
        result=self.plan(replace(self.draft,slots=(first,*self.draft.slots[1:])))
        self.assertEqual(result['total_suggestions'],5)
        self.assertIn('FLOW_1',result['bottleneck_slots'])

    def test_rotating_can_allow_same_fragment_across_videos(self):
        result=self.plan()
        used=[p['selections'][0]['material_id'] for d in result['days'] for p in d['proposals']]
        self.assertGreater(len(used),len(set(used)))

    def test_all_fixed_has_only_one_unique_combination(self):
        fixed=tuple(replace(s,selection_policy='FIXED',fixed_material_id=next(p for p in self.catalogs if p['pool_id']==s.material_pool)['files'][1 if s.slot_position=='HAND_2' else 0]['material_id']) for s in self.draft.slots)
        result=self.plan(replace(self.draft,slots=fixed))
        self.assertEqual(result['total_suggestions'],1)

    def test_signature_uses_ordered_actual_material_not_version_names(self):
        result=self.plan(days=1);selections=result['days'][0]['proposals'][0]['selections']
        renamed=[{**s,'slot_position':'NEW_1','module_type':'自定义'} for s in selections]
        self.assertEqual(composition_signature(selections),composition_signature(renamed))
        changed=[*selections[:-1],{**selections[-1],'material_id':'DIFFERENT_CONTENT'}]
        self.assertNotEqual(composition_signature(selections),composition_signature(changed))

    def test_recent_whole_combo_blocks_but_fixed_piece_does_not(self):
        result=self.plan(days=1)
        history=[{'account_id':self.account,'signature':p['composition_signature'],'used_at':NOW.isoformat()} for p in result['days'][0]['proposals']]
        newer=self.plan(days=1,composition_history=history)
        self.assertEqual(newer['total_suggestions'],5)
        self.assertFalse({p['composition_signature'] for p in newer['days'][0]['proposals']} & {r['signature'] for r in history})

    def test_before_twenty_does_not_use_strong_affinity(self):
        slot=self.draft.slots[1];mid=self.hand['files'][0]['material_id']
        affinities=[{'account_id':self.account,'slot_position':slot.slot_position,'material_id':mid,'normalized_score':3,'sample_count':20}]
        result=self.plan(days=1,samples=19,affinities=affinities)
        self.assertTrue(all(p['selections'][1]['selection_branch']=='COLD_BALANCED_EXPLORATION' for p in result['days'][0]['proposals']))
        self.assertEqual(self.plan(days=1,samples=19,affinities=affinities)['days'],self.plan(days=1,samples=19)['days'])

    def test_after_twenty_weights_only_learnable_slot_and_does_not_change_structure(self):
        draft=replace(self.draft,slots=(self.draft.slots[0],replace(self.draft.slots[1],exploration_ratio=0),*self.draft.slots[2:]))
        mid=self.hand['files'][-1]['material_id']
        affinity=[{'account_id':self.account,'slot_position':'HAND_1','material_id':mid,'normalized_score':3,'sample_count':20}]
        result=self.plan(draft,days=1,samples=20,affinities=affinity)
        self.assertEqual(result['days'][0]['proposals'][0]['selections'][1]['material_id'],mid)
        self.assertEqual(result['template_hash'],draft.config_hash())
        self.assertTrue(all(p['selections'][1]['selection_branch']=='ACCOUNT_SLOT_AFFINITY' for p in result['days'][0]['proposals']))

    def test_lock_and_block_apply_only_to_the_account_slot(self):
        mid=self.hand['files'][0]['material_id']
        override=[{'account_id':self.account,'slot_position':'HAND_1','material_id':mid,'override':'LOCK'}]
        result=self.plan(days=1,affinities=override)
        self.assertTrue(all(p['selections'][1]['material_id']==mid for p in result['days'][0]['proposals']))
        blocked=[{**override[0],'override':'BLOCK'}]
        result=self.plan(days=1,affinities=blocked)
        self.assertTrue(all(p['selections'][1]['material_id']!=mid for p in result['days'][0]['proposals']))
        preferred=[{**override[0],'override':'PREFERRED'}]
        result=self.plan(days=1,samples=0,affinities=preferred)
        self.assertEqual(result['days'][0]['proposals'][0]['selections'][1]['material_id'],mid)

    def test_preferred_collection(self):
        mid=self.flow['files'][0]['material_id']
        first=replace(self.draft.slots[0],selection_policy='PREFERRED_POOL',preferred_material_ids=(mid,),preferred_only=True,max_uses_7d=None)
        result=self.plan(replace(self.draft,slots=(first,*self.draft.slots[1:])),days=1)
        self.assertEqual(result['total_suggestions'],5)
        self.assertTrue(all(p['selections'][0]['material_id']==mid for p in result['days'][0]['proposals']))

    def test_other_accounts_cannot_supply_learning_history(self):
        with self.assertRaises(PermissionError):self.plan(affinities=[{'account_id':'BINGYAO'}])
        with self.assertRaises(PermissionError):self.plan(material_history=[{'account_id':'BINGYAO'}])
        with self.assertRaises(PermissionError):
            preview(self.actor,self.draft,[{**p,'account_id':'BINGYAO'} for p in self.catalogs],NOW)

    def test_unused_pool_changes_do_not_override_selected_template(self):
        receipt=self.builder.preview_draft(self.actor,self.draft,NOW)
        unused=next(p for p in self.catalogs if Path(p['root']).name=='2')
        (Path(unused['root'])/'unrelated.mp4').write_bytes(b'new synthetic unrelated material')
        version=self.builder.confirm(self.actor,self.draft,receipt['token'])
        self.assertEqual(version.version,1)

    def test_preview_then_human_save_version_one_stays_disabled(self):
        self.draft=replace(self.draft,slots=tuple(replace(s,max_uses_7d=None) if s.module_type=='手法' else s for s in self.draft.slots))
        receipt=self.builder.preview_draft(self.actor,self.draft,NOW)
        self.assertIsNone(self.builder.state(self.actor,self.account)['active_version'])
        v1=self.builder.confirm(self.actor,self.draft,receipt['token'])
        self.assertEqual(v1.version,1);self.assertEqual(v1.confirmed_by,self.actor.employee_id)
        self.assertFalse(self.shadows.load(self.actor,self.account)[1].enabled)
        result=self.builder.confirmed_shadow(self.actor,self.account,NOW)
        self.assertEqual(result['template_version'],1)
        self.assertEqual(result['total_suggestions'],35)

    def test_cannot_save_without_preview_or_after_edit(self):
        with self.assertRaises(PermissionError):self.builder.confirm(self.actor,self.draft,'no-preview')
        receipt=self.builder.preview_draft(self.actor,self.draft,NOW)
        changed=replace(self.draft,slots=tuple(reversed(self.draft.slots)))
        with self.assertRaises(PermissionError):self.builder.confirm(self.actor,changed,receipt['token'])

    def test_versions_append_only_and_same_receipt_idempotent(self):
        receipt=self.builder.preview_draft(self.actor,self.draft,NOW)
        v1=self.builder.confirm(self.actor,self.draft,receipt['token'])
        self.assertEqual(self.builder.confirm(self.actor,self.draft,receipt['token']).version,1)
        changed=replace(self.draft,slots=(replace(self.draft.slots[0],max_uses_7d=8),*self.draft.slots[1:]))
        r2=self.builder.preview_draft(self.actor,changed,NOW)
        v2=self.builder.confirm(self.actor,changed,r2['token']);self.assertEqual(v2.version,2)
        with self.shadows.connect(readonly=True) as db:
            original=json.loads(db.execute('SELECT payload_json FROM composition_template_versions WHERE version=1').fetchone()[0])
            self.assertEqual(original['slots'][0]['max_uses_7d'],7)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.shadows.connect() as db:db.execute('UPDATE composition_template_versions SET version=99')

    def test_concurrent_version_preview_cannot_overwrite(self):
        a=self.builder.preview_draft(self.actor,self.draft,NOW)
        b=self.builder.preview_draft(self.actor,self.draft,NOW)
        self.builder.confirm(self.actor,self.draft,a['token'])
        with self.assertRaises(PermissionError):self.builder.confirm(self.actor,self.draft,b['token'])

    def test_new_file_auto_catalog_refresh_hash_and_copy_dedup(self):
        folder=Path(self.tail['root'])
        (folder/'new.mp4').write_bytes(b'new small synthetic content')
        (folder/'copy.mp4').write_bytes(b'new small synthetic content')
        fresh=self.builder.catalog.refresh(self.actor,self.account,hash_budget=0)
        tail=next(p for p in fresh if p['pool_id']==self.tail['pool_id'])
        self.assertEqual(tail['pending_hash_count'],2)
        fresh=self.builder.catalog.refresh(self.actor,self.account,hash_budget=5)
        tail=next(p for p in fresh if p['pool_id']==self.tail['pool_id'])
        self.assertEqual(tail['verified_unique_count'],2)

    def test_pool_changed_after_preview_requires_repreview(self):
        receipt=self.builder.preview_draft(self.actor,self.draft,NOW)
        (Path(self.flow['root'])/'another.mp4').write_bytes(b'new small synthetic')
        with self.assertRaises(PermissionError):self.builder.confirm(self.actor,self.draft,receipt['token'])

    def test_slot_reorder_preserves_duplicate_type_ids(self):
        rows=[asdict(s) for s in self.draft.slots]
        result=reorder(rows,['flow','hand2','hand1','tail'])
        self.assertEqual([s['slot_position'] for s in result],['FLOW_1','HAND_2','HAND_1','TAIL_1'])
        with self.assertRaises(ValueError):reorder(rows,['flow','flow','hand1','tail'])

    def test_no_existing_plan_job_or_provider_effect(self):
        result=self.plan()
        self.assertEqual(self.fixture.store.jobs(self.fixture.fixture.token),[])
        for key in ('render_jobs_created','publish_jobs_created','provider_tasks_created','upload_count','publish_count'):self.assertEqual(result[key],0)

    def test_new_slot_cannot_reuse_retired_slot_affinity_identity(self):
        receipt=self.builder.preview_draft(self.actor,self.draft,NOW)
        self.builder.confirm(self.actor,self.draft,receipt['token'])
        changed=replace(self.draft,slots=(self.draft.slots[0],replace(self.draft.slots[1],slot_id='another-hand'),*self.draft.slots[2:]))
        receipt=self.builder.preview_draft(self.actor,changed,NOW)
        with self.assertRaises(PermissionError):self.builder.confirm(self.actor,changed,receipt['token'])

    def test_scheduled_queue_evidence_does_not_increment_valid_samples(self):
        with self.shadows.connect() as db:
            db.execute('INSERT INTO composition_public_samples VALUES(?,?,?,?)',
                (self.account,'QUEUED',NOW.isoformat(),json.dumps({'provider_state':'success','platform_state':'SCHEDULED_QUEUED'})))
            db.execute('INSERT INTO composition_public_samples VALUES(?,?,?,?)',
                (self.account,'VISIBLE',NOW.isoformat(),json.dumps({'work_id':'VISIBLE','public_visibility_confirmed':True})))
        self.assertEqual(self.builder.context(self.actor,self.account)[0],1)

    def test_other_owner_cannot_preview_confirm_or_register_pool(self):
        other=Actor('another-owner',frozenset({self.account}))
        with self.assertRaises(PermissionError):self.builder.preview_draft(other,self.draft,NOW)
        receipt=self.builder.preview_draft(self.actor,self.draft,NOW)
        with self.assertRaises(PermissionError):self.builder.confirm(other,self.draft,receipt['token'])
        with self.assertRaises(PermissionError):self.builder.catalog.register(other,self.account,'wrong-owner',self.flow['root'])

    def test_fixed_blocked_is_not_silently_replaced(self):
        mid=self.tail['files'][0]['material_id']
        result=self.plan(affinities=[{'account_id':self.account,'slot_position':'TAIL_1','material_id':mid,'override':'BLOCK'}])
        self.assertEqual(result['total_suggestions'],0)
        self.assertIn('TAIL_1',result['bottleneck_slots'])

    def test_affinity_same_material_separates_hand_one_and_two(self):
        from startup_autopilot.tests import test_foundation as metrics_fixture
        from startup_autopilot.slot_affinity import build_slot_affinities
        maker=metrics_fixture.MetricsTests()
        base=maker.sample('BASE',account=self.account,views=100,observed='2026-10-03T09:00:00+08:00',full=True)
        first=maker.sample('ONE',account=self.account,views=200,observed='2026-10-03T10:00:00+08:00',full=True)
        second=maker.sample('TWO',account=self.account,views=50,observed='2026-10-03T11:00:00+08:00',full=True)
        rows=build_slot_affinities(self.actor,self.account,[base,first,second],{
            'ONE':[{'material_id':'M','module_type':'手法','slot_position':'HAND_1'}],
            'TWO':[{'material_id':'M','module_type':'手法','slot_position':'HAND_2'}]},[],NOW)
        self.assertEqual({r['slot_position'] for r in rows},{'HAND_1','HAND_2'})
        self.assertEqual(len(rows),2)
        self.assertNotEqual(rows[0]['normalized_score'],rows[1]['normalized_score'])


if __name__=='__main__':unittest.main()
