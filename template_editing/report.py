"""生成人工审核HTML与可复核的阶段说明。"""
from html import escape
import json
from pathlib import Path

ROLES = {'PRODUCT_XIAOMIAOZHAO': '商品', 'PRODUCT_LIKELY': '大概率商品',
         'TIP_GENERIC': '普通技巧', 'AMBIGUOUS': '不确定'}


def clock(seconds):
    return f'{int(seconds // 3600):02d}:{int(seconds % 3600 // 60):02d}:{seconds % 60:06.3f}'


def render_report(report, output):
    output = Path(output)
    nav, sections = [], []
    for number, slot in enumerate(report['slots'], 1):
        nav.append(f'<button class="nav {"active" if number == 1 else ""}" data-target="{slot["id"]}">'
                   f'<span>Slot {number}</span><strong>{escape(slot["type"])}</strong><small>{escape(slot["name"])} · {slot["selected_count"]}条</small></button>')
        cards = []
        for row in slot['selected']:
            s, p = row['segment'], row['preview']
            meta = s['recommend_metadata']
            gold = s['gold_example_matches'][0] if s.get('gold_example_matches') else None
            gold_html = '<p>未匹配Gold Example。</p>'
            if gold:
                gold_html = f'''<div class="gold"><div class="eyebrow">最相似黄金案例 · {escape(gold['source_sheet'])}!{gold['source_cell']}</div>
                <div class="gold-meta">原类型：{escape(gold['original_type'])} · {escape(gold['evidence_kind'])} · BGE相似度 {gold['semantic_similarity']:.4f}</div>
                <blockquote>{escape(gold['original_text'])}</blockquote>
                <p><b>案例功能：</b>{escape(' / '.join(gold['functions']))}</p>
                <p>{escape(gold['same_function_reason'])}</p></div>'''
            role_html = ''
            if meta['xiaomiaozhao_mentioned'] or s['product_entities']:
                role_html = f'<div class="meaning"><b>小妙招含义：{ROLES[s["xiaomiaozhao_role"]]}</b><br>{escape(meta["xiaomiaozhao_reason"])}</div>'
            cards.append(f'''<article class="candidate" data-slot="{slot['id']}" data-segment="{s['segment_id']}">
              <div class="card-head"><b>#{row['rank']:02d}</b><span>{escape(s['content_type'])} · {s['duration']:.2f} 秒</span><strong>推荐分 {row['score']:.3f}</strong></div>
              <div class="card-body"><div class="media"><video controls preload="none" playsinline poster="{p['poster']}" src="{p['path']}"></video>
                <p>原画面 / 原声音 · 前后各约0.65秒试听余量</p>
                <div class="source"><b>{escape(s['file_name'])}</b><br>{clock(s['source_start'])} → {clock(s['source_end'])}<br>
                asset_id：{escape(s['asset_id'])}<br>video_id：{s['video_id']}<br>原字幕video_id：{meta['source_video_id']}</div>
              </div><div class="content"><p class="transcript">{escape(s['transcript'])}</p>
                <div class="tags">{''.join('<span>'+escape(tag)+'</span>' for tag in s['function_tags'])}</div>
                <p class="reason">{escape(row['recommend_reason'])}</p>{role_html}{gold_html}
                <details><summary>上下文、来源与评分明细</summary>
                  <p><b>前文：</b>{escape(meta['context_before']) or '无相邻句'}</p><p><b>后文：</b>{escape(meta['context_after']) or '无相邻句'}</p>
                  <p>{escape(meta['scene_note'])}。{escape(meta['boundary_note'])}</p>
                  <p>来源：{escape(' + '.join(meta['recall_origins']))}；主题：{escape(' / '.join(s['topic_tags'])) or '未识别'}</p>
                  <p class="path">{escape(s['file_path'])}</p>
                  <pre>{escape(json.dumps({k:row[k] for k in ['scores','weights','baseline_score','gold_example_score','gold_effective_score','gold_weight','hook_score','product_bridge_score','result_score','cta_score','product_relevance_score']},ensure_ascii=False,indent=2))}</pre>
                  <p>最终分 = 基础规则分 × (1 − Gold权重) + Gold有效分 × Gold权重。摘要/标题Gold有效分再乘0.6；无共同功能不加Gold分。所有分数均非可用率。</p>
                </details>
              </div></div>
              <div class="feedback"><div class="choices"><button data-rating="use">✅ 会用</button><button data-rating="maybe">🤔 勉强可用</button><button data-rating="reject">❌ 不会用</button></div>
              <label>备注<textarea maxlength="4000" rows="2" placeholder="例如：开头有前文依赖、效果反馈完整、剪点要后移…"></textarea></label>
              <div class="save-row"><button class="save">保存评价与备注</button><span class="save-status" role="status">尚未评价</span></div></div>
            </article>''')
        sections.append(f'''<section id="{slot['id']}" class="slot" {'' if number==1 else 'hidden'}>
            <div class="slot-title"><div><span class="eyebrow">SLOT {number:02d}</span><h2>{escape(slot['type'])} <small>{escape(slot['name'])}</small></h2></div>
            <span>目标 {slot['duration'][0]}–{slot['duration'][1]} 秒</span></div>
            <p class="slot-info">召回 {slot['recall_unique_windows']} 个窗口 → {slot['constructed_segments']} 个内容片段 → {slot['eligible_segments']} 个规则有效候选 → 展示 {slot['selected_count']} 条。规则有效不代表人工会用。</p>
            {''.join(cards)}</section>''')
    gold_set = report.get('gold_set') or {}
    total = report['counts']['displayed_candidates']
    page = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>坐诊转化型 V1 · 候选审核</title><style>
    :root{--ink:#172338;--muted:#637184;--line:#dce2e9;--blue:#244ab4;--bg:#f1f4f8}*{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 "Microsoft YaHei",system-ui,sans-serif}
    header{padding:30px 38px 22px;background:#172338;color:white}h1{font-size:27px;margin:4px 0 10px;letter-spacing:.02em}
    .eyebrow{font-size:12px;letter-spacing:.13em;font-weight:700}.header-row{display:flex;justify-content:space-between;align-items:center;gap:24px}
    .header-row p{margin:0;color:#bfcde2}.summary{display:flex;gap:30px;white-space:nowrap}.summary b{display:block;font-size:28px}.summary span{font-size:12px;color:#bfcde2}
    .notice{padding:12px 38px;border-bottom:1px solid var(--line);background:#fff;font-size:13px}.layout{display:grid;grid-template-columns:220px minmax(0,1fr);max-width:1680px;margin:auto}
    nav{position:sticky;top:0;align-self:start;padding:24px 16px;max-height:100vh;overflow:auto}.nav{display:block;width:100%;text-align:left;border:0;background:none;padding:12px 14px;border-radius:8px;color:var(--muted);margin-bottom:5px;cursor:pointer}
    .nav span,.nav strong,.nav small{display:block}.nav span{font-size:11px}.nav strong{font-size:14px;overflow-wrap:anywhere}.nav.active{background:#e0e8fc;color:#173d9d}.nav:hover{background:#e6eaf0}
    main{padding:24px 30px 60px;min-width:0}.slot-title{display:flex;justify-content:space-between;align-items:center}.slot-title h2{font-size:23px;margin:4px 0}.slot-title small{font-size:15px;font-weight:400;color:var(--muted);margin-left:10px}.slot-info{color:var(--muted);font-size:13px;margin:8px 0 24px}
    .candidate{background:white;border:1px solid var(--line);border-radius:12px;margin-bottom:28px;overflow:hidden;box-shadow:0 4px 16px #17233805}.card-head{display:flex;gap:18px;align-items:center;padding:13px 20px;border-bottom:1px solid var(--line)}.card-head>b{font-size:20px;color:var(--blue)}.card-head>strong{margin-left:auto;font-size:14px}
    .card-body{display:grid;grid-template-columns:minmax(220px,32%) minmax(0,1fr);gap:24px;padding:22px}.media video{width:100%;height:320px;background:#101722;border-radius:7px;object-fit:contain}.media p{font-size:12px;color:var(--muted);margin:6px 0}.source{font-size:12px;overflow-wrap:anywhere;margin-top:16px;color:var(--muted)}.source b{color:var(--ink)}
    .transcript{font-size:19px;line-height:1.8;margin:0 0 14px}.tags{display:flex;gap:6px;flex-wrap:wrap}.tags span{background:#eef2f7;color:#465774;padding:2px 7px;border-radius:4px;font-size:11px}.reason{font-size:13px;color:var(--muted)}.meaning{font-size:13px;padding:10px 13px;background:#f4f7fc;border-left:3px solid #7897d5;margin:15px 0}
    .gold{border:1px solid #e8dfcc;background:#fdfbf6;border-radius:7px;padding:14px 16px;font-size:13px}.gold .eyebrow{color:#83682c;letter-spacing:.04em}.gold-meta{font-size:12px;color:#857354;margin-top:5px}.gold blockquote{margin:10px 0;padding-left:12px;border-left:2px solid #d9cbaa;line-height:1.85;max-height:190px;overflow:auto}.gold p{margin:7px 0 0}details{font-size:13px;margin-top:16px}summary{cursor:pointer;color:var(--blue)}pre{white-space:pre-wrap;background:#f7f8fa;padding:12px}.path{overflow-wrap:anywhere}
    .feedback{border-top:1px solid var(--line);padding:18px 22px;background:#fbfcfe}.choices{display:flex;gap:10px;margin-bottom:13px}button{font:inherit}.choices button,.save{padding:7px 14px;border:1px solid #c8d2e1;background:white;color:var(--ink);border-radius:6px;cursor:pointer}.choices button.selected{background:#e4ecff;border-color:var(--blue);color:#193c98}.feedback label{display:block;font-size:12px;color:var(--muted)}textarea{display:block;width:100%;padding:9px 11px;border:1px solid #d5dce8;border-radius:6px;margin-top:4px;resize:vertical;font:14px/1.6 inherit}.save-row{display:flex;gap:15px;align-items:center;margin-top:12px}.save{background:var(--blue);color:white;border-color:var(--blue);font-size:13px}.save-status{font-size:12px;color:var(--muted)}.error{color:#b43130!important}#connection{font-weight:600}a{color:var(--blue)}
    @media(max-width:950px){.layout{grid-template-columns:160px minmax(0,1fr)}main{padding:20px 14px}.card-body{grid-template-columns:1fr}.media video{height:300px}.header-row{display:block}.summary{margin-top:18px}.slot-title{display:block}}
    @media(max-width:620px){header{padding:22px}.notice{padding:12px 22px}.layout{display:block}nav{position:static;display:flex;overflow:auto;padding:12px}.nav{min-width:150px}main{padding-top:10px}.slot-title h2{font-size:20px}}
    </style></head><body>'''
    page += f'''<header><div class="eyebrow">TEMPLATE EDITING V0.1 · 人工审核</div><div class="header-row"><div><h1>坐诊转化型 V1</h1>
        <p>逐个判断：这个位置推荐的素材，你会不会用？</p></div><div class="summary"><div><b>{len(report['slots'])}</b><span>模板位置</span></div><div><b>{total}</b><span>可播放候选</span></div><div><b>{gold_set.get('example_count',0)}</b><span>黄金案例</span></div></div></div></header>
        <div class="notice"><span id="connection">正在连接本机反馈文件…</span><br>评价保存至本报告目录的 template_feedback.json。{gold_set.get('utterance_count',0)}条案例原话 / {gold_set.get('summary_count',0)}条标题摘要。
        <a href="report.md" target="_blank">方法、数量与耗时</a> · <a href="report_data.json" target="_blank">完整结果</a><br>
        当前仅候选推荐。坐诊/连麦由字幕推定，需看画面听原声；Slot 2承接具体HOOK未计算，Slot 5/7允许重复。<br>
        已观察到口语碎片、转写噪声和否定句误召回；Gold相似或标签相同不等于含义一致，尤其注意“都有/没有”等表述。</div>
        <div class="layout"><nav>{''.join(nav)}</nav><main>{''.join(sections)}</main></div>'''
    page += '<script>const REPORT_ID=' + json.dumps(report['report_id']) + ';</script>'
    page += '''<script>
    const cards=[...document.querySelectorAll('.candidate')];let online=false;
    document.querySelectorAll('.nav').forEach(button=>button.addEventListener('click',()=>{
      document.querySelectorAll('video').forEach(v=>v.pause());
      document.querySelectorAll('.slot').forEach(s=>s.hidden=s.id!==button.dataset.target);
      document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b===button));window.scrollTo(0,0);
    }));
    document.querySelectorAll('video').forEach(v=>v.addEventListener('play',()=>document.querySelectorAll('video').forEach(o=>{if(o!==v)o.pause()})));
    cards.forEach(card=>{
      card.querySelectorAll('[data-rating]').forEach(button=>button.addEventListener('click',()=>{
        card.dataset.rating=button.dataset.rating;card.querySelectorAll('[data-rating]').forEach(b=>b.classList.toggle('selected',b===button));
        card.querySelector('.save-status').textContent='已选择，点击保存写入文件';
      }));
      card.querySelector('textarea').addEventListener('input',()=>card.querySelector('.save-status').textContent='备注已修改，尚未保存');
      card.querySelector('.save').addEventListener('click',async()=>{
        const status=card.querySelector('.save-status');status.classList.remove('error');
        if(!online||!card.dataset.rating){status.textContent=online?'请先选择评价':'请通过本机审核服务打开后保存';status.classList.add('error');return;}
        const button=card.querySelector('.save');button.disabled=true;status.textContent='保存中…';
        try{const response=await fetch('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({report_id:REPORT_ID,slot_id:card.dataset.slot,segment_id:card.dataset.segment,rating:card.dataset.rating,note:card.querySelector('textarea').value})});
          const data=await response.json();if(!response.ok||!data.saved)throw Error(data.error||'保存失败');status.textContent='已保存到 template_feedback.json';
        }catch(e){status.textContent='保存失败：'+e.message;status.classList.add('error');}finally{button.disabled=false;}
      });
    });
    async function loadFeedback(){const banner=document.querySelector('#connection');
      if(location.protocol==='file:'){banner.textContent='本地文件预览模式：请运行“打开模板候选审核.bat”，再访问 http://127.0.0.1:8503/report.html 保存反馈';return;}
      try{const response=await fetch('/api/feedback');if(!response.ok)throw Error('连接失败');const data=await response.json();online=true;banner.textContent='已连接本机审核服务，评价可保存并在刷新后恢复';
        for(const card of cards){const row=data.records[[REPORT_ID,card.dataset.slot,card.dataset.segment].join('|')];if(row){card.dataset.rating=row.rating;card.querySelector('textarea').value=row.note;card.querySelectorAll('[data-rating]').forEach(b=>b.classList.toggle('selected',b.dataset.rating===row.rating));card.querySelector('.save-status').textContent='已保存的评价';}}
      }catch(e){banner.textContent='反馈服务未连接，保存不可用';banner.classList.add('error');}}
    loadFeedback();</script></body></html>'''
    (output / 'report.html').write_text(page, 'utf-8')
    write_markdown(report, output)


def write_markdown(r, output):
    c = r['counts']
    lines = [f"# Template Editing V0.1 — {r['status']}", '',
        'READY只代表80个候选可供真实试听和反馈；不表示人工可用率、连麦画面或营销效果已验收。', '',
        '## 生成与范围', '',
        '正式Speech BGE查询，按模板多query召回；追加Gold原型。原召回结果保留，增量后每slot最多500个窗口。',
        '通过Speech原ID/run映射，用只读连接按主键回查生产字幕。读取上下文，最多20秒内合并连续段，排除长停顿、倒序、越界时间和独立低信息字幕。最终边界沿用Whisper，需人工听审。',
        f"正式库 {c['source_subtitles']:,} 条字幕；索引覆盖 {c['formal_subtitled_assets']} 个有字幕asset。实际召回涉及 {c['recall_assets']} 个asset、{c['unique_recalled_windows']:,} 个唯一窗口。",
        f"参与构造的seed原字幕去重 {c['unique_original_subtitles_in_seeds']:,} 条；含上下文实际读取并核对 {c['unique_original_subtitles_with_context']:,} 条；最终池 {c['content_segments']:,} 个独立Content Segment。",
        f"展示 {c['displayed_candidates']} 条、实际独立预览 {c['unique_preview_segments']} 个（重复slot复用同文件）。", '',
        '## 各Slot', '', '| Slot | 构造片段 | 规则有效 | 有效asset | 去重后可选 | 展示 | 数量判断 |', '|---|---:|---:|---:|---:|---:|---|']
    for s in r['slots']:
        stock = '充足，待听审' if s['diverse_candidates'] >= 30 else '偏少，待听审' if s['diverse_candidates'] >= 10 else '不足Top10'
        lines.append(f"| {s['id']} {s['type']} | {s['constructed_segments']} | {s['eligible_segments']} | {s['eligible_assets']} | {s['diverse_candidates']} | {s['selected_count']} | {stock} |")
    lines += ['', '## 功能规则', '',
        '- HOOK：坐诊身体部位/问题，加不是、其实、为什么、强痛点等；独立句首优先，不预测爆款概率。',
        '- CONSULT：身体部位和问题，加原因、肌肉、受力、治疗逻辑。当前不评估与某条HOOK的实际衔接。',
        '- PRODUCT_BRIDGE：本段指向商品，加这些方法、自己能判断、系统学习、课程里面教等过渡线索。',
        '- PRODUCT_INTRO：商品内容、受众、学习方式和价值，直接下单片段归CTA优先。',
        '- 小妙招：前后各至多2句的商品证据优先；无商品证据而有具体动作才TIP_GENERIC；证据不足用PRODUCT_LIKELY；明确否定/冲突保留AMBIGUOUS。',
        '- CALL_RESULT：连麦上下文加肯定改善，或效果核验问句。问句不标PROOF，字幕不能证明视觉上确为连麦。',
        '- CTA：软引导/购买行动/紧迫感；CTA_END额外要求收束或紧迫话术，是否适合整片结束仍须人工确认。',
        '- 基础分按槽位匹配0.34、Semantic0.18、信息0.10、独立性0.14、时长0.10、句首0.07、句尾0.07计算。Gold为额外12%：0.88×基础分+0.12×Gold有效分，摘要折减为0.6，无共同功能不加分。', '',
        '## 性能', '', '| Slot | Semantic秒 | 上下文秒 | 构造秒 | 分类秒 | Gold匹配秒 | 排序秒 | 预览秒 |', '|---|---:|---:|---:|---:|---:|---:|---:|']
    for s in r['slots']:
        keys = ['semantic_recall_seconds','context_expansion_seconds','segment_construction_seconds','classification_seconds','gold_matching_seconds','ranking_seconds','preview_seconds']
        lines.append('| ' + s['id'] + ' | ' + ' | '.join(f"{s['timings'].get(k,0):.3f}" for k in keys) + ' |')
    lines += ['', f"8-slot完整生成累计 {r['total_generation_seconds']:.3f} 秒。基础索引冷加载 {r['index_load_seconds']:.3f} 秒；增量Gold阶段 {r['gold_augmentation_seconds']:.3f} 秒；审核阶段Gold模型加载 {r['gold_model_load_seconds']:.3f} 秒。",
              r['timing_scope'], 'Gold重复query按首次使用slot归账，不重复累加；全程墙钟包含额外检查、模型加载和报告写盘，不等于各列之和。', '']
    if r.get('generation_history'):
        lines += [r['generation_history']['description'], '']
    gold = r.get('gold_set')
    if gold:
        lines += ['## Gold Example Set', '', f"来源：{gold['source_path']}（Sheet1!A1:B20）。20条案例 = {gold['utterance_count']}条话术 + {gold['summary_count']}条标题/摘要；拆为 {len(gold['prototypes'])} 个长度受控语义原型。原Excel SHA256：`{gold['source_sha256']}`。", '',
            '苗老师→陶老师、小灵招→小妙招。原话与映射版并存；检索和候选比较使用老师/这套课程弱化名称。原型功能按具体话术人工记录，多标签计数可超过20。', '',
            '| function | 案例数 |', '|---|---:|']
        lines += [f'| {k} | {v} |' for k,v in gold['function_distribution'].items()]
        lines += ['', '商品价值/介绍/证明样本较多；HOOK只有2个标题，CONSULT只有3个主题摘要，完整EXPLANATION为0；CTA_URGENCY只有1例，CTA_END只有2例。CALL_RESULT的4例中2例是摘要，不能当成4条完整连麦话术。', '',
            '### 原语义召回与Gold互补', '', '| Slot | 原池窗口 | Gold窗口 | 交集 | Gold独有 | 原池独有 | 最终Top10来源 |', '|---|---:|---:|---:|---:|---:|---|']
        for s in r['slots']:
            x = s['gold_complement']
            lines.append(f"| {s['id']} | {x.get('baseline_windows',0)} | {x.get('gold_windows',0)} | {x.get('overlap_windows',0)} | {x.get('gold_only_windows',0)} | {x.get('baseline_only_windows',0)} | {json.dumps(x.get('selected_origins',{}),ensure_ascii=False)} |")
        lines += ['', '互补计数是召回覆盖证据，不是人工可用率提升证明。最终500窗口池用两路交替采样；Semantic相似不能取代规则功能检查。', '']
    lines += ['## 文件与验收', '', f"HTML：{output / 'report.html'}", f"反馈：{output / 'template_feedback.json'}", f"片段池：{r['pool_path']}",
        f"保护检查：{r['protection']['checked_files']} 个文件大小/修改时间与集合不变；原事实库、正式索引、寻帧Web和auto_remake未写入。", '',
        '有限预览生成失败的候选已记录在report_data.json各slot的preview_failures，并顺延选择可解码候选；不修改失败源文件。',
        '真实抽查发现口语碎片、句尾不完整、转写噪声，以及“课程里面没有”对“课程里面都有”的语义误召回。透明规则仍可能误标功能，Gold相似度不代表含义一致。当前交付用于人工可用性评审，未通过人工效果验收。',
        '人工验证：运行根目录“打开模板候选审核.bat”，依次看8个位置的预览并试听；选择会用/勉强/不会用，写备注后点保存，刷新确认恢复。重点看句首依赖、剪点、商品含义和是否真实连麦。', '',
        '建议先完成这80条人工反馈，再决定V0.2。当前缺少人工可用率，不建议直接进入Transition Scoring。本轮停止于V0.1。', '']
    (output / 'report.md').write_text('\n'.join(lines), 'utf-8')
