"""合成证据测试；不加载模型、FAISS或素材视频。"""
from copy import deepcopy
import unittest
from unittest.mock import Mock

from auto_remake.aggregation import aggregate_shot
from auto_remake.multimodal_evidence import fuse,trajectory,independent,overlap
from auto_remake.speech_matcher import SpeechMatcher,speech_queries,information_level


def query(n=1,start=0,end=3,asset='A',source=100,segments=None):
    hit=dict(asset_id=asset,video_id=1,source_video_id=1,file_name='source.ts',file_path='source.ts',
        source_start=source,source_end=source+end-start,matched_text='这是一段完整而且具有信息量的话术',semantic_score=.8,
        timestamp_warning=False,semantic_rank=1,window_id=n,first_segment_id=n,last_segment_id=n,context_before='',context_after='')
    return dict(query_id=f'q{n}',segment_ids=segments or [n],window_size=len(segments or [n]),reference_start=start,reference_end=end,
        text='这是一段完整而且具有信息量的话术',normalized_text='这是一段完整而且具有信息量的话术',speech_information_level='HIGH',eligible=True,matches=[hit])


def shot(n=1,start=0,end=3,asset='A',source_offset=100):
    frames=[];results=[]
    for i,fraction in enumerate((.15,.5,.85)):
        t=start+(end-start)*fraction
        frames.append(dict(frame_index=n*10+i,timestamp=t,image_path='x.jpg'))
        results.append(dict(query_frame_index=n*10+i,query_timestamp=t,query_image_path='x.jpg',
            hits=[dict(asset_id=asset,video_id=1,file_name='source.ts',file_path='source.ts',timestamp=source_offset+t,similarity=.8,rank=1)]))
    s=dict(shot_id=n,start=start,end=end,duration=end-start,query_frames=frames,frame_results=results)
    s['matches']=aggregate_shot(s,results)
    return s


class MultimodalTests(unittest.TestCase):
    def test_empty_candidates_remain_reviewable(self):
        s=dict(shot_id=1,start=0,end=3,query_frames=[],frame_results=[],matches=[])
        result=fuse(dict(shots=[s]),dict(queries=[]))
        self.assertIsNone(result['shots'][0]['selected_match'])
        self.assertFalse(result['shots'][0]['modality_top1']['top1_same_asset'])
        self.assertEqual(result['source_sequences'],[])

    def test_information_and_windows(self):
        self.assertEqual(information_level('嗯，对，好，来'),'LOW')
        self.assertEqual(information_level('这是一段足够长且包含否定的完整话术'),'HIGH')
        segments=[dict(segment_id=i,reference_start=i,reference_end=i+1,text='这是一段完整的话术') for i in range(4)]
        queries=speech_queries(segments)
        self.assertEqual([sum(q['window_size']==n for q in queries) for n in (1,2,3)],[4,3,2])
        segments[2]['reference_start']=20;segments[2]['reference_end']=21
        self.assertFalse(any(q['segment_ids']==[1,2] for q in speech_queries(segments)))

    def test_matcher_only_formal_semantic_top20(self):
        backend=Mock();backend.search.return_value=dict(results=[],timings={})
        queries=[query()];SpeechMatcher(backend).search_queries(queries)
        backend.search.assert_called_once_with(queries[0]['text'],top_k=20,mode='semantic')
        backend.reset_mock();queries[0]['eligible']=False
        SpeechMatcher(backend).search_queries(queries);backend.search.assert_not_called()

    def test_two_modalities_and_time_agreement(self):
        result=fuse(dict(shots=[shot()]),dict(queries=[query()]))
        s=result['shots'][0]['selected_match']
        self.assertEqual(s['confidence'],'HIGH_CONFIDENCE')
        self.assertEqual(s['source_start_estimate'],100)
        self.assertEqual(s['source_end_estimate'],103)
        self.assertFalse(s['is_ground_truth'])

    def test_same_asset_distant_times_require_review(self):
        result=fuse(dict(shots=[shot()]),dict(queries=[query(source=1000)]))
        s=result['shots'][0]['selected_match']
        self.assertEqual(s['confidence'],'NEEDS_REVIEW')
        self.assertTrue(s['conflicts']['same_asset_source_time_conflict'])

    def test_visual_only_cannot_be_high(self):
        s=fuse(dict(shots=[shot()]),dict(queries=[]))['shots'][0]
        self.assertEqual(s['selected_match']['confidence'],'NEEDS_REVIEW')

    def test_cross_asset_conflict_and_warning(self):
        result=fuse(dict(shots=[shot()]),dict(queries=[query(asset='B')]))
        self.assertEqual(result['shots'][0]['selected_match']['confidence'],'NEEDS_REVIEW')
        q=query();q['matches'][0]['timestamp_warning']=True
        result=fuse(dict(shots=[shot()]),dict(queries=[q]))
        self.assertNotEqual(result['shots'][0]['selected_match']['confidence'],'HIGH_CONFIDENCE')

    def test_speech_crosses_shot_boundary(self):
        q=query(start=1,end=5)
        r=fuse(dict(shots=[shot(1,0,3),shot(2,3,6)]),dict(queries=[q]))
        self.assertTrue(all(s['overlapping_speech_queries']==['q1'] for s in r['shots']))
        self.assertEqual(r['source_sequences'],[])  # 同一句跨镜不能伪造两个独立时间锚点。

    def test_correlated_windows_not_independent(self):
        from auto_remake.multimodal_evidence import flattened
        q1=query(1,segments=[1]);q2=query(2,segments=[1,2]);q3=query(3,segments=[1,2,3])
        self.assertEqual(len(independent(flattened([q1,q2,q3]))),1)

    def test_speed_and_reverse_trajectory(self):
        from auto_remake.multimodal_evidence import flattened
        rows=flattened([query(1,0,2,source=100),query(2,5,7,source=107),query(3,10,12,source=114)])
        self.assertEqual(trajectory(rows)['level'],'HIGH')
        rows[2]['source_midpoint']=90
        self.assertEqual(trajectory(rows)['level'],'LOW')
        self.assertTrue(trajectory(rows)['reversed'])

    def test_observed_sequence_not_projected_only(self):
        r=fuse(dict(shots=[shot(1,0,3),shot(2,3,6),shot(3,6,9)]),
               dict(queries=[query(1,0,3,source=100),query(2,3,6,source=103),query(3,6,9,source=106)]))
        self.assertEqual(len(r['source_sequences']),1)
        self.assertTrue(r['source_sequences'][0]['verified_by_both_modalities'])
