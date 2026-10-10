"""纯排期回归：素材唯一、每日上限、跨日无重复、不创建任务。"""
from collections import Counter
from dataclasses import replace
from datetime import date, time, datetime, timedelta
import unittest
from publish_planner.models import Plan
from publish_planner.planner import preview, validate_slot_uniqueness, ALLOW_REPEAT_CONTENT


class UniqueStartupTests(unittest.TestCase):
    def plan(self, **values):
        return replace(Plan('unique-plan', date(2026,10,6), date(2026,10,15), time(0),
            ('A',), tuple(f'test-{n}.mp4' for n in range(28)), daily_count=20), **values)

    def test_28_sources_ten_days_twenty_max_only_28(self):
        self.assertEqual(len(preview(self.plan())), 28)

    def test_daily_eight_is_eight_eight_eight_four(self):
        self.assertEqual(list(Counter(s.scheduled_at[:10] for s in preview(self.plan(daily_count=8))).values()), [8,8,8,4])

    def test_three_hours_twenty_daily_capped_and_unique(self):
        rows = preview(self.plan())
        self.assertEqual(len(set((s.account_id,s.scheduled_at) for s in rows)),28)
        self.assertTrue(all(v<=8 for v in Counter(s.scheduled_at[:10] for s in rows).values()))

    def test_long_date_range_stops_when_contents_exhausted(self):
        rows = preview(self.plan(end_date=date(2027,1,1)))
        self.assertEqual(rows[-1].scheduled_at[:10],'2026-10-09')

    def test_duplicate_selection_consumed_once(self):
        plan = self.plan()
        rows = preview(replace(plan,video_paths=plan.video_paths+plan.video_paths[:3]))
        self.assertEqual(len(rows),28)
        self.assertEqual(len({s.content_id for s in rows}),28)

    def test_repeat_hard_gate(self):
        self.assertFalse(ALLOW_REPEAT_CONTENT)
        plan = self.plan()
        rows = preview(plan)
        with self.assertRaisesRegex(ValueError,'DUPLICATE_CONTENT_SCHEDULE_BLOCKED'):
            validate_slot_uniqueness(plan,rows+[replace(rows[0],item_id='forged')])

    def test_collision_hard_gate(self):
        plan = self.plan()
        rows = preview(plan)
        rows[1] = replace(rows[1], scheduled_at=rows[0].scheduled_at)
        with self.assertRaisesRegex(ValueError,'ACCOUNT_TIME_COLLISION_BLOCKED'):
            validate_slot_uniqueness(plan, rows)

    def test_insufficient_dates_do_not_silently_drop_selection(self):
        with self.assertRaisesRegex(ValueError,'CAPACITY_TOO_SMALL'):
            preview(self.plan(end_date=date(2026,10,6)))

    def test_existing_account_time_uses_next_legal_slot(self):
        plan = self.plan()
        rows = preview(plan,occupied_slots=[('A','2026-10-06T00:00:00+08:00')])
        self.assertEqual(rows[0].scheduled_at,'2026-10-06T03:00:00+08:00')
        self.assertEqual(len(rows),28)

    def test_cross_day_preserves_interval_and_latest_date(self):
        plan = self.plan(daily_first_time=time(9),allow_cross_day=True)
        rows = preview(plan)
        times = [datetime.fromisoformat(r.scheduled_at) for r in rows]
        self.assertTrue(all(b-a>=timedelta(hours=3) for a,b in zip(times,times[1:])))
        self.assertTrue(all(t.date()<=plan.end_date for t in times))
        self.assertEqual(list(Counter(r.scheduled_at[:10] for r in rows).values()),[5,8,8,7])
