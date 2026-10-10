"""仅初始化2060S隔离开发库，调用既有迁移，不复制账号或生产数据。"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if ROOT != Path(r"D:\Projects\XunZhen"):
    raise SystemExit("2060S development checkout only")
sys.path.insert(0, str(ROOT))
from publish_planner.storage import PlannerStore
from startup_pipeline.service import StartupPipeline

config = json.loads((ROOT / "xiaovcat_adapter/config.json").read_text(encoding="utf-8-sig"))
if config.get("real_publish_enabled") is not False:
    raise SystemExit("Real publishing must remain disabled")
store = PlannerStore()
if not store.path.is_relative_to((ROOT / "development_link/verification").resolve()):
    raise SystemExit("Refusing migration outside isolated development directory")
result = StartupPipeline(store).migrate()
with store.connect() as db:
    counts = {name: db.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0]
              for name in ("employees", "accounts", "publish_jobs")}
print(json.dumps({"database": str(store.path), "migration": result, "counts": counts,
                  "production_data_copied": False, "real_publish_attempts": 0}, ensure_ascii=False))
