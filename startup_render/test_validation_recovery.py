import tempfile
from pathlib import Path
import unittest
from copy import deepcopy
from .common import save
from .validation_recovery import fingerprint,validate_recovery


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'current-run'/'server';self.root.mkdir(parents=True)
        self.identity={'job_id':'STARTUP-current','content_id':'STARTUP-current','target_account_id':'stable'}
        self.failed={'status':'NEEDS_MANUAL','failed_step':'VALIDATING','error':'ValueError:EXPORTED_MEDIA_VALIDATION_FAILED',
                     'events':[{'status':'EXPORTED'},{'status':'PROCESS_EXITED'}]}
        self.done={'status':'COMPLETED','real_publish_attempts':0,'media':{'codec':'h264'},
                   'normalization':{'original_sha256':'raw-sha'},'recovery_of_receipt_sha256':fingerprint(self.failed)}
        save(self.root.parent/'GENERATION_RESULT.json',{'registered':[{'content_id':'STARTUP-current'}]})
        save(self.root.parent/'VALIDATION_RECOVERY_APPROVAL.json',{'run_id':'current-run','job_id':'STARTUP-current',
             'account_id':'stable','original_sha256':'raw-sha'})

    def test_current_exact_failure_allowed_with_evidence(self):
        self.assertTrue(validate_recovery(self.root,self.identity,self.failed,self.done)['approved'])

    def test_without_local_approval_history_immutable(self):
        (self.root.parent/'VALIDATION_RECOVERY_APPROVAL.json').unlink()
        with self.assertRaisesRegex(ValueError,'RESULT_IMMUTABLE'):
            validate_recovery(self.root,self.identity,self.failed,self.done)

    def test_historical_job_not_recoverable(self):
        identity=dict(self.identity,job_id='STARTUP-old',content_id='STARTUP-old')
        with self.assertRaises(PermissionError):validate_recovery(self.root,identity,self.failed,self.done)

    def test_non_codec_failure_rejected(self):
        failed=dict(self.failed,error='JIANYING_DRAFT_NOT_VISIBLE')
        with self.assertRaises(PermissionError):validate_recovery(self.root,self.identity,failed,self.done)

    def test_raw_sha_mismatch_rejected(self):
        done=deepcopy(self.done);done['normalization']['original_sha256']='other'
        with self.assertRaises(PermissionError):validate_recovery(self.root,self.identity,self.failed,done)

    def test_non_h264_rejected(self):
        done=deepcopy(self.done);done['media']['codec']='hevc'
        with self.assertRaises(PermissionError):validate_recovery(self.root,self.identity,self.failed,done)

    def test_failure_fingerprint_mismatch_rejected(self):
        with self.assertRaises(PermissionError):
            validate_recovery(self.root,self.identity,self.failed,dict(self.done,recovery_of_receipt_sha256='other'))

    def test_other_account_rejected(self):
        with self.assertRaises(PermissionError):
            validate_recovery(self.root,dict(self.identity,target_account_id='other'),self.failed,self.done)
