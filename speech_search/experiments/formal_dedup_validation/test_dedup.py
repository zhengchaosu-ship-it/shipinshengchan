import unittest
from run import dedup


def row(w,a,s,e,score):
    return dict(window_id=w,asset_id=a,start_time=s,end_time=e,semantic_score=score)


class DedupTests(unittest.TestCase):
    def test_highest_score_and_other_asset_preserved(self):
        r=[row(1,'a',10,20,.9),row(2,'a',12,22,.8),row(3,'b',10,20,.7)]
        self.assertEqual([x['window_id'] for x in dedup(r,'C_time')],[1,3])
        self.assertEqual(r[0]['semantic_score'],.9)

    def test_distinct_positions_in_one_asset_remain(self):
        r=[row(1,'a',0,2,.9),row(2,'a',100,102,.8)]
        self.assertEqual(len(dedup(r,'C_time')),2)
        self.assertEqual(len(dedup(r,'B_asset')),1)

    def test_center_boundary_and_no_transitive_chain(self):
        r=[row(1,'a',0,1,.9),row(2,'a',9,10,.8),row(3,'a',18,19,.7)]
        self.assertEqual([x['window_id'] for x in dedup(r,'C_time')],[1,3])
        self.assertEqual(len(dedup([r[0],row(4,'a',10,11,.6)],'C_time')),2)

    def test_nested_windows_and_long_overlaps(self):
        r=[row(1,'a',0,60,.9),row(2,'a',45,55,.8)]
        self.assertEqual(len(dedup(r,'C_time')),1)


if __name__=='__main__':unittest.main()
