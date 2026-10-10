"""纯参数校验；权限另在存储事务内再次校验。"""
from datetime import datetime, timedelta
from pathlib import Path


class PlannerError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


def validate(plan, *, check_files=False):
    def require(ok, code, message):
        if not ok:
            raise PlannerError(code, message)
    require(bool(plan.plan_id), "INVALID_PLAN", "缺少计划ID")
    require(plan.business_type in {"STARTUP", "COMMERCE"}, "INVALID_BUSINESS_TYPE", "业务类型须为起号或带货")
    require(type(plan.daily_count) is int and 1 <= plan.daily_count <= 20, "INVALID_COUNT", "每天数量须为1～20的整数")
    require(type(plan.interval_minutes) is int and 1 <= plan.interval_minutes <= 1440, "INVALID_INTERVAL", "间隔须为1～1440的整数分钟")
    require(0 <= (plan.end_date - plan.start_date).days <= 365, "INVALID_DATE_RANGE", "日期范围须为1～366天")
    require(plan.daily_first_time.tzinfo is None and plan.daily_first_time.second == 0
            and plan.daily_first_time.microsecond == 0, "INVALID_TIME", "首发时间精确到分钟")
    require(plan.daily_count_mode in {"PER_ACCOUNT", "PER_PLAN_TOTAL"}, "INVALID_MODE", "未知数量模式")
    require(plan.assignment_mode in {"SEQUENTIAL", "ROUND_ROBIN_ACCOUNT"}, "INVALID_ASSIGNMENT", "未知分配模式")
    require(0 < len(plan.account_ids) <= 100 and len(set(plan.account_ids)) == len(plan.account_ids), "INVALID_ACCOUNTS", "请选择1～100个不同账号ID")
    require(bool(plan.video_paths), "INVALID_VIDEOS", "请选择MP4成片")
    total = ((plan.end_date - plan.start_date).days + 1) * plan.daily_count
    if plan.daily_count_mode == "PER_ACCOUNT":
        total *= len(plan.account_ids)
    if plan.business_type == 'STARTUP':
        total = len({str(Path(p).resolve()).casefold() for p in plan.video_paths})
    require(total <= 20000, "PLAN_TOO_LARGE", "单份本地测试计划最多20000条，请缩小日期范围或账号数")
    if plan.business_type != 'STARTUP':
        require(len(set(plan.video_paths)) == len(plan.video_paths), "DUPLICATE_VIDEO", "视频路径重复")
    last = datetime.combine(plan.start_date, plan.daily_first_time) + timedelta(
        minutes=(plan.daily_count - 1) * plan.interval_minutes)
    require(plan.business_type == 'STARTUP' or plan.allow_cross_day or last.date() == plan.start_date, "DAILY_SCHEDULE_OVERFLOW",
            "当前计划会跨到次日，请提前首发时间、缩短间隔或开启允许跨天。")
    for source in plan.video_paths:
        require(Path(source).suffix.lower() == ".mp4", "INVALID_VIDEO", "仅支持MP4")
        if check_files:
            require(Path(source).is_file(), "VIDEO_NOT_FOUND", f"成片不存在：{source}")
