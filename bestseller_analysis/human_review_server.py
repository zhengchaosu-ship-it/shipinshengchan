"""带货爆款第一轮人工审核 V0.1 本地Web界面。"""
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
from .human_review import HumanReviewStore


HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>带货爆款第一轮人工审核 V0.1</title>
<style>
:root{color-scheme:dark;--bg:#0d1015;--panel:#171c24;--panel2:#202733;--line:#344052;--text:#f4f6f9;--muted:#9caabc;--gold:#f3bb4b;--blue:#5ea9ff;--green:#55d68b;--red:#ff7777}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px "Microsoft YaHei",system-ui,sans-serif}button,input,select,textarea{font:inherit;background:#242c38;color:var(--text);border:1px solid #46546a;border-radius:6px;padding:7px}button{cursor:pointer}button.primary{background:#8d5b14;border-color:var(--gold)}button:disabled{opacity:.45;cursor:not-allowed}a{color:inherit;text-decoration:none}
header{position:sticky;top:0;z-index:5;background:#0d1015f2;border-bottom:1px solid var(--line);padding:10px 16px}.top{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.top h1{font-size:18px;margin:0 10px 0 0}.nav{display:flex;gap:5px}.nav a{padding:7px 10px;border-radius:6px;background:var(--panel2)}.nav a.active{background:#8d5b14}.progress{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;color:var(--muted)}.counts b{color:var(--text)}
main{display:grid;grid-template-columns:minmax(440px,44%) 1fr;height:calc(100vh - 105px)}.left,.right{padding:14px;overflow:auto}.left{border-right:1px solid var(--line)}video{width:100%;max-height:44vh;background:#000;border-radius:8px}.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0}.meta,.muted{color:var(--muted)}.queue,.timeline{margin-top:10px}.card,.segment{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:9px;margin:7px 0;cursor:pointer}.card.active,.segment.active{border-color:var(--gold);box-shadow:0 0 0 1px var(--gold)}.segment.proof{border-left:4px solid var(--green)}.segment.cta{border-left:4px solid var(--red)}.segment.product{border-left:4px solid var(--blue)}.segment.goldmatch{box-shadow:inset 0 0 0 1px var(--gold)}.role{color:var(--gold);font-weight:700}.time{font-variant-numeric:tabular-nums;color:var(--muted)}.text{line-height:1.55;margin-top:5px}.badge{display:inline-block;padding:2px 6px;border-radius:10px;background:#303b4b;margin:2px;font-size:12px}.ok{color:var(--green)}.warn{color:var(--gold)}.error{color:var(--red)}
h2{font-size:18px;margin:4px 0 12px}h3{font-size:15px;margin:16px 0 7px}.form{display:grid;grid-template-columns:170px 1fr;gap:9px;align-items:start}.form .full{width:100%}.form textarea{min-height:74px}.machine,.context{white-space:pre-wrap;background:#11151c;border:1px solid var(--line);border-radius:7px;padding:9px;line-height:1.5}.checks{display:flex;gap:8px;flex-wrap:wrap}.checks label{background:#222a35;padding:5px 7px;border-radius:6px}.radio{display:flex;gap:10px;flex-wrap:wrap}.row{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.cta-row{display:grid;grid-template-columns:90px 90px 130px 1fr 60px;gap:6px;margin:6px 0}.product-times{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.product-times label{display:grid;gap:4px}.report{margin-left:auto}.hidden{display:none!important}
@media(max-width:950px){main{display:block;height:auto}.left{border:0}.form{grid-template-columns:1fr}.cta-row{grid-template-columns:1fr 1fr}.product-times{grid-template-columns:1fr}}
</style></head><body>
<header><div class="top"><h1>第一轮人工审核 V0.1</h1><nav class="nav"><a href="/gold" data-mode="gold">Gold审核</a><a href="/cta" data-mode="cta">CTA专项</a><a href="/replication" data-mode="replication">复刻候选</a></nav><button id="reportBtn" class="report">生成第一轮审核报告</button><span id="message"></span></div><div id="progress" class="progress"></div></header>
<main><section class="left"><div id="queueTools" class="toolbar"></div><video id="player" controls preload="metadata"></video><div id="videoMeta" class="meta"></div><div id="queue" class="queue"></div></section><section class="right"><div id="editor"><h2>正在加载…</h2></div></section></main>
<script>
const ROLES=__ROLES__, $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const mode=location.pathname.startsWith('/cta')?'cta':location.pathname.startsWith('/replication')?'replication':'gold';let items=[],selected=null,progress=null;
document.querySelectorAll('.nav a').forEach(a=>a.classList.toggle('active',a.dataset.mode===mode));
async function api(url,options){const r=await fetch(url,options),data=await r.json();if(!r.ok)throw new Error(data.error||'请求失败');return data}
function fmt(sec){sec=Number(sec||0);const h=Math.floor(sec/3600),m=Math.floor((sec%3600)/60),s=(sec%60).toFixed(1);return h?`${h}:${String(m).padStart(2,'0')}:${String(s).padStart(4,'0')}`:`${m}:${String(s).padStart(4,'0')}`}
function roleClass(role){return role.startsWith('CTA_')?'cta':['PROOF','TESTIMONIAL','CALL_RESULT','AUTHORITY','TRUST'].includes(role)?'proof':role.startsWith('PRODUCT_')?'product':''}
function productTimes(review={}){return `<div class="product-times"><label>首次提到产品（秒）<input id="pMention" type="number" min="0" step="0.01" value="${review.product_first_mention??''}"></label><label>首次画面出现产品（秒）<input id="pVisual" type="number" min="0" step="0.01" value="${review.product_first_visual??''}"></label><label>首次承担销售功能（秒）<input id="pSales" type="number" min="0" step="0.01" value="${review.product_first_sales_function??''}"></label></div>`}
function productPayload(){return {product_first_mention:$('pMention').value||null,product_first_visual:$('pVisual').value||null,product_first_sales_function:$('pSales').value||null}}
async function loadProgress(){progress=await api('/api/progress');const c=progress.material_grade_counts;$('progress').innerHTML=`<span>Gold：<b>${progress.gold.reviewed} / 25</b></span><span>CTA专项：<b>${progress.cta.reviewed} / 7</b></span><span>复刻候选：<b>${progress.replication.reviewed} / 5</b></span><span class="counts">GOLD <b>${c.GOLD}</b>｜USABLE <b>${c.USABLE}</b>｜REJECT <b>${c.REJECT}</b>｜未审核 <b>${c['未审核']}</b></span>`;$('reportBtn').disabled=!progress.report_ready;$('reportBtn').title=progress.report_ready?'可生成':'需完成25+7+5项审核后生成'}
function setVideo(item){$('player').src='/media/'+encodeURIComponent(item.video_id);$('videoMeta').textContent=`${item.file_name}｜总时长 ${fmt(item.duration||0)}`}
function jump(t){$('player').currentTime=Number(t);$('player').play().catch(()=>{})}
function timeline(video,goldIds=new Set()){return `<div class="timeline">${video.content_segments.map(s=>`<div class="segment ${roleClass(s.primary_role)} ${goldIds.has(s.segment_id)?'goldmatch':''}" onclick="jump(${s.start})"><span class="time">${fmt(s.start)}–${fmt(s.end)}</span> <span class="role">${esc(s.primary_role)}</span>${goldIds.has(s.segment_id)?' <span class="badge">Gold候选</span>':''}<div class="text">${esc(s.transcript)}</div></div>`).join('')}</div>`}
function option(value,label,current){return `<option value="${esc(value)}" ${value===current?'selected':''}>${esc(label??value)}</option>`}
async function init(){await loadProgress();if(mode==='gold')await loadGold();else if(mode==='cta')await loadCTA();else await loadReplication()}

async function loadGold(group='ALL'){items=await api('/api/gold?group='+group);$('queueTools').innerHTML=`<label>员工筛选 <select id="group"><option value="ALL">全部25条</option><option value="A">审核组A</option><option value="B">审核组B</option><option value="C">审核组C</option></select></label><span class="muted">A：HOOK/CONSULT/PRODUCT｜B：PROOF/TRUST｜C：CTA</span>`;$('group').value=group;$('group').onchange=e=>loadGold(e.target.value);renderGoldQueue();if(items.length)selectGold(items[0].candidate_id)}
function renderGoldQueue(){ $('queue').innerHTML=items.map(x=>`<div class="card ${selected===x.candidate_id?'active':''}" onclick="selectGold('${x.candidate_id}')"><b>${x.candidate_id}</b> <span class="badge">组${x.review_group}</span> <span class="role">${esc(x.gold_role)}</span> ${x.human_review?`<span class="ok">✓ ${esc(x.human_review.material_grade)}</span>`:'<span class="warn">未审核</span>'}<div class="text">${esc(x.transcript)}</div></div>`).join('')}
function selectGold(id){selected=id;const x=items.find(i=>i.candidate_id===id),m=x.machine,r=x.human_review||{};renderGoldQueue();setVideo({video_id:x.video_id,file_name:x.file_name,duration:0});$('videoMeta').textContent=`${x.file_name}｜${fmt(x.start)}–${fmt(x.end)}｜${x.candidate_id}｜审核组${x.review_group}`;jump(r.start??x.start);$('editor').innerHTML=`<h2>${x.candidate_id} · ${esc(x.gold_role)}</h2><h3>前一段上下文</h3><div class="context">${x.previous_context?`[${esc(x.previous_context.primary_role)} ${fmt(x.previous_context.start)}–${fmt(x.previous_context.end)}] ${esc(x.previous_context.transcript)}`:'视频开始'}</div><h3>候选原话术</h3><div class="context">${esc(x.transcript)}</div><h3>后一段上下文</h3><div class="context">${x.next_context?`[${esc(x.next_context.primary_role)} ${fmt(x.next_context.start)}–${fmt(x.next_context.end)}] ${esc(x.next_context.transcript)}`:'视频结束'}</div><h3>机器判断</h3><div class="machine">primary_role: ${esc(m.primary_role)}\nfunction_tags: ${esc((m.function_tags||[]).join(', '))}\nproduct_entry_type: ${esc(m.product_entry_type||'-')}\ntrust_mechanism: ${esc((m.trust_mechanism||[]).join(', ')||'-')}\nsales_mechanism: ${esc((m.sales_mechanism||[]).join(', ')||'-')}\nconfidence: ${esc(m.confidence)}\nAI reason: ${esc(x.why_good_candidate)}\nevidence: ${esc(JSON.stringify(m.evidence,null,2))}</div><h3>人工审核</h3><div class="form"><label>素材等级</label><select id="grade"><option value="">请选择</option>${['GOLD','USABLE','REJECT'].map(v=>option(v,v,r.material_grade)).join('')}</select><label>边界</label><select id="boundary"><option value="">请选择</option>${['正确','起点需要调整','终点需要调整','起止都需要调整'].map(v=>option(v,v,r.boundary_result)).join('')}</select><label>start / end</label><div class="row"><input id="start" type="number" step="0.01" value="${r.start??x.start}"><input id="end" type="number" step="0.01" value="${r.end??x.end}"><button onclick="jump($('start').value)">跳转</button></div><label>Primary role</label><select id="role">${ROLES.map(v=>option(v,v,r.primary_role||m.primary_role)).join('')}</select><label>Function tags</label><input id="tags" class="full" value="${esc((r.function_tags||m.function_tags||[]).join(','))}"><label>错误原因（多选）</label><div class="checks">${['边界错误','功能分类错误','商品判断错误','信任判断错误','CTA判断错误','需要上下文','本身不是好素材','其它'].map(v=>`<label><input type="checkbox" name="err" value="${v}" ${(r.error_reasons||[]).includes(v)?'checked':''}>${v}</label>`).join('')}</div><label>实际会用于剪辑吗</label><select id="editingUse"><option value="">请选择</option>${['会直接用','修改后可用','不会用'].map(v=>option(v,v,r.editing_use)).join('')}</select><label>人工备注</label><textarea id="notes" class="full">${esc(r.notes||'')}</textarea></div><p><button class="primary" onclick="saveGold()">保存Gold审核</button> <span id="saveState"></span></p>`}
async function saveGold(){try{const body={candidate_id:selected,material_grade:$('grade').value,boundary_result:$('boundary').value,start:$('start').value,end:$('end').value,primary_role:$('role').value,function_tags:$('tags').value.split(',').map(x=>x.trim()).filter(Boolean),error_reasons:[...document.querySelectorAll('input[name=err]:checked')].map(x=>x.value),editing_use:$('editingUse').value,notes:$('notes').value};await api('/api/gold/save',post(body));$('saveState').textContent='已保存';$('saveState').className='ok';const group=$('group')?.value||'ALL';await loadProgress();await loadGold(group)}catch(e){$('saveState').textContent=e.message;$('saveState').className='error'}}

async function loadCTA(){items=await api('/api/cta');$('queueTools').innerHTML='<b>7条未识别可靠CTA的视频</b><span class="muted">逐条查看完整业务时间线</span>';renderVideoQueue('cta');if(items.length)selectCTA(items[0].video_id)}
function renderVideoQueue(kind){$('queue').innerHTML=items.map(x=>`<div class="card ${selected===x.video_id?'active':''}" onclick="${kind==='cta'?'selectCTA':'selectReplication'}('${x.video_id}')"><b>${x.file_name}</b> <span>${fmt(x.duration)}</span> ${x.human_review?'<span class="ok">✓ 已审核</span>':'<span class="warn">未审核</span>'}<div class="muted">${x.content_segments.length}个业务片段</div></div>`).join('')}
function ctaRows(rows=[]){return `<div id="ctaRows">${rows.map((r,i)=>ctaRow(r,i)).join('')}</div><button onclick="addCtaRow()">＋新增CTA范围</button>`}
function ctaRow(r={},i=Date.now()){return `<div class="cta-row" data-row="${i}"><input class="cs" type="number" step="0.01" placeholder="start" value="${r.start??''}"><input class="ce" type="number" step="0.01" placeholder="end" value="${r.end??''}"><select class="ct">${['CTA_SOFT','CTA_DIRECT','CTA_URGENCY','CTA_END','OTHER'].map(v=>option(v,v,r.cta_type||'CTA_SOFT')).join('')}</select><input class="cp" placeholder="CTA前业务角色，如 PROOF" value="${esc(r.preceding_role||'')}"><button onclick="this.parentElement.remove()">删除</button></div>`}
function addCtaRow(){ $('ctaRows').insertAdjacentHTML('beforeend',ctaRow()) }
function collectCtaRows(){return [...document.querySelectorAll('.cta-row')].filter(x=>x.querySelector('.cs').value&&x.querySelector('.ce').value).map(x=>({start:x.querySelector('.cs').value,end:x.querySelector('.ce').value,cta_type:x.querySelector('.ct').value,preceding_role:x.querySelector('.cp').value}))}
function selectCTA(id){selected=id;const x=items.find(i=>i.video_id===id),r=x.human_review||{};renderVideoQueue('cta');setVideo(x);$('queue').insertAdjacentHTML('beforeend',timeline(x));$('editor').innerHTML=`<h2>${x.file_name} · CTA专项</h2><div class="machine">机器结论：未识别可靠CTA\n完整业务序列：${esc(x.compressed_sequence.join(' → '))}\n机器产品节点：${esc(JSON.stringify(x.product_entry))}</div><h3>人工结论</h3><div class="form"><label>CTA审核结果</label><select id="ctaResult"><option value="">请选择</option>${['确实无CTA','AI漏掉CTA'].map(v=>option(v,v,r.review_result)).join('')}</select><label>CTA范围</label><div>${ctaRows(r.cta_ranges||[])}</div><label>产品三个进入时间</label>${productTimes(r)}<label>人工备注</label><textarea id="notes" class="full">${esc(r.notes||'')}</textarea></div><p><button class="primary" onclick="saveCTA()">保存CTA专项审核</button> <span id="saveState"></span></p><h3>完整业务时间线</h3>${timeline(x)}`}
async function saveCTA(){try{const body={video_id:selected,review_result:$('ctaResult').value,cta_ranges:collectCtaRows(),...productPayload(),notes:$('notes').value};await api('/api/cta/save',post(body));await loadProgress();await loadCTA()}catch(e){$('saveState').textContent=e.message;$('saveState').className='error'}}

async function loadReplication(){items=await api('/api/replication');$('queueTools').innerHTML='<b>5条复刻候选</b><span class="muted">程序不自动决定最终选择</span>';renderVideoQueue('replication');if(items.length)selectReplication(items[0].video_id)}
function selectReplication(id){selected=id;const x=items.find(i=>i.video_id===id),r=x.human_review||{},goldIds=new Set(x.gold_matches.map(g=>g.segment_id));renderVideoQueue('replication');setVideo(x);$('queue').insertAdjacentHTML('beforeend',timeline(x,goldIds));const nodes=x.content_segments.filter(s=>roleClass(s.primary_role)).map(s=>`${fmt(s.start)} ${s.primary_role}`).join('｜');$('editor').innerHTML=`<h2>${x.file_name} · 复刻候选审核</h2><div class="machine">总时长：${fmt(x.duration)}\n机器结构：${esc(x.template_skeleton.join(' → '))}\nGold匹配：${x.gold_matches.length}个\n商品/PROOF/CTA节点：${esc(nodes||'未识别')}\n机器候选理由：${esc(x.machine_candidate.reason)}</div><h3>人工审核</h3><div class="form"><label>结构清晰度</label><select id="clarity"><option value="">1-5</option>${[1,2,3,4,5].map(v=>option(String(v),String(v),String(r.structure_clarity||''))).join('')}</select><label>本地素材易替代程度</label><select id="replace"><option value="">1-5</option>${[1,2,3,4,5].map(v=>option(String(v),String(v),String(r.local_material_replaceability||''))).join('')}</select><label>依赖原商品画面</label><select id="productDep"><option value="">请选择</option>${['低','中','高'].map(v=>option(v,v,r.original_product_dependency)).join('')}</select><label>依赖原人物/案例</label><select id="personDep"><option value="">请选择</option>${['低','中','高'].map(v=>option(v,v,r.original_person_case_dependency)).join('')}</select><label>适合第一次复刻测试</label><select id="suitable"><option value="">请选择</option>${['是','否'].map(v=>option(v,v,r.suitable_for_first_replication)).join('')}</select><label>产品三个进入时间</label>${productTimes(r)}<label>备注</label><textarea id="notes" class="full">${esc(r.notes||'')}</textarea></div><p><button class="primary" onclick="saveReplication()">保存复刻候选审核</button> <span id="saveState"></span></p><h3>完整业务结构</h3>${timeline(x,goldIds)}`}
async function saveReplication(){try{const body={video_id:selected,structure_clarity:$('clarity').value,local_material_replaceability:$('replace').value,original_product_dependency:$('productDep').value,original_person_case_dependency:$('personDep').value,suitable_for_first_replication:$('suitable').value,...productPayload(),notes:$('notes').value};await api('/api/replication/save',post(body));await loadProgress();await loadReplication()}catch(e){$('saveState').textContent=e.message;$('saveState').className='error'}}
function post(body){return {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}}
$('reportBtn').onclick=async()=>{try{const result=await api('/api/report',post({}));$('message').textContent='报告已生成：'+result.report;$('message').className='ok'}catch(e){$('message').textContent=e.message;$('message').className='error'}};
init().catch(e=>{$('editor').innerHTML=`<h2 class="error">${esc(e.message)}</h2>`});
</script></body></html>'''.replace("__ROLES__", json.dumps(ROLES, ensure_ascii=False))


def make_handler(store: HumanReviewStore):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BestsellerHumanReview/0.1"

        def log_message(self, fmt, *args):
            print(fmt % args, flush=True)

        def local_request(self) -> bool:
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def send_json(self, value, status=200):
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.local_request():
                self.send_json({"error": "仅限127.0.0.1访问"}, 403); return
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path in {"/", "/gold", "/cta", "/replication"}:
                body = HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body); return
            if path == "/api/progress":
                self.send_json(store.progress()); return
            if path == "/api/gold":
                query = parsed.query
                group = query.split("group=", 1)[1].split("&", 1)[0] if "group=" in query else "ALL"
                if group not in {"ALL", "A", "B", "C"}: group = "ALL"
                self.send_json(store.gold_queue(group)); return
            if path == "/api/cta":
                self.send_json(store.cta_queue()); return
            if path == "/api/replication":
                self.send_json(store.replication_queue()); return
            match = re.fullmatch(r"/media/([^/]+)", path)
            if match:
                self.serve_media(match.group(1)); return
            self.send_error(404)

        def serve_media(self, video_id: str):
            if video_id not in store.videos:
                self.send_error(404); return
            target = Path(store.videos[video_id]["file_path"]).resolve(strict=True)
            size = target.stat().st_size
            start, end = 0, size - 1
            header = self.headers.get("Range")
            if header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
                if not match:
                    self.send_error(416); return
                if match.group(1): start = int(match.group(1))
                if match.group(2): end = min(end, int(match.group(2)))
                if start > end or start >= size:
                    self.send_error(416); return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            with target.open("rb") as stream:
                stream.seek(start); remaining = end - start + 1
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk: break
                    try: self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError): break
                    remaining -= len(chunk)

        def do_POST(self):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if not self.local_request() or self.headers.get("Origin") != origin:
                self.send_json({"error": "仅接受本页同源审核"}, 403); return
            path = urlparse(self.path).path
            actions = {
                "/api/gold/save": store.save_gold,
                "/api/cta/save": store.save_cta,
                "/api/replication/save": store.save_replication,
                "/api/report": lambda _: store.generate_report(),
            }
            if path not in actions:
                self.send_error(404); return
            try:
                if self.headers.get("Content-Type") != "application/json":
                    raise ValueError("请求格式错误")
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 256 * 1024:
                    raise ValueError("请求大小非法")
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                result = actions[path](payload)
                self.send_json({"status": "saved", **(result if isinstance(result, dict) else {})})
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 409 if path == "/api/report" else 400)
            except Exception as exc:
                self.send_json({"error": str(exc)}, 400)

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="带货爆款第一轮人工审核 V0.1")
    parser.add_argument("output", type=Path)
    parser.add_argument("--port", type=int, default=8505)
    args = parser.parse_args()
    try:
        store = HumanReviewStore(args.output)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(store))
    except Exception as exc:
        print(f"启动失败：{exc}", file=sys.stderr); return 1
    print(f"Gold审核: http://127.0.0.1:{args.port}/gold", flush=True)
    print(f"CTA专项: http://127.0.0.1:{args.port}/cta", flush=True)
    print(f"复刻候选: http://127.0.0.1:{args.port}/replication", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
