import unittest
from reranker import Reranker,PARAMS,MODEL_DIR


class Inputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from transformers import AutoTokenizer
        cls.rr=Reranker.__new__(Reranker)
        cls.rr.tokenizer=AutoTokenizer.from_pretrained(MODEL_DIR,local_files_only=True)

    def test_context_cannot_displace_matched_window(self):
        row=dict(original_text='腰疼不一定是腰的问题',context_before='前一句很长'*300,context_after='后一句很长'*300)
        encoded,info=self.rr.prepare('腰疼原因',row,'context')
        self.assertFalse(info['window_truncated'])
        self.assertLessEqual(info['tokens'],512)
        self.assertEqual(info['before_tokens'],40)
        self.assertEqual(info['after_tokens'],40)
        self.assertIn('腰疼不一定是腰的问题',self.rr.tokenizer.decode(encoded['input_ids']).replace(' ',''))

    def test_long_input_has_explicit_truncation(self):
        _,info=self.rr.prepare('问题'*300,dict(original_text='原文'*1000),'window')
        self.assertTrue(info['query_truncated']);self.assertTrue(info['window_truncated'])
        self.assertLessEqual(info['tokens'],512)

    def test_window_input_excludes_context(self):
        row=dict(original_text='原文',context_before='不能出现前文',context_after='不能出现后文')
        encoded,info=self.rr.prepare('问题',row,'window')
        self.assertEqual(info['before_tokens']+info['after_tokens'],0)
        self.assertNotIn('不能出现',self.rr.tokenizer.decode(encoded['input_ids']).replace(' ',''))
        self.assertEqual(PARAMS['candidate_pools'],[20,50,100])


if __name__=='__main__':unittest.main()
