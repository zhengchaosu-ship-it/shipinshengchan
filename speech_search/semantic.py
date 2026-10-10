"""中文BGE小规模验证；本阶段硬限制150000窗口且不超过20个asset。"""
import argparse
import contextlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from speech_search.common import (DB, HERE, MODEL_DIR, MODEL_ID, REVISION, ROOT, RULES,
                                 read_json, ro, sha256, write_json)


class Encoder:
    def __init__(self, device='cpu'):
        sys.path.insert(0, str(ROOT / 'benchmark/experiments/embedding_comparison/deps'))
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        import torch
        from transformers import AutoModel, AutoTokenizer
        torch.set_num_threads(4)
        if device == 'cuda' and not torch.cuda.is_available():
            raise RuntimeError('CUDA不可用；不静默回退CPU')
        manifest = read_json(HERE / 'models/model_manifest.json')
        if manifest['revision'] != REVISION or manifest['model_id'] != MODEL_ID:
            raise RuntimeError('模型版本不匹配')
        for name, expected in manifest['files'].items():
            if (MODEL_DIR/name).stat().st_size != expected['size'] or sha256(MODEL_DIR/name) != expected['sha256']:
                raise RuntimeError('中文模型文件校验失败：'+name)
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, local_files_only=True)
        self.model = AutoModel.from_pretrained(MODEL_DIR, local_files_only=True).to(device).eval()
        self.device = device
        self.dim = self.model.config.hidden_size

    def encode(self, texts, query=False):
        import torch
        values = [RULES['query_instruction'] + t if query else t for t in texts]
        batch = self.tokenizer(values, padding=True, truncation=True, max_length=256, return_tensors='pt').to(self.device)
        with torch.inference_mode():
            output = self.model(**batch).last_hidden_state[:, 0]
            output = torch.nn.functional.normalize(output.float(), p=2, dim=1)
        return output.cpu().numpy().astype('float32')


def build_pilot(plan_path, device='cuda', batch_size=64):
    import faiss
    import numpy as np
    plan = read_json(plan_path)
    if not 1 <= len(plan['asset_ids']) <= 20:
        raise ValueError('本阶段仅允许1–20个asset的独立pilot')
    output = HERE / 'semantic_pilot'
    output.mkdir(exist_ok=True)
    with contextlib.closing(ro(DB)) as c:
        marks = ','.join('?' for _ in plan['asset_ids'])
        rows = c.execute(f'SELECT id,normalized_text FROM windows WHERE asset_id IN ({marks}) ORDER BY id', plan['asset_ids']).fetchall()
    if len(rows) > RULES['semantic_max_windows']:
        raise ValueError('超过本阶段小规模编码上限，禁止扩大为全库')
    plan_hash = sha256(plan_path)
    if (output / 'report.json').exists():
        old = read_json(output / 'report.json')
        if old['plan_sha256'] != plan_hash:
            raise ValueError('已存在其它pilot；禁止静默覆盖')
        return old
    encoder = Encoder(device)
    index = faiss.IndexFlatIP(encoder.dim)
    ids = np.array([r['id'] for r in rows], dtype='int64')
    started = time.perf_counter(); inference = 0.0
    for first in range(0, len(rows), batch_size):
        t = time.perf_counter()
        vectors = encoder.encode([r['normalized_text'] for r in rows[first:first + batch_size]])
        inference += time.perf_counter() - t
        index.add(vectors)
        if first % (batch_size * 20) == 0:
            write_json(output / 'progress.json', dict(encoded=index.ntotal,total=len(rows),elapsed_seconds=time.perf_counter()-started))
    faiss.write_index(index, str(output / 'text.faiss'))
    np.save(output / 'window_ids.npy', ids)
    report = dict(status='READY',scope='PILOT_ONLY',asset_ids=plan['asset_ids'],windows=len(rows),
                  dim=encoder.dim,model_id=MODEL_ID,revision=REVISION,plan_sha256=plan_hash,
                  build_seconds=time.perf_counter()-started,inference_seconds=inference,device=device,
                  rules=RULES,faiss_bytes=(output/'text.faiss').stat().st_size,
                  files={n:sha256(output/n) for n in ['text.faiss','window_ids.npy']})
    write_json(output / 'report.json',report)
    print(report,flush=True)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,default=HERE/'validation/pilot_plan.json')
    p.add_argument('--device',choices=['cpu','cuda'],default='cuda')
    args=p.parse_args()
    build_pilot(args.plan,args.device)
