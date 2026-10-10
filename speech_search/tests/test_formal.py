import unittest
import numpy as np
from speech_search.build_formal import encode_resilient,Encoder
from speech_search.semantic import Encoder as PilotEncoder


class FakeEncoder:
    def encode(self,texts):
        if 'BAD' in texts:raise ValueError('damaged text')
        result=np.zeros((len(texts),512),dtype='float32');result[:,0]=1
        return result


class FormalTests(unittest.TestCase):
    def test_bad_text_does_not_discard_good_batch(self):
        rows=[dict(row_id=i,normalized_text=s) for i,s in enumerate(['一','BAD','二','三'])]
        results=encode_resilient(FakeEncoder(),rows)
        self.assertEqual([r[0]['row_id'] for r in results],[0,1,2,3])
        self.assertEqual(sum(r[1] is not None for r in results),3)
        self.assertEqual(sum(bool(r[2]) for r in results),1)

    def test_system_error_is_not_mislabeled_as_bad_text(self):
        class Broken:
            def encode(self,texts):raise RuntimeError('CUDA lost')
        with self.assertRaises(RuntimeError):encode_resilient(Broken(),[dict(normalized_text='一')])

    def test_exact_same_encoder(self):
        self.assertIs(Encoder,PilotEncoder)


if __name__=='__main__':unittest.main()
