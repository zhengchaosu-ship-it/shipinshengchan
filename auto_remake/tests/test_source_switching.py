import unittest
from auto_remake.source_switching import windows,ranked_votes
from auto_remake.source_graph import compatible,fill_unknown,union_length,annotate_unknown


class SourceSwitchingTests(unittest.TestCase):
    def test_unexplained_windows_do_not_include_anchored_prefix(self):
        rows=windows(8.24,27.433333)
        self.assertEqual(len(rows),7)
        self.assertEqual(rows[0]['reference_start'],8.24)
        self.assertEqual(rows[-1]['reference_end'],27.433333)
        self.assertTrue(all(3<=r['reference_end']-r['reference_start']<=5.001 for r in rows))

    def test_one_vote_per_asset_per_query(self):
        items=[dict(query_id='q1',hits=[dict(asset_id='a',rank=1),dict(asset_id='a',rank=2),dict(asset_id='b',rank=3)])]
        rows=ranked_votes(items,'hits','rank')
        self.assertEqual(rows[0]['votes'],1)
        self.assertEqual(rows[0]['evidence'][0]['rank'],1)

    def test_backward_source_allowed_only_as_separate_node(self):
        a=dict(asset_id='a',reference_start=0,reference_end=8.24,source_start=7105.83,source_end=7114.03,status='ANCHORED')
        b=dict(asset_id='a',reference_start=11.4,reference_end=14.12,source_start=6565.71,source_end=6568.41,status='LOCALIZED')
        self.assertFalse(compatible(a,b))
        graph=fill_unknown([a,b],0,20)
        self.assertEqual([r['status'] for r in graph],['ANCHORED','UNRESOLVED','LOCALIZED','UNRESOLVED'])
        self.assertEqual(graph[0],a)

    def test_forward_deleted_source_is_not_one_continuous_clip(self):
        a=dict(asset_id='a',reference_start=11.4,reference_end=14.12,source_start=6565.7,source_end=6568.4)
        b=dict(asset_id='a',reference_start=14.12,reference_end=17.04,source_start=6571.7,source_end=6574.4)
        self.assertFalse(compatible(a,b))
        b.update(source_start=6568.42,source_end=6571.34)
        self.assertTrue(compatible(a,b))

    def test_overlapping_windows_do_not_inflate_coverage(self):
        self.assertAlmostEqual(union_length([(0,4.44),(4.92,8.24),(11.4,14.12),(12,13)]),10.48)

    def test_unknown_candidates_do_not_become_trusted_source(self):
        node=dict(reference_start=8.,reference_end=20.,status='UNRESOLVED',asset_id=None,video_id=None,source_start=None,source_end=None,evidence={})
        ev=dict(reference_start=10.,reference_end=12.,asset_id='a',video_id=1,source_start=100.,source_end=102.,score=.8,
            anchor=dict(anchor_id='chunk',individually_supported=True),half_checks_passed=False,internal_trajectory_consistent=False,corroborated=True)
        result=annotate_unknown([node],[ev])
        self.assertEqual(len(result),3)
        self.assertIsNone(result[1]['asset_id']);self.assertIsNone(result[1]['source_start'])
        self.assertEqual(result[1]['candidate_hypothesis']['source_start'],100.)


if __name__=='__main__':unittest.main()
