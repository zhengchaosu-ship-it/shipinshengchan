"""不读取正式索引的顺序约束与拒绝强行HIGH测试。"""
import unittest

from auto_remake.asset_local import visual_peaks
from auto_remake.sequence_alignment import (align_layers,transition,time_bands,quality,choose_anchors,union_seconds,decide,sequence_shape)
from auto_remake.speech_matcher import speech_queries
import numpy as np


def node(ref,source,q=1):return dict(reference_time=ref,source_time=source,quality=q)
def layer(i,candidates,weight=1):return dict(query_id=f'q{i}',reference_time=i,weight=weight,candidates=candidates)


class AlignmentTests(unittest.TestCase):
    def test_small_repeats_cannot_accumulate_large_backtracking(self):
        nodes=[dict(node(i*3,100-i),modality='speech') for i in range(4)]
        shape=sequence_shape(nodes,[transition(a,b) for a,b in zip(nodes,nodes[1:])],10)
        self.assertEqual(shape['large_backward_steps'],0)
        self.assertEqual(shape['maximum_cumulative_backtrack_seconds'],3)
        self.assertEqual(shape['sequence_consistency'],'LOW')

    def test_backward_cost_exceeds_forward(self):
        a=node(0,100)
        self.assertGreater(transition(a,node(10,0))['penalty'],transition(a,node(10,200))['penalty']*5)

    def test_forward_jump_allowed_and_not_forced_one_x(self):
        result=align_layers([layer(0,[node(0,100)]),layer(10,[node(10,125)]),layer(20,[node(20,139)])])
        self.assertEqual([n['source_time'] for n in result['aligned_nodes']],[100,125,139])
        self.assertEqual(result['transitions'][0]['kind'],'forward_jump')

    def test_uses_second_peak_instead_of_backward_top1(self):
        result=align_layers([layer(0,[node(0,100)]),layer(10,[node(10,20),node(10,111,.8)]),layer(20,[node(20,123)])])
        self.assertEqual([n['source_time'] for n in result['aligned_nodes']],[100,111,123])

    def test_skip_does_not_reset_time(self):
        result=align_layers([layer(0,[node(0,100)]),layer(10,[]),layer(20,[node(20,0)])])
        self.assertEqual(len(result['aligned_nodes']),1)
        self.assertEqual(len(result['skipped_queries']),2)

    def test_all_weak_evidence_does_not_get_high_score(self):
        result=align_layers([layer(i,[node(i,100+i,0)]) for i in range(5)])
        self.assertLess(result['alignment_score'],.2)

    def test_time_bands_do_not_fill_deleted_minutes(self):
        bands=time_bands(5,[node(0,100),node(10,400)])
        self.assertFalse(any(a<=250<=b for a,b in bands))
        self.assertEqual(len(bands),2)

    def test_quality_separate_modal_scales(self):
        self.assertNotEqual(quality(.65,'speech'),quality(.65,'visual'))
        self.assertEqual(quality(.95,'speech'),1)

    def test_anchor_segments_never_vote_twice(self):
        seg=[dict(segment_id=i,reference_start=i,reference_end=i+1,text='这是一段很长的话术内容') for i in range(4)]
        qs=speech_queries(seg)
        for q in qs:q['reference_time']=(q['reference_start']+q['reference_end'])/2
        anchors=choose_anchors(qs,seg)
        ids=[i for q in anchors for i in q['segment_ids']]
        self.assertEqual(len(ids),len(set(ids)))

    def test_visual_peaks_fold_nearby_keep_distant(self):
        rows=[dict(timestamp=t,frame_id=str(t),frame_number=t,index_id=i) for i,t in enumerate([10,11,20])]
        peaks=visual_peaks(np.array([.8,.9,.7]),rows,20,3)
        self.assertEqual([h['source_time'] for h in peaks],[11,20])

    def test_coverage_union_not_sum(self):
        self.assertEqual(union_seconds([(0,5),(2,7),(10,20)],12),9)

    def test_margin_prevents_high_when_candidates_tied(self):
        support=dict(mean_quality=1,coverage=1,low_regret_fraction=1,severe_regrets=0,selected_nodes=4,timestamp_warnings=0)
        a=dict(alignment_score=.9,speech_support=support,visual_support=support,reference_coverage=1,large_backward_steps=0,sequence_consistency='HIGH')
        result=decide([a,dict(a)])
        self.assertEqual(result['verdict'],'ALIGNMENT_NOT_READY');self.assertEqual(result['reasons'],['margin'])


if __name__=='__main__':unittest.main()
