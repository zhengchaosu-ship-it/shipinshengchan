"""只下载公开模型至独立目录，不上传文本、不改变生产依赖。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from speech_search.common import MODEL_DIR, MODEL_ID, REVISION, HERE, sha256, write_json


def main():
    os.environ['HF_HUB_DISABLE_XET'] = '1'
    from huggingface_hub import snapshot_download
    files = ['config.json', 'model.safetensors', 'tokenizer.json', 'tokenizer_config.json',
             'special_tokens_map.json', 'vocab.txt']
    snapshot_download(MODEL_ID, revision=REVISION, local_dir=str(MODEL_DIR),
                      allow_patterns=files, max_workers=2)
    write_json(HERE / 'models/model_manifest.json', dict(model_id=MODEL_ID, revision=REVISION,
               files={name: dict(size=(MODEL_DIR / name).stat().st_size,
                      sha256=sha256(MODEL_DIR / name)) for name in files}))
    print('MODEL_READY', MODEL_DIR, flush=True)


if __name__ == '__main__':
    main()
