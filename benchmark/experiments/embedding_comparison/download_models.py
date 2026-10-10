"""只下载公开权重到实验目录，不上传图片或改写生产缓存。"""
import os
from pathlib import Path
import sys
import json
import hashlib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'deps'))
os.environ['HF_HUB_DISABLE_XET'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['HF_HUB_DOWNLOAD_TIMEOUT'] = '120'
from huggingface_hub import HfApi, hf_hub_download


def main():
    api = HfApi(token=False)
    records = {}
    for name, repo in [('dinov2', 'facebook/dinov2-small'), ('clip', 'openai/clip-vit-base-patch32')]:
        info = api.model_info(repo, token=False)
        names = {s.rfilename for s in info.siblings}
        weight = 'model.safetensors' if 'model.safetensors' in names else 'pytorch_model.bin'
        files = ['config.json', 'preprocessor_config.json', weight]
        destination = HERE / 'weights' / name
        records[name] = dict(repository=repo, revision=info.sha, files={})
        for file in files:
            print('DOWNLOAD', repo, info.sha, file, flush=True)
            path = Path(hf_hub_download(repo, file, revision=info.sha, local_dir=destination, token=False))
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                    digest.update(block)
            records[name]['files'][file] = dict(size=path.stat().st_size, sha256=digest.hexdigest())
    (HERE / 'weights_manifest.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print('MODEL DOWNLOADS COMPLETE', flush=True)


if __name__ == '__main__':
    main()
