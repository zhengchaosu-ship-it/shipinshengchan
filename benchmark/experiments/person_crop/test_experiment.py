import unittest
from benchmark.experiments.person_crop.run_experiment import expanded_box, scores, ranked


class ExperimentTests(unittest.TestCase):
    def test_crop_clips_to_image(self):
        self.assertEqual(expanded_box([0, 0, 20, 20], 40, 60), [0, 0, 40, 60])

    def test_fallback_and_fixed_fusion(self):
        self.assertEqual(scores(.4, None), dict(A=.4, B=.4, C=.4))
        self.assertAlmostEqual(scores(.4, .8)['C'], .6)

    def test_rank_methods_and_tie_break(self):
        rows = [dict(faiss_rank=2,scores=scores(.5,.9)),dict(faiss_rank=1,scores=scores(.7,.9))]
        self.assertEqual(ranked(rows,'B')[0]['faiss_rank'],1)
        self.assertEqual(ranked(rows,'A')[0]['faiss_rank'],1)


if __name__ == '__main__':
    unittest.main()
