import unittest
from unittest.mock import patch

from content_pool.build import construct
from content_pool.classify import classify, disambiguate
from content_pool.schema import ContentSegment


def sample(text):
    return ContentSegment('s', 'a', 1, 'v.mp4', 'v.mp4', 0, 6, 6, text)


class ContentTests(unittest.TestCase):
    def test_product_context(self):
        role, _, _ = disambiguate('这个小妙招大家都可以学', '课程里面会教大家', '')
        self.assertEqual(role, 'PRODUCT_XIAOMIAOZHAO')

    def test_tip(self):
        self.assertEqual(disambiguate('今天教大家一个小妙招，你按住这里往上推三次')[0], 'TIP_GENERIC')

    def test_product_overrides_action(self):
        self.assertEqual(disambiguate('小妙招，按住这里', '', '想学的可以购买课程')[0], 'PRODUCT_XIAOMIAOZHAO')

    def test_prior_and_ambiguous(self):
        self.assertEqual(disambiguate('这个小妙招大家都可以学')[0], 'PRODUCT_LIKELY')
        self.assertEqual(disambiguate('这个小妙招不是课程')[0], 'AMBIGUOUS')

    def test_product_tags(self):
        s = classify(sample('这些方法我们小妙招课程里面都会教，学完自己就会判断'))
        self.assertIn('PRODUCT_BRIDGE', s.function_tags)
        self.assertIn('PRODUCT_INTRO', s.function_tags)

    def test_second_product_config(self):
        with patch('content_pool.classify.PRODUCTS', [dict(id='another', name='基础课', aliases=['基础课'], default_prior='PRODUCT')]):
            s = classify(sample('基础课里面会教大家这些方法，学完自己能判断'))
            self.assertEqual(s.product_entities[0]['id'], 'another')
            self.assertIn('PRODUCT_INTRO', s.function_tags)

    def test_call_question_not_proof(self):
        s = classify(sample('你现在还疼不疼，你试一下'))
        self.assertIn('CALL_RESULT', s.function_tags)
        self.assertNotIn('PROOF', s.function_tags)
        self.assertNotIn('PROOF', classify(sample('你现在是不是好多了')).function_tags)
        self.assertNotIn('PROOF', classify(sample('老师，如果这样按就不疼了')).function_tags)
        self.assertIn('PROOF', classify(sample('老师，现在不疼了，轻松了好多')).function_tags)
        self.assertNotIn('CALL_RESULT', classify(sample('老师，我的腰还是痛，没有效果')).function_tags)

    def test_merge_and_filter(self):
        seed = dict(asset_id='a',video_id=1,file_name='v',file_path='v', first_segment_id=1,
                    last_segment_id=1, window_id=1,semantic_score=.7)
        rows = [dict(id=1,video_id=1,start=0.,end=1.,text='腰疼'),
                dict(id=2,video_id=1,start=1.,end=5.,text='因为这里肌肉受力不平衡')]
        s = construct(seed, rows)
        self.assertEqual(s.duration, 5)
        self.assertEqual(s.recommend_metadata['source_subtitle_ids'], [1, 2])
        rows[0]['text'], rows[1]['text'] = '嗯', '对'
        self.assertIsNone(construct(seed, rows))

    def test_no_cross_gap_run_or_invalid_time(self):
        seed = dict(asset_id='a',video_id=1,file_name='v',file_path='v', first_segment_id=1,
                    last_segment_id=2, window_id=1,semantic_score=.7)
        rows = [dict(id=1,video_id=1,start=0.,end=1.,text='腰疼'),
                dict(id=2,video_id=1,start=8.,end=12.,text='因为这里肌肉受力不平衡')]
        self.assertIsNone(construct(seed, rows))
        rows[1].update(start=1., run_id=2)
        self.assertIsNone(construct(seed, rows))


if __name__ == '__main__':
    unittest.main()
