import unittest
import numpy as np
from auto_remake.business_speed import resample_copy,restore_coordinates,speed_pair
from auto_remake.business_benchmark import adapted_functions,verify_freeze


class BusinessSpeedTests(unittest.TestCase):
    def test_ratio_direction_and_original_not_mutated(self):
        source=np.arange(1000,dtype=np.float32);before=source.copy()
        quick=resample_copy(source,1.25);slow=resample_copy(source,.8)
        self.assertLess(len(quick),len(source));self.assertGreater(len(slow),len(source))
        self.assertAlmostEqual(float(quick[100]),125.)
        np.testing.assert_array_equal(source,before)

    def test_one_x_exact_copy(self):
        x=np.array([.1,.5,-.4],np.float32);y=resample_copy(x,1.)
        np.testing.assert_array_equal(x,y);self.assertIsNot(x,y)

    def test_restores_original_pts_not_stretched_seconds(self):
        data=dict(anchors=[dict(peaks=[dict(source_start=2.,source_end=4.,source_midpoint=3.,speed_ratio=1.,sampled_path=[dict(reference_time=2.,source_time=3.)])])])
        result=restore_coordinates(data,1.25,100.)['anchors'][0]['peaks'][0]
        self.assertEqual(result['source_start'],102.5);self.assertEqual(result['source_end'],105.)
        self.assertEqual(result['sampled_path'][0]['source_time'],103.75)
        self.assertEqual(data['anchors'][0]['peaks'][0]['source_start'],2.)

    def test_adjacent_consistent_speed_not_jump(self):
        a=dict(asset_id='a',band_id='b',reference_start=0.,reference_end=3.,reference_midpoint=1.5,source_start=100.,source_end=103.6,source_midpoint=101.8,best_speed_ratio=1.2)
        b=dict(asset_id='a',band_id='b',reference_start=3.,reference_end=6.,reference_midpoint=4.5,source_start=103.6,source_end=107.2,source_midpoint=105.4,best_speed_ratio=1.2)
        self.assertTrue(speed_pair(a,b))
        b['source_midpoint']+=10;self.assertFalse(speed_pair(a,b))

    def test_overlap_cannot_count_as_two_chunks(self):
        a=dict(asset_id='a',band_id='b',reference_start=0.,reference_end=4.,reference_midpoint=2.,source_start=100.,source_end=104.8,source_midpoint=102.4,best_speed_ratio=1.2)
        b=dict(a,reference_start=2.,reference_end=6.,reference_midpoint=4.,source_start=102.4,source_end=107.2,source_midpoint=104.8)
        self.assertFalse(speed_pair(a,b))

    def test_frozen_sources_unchanged_and_adapter_compiles(self):
        verify_freeze();recall,graph=adapted_functions();self.assertTrue(callable(recall));self.assertTrue(callable(graph))


if __name__=='__main__':unittest.main()
