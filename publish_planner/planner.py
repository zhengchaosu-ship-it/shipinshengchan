"""按日重置首发时间；没有任何 UI 控制或队列调用。"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
from .models import Slot, digest
from .validator import validate, PlannerError

ALLOW_REPEAT_CONTENT = False  # STARTUP固定关闭；不提供客户端开关。


def daily_capacity(plan):
    first = plan.daily_first_time.hour * 60 + plan.daily_first_time.minute
    minutes = 1440 if plan.allow_cross_day else 1440 - first
    return (minutes + plan.interval_minutes - 1) // plan.interval_minutes


def validate_slot_uniqueness(plan, slots, selected_ids=None):
    if plan.business_type != 'STARTUP':
        return
    expected = set(selected_ids) if selected_ids is not None else {
        'planner-source-'+digest(str(Path(p).resolve()).casefold()) for p in plan.video_paths}
    ids = [s.content_id for s in slots]
    if len(ids) != len(set(ids)) or len(ids) > len(expected):
        raise PlannerError('DUPLICATE_CONTENT_SCHEDULE_BLOCKED', '起号素材在同一计划中只能安排一次')
    keys = [(s.account_id, datetime.fromisoformat(s.scheduled_at)) for s in slots]
    if len(keys) != len(set(keys)):
        raise PlannerError('ACCOUNT_TIME_COLLISION_BLOCKED', '同账号同一时间不能重复安排')
    if set(ids) != expected:
        raise PlannerError('SCHEDULE_CAPACITY_TOO_SMALL_FOR_SELECTED_CONTENT', '日期范围内无法排完全部素材，请延长结束日期')


def _startup_preview(plan, occupied_slots):
    # 不循环素材；路径大小写/重复选项只消费一次，业务content_id由接线层替换。
    videos = list(dict.fromkeys(str(Path(p).resolve()).casefold() for p in plan.video_paths))
    paths = {str(Path(p).resolve()).casefold(): str(Path(p).resolve()) for p in plan.video_paths}
    zone = timezone(timedelta(hours=8))
    occupied = {(account,datetime.fromisoformat(stamp).astimezone(zone).isoformat(timespec='seconds')) for account,stamp in occupied_slots}
    result, next_time, counts = [], {}, {}
    count = min(plan.daily_count, daily_capacity(plan))
    for day in range((plan.end_date-plan.start_date).days+1):
        start = datetime.combine(plan.start_date+timedelta(days=day), plan.daily_first_time, zone)
        if plan.daily_count_mode == 'PER_ACCOUNT':
            assignments = [(a, n) for n in range(count) for a in plan.account_ids]
        else:
            assignments = [(plan.account_ids[n % len(plan.account_ids)] if plan.assignment_mode == 'ROUND_ROBIN_ACCOUNT'
                else plan.account_ids[min(n*len(plan.account_ids)//count, len(plan.account_ids)-1)], n) for n in range(count)]
        for account, index in assignments:
            instant = start+timedelta(minutes=index*plan.interval_minutes)
            if instant.date() > plan.end_date:
                continue
            stamp = instant.isoformat(timespec='seconds')
            day_key = (account if plan.daily_count_mode == 'PER_ACCOUNT' else '*', instant.date())
            if ((account, stamp) in occupied or instant < next_time.get(account, start)
                or counts.get(day_key, 0) >= plan.daily_count):
                continue
            path_key = videos[len(result)]
            video = paths[path_key]
            content = 'planner-source-'+digest(path_key)
            item = digest(f'{plan.plan_id}:{account}:{stamp}:{content}')
            signature = digest(json.dumps([plan.plan_id, item, content, account, stamp]))
            result.append(Slot(item, content, account, video, stamp, signature))
            occupied.add((account, stamp))
            next_time[account] = instant+timedelta(minutes=plan.interval_minutes)
            counts[day_key] = counts.get(day_key, 0)+1
            if len(result) == len(videos):
                validate_slot_uniqueness(plan, result)
                return result
    validate_slot_uniqueness(plan, result)  # 不允许悄悄只安排部分已选素材。
    return result


def preview(plan, *, occupied_slots=()):
    validate(plan)
    if plan.business_type == 'STARTUP':
        return _startup_preview(plan, occupied_slots)
    result = []
    local_zone = timezone(timedelta(hours=8))
    for day in range((plan.end_date - plan.start_date).days + 1):
        start = datetime.combine(plan.start_date + timedelta(days=day), plan.daily_first_time, local_zone)
        count = plan.daily_count
        accounts = plan.account_ids
        if plan.daily_count_mode == "PER_ACCOUNT":
            if plan.assignment_mode == "ROUND_ROBIN_ACCOUNT":
                assignments = [(a, n) for n in range(count) for a in accounts]
            else:
                assignments = [(a, n) for a in accounts for n in range(count)]
        else:
            assignments = [(accounts[n % len(accounts)] if plan.assignment_mode == "ROUND_ROBIN_ACCOUNT"
                            else accounts[min(n * len(accounts) // count, len(accounts) - 1)], n)
                           for n in range(count)]
        for account_id, index in assignments:
            video = str(Path(plan.video_paths[len(result) % len(plan.video_paths)]).resolve())
            content_id = "planner-source-" + digest(video)
            item_id = digest(f"{plan.plan_id}:{day}:{account_id}:{index}")
            scheduled_at = (start + timedelta(minutes=index * plan.interval_minutes)).isoformat(timespec="seconds")
            signature = digest(json.dumps([plan.plan_id, item_id, content_id, account_id, scheduled_at]))
            result.append(Slot(item_id, content_id, account_id, video, scheduled_at, signature))
    return result
