import unittest
import numpy as np

from auto_remake.transcript_alignment import local_score,align_sequence
from auto_remake.audio_alignment import acoustic_peaks,features,consistent_audio_chain


def ref(texts):return [dict(ref_segment_id=i+1,reference_start=i*3.,reference_end=i*3+2.,text=t,normalized_text=t,duration=2.,information_level='HIGH') for i,t in enumerate(texts)]
def source(texts):return [dict(source_segment_id=i+1,source_start=100+i*3.,source_end=102+i*3.,text=t,normalized_text=t) for i,t in enumerate(texts)]


class LocalizationTests(unittest.TestCase):
    def test_negative_not_equal_positive(self):
        self.assertLess(local_score('不是腰的问题','是腰的问题')['score'],.56)
        self.assertLess(local_score('不疼','疼')['score'],.56)
        self.assertEqual(local_score('不是腰的问题','不是腰的问题')['score'],1)

    def test_one_to_two_and_two_to_one(self):
        r=align_sequence(ref(['你这个位置疼其实不是腰的问题']),source(['你这个位置疼','其实不是腰的问题']),3,1)[0]
        self.assertEqual(r['alignment_path'][0]['merge'],[1,2])
        r=align_sequence(ref(['你这个位置疼','其实不是腰的问题']),source(['你这个位置疼其实不是腰的问题']),6,1)[0]
        self.assertEqual(r['alignment_path'][0]['merge'],[2,1])

    def test_reversed_transcript_cannot_match_whole(self):
        texts=['首先抬起你的右手看看','然后慢慢转动左边肩膀','最后用力向前伸展身体']
        r=align_sequence(ref(texts),source(list(reversed(texts))),9,1)[0]
        self.assertLess(r['reference_segments_matched'],3)
        self.assertTrue(r['ordered'])

    def test_source_gap_and_reference_missed_sentence(self):
        texts=['首先抬起你的右手看看','然后慢慢转动左边肩膀','最后用力向前伸展身体']
        r=align_sequence(ref(texts),source([texts[0],'这句话被二创删掉了',texts[1],texts[2]]),9,1)[0]
        self.assertEqual(r['reference_segments_matched'],3)

    def test_dtw_locates_shifted_features(self):
        rng=np.random.default_rng(42);q=rng.normal(size=(70,40)).astype('float32');q/=np.linalg.norm(q,axis=1,keepdims=True)
        s=rng.normal(size=(300,40)).astype('float32');s/=np.linalg.norm(s,axis=1,keepdims=True);s[120:190]=q
        peaks=acoustic_peaks(q,s,np.arange(70)*.02,np.arange(300)*.02,100)
        self.assertGreater(peaks[0]['score'],.99);self.assertAlmostEqual(peaks[0]['source_start'],102.4,places=2)

    def test_mfcc_gain_invariance(self):
        t=np.arange(64000)/16000;x=(np.sin(2*np.pi*(200*t+70*t*t))+.4*np.sin(2*np.pi*800*t)).astype('float32')
        a,_,_=features(x);b,_,_=features(x*.3)
        self.assertGreater(float(np.mean(np.sum(a*b,axis=1))),.98)

    def test_disordered_acoustic_anchors_not_full_chain(self):
        anchors=[]
        for i,ts in enumerate([100,600,110]):
            anchors.append(dict(anchor_id=str(i),reference_start=i*4,reference_end=i*4+2,reference_midpoint=i*4+1,
                individually_supported=True,peaks=[dict(score=.9,source_start=ts,source_end=ts+2,source_midpoint=ts+1)]))
        self.assertLess(len(consistent_audio_chain(anchors)),3)


if __name__=='__main__':unittest.main()
