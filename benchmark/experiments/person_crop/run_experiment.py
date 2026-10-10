"""独立人物区域重排实验；不修改生产索引、配置或搜索函数。"""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
from PIL import Image
import torch

from benchmark.run import load_cases, evaluate_case, summarize
from benchmark.search_adapter import ProductionSearch


PROTOCOL = {
    "candidate_count": 20,
    "A": "现有索引全图余弦相似度排序（无生产ORB精排）",
    "B": "query与候选所有人物区域配对的最大余弦相似度排序",
    "C": "0.5*全图余弦相似度+0.5*人物区域余弦相似度",
    "missing_crop": "任一侧无区域/解码失败时，B和C该候选回退全图分数，不删除候选",
    "detector": "本地YuNet人脸定位扩展区域；不能识别患者角色",
    "face_score_threshold": 0.8,
    "face_min_area_fraction": 0.005,
    "detector_max_side": 640,
    "crop": "人脸中心左右各1.5倍脸宽；从脸顶上0.25倍脸高至脸顶下5倍脸高，裁至图像边界",
    "ranking": "逐帧排名、不按视频去重；同分保留原FAISS顺序；不设新分数过滤阈值",
    "weights": "原MobileNetV2、原224x224预处理、FP32及L2归一化；不下载模型",
    "scope": "固定全图候选池的重排实验，不是全库crop召回实验；不以正确ID或timestamp选择候选/区域",
}


def expanded_box(face, width, height):
    x, y, w, h = map(float, face[:4])
    center = x + w / 2
    return [max(0, int(center - 1.5 * w)), max(0, int(y - .25 * h)),
            min(width, int(center + 1.5 * w)), min(height, int(y + 5 * h))]


def scores(full, crop):
    return {"A": full, "B": full if crop is None else crop,
            "C": full if crop is None else .5 * full + .5 * crop}


def ranked(rows, method):
    return sorted(rows, key=lambda row: (-row["scores"][method], row["faiss_rank"]))[:10]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot():
    # 只读记录已有代码、配置及生产文件元数据，不全量哈希几十GB数据。
    paths = list(ROOT.glob("*.py")) + list((ROOT / "benchmark").glob("*.py")) + [ROOT / "config.json"]
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


class Regions:
    def __init__(self, engine):
        self.model, self.preprocess, self.device = engine.space["load_feature_model"]()
        self.detector_path = ROOT / "models/face_detection_yunet.onnx"
        self.detector = cv2.FaceDetectorYN_create(str(self.detector_path), "", (320, 320), .8, .3, 5000)

    def embed(self, images):
        batch = torch.stack([self.preprocess(Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB))) for im in images]).to(self.device)
        with torch.no_grad():
            values = self.model(batch).flatten(1).cpu().numpy()
        norms = np.linalg.norm(values, axis=1, keepdims=True)
        if not np.isfinite(values).all() or np.any(norms == 0):
            raise ValueError("无效embedding")
        return values / norms

    def extract(self, frame):
        if frame is None:
            return [], None, "decode_failed"
        height, width = frame.shape[:2]
        scale = min(1., 640 / max(width, height))
        small = cv2.resize(frame, (round(width * scale), round(height * scale)))
        self.detector.setInputSize((small.shape[1], small.shape[0]))
        _, faces = self.detector.detect(small)
        boxes = []
        if faces is not None:
            for face in faces:
                mapped = face[:4] / scale
                if mapped[2] * mapped[3] < .005 * width * height:
                    continue
                box = expanded_box(mapped, width, height)
                if box[2] > box[0] and box[3] > box[1] and box not in boxes:
                    boxes.append(box)
        if not boxes:
            return [], None, "no_face_region"
        crops = [frame[y1:y2, x1:x2] for x1, y1, x2, y2 in boxes]
        return boxes, self.embed(crops), "ok"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "benchmark/cases/business20_baseline.json")
    parser.add_argument("--baseline", type=Path, default=ROOT / "benchmark/results/20260926_212832_165f5c2a/report.json")
    args = parser.parse_args()
    cases = load_cases(args.cases)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    assert len(cases) == 20 and sha(args.cases) == baseline["case_manifest_sha256"], "必须使用原20例清单"
    out = Path(__file__).parent / "results" / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8])
    out.mkdir(parents=True)
    before = snapshot()
    engine = ProductionSearch()
    provenance = engine.provenance()
    region = Regions(engine)
    detector_hash = sha(region.detector_path)
    (out / "protocol.json").write_text(json.dumps(dict(protocol=PROTOCOL,manifest_sha256=sha(args.cases),script_sha256=sha(__file__),detector_sha256=detector_hash), ensure_ascii=False, indent=2), encoding="utf-8")
    index, metadata = engine.space["load_faiss_index"]()
    assert index is not None and index.d == 1280
    cache, records = {}, []
    evaluated = {method: [] for method in "ABC"}
    for case in cases:
        print("实验", case["id"], flush=True)
        assert sha(case["image"]) == case["image_sha256"]
        frame = cv2.imdecode(np.frombuffer(Path(case["image"]).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"无法读取query: {case['id']}")
        query = region.embed([frame])[0]
        qboxes, qfeatures, qstatus = region.extract(frame)
        similarities, indices = index.search(query.reshape(1, -1).astype(np.float32), 20)
        candidates = []
        for rank, (similarity, idx) in enumerate(zip(similarities[0], indices[0]), 1):
            if idx < 0:
                continue
            path, name, timestamp = metadata[int(idx)]
            vid = engine.video_ids.get(path)
            key = (path, float(timestamp))
            if key not in cache:
                try:
                    candidate = engine.space["load_frame_for_matching"](path, timestamp, vid)
                    cache[key] = region.extract(candidate)
                except (cv2.error, ValueError, OSError) as exc:
                    cache[key] = ([], None, f"error:{type(exc).__name__}:{exc}")
            boxes, features, status = cache[key]
            crop = float(np.max(qfeatures @ features.T)) if qfeatures is not None and features is not None else None
            candidates.append(dict(file_path=path, file_name=name, timestamp=float(timestamp), video_id=vid,
                                   faiss_rank=rank, faiss_row=int(idx), full_score=float(similarity), crop_score=crop,
                                   scores=scores(float(similarity), crop), crop_boxes=boxes, crop_status=status,
                                   fallback=crop is None))
        for method in "ABC":
            evaluated[method].append(evaluate_case(case, ranked(candidates, method)))
        records.append(dict(id=case["id"], category=case["category"], query_boxes=qboxes, query_status=qstatus, candidates=candidates))
    unchanged = before == snapshot() and provenance == engine.provenance() and detector_hash == sha(region.detector_path)
    summaries = {method: summarize(rows) for method, rows in evaluated.items()}
    by_category = {cat: {method: summarize([row for row in rows if next(c for c in cases if c['id'] == row['id'])['category'] == cat])
                        for method, rows in evaluated.items()} for cat in sorted({c['category'] for c in cases})}
    recall = sum(any(v['video_id'] in c['acceptable_video_ids'] for v in rec['candidates']) for c, rec in zip(cases, records))
    coverage = dict(query_with_regions=sum(bool(rec['query_boxes']) for rec in records),
                    candidate_pairs=sum(len(rec['candidates']) for rec in records),
                    crop_scored_pairs=sum(not v['fallback'] for rec in records for v in rec['candidates']),
                    candidate_status=dict(Counter(v['crop_status'] for rec in records for v in rec['candidates'])),
                    candidate_pool_video_hit_cases=recall)
    report = dict(protocol=PROTOCOL, production_unchanged=unchanged, environment=provenance,
                  cases=cases, summary=summaries, categories=by_category, coverage=coverage,
                  production_baseline_reference=baseline['summary'], records=records, evaluations=evaluated)
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines = ['# 人物区域crop独立实验', '', '仅实验，不合并生产。A是纯全图embedding对照，与含ORB精排的原生产baseline不是同一种排序。', '', '| 方案 | Top1视频 | Top5视频 | Top10视频 |', '|---|---:|---:|---:|']
    for method,s in [('原生产baseline（参考）',baseline['summary']),*summaries.items()]:
        lines.append('| '+method+' | '+' | '.join(f"{s['video_hit_rates'][str(k)]:.2%}" for k in (1,5,10))+' |')
    for cat, methods in by_category.items():
        lines += ['', f'## {cat}', '', '| 方案 | Top1视频 | Top5视频 | Top10视频 |', '|---|---:|---:|---:|']
        for method,s in methods.items():
            lines.append('| '+method+' | '+' | '.join(f"{s['video_hit_rates'][str(k)]:.2%}" for k in (1,5,10))+' |')
    lines += ['', '普通截图0例，无可评估样本。', '', '## 逐case视频命中', '', '单元格依次为Top1/Top5/Top10（1命中，0未命中）。', '', '| Case | A | B | C | Query区域数 |', '|---|---|---|---|---:|']
    for i,rec in enumerate(records):
        cells=['/'.join(str(int(evaluated[m][i]['video_hits'][str(k)])) for k in (1,5,10)) for m in 'ABC']
        lines.append('| '+rec['id']+' | '+' | '.join(cells)+f" | {len(rec['query_boxes'])} |")
    lines += ['', '## 覆盖与限制', '', json.dumps(coverage,ensure_ascii=False), '',
              '固定FAISS全图Top20候选，三组共享候选，不新增crop索引。B/C只能改变候选顺序，无法召回池外正确视频。裁剪配对取最大值，可能由医生而非患者决定，也可能受人物数量影响。人脸扩展框不等于人体分割，可能漏掉背身患者或包含背景；不声称已验证患者专属特征。', '',
              '无区域或取帧失败回退全图分数，完整回退标记、区域坐标与所有候选分数见report.json。沿用现有取帧方式，不修复解码、不修改标注，不因结果重调权重。20例用于本次探索，不能视为独立泛化验证。', '',
              f'生产代码/配置哈希、模型哈希和索引/数据库元数据检查一致：{unchanged}。']
    (out/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(summary=summaries,coverage=coverage,unchanged=unchanged),ensure_ascii=False,indent=2))
    print('REPORT',out/'report.md',flush=True)
    if not unchanged:
        raise SystemExit('生产完整性检查失败')


if __name__ == '__main__':
    main()
