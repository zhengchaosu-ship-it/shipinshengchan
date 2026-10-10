"""仅在本机提供独立GT确认包和GT写入；不连接生产Web或反馈库。"""
import argparse
from datetime import datetime, timezone
import json
import math
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import shutil
import threading
from urllib.parse import urlparse

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / 'auto_remake/benchmarks/real_business_gt_review_v1/review_pack'
LOCK = threading.Lock()


def validate_annotations(rows, case):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100: raise ValueError('区间数量不合法')
    ids = set(); valid_blocks = {b['block_id'] for b in case['blocks']}
    def number(v): return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    def source(row, required=False):
        start, end = row.get('correct_source_start'), row.get('correct_source_end')
        for v in (start, end):
            if v is not None and (not number(v) or v < 0): raise ValueError('原片时间必须为非负秒数')
        if required and (start is None or end is None): raise ValueError('CONFIRMED必须填写原片起止时间')
        if start is not None and end is not None and end < start: raise ValueError('原片结束不能早于开始')
    for row in rows:
        if row.get('case_id') != case['case_id'] or row.get('reference_video') != case['reference_video']: raise ValueError('参考文件不匹配')
        if row.get('block_id') not in valid_blocks: raise ValueError('未知参考block')
        if not isinstance(row.get('annotation_id'), str) or row['annotation_id'] in ids: raise ValueError('重复区间ID')
        ids.add(row['annotation_id'])
        start, end = row.get('reference_start'), row.get('reference_end')
        if not number(start) or not number(end) or not 0 <= start < end <= case['duration'] + .001: raise ValueError('参考区间超出视频范围')
        status = row.get('status')
        if status not in {'UNKNOWN','PARTIAL','CONFIRMED','SOURCE_NOT_IN_LIBRARY'}: raise ValueError('非法GT状态')
        if status in {'CONFIRMED','PARTIAL'} and not (row.get('correct_asset_id') and row.get('correct_video_id') is not None): raise ValueError('请选择候选身份')
        if status in {'UNKNOWN','SOURCE_NOT_IN_LIBRARY'} and any(row.get(k) is not None for k in ['correct_asset_id','correct_video_id','correct_source_start','correct_source_end']): raise ValueError('未知/库外不能附带确定来源')
        source(row, status == 'CONFIRMED')
        alternatives = row.get('acceptable_alternatives')
        if not isinstance(alternatives, list): raise ValueError('替代来源格式错误')
        for alt in alternatives:
            if not alt.get('correct_asset_id') or alt.get('correct_video_id') is None: raise ValueError('替代来源缺少身份')
            source(alt, True)
        reviews = row.get('candidate_reviews', {})
        if not isinstance(reviews, dict) or any(v not in {'CORRECT','NOT_SOURCE','POSSIBLE'} for v in reviews.values()): raise ValueError('候选判断格式错误')


def make_handler(root, gt_file):
    manifest = json.loads((root/'manifest.json').read_text('utf-8'))
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(root),**kwargs)
        def log_message(self,*args): pass
        def reply(self, code, payload):
            body=json.dumps(payload,ensure_ascii=False).encode('utf-8');self.send_response(code)
            self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if urlparse(self.path).path == '/api/gt':
                try: self.reply(200,json.loads(gt_file.read_text('utf-8')))
                except Exception as exc: self.reply(500,dict(error=str(exc)))
                return
            super().do_GET()
        def do_POST(self):
            if self.path != '/api/gt': self.reply(404,dict(error='未知路径'));return
            expected='http://'+self.headers.get('Host','')
            if self.headers.get('Origin') != expected: self.reply(403,dict(error='仅允许本机页面同源写入'));return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 2_000_000: raise ValueError('请求大小不合法')
                payload=json.loads(self.rfile.read(size))
                case=next(c for c in manifest['cases'] if c['case_id']==payload['case_id'])
                validate_annotations(payload['annotations'],case)
                with LOCK:
                    current=json.loads(gt_file.read_text('utf-8'))
                    if payload['revision'] != current['revision']:
                        self.reply(409,dict(error='GT已由另一页面更新，请先导出草稿，再刷新合并'));return
                    current['annotations']=[r for r in current['annotations'] if r['case_id']!=case['case_id']]+payload['annotations']
                    current['revision']+=1;current['updated_at']=datetime.now(timezone.utc).isoformat()
                    history=gt_file.parent/'gt_history';history.mkdir(exist_ok=True)
                    shutil.copy2(gt_file,history/f'{gt_file.stem}_revision_{current["revision"]-1:04d}.json')
                    temporary=gt_file.with_suffix('.tmp');temporary.write_text(json.dumps(current,ensure_ascii=False,indent=2),'utf-8');temporary.replace(gt_file)
                self.reply(200,current)
            except Exception as exc: self.reply(400,dict(error=str(exc)))
        def send_head(self):
            # HTML5 seek需要字节Range；只服务确认包中的文件。
            self._remaining=None
            path=Path(self.translate_path(self.path)).resolve()
            if not path.is_relative_to(root.resolve()): self.send_error(403);return None
            header=self.headers.get('Range')
            if path.is_file() and header:
                match=re.fullmatch(r'bytes=(\d+)-(\d*)',header)
                size=path.stat().st_size
                if not match: self.send_error(416);return None
                start=int(match[1]);end=min(int(match[2]) if match[2] else size-1,size-1)
                if not 0<=start<=end<size: self.send_error(416);return None
                file=path.open('rb');file.seek(start);self._remaining=end-start+1
                self.send_response(206);self.send_header('Content-Type',self.guess_type(str(path)))
                self.send_header('Accept-Ranges','bytes');self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                self.send_header('Content-Length',str(self._remaining));self.end_headers();return file
            return super().send_head()
        def copyfile(self,source,output):
            try:
                if self._remaining is None: return super().copyfile(source,output)
                while self._remaining:
                    chunk=source.read(min(65536,self._remaining))
                    if not chunk: break
                    output.write(chunk);self._remaining-=len(chunk)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass
    return Handler


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8510);parser.add_argument('--root',type=Path,default=DEFAULT_ROOT);parser.add_argument('--gt-file',type=Path)
    args=parser.parse_args();gt=args.gt_file or args.root/'ground_truth.json'
    server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(args.root,gt))
    print(f'GT review: http://127.0.0.1:{args.port} / GT={gt}',flush=True)
    server.serve_forever()
