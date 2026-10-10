import ast
from pathlib import Path
import unittest
from benchmark.experiments.topk_recall.run_experiment import top_results, compile_top500, ROOT


class TopKTests(unittest.TestCase):
    def test_stable_ties_and_filtered_candidates(self):
        raw=[dict(file_path='a',timestamp=1,sim_mobi=.5),dict(file_path='b',timestamp=2,sim_mobi=.4),dict(file_path='c',timestamp=3,sim_mobi=.3)]
        scored=[dict(raw[1],similarity=.8),dict(raw[0],similarity=.8)]
        self.assertEqual([r['file_path'] for r in top_results(raw,scored)],['a','b'])
        self.assertEqual(top_results(raw[2:],scored),[])

    def test_only_candidate_count_differs(self):
        source=(ROOT/'video_search.py').read_text(encoding='utf-8-sig')
        space=compile_top500({},source)
        self.assertIn('search_similar_frames',space)
        fn=space['search_similar_frames']
        self.assertIn(500,fn.__code__.co_consts)
        self.assertEqual(fn.__defaults__,(20,))


if __name__ == '__main__':
    unittest.main()
