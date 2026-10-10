"""仅下载已告知用户的单个公开reranker；不上传业务文本。"""
import os
import sys
from pathlib import Path

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT))
from speech_search.common import sha256,write_json

MODEL='BAAI/bge-reranker-base'
REVISION='2cfc18c9415c912f9d8155881c133215df768a70'
FILES=['config.json','model.safetensors','tokenizer.json','tokenizer_config.json','special_tokens_map.json','sentencepiece.bpe.model']
MODEL_DIR=OUT/'model'


def main():
    os.environ['HF_HUB_DISABLE_XET']='1'
    os.environ['HF_HUB_DOWNLOAD_TIMEOUT']='120'
    from huggingface_hub import snapshot_download
    snapshot_download(MODEL,revision=REVISION,local_dir=str(MODEL_DIR),allow_patterns=FILES,max_workers=2)
    write_json(OUT/'model_manifest.json',dict(model=MODEL,revision=REVISION,
        files={n:dict(size=(MODEL_DIR/n).stat().st_size,sha256=sha256(MODEL_DIR/n)) for n in FILES}))
    print('RERANKER_MODEL_READY',flush=True)


if __name__=='__main__':main()
