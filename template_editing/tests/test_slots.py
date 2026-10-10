import unittest
from content_pool.classify import classify
from content_pool.schema import ContentSegment
from template_editing.models import evaluate_transition, load_template
from template_editing.slot_matcher import match


class SlotTests(unittest.TestCase):
    def row(self, text):
        s = ContentSegment('s','a',1,'v','v',0,6,6,text)
        s.recommend_metadata['semantic_score'] = .8
        return classify(s)

    def test_all_slots(self):
        texts = ['你的腰疼其实不是腰的问题', '腰疼是因为肌肉受力不平衡',
                 '这些问题自己也可以判断，小妙招课程里面都会教', '小妙招课程教大家如何判断，学完自己会做',
                 '老师现在不疼了，舒服多了', '想学的赶紧去拍小妙招',
                 '老师现在不疼了，舒服多了', '最后想学的赶紧去拍小妙招']
        for slot, text in zip(load_template()['slots'], texts):
            with self.subTest(slot=slot['type']):
                self.assertTrue(match(self.row(text), slot)['eligible'])

    def test_tip_not_product(self):
        s = self.row('教大家一个小妙招，按住这里往上推三次')
        for slot in load_template()['slots'][2:4]:
            self.assertFalse(match(s, slot)['eligible'])

    def test_transition_reserved(self):
        self.assertIsNone(evaluate_transition(self.row('腰疼'), self.row('肩膀疼')))


if __name__ == '__main__':
    unittest.main()
