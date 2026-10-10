"""导出受控源码快照；不写业务源码、生产配置、数据库或素材。"""
import argparse
import ast
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "development_link"
SNAPSHOT = AREA / "snapshot"
BARE = AREA / "XunZhen.git"
MODULES = {"asset_inventory", "auto_remake", "benchmark", "bestseller_analysis",
           "clip_index", "content_pool", "dino_index", "jianying_auto", "publish_planner",
           "speech_search", "startup_pipeline", "template_editing", "tests", "video_recipe",
           "xiaovcat_adapter", "development_link", "startup_render"}
SKIP = {".git", "node_modules", "__pycache__", "deps", "runtime", "results", "outputs",
        "models", "thumbnails", "test_videos", "cache", "text_cache", "snapshot", "XunZhen.git",
        "downloads", "weights", "backups", "source_backups", "data", "reports", "frames"}
EXTS = {".py", ".ps1", ".bat", ".md", ".sql", ".css", ".html", ".js", ".ts", ".toml"}
JSON_ALLOW = {"jianying_auto/combo_skeleton.json", "startup_pipeline/export_config.json"}
IGNORE = """
# 开发快照安全排除；生产配置不进入版本库。
.venv*/
node_modules/
**/deps/
**/runtime/
**/results/
**/outputs/
**/cache/
**/.ui-*/
**/tmp*/
*.db
*.sqlite
*.sqlite3
*.db-*
*.private.json
*.bak
*.mp4
*.mov
*.ts
*.mkv
*.wav
*.faiss
*.pkl
*.bin
*.pt
*.onnx
*.exe
.env
.env.*
!.env.example
**/secrets.toml
config.json
jianying_auto/jianying_source_folders.json
benchmark/experiments/dino_july_web/search_config.json
development_link/verification/
development_link/snapshot/
development_link/XunZhen.git/
"""


def selected():
    for folder, dirs, files in os.walk(ROOT, followlinks=False):
        base = Path(folder)
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith((".", "tmp"))
                   and not (base / d).is_symlink() and not (base / d).is_junction()
                   and (base != ROOT or d in MODULES)]
        for name in sorted(files):
            path = base / name
            rel = path.relative_to(ROOT).as_posix()
            if path.is_symlink() or path.stat().st_size > 2_000_000:
                continue
            if name.endswith(".bak") or ".private." in name or name.startswith("_audit_"):
                continue
            if path.suffix in EXTS or name == ".gitignore" or name == "USAGE.txt" and rel.startswith("development_link/") or name.startswith("requirements") and name.endswith(".txt") or rel in JSON_ALLOW or name.endswith(".example.json"):
                yield path, rel


def scan(path, rel):
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s*\n[A-Za-z0-9+/]{20}", content):
        raise ValueError("私钥标记，拒绝同步: " + rel)
    if path.suffix != ".py":
        return
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str) or not value.value:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = [getattr(t, "id", getattr(t, "attr", "")) for t in targets]
        if any(n.lower() in {"password", "api_key", "access_token", "cookie", "private_key", "client_secret"} for n in names):
            fixture = any(v in value.value.lower() for v in ("test", "fixture", "example", "dummy"))
            if not fixture:
                raise ValueError(f"疑似凭据常量，需人工审核（未打印值）: {rel}:{node.lineno}")


def git(*args, cwd=SNAPSHOT):
    return subprocess.run(["git", "-c", "safe.directory=" + str(SNAPSHOT),
                           "-c", "safe.directory=" + str(BARE), *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def run():
    chosen = list(selected())
    for path, rel in chosen:
        scan(path, rel)
    SNAPSHOT.mkdir(parents=True, exist_ok=True)
    old_manifest = SNAPSHOT / "SOURCE_MANIFEST.json"
    old = json.loads(old_manifest.read_text(encoding="utf-8")) if old_manifest.exists() else {"files": []}
    names = {rel for _, rel in chosen}
    # 只删除本工具上次明确生成的快照文件，不触碰源目录/未登记文件。
    for row in old["files"]:
        rel = row["path"]
        target = (SNAPSHOT / rel).resolve()
        if target.is_relative_to(SNAPSHOT.resolve()) and rel not in names and target.is_file():
            target.unlink()
    manifest = []
    for path, rel in chosen:
        target = SNAPSHOT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        manifest.append({"path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size})
    original_ignore = (ROOT / ".gitignore").read_text(encoding="utf-8-sig")
    (SNAPSHOT / ".gitignore").write_text(original_ignore + IGNORE, encoding="utf-8")
    manifest = [r for r in manifest if r["path"] != ".gitignore"]
    manifest.append({"path": ".gitignore", "sha256": hashlib.sha256((SNAPSHOT / ".gitignore").read_bytes()).hexdigest(), "size": (SNAPSHOT / ".gitignore").stat().st_size})
    old_manifest.write_text(json.dumps({"source_root": str(ROOT), "original_git_history": False, "files": sorted(manifest, key=lambda x: x["path"])}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not (SNAPSHOT / ".git").exists():
        git("init", "-b", "main")
    git("add", "--all")
    if git("diff", "--cached", "--name-only"):
        git("-c", "user.name=XunZhen Source Snapshot", "-c", "user.email=snapshot@localhost", "commit", "-m", "Vetted server source snapshot")
    if not BARE.exists():
        git("clone", "--bare", "--no-hardlinks", str(SNAPSHOT), str(BARE), cwd=AREA)
    else:
        git("push", str(BARE), "main:main")
    git("update-server-info", cwd=BARE)
    print(json.dumps({"files": len(manifest), "bytes": sum(r["size"] for r in manifest), "commit": git("rev-parse", "HEAD"), "snapshot": str(SNAPSHOT), "bare": str(BARE)}, ensure_ascii=False))


if __name__ == "__main__":
    run()
