"""本地 Content Segment 人工Review界面。

用法：python -B -m bestseller_analysis.review_server <结果目录> --port 8504
只监听127.0.0.1；反馈保存到结果目录 review_feedback.json。
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlparse

from .business_taxonomy import ROLES


HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>带货 Content Segment Review</title>
<style>
:root{color-scheme:dark;--bg:#101216;--panel:#1a1e25;--line:#333b48;--text:#f4f6f8;--muted:#aab4c3;--accent:#ffb347;--good:#56d68b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft YaHei",system-ui,sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;gap:14px;align-items:center;position:sticky;top:0;background:#101216ee;z-index:2}
h1{font-size:18px;margin:0}select,input,textarea,button{background:#242a33;color:var(--text);border:1px solid #46505f;border-radius:6px;padding:7px}button{cursor:pointer}button.primary{background:#8a5619;border-color:var(--accent)}
.layout{display:grid;grid-template-columns:minmax(420px,44%) 1fr;height:calc(100vh - 58px)}.left,.right{overflow:auto;padding:16px}.left{border-right:1px solid var(--line)}video{width:100%;max-height:44vh;background:#000;border-radius:8px}.meta{color:var(--muted);font-size:13px;margin:8px 0 14px}.segment{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:10px;margin:8px 0;cursor:pointer}.segment.active{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}.role{color:var(--accent);font-weight:700}.time{color:var(--muted);font-variant-numeric:tabular-nums}.transcript{margin-top:6px;line-height:1.55}.grid{display:grid;grid-template-columns:150px 1fr;gap:10px;align-items:center}.grid textarea{min-height:72px}.wide{width:100%}.evidence{white-space:pre-wrap;background:#12151a;border:1px solid var(--line);padding:10px;border-radius:6px;max-height:240px;overflow:auto;font-size:12px}.ok{color:var(--good)}.warn{color:var(--accent)}
@media(max-width:900px){.layout{display:block;height:auto}.left{border-right:0}.grid{grid-template-columns:1fr}}
</style></head><body>
<header><h1>带货 Content Segment Review</h1><select id="videoSelect"></select><button id="reload">刷新</button><span id="status" class="meta"></span></header>
<main class="layout"><section class="left"><video id="player" controls preload="metadata"></video><div id="videoMeta" class="meta"></div><div id="segments"></div></section>
<section class="right"><h2 id="segmentTitle">选择一个片段</h2><div id="editor" hidden>
<div class="grid">
<label>开始/结束秒</label><div><input id="start" type="number" step="0.01"> <input id="end" type="number" step="0.01"> <button id="jump">跳到片段</button></div>
<label>Primary role</label><select id="role"></select>
<label>Function tags</label><input id="tags" class="wide" placeholder="逗号分隔">
<label>Product visible</label><select id="product"><option value="null">不确定</option><option value="true">是</option><option value="false">否</option></select>
<label>Product display type</label><input id="display" class="wide">
<label>Trust mechanism</label><input id="trust" class="wide" placeholder="逗号分隔">
<label>边界/标签错误原因</label><textarea id="error" class="wide"></textarea>
<label>人工备注</label><textarea id="notes" class="wide"></textarea>
<label>批准为Gold Data</label><input id="approved" type="checkbox">
</div><h3>原话术</h3><div id="transcript" class="transcript"></div><h3>AI理由/证据</h3><div id="evidence" class="evidence"></div>
<p><button id="save" class="primary">保存人工修改</button> <span id="saveStatus"></span></p></div></section></main>
<script>
const $=id=>document.getElementById(id); let current=null, selected=null;
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function loadVideos(){const data=await (await fetch('/api/videos')).json(); $('videoSelect').innerHTML=data.videos.map(v=>`<option value="${esc(v.video_id)}">${esc(v.file_name)}</option>`).join(''); if(data.videos.length) await loadVideo(data.videos[0].video_id)}
async function loadVideo(id){current=await (await fetch('/api/video/'+encodeURIComponent(id))).json(); selected=null; $('player').src='/media/'+encodeURIComponent(id); $('videoMeta').textContent=`${current.file_name}｜${current.duration.toFixed(2)}秒｜${current.content_segments.length}个Content Segment`; renderSegments(); $('editor').hidden=true}
function merged(seg){return Object.assign({},seg,current.feedback?.[seg.segment_id]||{})}
function renderSegments(){ $('segments').innerHTML=current.content_segments.map(seg=>{const x=merged(seg);return `<div class="segment ${selected===seg.segment_id?'active':''}" data-id="${esc(seg.segment_id)}"><span class="time">${x.start.toFixed(2)}–${x.end.toFixed(2)}</span> <span class="role">${esc(x.primary_role)}</span>${x.approved?' <span class="ok">✓ Gold</span>':''}<div class="transcript">${esc(seg.transcript.slice(0,130))}</div></div>`}).join(''); document.querySelectorAll('.segment').forEach(el=>el.onclick=()=>selectSegment(el.dataset.id))}
function selectSegment(id){selected=id;renderSegments();const base=current.content_segments.find(x=>x.segment_id===id),x=merged(base);$('editor').hidden=false;$('segmentTitle').textContent=id;$('start').value=x.start;$('end').value=x.end;$('role').value=x.primary_role;$('tags').value=(x.function_tags||[]).join(',');$('product').value=x.product_visible===true?'true':x.product_visible===false?'false':'null';$('display').value=x.product_display_type||'';$('trust').value=(x.trust_mechanism||[]).join(',');$('error').value=x.error_reason||'';$('notes').value=x.notes||'';$('approved').checked=!!x.approved;$('transcript').textContent=base.transcript;$('evidence').textContent=JSON.stringify(base.evidence,null,2);$('player').currentTime=x.start;$('player').play().catch(()=>{})}
async function save(){if(!selected)return;const body={video_id:current.video_id,segment_id:selected,start:+$('start').value,end:+$('end').value,primary_role:$('role').value,function_tags:$('tags').value.split(',').map(x=>x.trim()).filter(Boolean),product_visible:$('product').value==='null'?null:$('product').value==='true',product_display_type:$('display').value||null,trust_mechanism:$('trust').value.split(',').map(x=>x.trim()).filter(Boolean),error_reason:$('error').value,notes:$('notes').value,approved:$('approved').checked};const r=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();$('saveStatus').textContent=r.ok?'已保存':'失败：'+data.error;$('saveStatus').className=r.ok?'ok':'warn';if(r.ok){current.feedback[selected]=body;renderSegments()}}
$('videoSelect').onchange=e=>loadVideo(e.target.value);$('reload').onclick=()=>loadVideo($('videoSelect').value);$('jump').onclick=()=>$('player').currentTime=+$('start').value;$('save').onclick=save;for(const role of __ROLES__){$('role').insertAdjacentHTML('beforeend',`<option>${role}</option>`)}loadVideos().catch(e=>$('status').textContent=e);
</script></body></html>""".replace("__ROLES__", json.dumps(ROLES, ensure_ascii=False))


def _atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


class ReviewData:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        self.feedback_path = self.root / "review_feedback.json"
        self.videos = {}
        for path in sorted((self.root / "videos").glob("*/business_analysis.json"), key=lambda p: p.parent.name):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.videos[data["video_id"]] = data
        if not self.videos:
            raise ValueError("结果目录没有business_analysis.json")

    def feedback(self) -> dict:
        if not self.feedback_path.exists():
            return {"schema_version": "1.0", "segments": {}}
        return json.loads(self.feedback_path.read_text(encoding="utf-8"))

    def save(self, payload: dict) -> None:
        video_id, segment_id = str(payload.get("video_id", "")), str(payload.get("segment_id", ""))
        if video_id not in self.videos:
            raise ValueError("未知video_id")
        base = next((item for item in self.videos[video_id]["content_segments"] if item["segment_id"] == segment_id), None)
        if base is None:
            raise ValueError("未知segment_id")
        start, end = float(payload["start"]), float(payload["end"])
        if not 0 <= start < end <= self.videos[video_id]["duration"] + 0.1:
            raise ValueError("边界超出视频范围或start>=end")
        role = str(payload.get("primary_role", ""))
        if role not in ROLES:
            raise ValueError("非法primary_role")
        for field in ("function_tags", "trust_mechanism"):
            if not isinstance(payload.get(field), list) or any(not isinstance(item, str) or len(item) > 80 for item in payload[field]):
                raise ValueError(f"{field}必须是短字符串数组")
        record = {
            "video_id": video_id, "segment_id": segment_id, "start": round(start, 3), "end": round(end, 3),
            "primary_role": role, "function_tags": payload["function_tags"],
            "product_visible": payload.get("product_visible"),
            "product_display_type": (str(payload.get("product_display_type") or "")[:120] or None),
            "trust_mechanism": payload["trust_mechanism"],
            "error_reason": str(payload.get("error_reason", ""))[:1000],
            "notes": str(payload.get("notes", ""))[:2000], "approved": bool(payload.get("approved", False)),
        }
        feedback = self.feedback()
        feedback.setdefault("segments", {})[segment_id] = record
        _atomic_json(self.feedback_path, feedback)
        self.export_reviewed(feedback)

    def export_reviewed(self, feedback=None) -> None:
        feedback = feedback or self.feedback()
        records = feedback.get("segments", {})
        reviewed, gold = [], []
        for video in self.videos.values():
            for base in video["content_segments"]:
                correction = records.get(base["segment_id"])
                if not correction:
                    continue
                merged = dict(base)
                merged.update(correction)
                merged["machine_primary_role"] = base["primary_role"]
                merged["human_reviewed"] = True
                reviewed.append(merged)
                if correction.get("approved"):
                    merged["gold_status"] = "human_approved"
                    gold.append(merged)
        _atomic_json(self.root / "reviewed_segments.json", {"schema_version": "1.0", "segments": reviewed})
        _atomic_json(self.root / "human_gold_data.json", {"schema_version": "1.0", "status": "human_approved_only", "segments": gold})


def make_handler(data: ReviewData):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BestsellerReview/1.0"

        def log_message(self, fmt, *args):
            print(fmt % args, flush=True)

        def local_request(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def send_json(self, value, status=200):
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            if not self.local_request():
                self.send_json({"error": "仅限127.0.0.1访问"}, 403); return
            path = unquote(urlparse(self.path).path)
            if path in {"/", "/review.html"}:
                body = HTML.encode("utf-8")
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            if path == "/api/videos":
                self.send_json({"videos": [{"video_id": item["video_id"], "file_name": item["file_name"], "duration": item["duration"]} for item in data.videos.values()]}); return
            match = re.fullmatch(r"/api/video/([^/]+)", path)
            if match:
                video_id = match.group(1)
                if video_id not in data.videos: self.send_json({"error": "not found"}, 404); return
                value = dict(data.videos[video_id]); value["feedback"] = {key: item for key, item in data.feedback().get("segments", {}).items() if item.get("video_id") == video_id}
                self.send_json(value); return
            match = re.fullmatch(r"/media/([^/]+)", path)
            if match:
                self.serve_media(match.group(1)); return
            self.send_error(404)

        def serve_media(self, video_id):
            if video_id not in data.videos: self.send_error(404); return
            target = Path(data.videos[video_id]["file_path"]).resolve(strict=True)
            size = target.stat().st_size
            start, end = 0, size - 1
            range_header = self.headers.get("Range")
            if range_header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
                if not match: self.send_error(416); return
                if match.group(1): start = int(match.group(1))
                if match.group(2): end = min(end, int(match.group(2)))
                if start > end or start >= size: self.send_error(416); return
                self.send_response(206); self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "video/mp4")
            self.send_header("Accept-Ranges", "bytes"); self.send_header("Content-Length", str(end - start + 1)); self.end_headers()
            with target.open("rb") as stream:
                stream.seek(start); remaining = end - start + 1
                while remaining > 0:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk: break
                    try: self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError): break
                    remaining -= len(chunk)

        def do_POST(self):
            if not self.local_request() or self.headers.get("Origin") != f"http://127.0.0.1:{self.server.server_port}":
                self.send_json({"error": "仅接受本页同源反馈"}, 403); return
            if urlparse(self.path).path != "/api/save": self.send_error(404); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if self.headers.get("Content-Type") != "application/json": raise ValueError("请求格式错误")
                if length <= 0 or length > 128 * 1024: raise ValueError("请求大小非法")
                payload = json.loads(self.rfile.read(length).decode("utf-8")); data.save(payload)
                self.send_json({"status": "saved"})
            except Exception as exc:
                self.send_json({"error": str(exc)}, 400)
    return Handler


def write_review_html(output: Path) -> None:
    (output / "review.html").write_text(HTML, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="本地带货Content Segment人工Review")
    parser.add_argument("output", type=Path)
    parser.add_argument("--port", type=int, default=8504)
    args = parser.parse_args()
    try:
        data = ReviewData(args.output)
        data.export_reviewed()
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(data))
    except Exception as exc:
        print(f"启动失败：{exc}", file=sys.stderr); return 1
    print(f"Review: http://127.0.0.1:{args.port}/", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
