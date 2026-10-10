"""只读来源；在检索前冻结样本、排除依据和三方案参数。"""
from pathlib import Path
import hashlib, json, sqlite3, sys
import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
FORMAL = ROOT / 'dino_index/formal_v1_repaired'

def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def ro(path):
    c = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA query_only=ON')
    return c

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def signature(path):
    im = Image.open(path).convert('RGB')
    a = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2GRAY)
    def ph(x):
        d = cv2.dct(cv2.resize(x, (32, 32)).astype(np.float32))[:8, :8].flatten()
        return (d > np.median(d[1:])).tolist()
    return {'sha256':sha(path), 'rgb_sha256':hashlib.sha256(str(im.size).encode() + im.tobytes()).hexdigest(),
            'phash':ph(a), 'mirror_phash':ph(cv2.flip(a, 1)), 'size':list(im.size)}

def main():
    business = read(ROOT / 'benchmark/cases/business20_baseline.json')['cases']
    hell = read(ROOT / 'benchmark/experiments/hell10_diagnosis/results.json')['cases']
    excluded_images = [Path(c['query']) for c in hell]
    for directory in ['hell10_diagnosis', 'hell10_orb_rerank']:
        excluded_images += list((ROOT / 'benchmark/experiments' / directory).glob('*.jpg'))
        excluded_images += list((ROOT / 'benchmark/experiments' / directory).glob('*.png'))
    excluded_images = sorted(set(excluded_images))
    signatures = {str(p):signature(p) for p in excluded_images}
    with ro(ROOT / 'benchmark/feedback/search_feedback.db') as db:
        feedback = [dict(r) for r in db.execute('SELECT s.search_id,s.query_type,s.query_name,s.query_sha256,s.status,f.feedback_status,f.asset_id,f.corrected_timestamp FROM searches s LEFT JOIN feedback f USING(search_id)')]
    eligible_feedback = [f for f in feedback if f['query_type']=='image' and f['feedback_status']=='correct' and f['asset_id'] and f['corrected_timestamp'] is not None]
    # 此轮已检查为空；若未来增加有效反馈，要求显式重新准备而不是静默忽略。
    assert not eligible_feedback, '有新增合格反馈，需先纳入验证集'
    cases = []
    with ro(ROOT / 'asset_inventory/results/20260927_assets/logical_assets.db') as assets, ro(FORMAL / 'metadata.sqlite') as meta:
        for c in business:
            p = (ROOT / 'benchmark/cases' / c['image']).resolve()
            sig = signature(p)
            matches = []
            for vid in c['acceptable_video_ids']:
                matches += [dict(r) for r in assets.execute('SELECT asset_id,video_id,production_video_id,file_path FROM asset_files WHERE production_video_id=?', (vid,))]
            aids = sorted({r['asset_id'] for r in matches})
            assert aids, c['id']
            corpus = []
            for aid in aids:
                row = meta.execute('SELECT * FROM videos WHERE asset_id=?',(aid,)).fetchone()
                if row:
                    nearby = meta.execute('SELECT index_id,timestamp FROM frames WHERE asset_id=? ORDER BY abs(timestamp-?) LIMIT 1',(aid,c['expected_timestamp'])).fetchone()
                    corpus.append({'asset_id':aid,'video_id':row['video_id'],'file_name':row['file_name'],'duration':row['decoded_duration_seconds'],'nearest_frame':dict(nearby)})
            exact = [p for p,s in signatures.items() if s['sha256']==sig['sha256'] or s['rgb_sha256']==sig['rgb_sha256']]
            near = sorted([{'path':p,'phash_hamming':min(sum(a!=b for a,b in zip(sig['phash'],s[v])) for v in ['phash','mirror_phash'])} for p,s in signatures.items()],key=lambda x:x['phash_hamming'])[:3]
            overlaps = [{'hell_case':h['case_id'],'time_delta':abs(c['expected_timestamp']-h['gt_seconds'])} for h in hell if set(aids)&set(h['accepted_asset_ids']) and abs(c['expected_timestamp']-h['gt_seconds'])<=10]
            reason = 'EXACT_QUERY_OVERLAP' if exact else ('SAME_SCENE_WITHIN_10_SECONDS_OF_HELL10' if overlaps else None)
            cases.append({**c,'query':str(p),'signature':sig,'gt_asset_ids':aids,'mapping':matches,'corpus':corpus,
                          'exact_overlap':exact,'nearest_excluded_images':near,'same_scene_overlap':overlaps,'excluded_reason':reason})
    write('dataset_audit.json',{'feedback_records':feedback,'eligible_feedback_count':len(eligible_feedback), 'business_cases':cases,
                              'excluded_query_signatures':signatures,'scene_exclusion_policy':'同asset且GT相差<=10秒保守排除，检索前固定，人工查看联系图确认。'})
    paths = [('B'+str(i+1),Path(c['query'])) for i,c in enumerate(cases)] + [('H'+str(c['case_id']),Path(c['query'])) for c in hell]
    sheet=Image.new('RGB',(10*164,3*365),'#eeeeee');draw=ImageDraw.Draw(sheet)
    for i,(label,path) in enumerate(paths):
        im=Image.open(path).convert('RGB');im.thumbnail((160,338));x=(i%10)*164;y=(i//10)*365
        sheet.paste(im,(x,y+22));draw.text((x+3,y+3),label,fill='black')
    sheet.save(OUT/'independence_contact_sheet.jpg')
    protocol={'index':'formal_v1_repaired','topk':500,'asset_cap':5,'timestamp_gap_seconds':10,'query_long_edge':256,
              'query_resize':'INTER_AREA, aspect preserving','orb_views':['original','horizontal_mirror'],'orb_view_fusion':'max_quality','orb_weight':0.25,
              'schemes':['A_DINO','B_DEDUP','C_DEDUP_ORB'],'fusion':'0.75 * DINO_similarity + 0.25 * max_ORB_quality; tie by DINO rank',
              'orb_implementation':str(ROOT/'benchmark/experiments/hell10_orb_rerank/run_experiment.py'),
              'orb_implementation_sha256':sha(ROOT/'benchmark/experiments/hell10_orb_rerank/run_experiment.py'),
              'production_orb_sha256':sha(ROOT/'video_search.py'),
              'metric_primary':'前K条frame结果包含任一GT asset即命中；不要求时间正确。另列全唯一asset排名以避免口径混淆。',
              'timing_repeats':3,'timing_order':'每轮按case id；同一模型/FAISS实例；无JPEG/ORB描述子应用层缓存；首轮与后续均单列',
              'no_parameter_search':True,'source_business_sha256':sha(ROOT/'benchmark/cases/business20_baseline.json')}
    write('frozen_protocol.json',protocol)
    print(json.dumps({'feedback_count':len(feedback),'eligible_feedback':len(eligible_feedback),'cases':[{k:c[k] for k in ['id','gt_asset_ids','excluded_reason','same_scene_overlap','nearest_excluded_images']} for c in cases]},ensure_ascii=False))

if __name__=='__main__':main()
