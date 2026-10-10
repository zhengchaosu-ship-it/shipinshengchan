"""单个冻结中文cross-encoder，纯reranker logit，无分数融合。"""
import os
import sys
import time
from prepare_model import MODEL,REVISION,MODEL_DIR,OUT,ROOT

sys.path.insert(0,str(ROOT/'benchmark/experiments/embedding_comparison/deps'))
from speech_search.common import read_json,sha256

PARAMS=dict(candidate_pools=[20,50,100],inputs=['window','context'],batch_size=8,max_length=512,
    query_max_tokens=128,context_tokens_each=40,dtype='float16',device='cuda',
    ranking='reranker logit DESC; semantic score DESC only for exact ties; window_id ASC',
    output_collapse='existing speech_search.query.collapse unchanged',
    shortlist_selection='original32 only: no asset Top5/Top10 or nearby Top10 loss; highest asset Top1, nearby Top1, smallest K, window preferred',
    extra20_gate='no asset Top1/Top5/Top10 or nearby Top10 loss; no parameter adjustment')


class Reranker:
    def __init__(self):
        os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
        import torch
        from transformers import AutoTokenizer,AutoModelForSequenceClassification
        manifest=read_json(OUT/'model_manifest.json')
        assert manifest['model']==MODEL and manifest['revision']==REVISION
        for name,v in manifest['files'].items():
            if sha256(MODEL_DIR/name)!=v['sha256']:raise RuntimeError('reranker模型校验失败')
        if not torch.cuda.is_available():raise RuntimeError('CUDA不可用，不静默切CPU')
        torch.set_num_threads(4);self.torch=torch
        t=time.perf_counter()
        self.tokenizer=AutoTokenizer.from_pretrained(MODEL_DIR,local_files_only=True)
        self.model=AutoModelForSequenceClassification.from_pretrained(MODEL_DIR,local_files_only=True,torch_dtype=torch.float16).to('cuda').eval()
        assert self.model.config.num_labels==1
        self.load_seconds=time.perf_counter()-t

    def prepare(self,query,row,mode):
        tok=self.tokenizer
        q0=tok.encode(query,add_special_tokens=False);q=q0[:PARAMS['query_max_tokens']]
        core0=tok.encode(row['original_text'],add_special_tokens=False)
        budget=PARAMS['max_length']-len(q)-tok.num_special_tokens_to_add(pair=True)
        core=core0[:budget];remaining=budget-len(core)
        before=[];after=[]
        if mode=='context':
            # 中间匹配窗口优先，周围各最多40 token，不让上下文挤掉原窗口。
            left=tok.encode(row.get('context_before',''),add_special_tokens=False)
            right=tok.encode(row.get('context_after',''),add_special_tokens=False)
            n=min(PARAMS['context_tokens_each'],remaining//2)
            before=left[-n:] if n else [];after=right[:n]
        body=before+core+after
        encoded=tok.prepare_for_model(q,pair_ids=body,add_special_tokens=True,return_attention_mask=True,return_token_type_ids=False)
        meta=dict(tokens=len(encoded['input_ids']),query_truncated=len(q)<len(q0),window_truncated=len(core)<len(core0),
            before_tokens=len(before),after_tokens=len(after))
        return encoded,meta

    def score(self,query,rows,mode):
        torch=self.torch;torch.cuda.synchronize();started=time.perf_counter()
        prepared=[self.prepare(query,r,mode) for r in rows];scores=[]
        with torch.inference_mode():
            for first in range(0,len(rows),PARAMS['batch_size']):
                batch=self.tokenizer.pad([x[0] for x in prepared[first:first+PARAMS['batch_size']]],padding=True,return_tensors='pt').to('cuda')
                output=self.model(**batch,return_dict=True).logits.reshape(-1).float()
                if not torch.isfinite(output).all():raise RuntimeError('非有限reranker分数')
                scores.extend(output.cpu().tolist())
        torch.cuda.synchronize()
        return scores,[x[1] for x in prepared],(time.perf_counter()-started)*1000
