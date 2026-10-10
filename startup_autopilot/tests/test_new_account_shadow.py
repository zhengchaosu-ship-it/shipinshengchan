from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest

from startup_autopilot.demo import fixture
from startup_autopilot.material_catalog import inventory
from startup_autopilot.models import Profile, Slot, Template, digest, policy
from startup_autopilot.planner import StartupDailyPlanner
from startup_autopilot.week_shadow import seven_days
from startup_autopilot.tests.test_foundation import NOW


class NewAccountShadowTests(unittest.TestCase):
    def make(self, directory, counts):
        pools=[]
        for index,count in enumerate(counts):
            folder=Path(directory)/str(index);folder.mkdir()
            for i in range(count):
                (folder/f'{i:03d}.mp4').write_bytes(f'synthetic fixture {index} {i}'.encode())
            pools.append((('引流','手法','坐诊','收尾')[index],str(folder)))
        catalog=inventory(pools)
        actor,_,_,_=fixture(NOW)
        template=Template('DEMO_ACCOUNT','shadow-v1',tuple(Slot(p['module_type'],tuple(m['material_id'] for m in p['files'])) for p in catalog))
        profile=Profile('DEMO_ACCOUNT',None,template.version,status='COLD_START',execution_mode='SHADOW',
                        template_hash=digest(asdict(template)),policy_hash=digest(policy()))
        return actor,profile,template,catalog

    def test_disabled_null_target_observation_not_authorization(self):
        actor,profile,template,_=fixture(NOW)
        profile=replace(profile,enabled=False,execution_mode='SHADOW',target_follower_count=None)
        profile.validate()
        result=StartupDailyPlanner().shadow(actor,profile,template,'2026-10-07',NOW,observe_disabled=True)
        self.assertEqual(len(result['proposals']),5)
        self.assertFalse(result['profile_enabled'])
        with self.assertRaises(ValueError): replace(profile,enabled=True).validate()

    def test_35_with_sufficient_pool_and_no_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            actor,profile,template,catalog=self.make(directory,(24,24,24,24))
            result=seven_days(actor,profile,template,catalog,NOW)
            self.assertEqual(result['total_suggestions'],35)
            self.assertEqual(result['duplicate_count'],0)
            self.assertEqual(result['publish_count'],0)
            self.assertFalse(profile.enabled)

    def test_one_tail_cannot_fake_five_per_day(self):
        with tempfile.TemporaryDirectory() as directory:
            actor,profile,template,catalog=self.make(directory,(12,12,12,1))
            result=seven_days(actor,profile,template,catalog,NOW)
            self.assertTrue(result['capacity_limited'])
            self.assertEqual(result['maximum_daily_count'],1)
            # 默认所有Slot均为核心：一个收尾连相邻作品也不能重复。
            self.assertEqual(result['total_suggestions'],1)
            self.assertEqual(profile.daily_publish_limit,5)

    def test_other_account_history_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            actor,profile,template,catalog=self.make(directory,(12,12,12,1))
            with self.assertRaises(PermissionError):
                seven_days(actor,profile,template,catalog,NOW,material_history=[{'account_id':'BINGYAO'}])

    def test_missing_actual_material_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            actor,profile,template,catalog=self.make(directory,(12,12,12,1))
            item=catalog[-1]['files'][0]
            # 改引用到不存在的测试路径，避免删除文件。
            item['path']=str(Path(directory)/'missing.mp4')
            with self.assertRaises(ValueError): seven_days(actor,profile,template,catalog,NOW)


if __name__=='__main__': unittest.main()
