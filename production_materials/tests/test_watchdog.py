import unittest
from production_materials.watchdog import decision


class WatchdogTests(unittest.TestCase):
    def test_healthy_service_not_restarted(self):
        self.assertEqual(decision(True,2,'Running',True,[],100000),'HEALTHY')

    def test_existing_unhealthy_process_never_gets_second_resident(self):
        self.assertEqual(decision(False,2,'Ready',True,[],100000),'NEEDS_ATTENTION_EXISTING_PROCESS')

    def test_intentionally_disabled_service_not_enabled(self):
        self.assertEqual(decision(False,0,'Ready',False,[],100000),'DISABLED_NO_AUTOMATIC_START')

    def test_exited_original_task_recovered(self):
        self.assertEqual(decision(False,0,'Ready',True,[],100000),'START_ORIGINAL_TASK')

    def test_scheduler_running_start_is_not_duplicated(self):
        self.assertEqual(decision(False,0,'Running',True,[],100000),'TASK_NOT_READY_NO_SECOND_INSTANCE')

    def test_persistent_budget_prevents_restart_storm(self):
        self.assertEqual(decision(False,0,'Ready',True,[99940],100000),'RECOVERY_BACKOFF')
        self.assertEqual(decision(False,0,'Ready',True,[80000,85000,90000],100000),'RECOVERY_BACKOFF')
        self.assertEqual(decision(False,0,'Ready',True,[1000],100000),'START_ORIGINAL_TASK')


if __name__=='__main__':
    unittest.main()
