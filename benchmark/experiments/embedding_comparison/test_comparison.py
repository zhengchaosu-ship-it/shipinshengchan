import unittest
import numpy as np
from benchmark.experiments.embedding_comparison.run_comparison import normalize, top_indices
from benchmark.run import evaluate_case


class ComparisonTests(unittest.TestCase):
    def test_cosine_normalization_and_ranking(self):
        vectors=normalize(np.array([[3.,4.],[0.,2.]],dtype=np.float32))
        np.testing.assert_allclose(np.linalg.norm(vectors,axis=1),[1.,1.])
        self.assertEqual(list(top_indices(np.array([.4,.9,.9]))),[1,2,0])

    def test_invalid_embedding_rejected(self):
        for values in ([[0.,0.]],[[float('nan'),1.]]):
            with self.assertRaises(ValueError):normalize(np.array(values))

    def test_same_multivideo_and_time_rules(self):
        case=dict(id='sample',image='unused',acceptable_video_ids=[14,181],expected_timestamp=100.,time_tolerance_seconds=2.)
        row=evaluate_case(case,[dict(video_id=181,timestamp=103.),dict(video_id=14,timestamp=102.)])
        self.assertTrue(row['video_hits']['1'])
        self.assertFalse(row['timestamp_hits']['1'])
        self.assertTrue(row['timestamp_hits']['5'])


if __name__=='__main__':unittest.main()
