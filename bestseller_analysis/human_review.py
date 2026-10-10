"""带货爆款第一轮人工审核 V0.1 数据层。

只读取 batch_20_v1 的机器结果，所有人工数据写入 human_review/。
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from statistics import mean

from .business_taxonomy import ROLES


REVIEW_VERSION = "0.1"
GOLD_GRADES = {"GOLD", "USABLE", "REJECT"}
BOUNDARY_RESULTS = {"正确", "起点需要调整", "终点需要调整", "起止都需要调整"}
EDITING_USE = {"会直接用", "修改后可用", "不会用"}
ERROR_REASONS = {
    "边界错误", "功能分类错误", "商品判断错误", "信任判断错误",
    "CTA判断错误", "需要上下文", "本身不是好素材", "其它",
}
CTA_RESULTS = {"确实无CTA", "AI漏掉CTA"}
CTA_TYPES = {"CTA_SOFT", "CTA_DIRECT", "CTA_URGENCY", "CTA_END", "OTHER"}
DEPENDENCY_LEVELS = {"低", "中", "高"}
YES_NO = {"是", "否"}

REVIEW_GROUPS = {
    "A": {"HOOK", "CONSULT", "PRODUCT_BRIDGE", "PRODUCT_INTRO", "PRODUCT_VALUE"},
    "B": {"PROOF", "TESTIMONIAL", "CALL_RESULT", "AUTHORITY", "TRUST"},
    "C": {"CTA", "CTA_SOFT", "CTA_DIRECT", "CTA_URGENCY", "CTA_END"},
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _optional_time(value, duration: float):
    if value in (None, ""):
        return None
    result = round(float(value), 3)
    if not 0 <= result <= duration:
        raise ValueError("产品节点时间超出视频范围")
    return result


def _product_times(payload: dict, duration: float) -> dict:
    return {
        "product_first_mention": _optional_time(payload.get("product_first_mention"), duration),
        "product_first_visual": _optional_time(payload.get("product_first_visual"), duration),
        "product_first_sales_function": _optional_time(payload.get("product_first_sales_function"), duration),
    }


class HumanReviewStore:
    """机器层只读、人工层增量保存的审核仓库。"""

    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        self.human_root = self.root / "human_review"
        self.human_root.mkdir(parents=True, exist_ok=True)
        self.gold_path = self.human_root / "human_gold_data.json"
        self.cta_path = self.human_root / "cta_review.json"
        self.replication_path = self.human_root / "replication_review.json"
        self.progress_path = self.human_root / "review_progress.json"
        self.report_path = self.human_root / "ROUND1_REVIEW_REPORT.md"
        self.report_stats_path = self.human_root / "round1_review_statistics.json"

        self.videos: dict[str, dict] = {}
        for path in sorted((self.root / "videos").glob("*/business_analysis.json"), key=lambda p: int(p.parent.name)):
            item = json.loads(path.read_text(encoding="utf-8"))
            self.videos[str(item["video_id"])] = item
        if len(self.videos) != 20:
            raise ValueError(f"预期20条机器分析，实际{len(self.videos)}条")

        self.gold_machine = json.loads((self.root / "gold_examples.json").read_text(encoding="utf-8"))
        self.replication_machine = json.loads((self.root / "replication_candidates.json").read_text(encoding="utf-8"))
        if len(self.gold_machine) != 25:
            raise ValueError(f"预期25个Gold候选，实际{len(self.gold_machine)}个")
        self.no_cta_ids = [video_id for video_id, video in self.videos.items() if video["cta"]["cta_count"] == 0]
        self.replication_ids = [str(item["video_id"]) for item in self.replication_machine]
        if len(self.no_cta_ids) != 7 or len(self.replication_ids) != 5:
            raise ValueError("审核队列规模与V0.1要求不符")

        self._ensure_files()

    def _base(self, review_type: str) -> dict:
        return {
            "schema_version": REVIEW_VERSION,
            "review_round": "带货爆款第一轮人工审核 V0.1",
            "review_type": review_type,
            "machine_source": str(self.root),
            "machine_data_immutable": True,
            "updated_at": None,
        }

    def _ensure_files(self) -> None:
        if not self.gold_path.exists():
            value = self._base("gold_examples")
            value.update({"reviews": {}, "gold_segments": []})
            legacy = self.root / "human_gold_data.json"
            if legacy.exists():
                value["legacy_content_preserved"] = _read_json(legacy, {})
            _atomic_json(self.gold_path, value)
        if not self.cta_path.exists():
            value = self._base("cta_special_review")
            value.update({"machine_no_cta_video_ids": self.no_cta_ids, "reviews": {}})
            _atomic_json(self.cta_path, value)
        if not self.replication_path.exists():
            value = self._base("replication_candidate_review")
            value.update({"candidate_video_ids": self.replication_ids, "reviews": {}})
            _atomic_json(self.replication_path, value)
        self.write_progress()

    def _segment(self, video_id: str, segment_id: str) -> tuple[dict, int]:
        segments = self.videos[video_id]["content_segments"]
        for index, segment in enumerate(segments):
            if segment["segment_id"] == segment_id:
                return segment, index
        raise ValueError(f"找不到片段：{segment_id}")

    @staticmethod
    def group_for_role(role: str) -> str:
        for group, roles in REVIEW_GROUPS.items():
            if role in roles:
                return group
        return "OTHER"

    def gold_queue(self, group: str | None = None) -> list[dict]:
        saved = _read_json(self.gold_path, {}).get("reviews", {})
        queue = []
        for index, candidate in enumerate(self.gold_machine, 1):
            video_id = str(candidate["video_id"])
            segment, position = self._segment(video_id, candidate["segment_id"])
            segments = self.videos[video_id]["content_segments"]
            review_group = self.group_for_role(candidate.get("gold_role") or segment["primary_role"])
            if group and group != "ALL" and review_group != group:
                continue
            item = dict(candidate)
            item.update({
                "candidate_id": f"GOLD-{index:02d}",
                "review_group": review_group,
                "machine": segment,
                "previous_context": segments[position - 1] if position else None,
                "next_context": segments[position + 1] if position + 1 < len(segments) else None,
                "human_review": saved.get(f"GOLD-{index:02d}"),
            })
            queue.append(item)
        return queue

    def cta_queue(self) -> list[dict]:
        saved = _read_json(self.cta_path, {}).get("reviews", {})
        return [self._video_payload(video_id, saved.get(video_id)) for video_id in self.no_cta_ids]

    def replication_queue(self) -> list[dict]:
        saved = _read_json(self.replication_path, {}).get("reviews", {})
        gold_segments = {item["segment_id"]: item for item in self.gold_machine}
        machine_by_id = {str(item["video_id"]): item for item in self.replication_machine}
        result = []
        for video_id in self.replication_ids:
            item = self._video_payload(video_id, saved.get(video_id))
            item["machine_candidate"] = machine_by_id[video_id]
            item["gold_matches"] = [
                gold_segments[segment["segment_id"]]
                for segment in item["content_segments"] if segment["segment_id"] in gold_segments
            ]
            result.append(item)
        return result

    def _video_payload(self, video_id: str, review: dict | None) -> dict:
        video = dict(self.videos[video_id])
        video["human_review"] = review
        return video

    def save_gold(self, payload: dict) -> dict:
        candidate_id = str(payload.get("candidate_id", ""))
        candidates = {item["candidate_id"]: item for item in self.gold_queue()}
        if candidate_id not in candidates:
            raise ValueError("未知Gold候选")
        candidate = candidates[candidate_id]
        video_id = str(candidate["video_id"])
        duration = float(self.videos[video_id]["duration"])
        start, end = round(float(payload["start"]), 3), round(float(payload["end"]), 3)
        if not 0 <= start < end <= duration + 0.1:
            raise ValueError("边界超出视频范围或start>=end")
        grade = str(payload.get("material_grade", ""))
        boundary = str(payload.get("boundary_result", ""))
        editing_use = str(payload.get("editing_use", ""))
        role = str(payload.get("primary_role", ""))
        tags = payload.get("function_tags")
        errors = payload.get("error_reasons", [])
        if grade not in GOLD_GRADES or boundary not in BOUNDARY_RESULTS or editing_use not in EDITING_USE:
            raise ValueError("素材等级、边界和实际使用意愿均为必填")
        if role not in ROLES:
            raise ValueError("非法primary_role")
        if not isinstance(tags, list) or any(not isinstance(item, str) or len(item) > 80 for item in tags):
            raise ValueError("function_tags必须是短字符串数组")
        if not isinstance(errors, list) or any(item not in ERROR_REASONS for item in errors):
            raise ValueError("包含非法错误原因")
        record = {
            "candidate_id": candidate_id,
            "video_id": video_id,
            "segment_id": candidate["segment_id"],
            "material_grade": grade,
            "boundary_result": boundary,
            "start": start,
            "end": end,
            "primary_role": role,
            "function_tags": list(dict.fromkeys(tags)),
            "error_reasons": errors,
            "notes": str(payload.get("notes", ""))[:3000],
            "editing_use": editing_use,
            "review_group": candidate["review_group"],
            "reviewed_at": _now(),
        }
        document = _read_json(self.gold_path, self._base("gold_examples"))
        document.setdefault("reviews", {})[candidate_id] = record
        document["updated_at"] = record["reviewed_at"]
        document["gold_segments"] = [item for item in document["reviews"].values() if item.get("material_grade") == "GOLD"]
        _atomic_json(self.gold_path, document)
        self.write_progress()
        return record

    def save_cta(self, payload: dict) -> dict:
        video_id = str(payload.get("video_id", ""))
        if video_id not in self.no_cta_ids:
            raise ValueError("不属于CTA专项队列")
        result = str(payload.get("review_result", ""))
        if result not in CTA_RESULTS:
            raise ValueError("必须标记确实无CTA或AI漏掉CTA")
        duration = float(self.videos[video_id]["duration"])
        ranges = payload.get("cta_ranges", [])
        if not isinstance(ranges, list):
            raise ValueError("cta_ranges格式错误")
        normalized = []
        for item in ranges:
            start, end = round(float(item["start"]), 3), round(float(item["end"]), 3)
            cta_type = str(item.get("cta_type", ""))
            if not 0 <= start < end <= duration + 0.1 or cta_type not in CTA_TYPES:
                raise ValueError("CTA范围或类型非法")
            normalized.append({
                "start": start, "end": end, "cta_type": cta_type,
                "preceding_role": str(item.get("preceding_role", ""))[:80] or None,
                "notes": str(item.get("notes", ""))[:1000],
            })
        if result == "AI漏掉CTA" and not normalized:
            raise ValueError("AI漏掉CTA时至少新增一个时间范围")
        if result == "确实无CTA" and normalized:
            raise ValueError("确实无CTA时不能保留CTA范围")
        record = {
            "video_id": video_id,
            "review_result": result,
            "cta_ranges": normalized,
            **_product_times(payload, duration),
            "notes": str(payload.get("notes", ""))[:3000],
            "reviewed_at": _now(),
        }
        document = _read_json(self.cta_path, self._base("cta_special_review"))
        document.setdefault("reviews", {})[video_id] = record
        document["updated_at"] = record["reviewed_at"]
        _atomic_json(self.cta_path, document)
        self.write_progress()
        return record

    def save_replication(self, payload: dict) -> dict:
        video_id = str(payload.get("video_id", ""))
        if video_id not in self.replication_ids:
            raise ValueError("不属于复刻候选队列")
        clarity = int(payload.get("structure_clarity", 0))
        replaceability = int(payload.get("local_material_replaceability", 0))
        product_dependency = str(payload.get("original_product_dependency", ""))
        person_dependency = str(payload.get("original_person_case_dependency", ""))
        suitable = str(payload.get("suitable_for_first_replication", ""))
        if clarity not in range(1, 6) or replaceability not in range(1, 6):
            raise ValueError("评分必须为1-5")
        if product_dependency not in DEPENDENCY_LEVELS or person_dependency not in DEPENDENCY_LEVELS:
            raise ValueError("依赖程度必须为低/中/高")
        if suitable not in YES_NO:
            raise ValueError("是否适合首次复刻必须为是/否")
        duration = float(self.videos[video_id]["duration"])
        record = {
            "video_id": video_id,
            "structure_clarity": clarity,
            "local_material_replaceability": replaceability,
            "original_product_dependency": product_dependency,
            "original_person_case_dependency": person_dependency,
            "suitable_for_first_replication": suitable,
            **_product_times(payload, duration),
            "notes": str(payload.get("notes", ""))[:3000],
            "reviewed_at": _now(),
        }
        document = _read_json(self.replication_path, self._base("replication_candidate_review"))
        document.setdefault("reviews", {})[video_id] = record
        document["updated_at"] = record["reviewed_at"]
        _atomic_json(self.replication_path, document)
        self.write_progress()
        return record

    def progress(self) -> dict:
        gold_reviews = _read_json(self.gold_path, {}).get("reviews", {})
        cta_reviews = _read_json(self.cta_path, {}).get("reviews", {})
        replication_reviews = _read_json(self.replication_path, {}).get("reviews", {})
        grade_counts = Counter(item.get("material_grade") for item in gold_reviews.values())
        value = {
            "schema_version": REVIEW_VERSION,
            "generated_at": _now(),
            "gold": {"reviewed": len(gold_reviews), "total": 25},
            "cta": {"reviewed": len(cta_reviews), "total": 7},
            "replication": {"reviewed": len(replication_reviews), "total": 5},
            "material_grade_counts": {
                "GOLD": grade_counts["GOLD"], "USABLE": grade_counts["USABLE"],
                "REJECT": grade_counts["REJECT"], "未审核": 25 - len(gold_reviews),
            },
        }
        value["report_ready"] = all(value[key]["reviewed"] == value[key]["total"] for key in ("gold", "cta", "replication"))
        return value

    def write_progress(self) -> dict:
        value = self.progress()
        _atomic_json(self.progress_path, value)
        return value

    def generate_report(self) -> dict:
        progress = self.progress()
        if not progress["report_ready"]:
            raise ValueError("审核未完成：Gold需25/25、CTA需7/7、复刻候选需5/5")
        gold = _read_json(self.gold_path, {})["reviews"]
        cta = _read_json(self.cta_path, {})["reviews"]
        replication = _read_json(self.replication_path, {})["reviews"]
        candidates = {item["candidate_id"]: item for item in self.gold_queue()}
        role_rows = Counter()
        role_matches = Counter()
        for candidate_id, review in gold.items():
            machine_role = candidates[candidate_id]["machine"]["primary_role"]
            role_rows[machine_role] += 1
            if machine_role == review["primary_role"]:
                role_matches[machine_role] += 1
        consistency = {
            role: {"matched": role_matches[role], "total": total, "rate": round(role_matches[role] / total, 4)}
            for role, total in sorted(role_rows.items())
        }
        boundary = Counter(item["boundary_result"] for item in gold.values())
        editing = Counter(item["editing_use"] for item in gold.values())
        cta_results = Counter(item["review_result"] for item in cta.values())
        missed_types = Counter(r["cta_type"] for item in cta.values() for r in item["cta_ranges"])
        product_rows = {}
        for source in (cta, replication):
            for video_id, item in source.items():
                product_rows[video_id] = {key: item.get(key) for key in (
                    "product_first_mention", "product_first_visual", "product_first_sales_function"
                )}
        product_summary = {}
        for key in ("product_first_mention", "product_first_visual", "product_first_sales_function"):
            values = [row[key] for row in product_rows.values() if row[key] is not None]
            product_summary[key] = {"reviewed_count": len(values), "mean_seconds": round(mean(values), 3) if values else None}
        stats = {
            "schema_version": REVIEW_VERSION,
            "generated_at": _now(),
            "gold_grade_counts": progress["material_grade_counts"],
            "role_consistency": consistency,
            "boundary_counts": dict(boundary),
            "editing_use_counts": dict(editing),
            "editing_use_positive_rate": round((editing["会直接用"] + editing["修改后可用"]) / 25, 4),
            "cta_review_results": dict(cta_results),
            "cta_missed_types": dict(missed_types),
            "product_entry_times_by_video": product_rows,
            "product_entry_time_summary": product_summary,
            "replication_reviews": replication,
            "automatic_best_replication_selected": False,
        }
        _atomic_json(self.report_stats_path, stats)
        self.report_path.write_text(self._render_report(stats), encoding="utf-8")
        return {"report": str(self.report_path), "statistics": str(self.report_stats_path), "stats": stats}

    def _render_report(self, stats: dict) -> str:
        grades = stats["gold_grade_counts"]
        boundary = stats["boundary_counts"]
        editing = stats["editing_use_counts"]
        lines = [
            "# 带货爆款第一轮人工审核报告 V0.1", "",
            f"> 生成时间：{stats['generated_at']}。本报告仅使用 human_review/ 人工审核数据，不覆盖机器原始结果。", "",
            "## 1. Gold候选", "",
            f"- GOLD：{grades['GOLD']}；USABLE：{grades['USABLE']}；REJECT：{grades['REJECT']}。", "",
            "## 2. Primary role一致率", "", "|机器角色|一致|总数|一致率|", "|---|---:|---:|---:|",
        ]
        for role, item in stats["role_consistency"].items():
            lines.append(f"|{role}|{item['matched']}|{item['total']}|{item['rate']:.1%}|")
        lines += ["", "## 3. 边界", ""]
        lines.append(f"- 正确：{boundary.get('正确', 0)}；需要修改：{25 - boundary.get('正确', 0)}。")
        for label in BOUNDARY_RESULTS:
            lines.append(f"- {label}：{boundary.get(label, 0)}")
        lines += ["", "## 4. 实际剪辑使用意愿", ""]
        for label in EDITING_USE:
            lines.append(f"- {label}：{editing.get(label, 0)}")
        lines.append(f"- 会直接用或修改后可用：{stats['editing_use_positive_rate']:.1%}")
        lines += ["", "## 5. CTA专项", ""]
        lines.append(f"- 真正无CTA：{stats['cta_review_results'].get('确实无CTA', 0)}")
        lines.append(f"- AI漏识别：{stats['cta_review_results'].get('AI漏掉CTA', 0)}")
        lines.append("- 漏识别类型：" + ("、".join(f"{k}×{v}" for k, v in stats["cta_missed_types"].items()) or "无"))
        lines += ["", "## 6. 人工产品进入时间", ""]
        for key, label in (
            ("product_first_mention", "首次提到产品"), ("product_first_visual", "首次画面出现产品"),
            ("product_first_sales_function", "首次承担销售功能"),
        ):
            item = stats["product_entry_time_summary"][key]
            value = f"平均{item['mean_seconds']:.2f}秒" if item["mean_seconds"] is not None else "未填写"
            lines.append(f"- {label}：{value}（有效审核{item['reviewed_count']}条）")
        lines += ["", "## 7. 五条复刻候选人工结果", "", "|视频|结构清晰度|本地替代|商品依赖|人物/案例依赖|适合首次复刻|备注|", "|---|---:|---:|---|---|---|---|"]
        for video_id in self.replication_ids:
            item = stats["replication_reviews"][video_id]
            notes = item["notes"].replace("|", "｜").replace("\n", " ")
            lines.append(
                f"|{video_id}.mp4|{item['structure_clarity']}|{item['local_material_replaceability']}|"
                f"{item['original_product_dependency']}|{item['original_person_case_dependency']}|"
                f"{item['suitable_for_first_replication']}|{notes}|"
            )
        lines += ["", "> 不自动选择“最佳复刻视频”；最终选择完全由人工审核数据和负责人决定。", ""]
        return "\n".join(lines)
