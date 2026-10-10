"""固定小图库三编码器对比；纯图像余弦召回，不接入生产。"""
import ast
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE/'deps'))
sys.path.insert(0, str(ROOT))
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
import numpy as np
from PIL import Image
import torch
from torchvision import models, transforms
from benchmark.run import evaluate_case, summarize


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def normalize(values):
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if not np.isfinite(values).all() or np.any(norms == 0):
        raise ValueError('非有限或全零特征，停止')
    return values / norms


def top_indices(scores, k=10):
    return np.argsort(-scores, kind='stable')[:k]


def load_mobilenet():
    tree = ast.parse((ROOT/'video_search.py').read_text(encoding='utf-8-sig'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'load_feature_model')
    fn.decorator_list = []
    space = dict(torch=torch, models=models, transforms=transforms, QUERY_DEVICE=torch.device('cuda'))
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'production_model_readonly', 'exec'), space)
    return space['load_feature_model']()


def quality(path):
    with Image.open(path) as image:
        rgb = np.asarray(image.convert('RGB').resize((64,64)), dtype=np.float32)
    spread = rgb.max(2)-rgb.min(2)
    return dict(mean=float(rgb.mean()), std=float(rgb.std()),
                near_gray_fraction=float((spread<8).mean()), black_fraction=float((rgb.max(2)<8).mean()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', type=Path)
    args = parser.parse_args()
    start = time.perf_counter()
    gallery_dir = HERE/'fixed_gallery'
    data = json.loads((gallery_dir/'gallery_manifest.json').read_text(encoding='utf-8'))
    decoded = json.loads((gallery_dir/'extraction.json').read_text(encoding='utf-8'))
    weights = json.loads((HERE/'weights_manifest.json').read_text(encoding='utf-8'))
    assert len(decoded)==len(data['rows'])
    failed = {row['gallery_id']: row for row in decoded if not row['ok']}
    assert set(failed) == {'g0704', 'g0705'}, '仅允许排除用户确认的两帧'
    assert torch.cuda.is_available(), '独立CUDA环境不可用'
    torch.manual_seed(20260927)
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    cases = data['cases']
    gallery = [row for row in data['rows'] if row['gallery_id'] not in failed]
    excluded = [dict(row, extraction=failed[row['gallery_id']],
                     reason='解码缺失参考帧，输出为空')
                for row in data['rows'] if row['gallery_id'] in failed]
    (HERE/'excluded_frames.json').write_text(json.dumps(excluded, ensure_ascii=False, indent=2), encoding='utf-8')
    for case in cases:
        assert sha(case['image']) == case['image_sha256']
        assert any(row['video_id'] in case['acceptable_video_ids'] and abs(row['timestamp']-case['expected_timestamp'])<=case['time_tolerance_seconds'] for row in gallery), case['id']
    records = {r['gallery_id']: r for r in decoded}
    for row in gallery:
        assert sha(row['image']) == records[row['gallery_id']]['image_sha256']
    for name, weight in weights.items():
        for file, expected in weight['files'].items():
            assert sha(HERE/'weights'/name/file)==expected['sha256']
    out = args.resume.resolve() if args.resume else HERE/'results'/datetime.now().strftime('%Y%m%d_%H%M%S')
    if args.resume:
        assert out.parent == (HERE/'results').resolve() and out.is_dir()
    else:
        out.mkdir(parents=True, exist_ok=False)
    mobile_weight = Path(torch.hub.get_dir())/'checkpoints/mobilenet_v2-7ebf99e0.pth'
    assert mobile_weight.is_file(), '缺少原MobileNet权重，停止而非下载'
    protocol=dict(scope='小规模实验图库结果，不代表完整159万帧全库召回率',
        gallery_count=len(gallery),original_gallery_count=len(data['rows']),excluded_frames=excluded,
        query_count=len(cases),gallery_manifest_sha256=sha(gallery_dir/'gallery_manifest.json'),
        extraction_sha256=sha(gallery_dir/'extraction.json'),script_sha256=sha(__file__),
        weights=weights,mobilenet_sha256=sha(mobile_weight),
        seed=20260927,device=torch.cuda.get_device_name(0),dtype='float32',TF32=False,batch_size=16,
        scoring='L2归一化后余弦相似度，逐帧稳定排序，Top1/5/10；无二次精排；原多ID和2秒时间容差',
        feature_definition=dict(A='原MobileNetV2全局平均池化1280维',B='DINOv2-small最后层CLS token 384维',C='CLIP ViT-B/32图像投影512维'),
        packages={name:importlib.metadata.version(name) for name in ['torch','torchvision','transformers','huggingface-hub','tokenizers','safetensors']})
    if args.resume:
        previous_path = out/'resume_protocol.json' if (out/'resume_protocol.json').exists() else out/'protocol.json'
        previous = json.loads(previous_path.read_text(encoding='utf-8'))
        for key in protocol:
            if key == 'packages':
                # 首轮沙箱不可读取B/C依赖；仅允许尚未使用且版本未知的包补全。
                for name, version in previous[key].items():
                    if version is None:
                        assert name not in ('torch', 'torchvision')
                        assert not any((out/f'{label}_results.json').exists() for label in 'BC')
                    else:
                        assert protocol[key][name] == version, name
            elif key != 'script_sha256':
                assert previous[key] == protocol[key], key
        (out/'resume_protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    else:
        (out/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    paths=[c['image'] for c in cases]+[r['image'] for r in gallery]
    all_results={}
    for label in 'ABC':
        if args.resume and (out/f'{label}_results.json').is_file():
            all_results[label] = json.loads((out/f'{label}_results.json').read_text(encoding='utf-8'))
            print('MODEL REUSED', label, flush=True)
            continue
        print('MODEL START',label,flush=True)
        model_start=time.perf_counter()
        if label=='A':
            model,processor,device=load_mobilenet()
        else:
            from transformers import AutoImageProcessor, Dinov2Model, CLIPModel
            folder=HERE/'weights'/('dinov2' if label=='B' else 'clip')
            processor=AutoImageProcessor.from_pretrained(folder,local_files_only=True,use_fast=False)
            cls=Dinov2Model if label=='B' else CLIPModel
            model=cls.from_pretrained(folder,local_files_only=True,attn_implementation='eager').float().eval().to('cuda')
        batches=[]
        for begin in range(0,len(paths),16):
            images=[]
            for path in paths[begin:begin+16]:
                with Image.open(path) as image:
                    images.append(image.convert('RGB'))
            pixels=torch.stack([processor(image) for image in images]) if label=='A' else processor(images=images,return_tensors='pt')['pixel_values']
            with torch.inference_mode():
                outputs=model.get_image_features(pixel_values=pixels.to('cuda')) if label=='C' else model(pixels.to('cuda'))
                value=outputs.flatten(1) if label=='A' else (outputs.last_hidden_state[:,0,:] if label=='B' else outputs)
            batches.append(value.float().cpu().numpy())
            if begin%160==0: print('EMBED',label,begin,'/',len(paths),flush=True)
        embeddings=normalize(np.concatenate(batches))
        np.save(out/f'{label}_embeddings.npy',embeddings)
        similarities=embeddings[:len(cases)] @ embeddings[len(cases):].T
        np.save(out/f'{label}_similarities.npy',similarities)
        queries=[]
        for case,sim in zip(cases,similarities):
            top=[dict(gallery[int(i)],similarity=float(sim[i])) for i in top_indices(sim)]
            queries.append(evaluate_case(case,top))
        summary=summarize(queries)
        summary['top10_candidate_video_recall']=summary['video_hit_rates']['10']
        categories={cat:summarize([q for q,c in zip(queries,cases) if c['category']==cat]) for cat in sorted({c['category'] for c in cases})}
        all_results[label]=dict(summary=summary,categories=categories,queries=queries,dimensions=embeddings.shape[1],elapsed_seconds=time.perf_counter()-model_start)
        (out/f'{label}_results.json').write_text(json.dumps(all_results[label],ensure_ascii=False,indent=2),encoding='utf-8')
        print('MODEL DONE',label,json.dumps(summary,ensure_ascii=False),flush=True)
        del model,processor
        torch.cuda.empty_cache()
    qc=[]
    for row in gallery:
        if any(tag['type']=='positive_time_window' for tag in row['reasons']):
            qc.append(dict(gallery_id=row['gallery_id'],video_id=row['video_id'],timestamp=row['timestamp'],image=row['image'],quality=quality(row['image'])))
    (out/'positive_quality.json').write_text(json.dumps(qc,ensure_ascii=False,indent=2),encoding='utf-8')
    unchanged=all(sha(path)==digest for path,digest in data['code_hashes'].items())
    unchanged=unchanged and all(dict(size=Path(path).stat().st_size,mtime_ns=Path(path).stat().st_mtime_ns)==state for path,state in data['production_files'].items())
    unchanged=unchanged and sha(mobile_weight)==protocol['mobilenet_sha256']
    report=dict(protocol=protocol,models=all_results,production_unchanged=unchanged,total_elapsed_seconds=time.perf_counter()-start,
                gallery_positive_coverage={c['id']:sum(row['video_id'] in c['acceptable_video_ids'] and abs(row['timestamp']-c['expected_timestamp'])<=c['time_tolerance_seconds'] for row in gallery) for c in cases},
                decode_warning_count=sum(bool(r.get('warning')) for r in decoded))
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('REPORT',out/'report.json',flush=True)
    if not unchanged: raise SystemExit('生产完整性检查失败')


if __name__=='__main__':
    main()
