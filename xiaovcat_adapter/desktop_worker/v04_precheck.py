"""V0.4 单任务准备核验；只读取表单证据，不包含提交实现。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from .electron_probe import ROOT
from .uia_probe import LocalUIA

RESULTS = ROOT / "xiaovcat_adapter/results/real_publish_v04"


def read_bound_topics(descendants, account_id, include_offscreen_known=False):
    """既有UI的#话题chips及计数回读；不把字段标题当成话题。"""
    labels = [r['name'] for r in descendants if r['control_type'] == 50020
              and r['parent_id'] == account_id
              and (include_offscreen_known or not r['offscreen'])]
    markers = [i for i, name in enumerate(labels) if name.strip() == '当前话题']
    if len(markers) != 1 or markers[0] + 1 >= len(labels):
        raise ValueError('TOPIC_COUNT_UI_NOT_READABLE')
    marker = markers[0]
    count = labels[marker + 1].strip()
    if not count.isdecimal():
        raise ValueError('TOPIC_COUNT_UI_NOT_READABLE')
    topics = []
    for i, name in enumerate(labels[:marker]):
        if name.strip() == '#':
            if i + 1 >= marker or not labels[i + 1].strip() or labels[i + 1].strip() == '#':
                raise ValueError('TOPIC_CHIP_UI_NOT_READABLE')
            topics.append(labels[i + 1].strip())
    if len(topics) != int(count):
        raise ValueError('TOPIC_COUNT_CHIPS_MISMATCH')
    return topics


def verify_evidence(policy, account, text, timing, preview, selection, prior, *, include_offscreen_known=False, ready_profile=None):
    if policy.get("max_jobs") != 1 or policy.get("max_final_submit_invocations") != 1:
        raise ValueError("SINGLE_JOB_SCOPE_REQUIRED")
    if prior.get("submit_attempted") or prior.get("final_submit_invocations", 0) != 0:
        raise ValueError("ALREADY_ATTEMPTED_NO_RESUBMIT")
    if policy.get("schedule_delay_minutes") != 130:
        raise ValueError("ONLY_130_MINUTES_AUTHORIZED")
    chosen = [a for a in account["accounts"] if a["selected"]]
    if len(chosen) != 1 or chosen[0]["account_name"] != "丙曜" or chosen[0]["platform"] != "抖音" \
            or not chosen[0]["online"] or not chosen[0]["enabled"]:
        raise ValueError("EXACT_ONLINE_ACCOUNT_REQUIRED")
    title,description=('', '陶老师小妙招') if ready_profile is None else (ready_profile['title'],ready_profile['description'])
    for aid, expected in (("title", title), ("item_title", title), ("desc", description), ("text", description)):
        rows = [r for r in text["nodes"] if r["automation_id"] == aid and r["control_type"] == 50004
                and not r["password"] and (include_offscreen_known or not r["offscreen"])]
        if len(rows) != 1 or text["values"].get(rows[0]["runtime_id"]) != expected:
            raise ValueError("TEXT_UI_READBACK_MISMATCH:" + aid)
    panels = [r for r in text["nodes"] if r["control_type"] == 50033 and r["name"] == "丙曜 close"]
    if len(panels) != 1:
        raise ValueError("ACCOUNT_PANEL_CHANGED")
    account_id = panels[0]["runtime_id"]
    descendants = LocalUIA.descendants(text["nodes"], account_id)
    expected_topics=['健康','健康科普','养生'] if ready_profile is None else [t.lstrip('#') for t in ready_profile['topics']]
    topics = ([r["name"] for r in descendants if r["control_type"] == 50020
               and (include_offscreen_known or not r["offscreen"]) and r['name'] in {'健康','健康科普','养生'}]
              if ready_profile is None else read_bound_topics(descendants, account_id, include_offscreen_known))
    if sorted(topics) != sorted(expected_topics):
        raise ValueError("ACTUAL_TOPIC_CHIPS_MISMATCH")
    dates = [r for r in timing["nodes"] if r["control_type"] == 50004 and r["name"] == "请选择日期时间"
             and (include_offscreen_known or not r["offscreen"]) and not r["password"]]
    if len(dates) != 2 or any(timing["values"].get(r["runtime_id"]) != preview["ui_input"] for r in dates):
        raise ValueError("SCHEDULE_TWO_SIDES_MISMATCH")
    selected = [r for r in timing["nodes"] if r["control_type"] == 50013
                and timing["radio_selected"].get(r["runtime_id"]) and r["name"].strip() in
                {"立即发布", "定时发布", "本机定时"}]
    if len(selected) != 2 or any(r["name"].strip() != "定时发布" for r in selected):
        raise ValueError("SCHEDULE_MODE_MISMATCH")
    for r in timing["nodes"]:
        if r["control_type"] == 50002 and r["name"].strip() == "超时后改为即时发布" \
                and timing["checkbox_selected"].get(r["runtime_id"]) != 0:
            raise ValueError("IMMEDIATE_PUBLISH_FALLBACK_MUST_BE_OFF")
    base = datetime.fromisoformat(preview["base_local_time"])
    scheduled = datetime.fromisoformat(preview["scheduled_at"])
    if scheduled - base != timedelta(minutes=130) or scheduled.strftime("%Y-%m-%d %H:%M") != preview["ui_input"]:
        raise ValueError("SCHEDULE_CALCULATION_MISMATCH")
    remaining = scheduled - datetime.now().astimezone()
    if not timedelta(hours=2) < remaining <= timedelta(days=14):
        raise ValueError("ACCOUNT_UI_SCHEDULE_CONSTRAINT")
    if selection["video_path"] != policy["video_path"] or selection["file_dialog_value_readback"] != policy["video_path"]:
        raise ValueError("ORIGINAL_FILE_PATH_MISMATCH")
    final = [r for r in timing["nodes"] if r["control_type"] == 50000 and r["name"] == "一键分发"
             and r["enabled"] and not r["offscreen"]]
    if len(final) != 1:
        raise ValueError("FINAL_BUTTON_NOT_UNIQUE")
    return chosen[0]


def main():
    read = lambda name: json.loads((RESULTS / name).read_text(encoding="utf-8"))
    policy = read("LOCKED_REQUEST.json")
    account = read("ACCOUNT_RECHECK_FINAL.json")
    text = read("42_plus_130_right_text_topics.json")
    timing = read("43_plus_130_right_schedule.json")
    preview = read("SCHEDULE_PREVIEW.json")
    selection = read("ORIGINAL_FILE_SELECTION.json")
    prior = read("PRE_SUBMIT_CHECK.json")
    verify_evidence(policy, account, text, timing, preview, selection, prior)
    if Path(policy["video_path"]).stat().st_size != selection["size_bytes"]:
        raise RuntimeError("SOURCE_FILE_SIZE_CHANGED")
    config = json.loads((ROOT / "xiaovcat_adapter/config.json").read_text(encoding="utf-8"))
    if config.get("real_publish_enabled") is not False:
        raise RuntimeError("GLOBAL_PUBLISH_SWITCH_MUST_STAY_OFF")
    report = {**prior,
        "status": "AWAITING_ACTION_TIME_CONFIRMATION", "all_checks_passed": False,
        "form_fields_verified": True, "blocking_reason": "ACTION_TIME_CONFIRMATION_REQUIRED_BEFORE_REAL_SUBMIT",
        "schedule_constraint_resolved": True, "schedule_allowed_by_account_ui": True,
        "schedule_rule_requested": "LOCAL_TIME_AT_ACTUAL_PRE_SUBMIT_PLUS_130_MINUTES",
        "schedule_delay_minutes": 130, "schedule_base_local_time": preview["base_local_time"],
        "actual_schedule_base_local_time": preview["actual_base_local_time"],
        "scheduled_at": preview["scheduled_at"], "ui_scheduled_at": preview["ui_input"],
        "schedule_is_provisional_not_submitted": True,
        "refresh_schedule_and_live_validation_before_submit": True,
        "prepared_at": datetime.now().astimezone().isoformat(), "account_checked_at": account["checked_at"],
        "ui_readback": {**prior["ui_readback"],
            "title_description_topics_default_cover": "42_plus_130_right_text_topics.json",
            "title_description_topics_default_cover_visual": "42_plus_130_right_text_topics.png",
            "scheduled_mode_and_time_both_sides": "43_plus_130_right_schedule.json",
            "two_hour_constraint_visual": "43_plus_130_right_schedule.png"},
        "next_action": "WAIT_FOR_USER_CONFIRMATION_THEN_REFRESH_SCHEDULE_AND_VERIFY_NO_SECOND_JOB"}
    (RESULTS / "PRE_SUBMIT_CHECK.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("status", "video_path", "account_name", "platform", "title",
        "description", "topics", "publish_mode", "scheduled_at", "submit_attempted", "real_publish_enabled")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
