"""独立进程跑回归并保存机器结果，避免AppTest同名模块污染。"""
from datetime import datetime
import json
import os
import re
import subprocess
import sys
from .storage import ROOT


def run(results=None):
    results = results or ROOT / "xiaovcat_adapter/results/group_planner_v01"
    results.mkdir(parents=True, exist_ok=True)
    groups = [
        ("planner", ["-m", "unittest", "discover", "-s", "publish_planner/tests", "-v"]),
        ("adapter", ["-m", "unittest", "discover", "-s", "xiaovcat_adapter/tests", "-v"]),
        ("worker", ["-m", "unittest", "discover", "-s", "xiaovcat_adapter/desktop_worker/tests", "-v"]),
        ("workspace_ui", ["-m", "unittest", "discover", "-s", "benchmark/experiments/dino_july_web", "-p", "test_ui.py", "-v"]),
    ]
    report = {"captured_at": datetime.now().astimezone().isoformat(), "groups": [], "no_live_worker_calls": True}
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    for label, args in groups:
        done = subprocess.run([sys.executable, "-X", "utf8", *args], cwd=ROOT, env=env,
                              capture_output=True, timeout=120)
        output = (done.stdout + done.stderr).decode("utf-8", errors="replace")
        log = results / ("test_" + label + ".log")
        log.write_text(output, encoding="utf-8")
        matches = re.search(r"Ran (\d+) tests?", output)
        row = {"name": label, "passed": done.returncode == 0,
               "test_count": int(matches[1]) if matches else None, "log": str(log)}
        report["groups"].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    report["all_passed"] = all(r["passed"] for r in report["groups"])
    report["test_count"] = sum(r["test_count"] or 0 for r in report["groups"])
    (results / "TEST_RESULTS.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    run()
