"""适配器命令行入口。"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .data_collector import import_performance_export
from .discovery import discover, localhost_http_status
from .models import PublishJob, PublishMode
from .service import XiaovcatService
from .ui_driver import PywinautoDriver, load_config


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = PACKAGE_DIR / "config.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="小V猫发布与数据回流适配器 V0.1")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db", help="初始化独立 operations.db")
    discover_parser = commands.add_parser("discover", help="只读发现本机小V猫")
    discover_parser.add_argument("--output")
    create = commands.add_parser("create-job", help="创建一条 PublishJob")
    create.add_argument("--content-id", required=True)
    create.add_argument("--video", required=True)
    create.add_argument("--title", required=True)
    create.add_argument("--description", default="")
    create.add_argument("--platform", required=True)
    create.add_argument("--account", required=True)
    create.add_argument("--product-name", default="")
    create.add_argument("--product-id")
    create.add_argument("--cover")
    create.add_argument("--mode", choices=[mode.value for mode in PublishMode], default="NOW")
    create.add_argument("--scheduled-at")
    run = commands.add_parser("run", help="执行一条任务；默认 dry-run")
    run.add_argument("job_id")
    sync = commands.add_parser("sync-export", help="解析作品 CSV/Excel 并回写")
    sync.add_argument("path")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    service = XiaovcatService(config_path)
    if args.command == "init-db":
        with service.store.connect() as conn:
            tables = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )]
        print(json.dumps({"operations_db": str(service.store.path), "tables": tables},
                         ensure_ascii=False, indent=2))
        return 0
    if args.command == "discover":
        report = discover(config)
        for port in report.localhost_ports:
            report.notes.append(f"localhost:{port} GET / -> {localhost_http_status(port)}")
        payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(payload + "\n", encoding="utf-8")
        print(payload)
        return 0
    if args.command == "create-job":
        job = PublishJob.create(
            content_id=args.content_id,
            video_path=args.video,
            cover_path=args.cover,
            title=args.title,
            description=args.description,
            platform=args.platform,
            account_name=args.account,
            product_name=args.product_name,
            product_link_or_identifier=args.product_id,
            publish_mode=args.mode,
            scheduled_at=args.scheduled_at,
        )
        service.queue.enqueue(job)
        print(json.dumps(job.to_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "run":
        driver = PywinautoDriver(config, PACKAGE_DIR / "results")
        result = service.run_jobs([args.job_id], driver)[0]
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))
        return 0 if result.status.value in {"PUBLISHED", "DRY_RUN_READY"} else 2
    if args.command == "sync-export":
        result = import_performance_export(args.path, service.store)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

