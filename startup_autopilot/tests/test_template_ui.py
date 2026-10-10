"""用户首次配置、双手法预览、结构修改重新预览与保存的Streamlit隔离验收。"""
import unittest
from startup_autopilot.tests import test_template_builder as fixtures


class TemplateInterfaceTests(unittest.TestCase):
    def setUp(self):self.fixture=fixtures.TemplateBuilderTests();self.fixture.setUp()
    def tearDown(self):self.fixture.tearDown()
    def app(self):return self.fixture.fixture.app()
    def button(self,app,label):return next(b for b in app.button if b.label==label)

    def configure(self):
        app=self.app()
        next(n for n in app.number_input if n.label=='视频一共几段').set_value(4).run()
        for index,kind in enumerate(('引流','手法','手法','收尾')):
            [s for s in app.selectbox if s.label=='模块类型'][index].set_value(kind)
            [s for s in app.selectbox if s.label=='素材池'][index].set_value(
                (self.fixture.flow if index==0 else self.fixture.tail if index==3 else self.fixture.hand)['pool_id'])
            [s for s in app.selectbox if s.label=='素材选择策略'][index].set_value(('ROTATING','LEARNABLE','ROTATING','FIXED')[index])
        app.run();self.assertFalse(app.exception)
        next(s for s in app.selectbox if s.label=='固定素材').set_value(self.fixture.tail['files'][0]['material_id']).run()
        self.assertFalse(app.exception)
        return app

    def test_initial_editor_is_empty_not_inferred_from_nickname(self):
        app=self.app()
        self.assertTrue(any('先设置这个账号的视频模板' in x.value for x in app.info))
        self.assertEqual(next(n for n in app.number_input if n.label=='视频一共几段').value,0)
        self.assertTrue(self.button(app,'保存模板').disabled)
        self.assertTrue(self.button(app,'预览未来5条').disabled)

    def test_add_delete_and_keyboard_order_controls(self):
        app=self.app();self.button(app,'增加一段').click().run()
        self.assertEqual(next(n for n in app.number_input if n.label=='视频一共几段').value,1)
        self.button(app,'增加一段').click().run()
        self.assertEqual(len([b for b in app.button if b.label=='删除']),2)
        [b for b in app.button if b.label=='上移'][1].click().run();self.assertFalse(app.exception)
        self.button(app,'删除').click().run()
        self.assertEqual(next(n for n in app.number_input if n.label=='视频一共几段').value,1)

    def test_preview_five_contains_two_hand_columns_and_no_commit(self):
        app=self.configure();self.button(app,'预览未来5条').click().run()
        self.assertFalse(app.exception)
        table=next(d.value for d in app.dataframe if '视频' in d.value.columns)
        self.assertEqual(len(table),5)
        self.assertIn('手法1',table.columns);self.assertIn('手法2',table.columns)
        self.assertFalse(self.button(app,'保存模板').disabled)
        self.assertIsNone(self.fixture.builder.state(self.fixture.actor,self.fixture.account)['active_version'])
        self.assertEqual(self.fixture.fixture.store.jobs(self.fixture.fixture.fixture.token),[])

    def test_reorder_requires_new_preview_before_save_and_preserves_slot_ids(self):
        app=self.configure();self.button(app,'预览未来5条').click().run()
        [b for b in app.button if b.label=='上移'][2].click().run()
        self.assertFalse(app.exception);self.assertTrue(self.button(app,'保存模板').disabled)
        self.button(app,'预览未来5条').click().run()
        self.button(app,'保存模板').click().run()
        self.assertFalse(app.exception)
        active=self.fixture.builder.active(self.fixture.actor,self.fixture.account)
        self.assertEqual([s.slot_position for s in active.slots],['FLOW_1','HAND_2','HAND_1','TAIL_1'])
        self.assertEqual(active.version,1)
        self.assertFalse(self.fixture.shadows.load(self.fixture.actor,self.fixture.account)[1].enabled)

    def test_slot_specific_caps_affect_capacity_not_fixed_tail(self):
        app=self.configure()
        limits=[n for n in app.number_input if n.label=='7天最多使用次数（0为不限）']
        limits[0].set_value(1).run()
        self.button(app,'预览未来5条').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any('7天5条' in x.value for x in app.info))


if __name__=='__main__':unittest.main()
