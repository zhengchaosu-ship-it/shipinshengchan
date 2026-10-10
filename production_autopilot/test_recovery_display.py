import json
import unittest
from production_autopilot.ui import recovery_display_result, system_issue_label


class RecoveryDisplayTests(unittest.TestCase):
    def test_raw_system_reason_does_not_abort_page(self):
        self.assertIn('BACKUP_ACTIVE_PROFILE_MISMATCH',system_issue_label('BACKUP_ACTIVE_PROFILE_MISMATCH'))
        self.assertIn('磁盘空间不足',system_issue_label('磁盘空间：LOW'))
        for raw in (None,'','SYSTEM：','：LOW',{'code':'bad'}):
            self.assertIsInstance(system_issue_label(raw),str)

    def test_one_bad_json_does_not_stop_following_100(self):
        values=[json.dumps({'resumed':False,'errors':[]})]*100+['{broken']+[json.dumps({'errors':[]})]*100
        results=[recovery_display_result(v) for v in values]
        self.assertEqual(len(results),201)
        self.assertEqual(sum(bool(r.get('_display_error')) for r in results),1)
        self.assertTrue(all('errors' in r for r in results[101:]))

    def test_wrong_json_shape_is_locally_quarantined(self):
        for value in ['[]','null','1','{"errors":[1]}','{"awaiting_components":"bad"}']:
            self.assertTrue(recovery_display_result(value).get('_display_error'))


if __name__=='__main__':unittest.main()
