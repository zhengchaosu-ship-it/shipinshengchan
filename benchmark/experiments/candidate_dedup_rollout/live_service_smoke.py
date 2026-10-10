"""真实8502服务HTTP上传/WebSocket会话集成测试；不改Web、不mock上传/搜索。

浏览器文件选择器受限时补充服务端验收；不声称验证了原生文件选择对话框。
"""
from pathlib import Path
from contextlib import closing
from io import BytesIO
import json, sqlite3, time, uuid
import requests
from websockets.sync.client import connect
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from streamlit.proto.WidgetStates_pb2 import WidgetStates
from PIL import Image
import cv2

ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
BASE='http://127.0.0.1:8502'

class Session:
    def __init__(self):
        self.http=requests.Session();self.http.trust_env=False
        self.http.get(BASE+'/_stcore/health',timeout=10).raise_for_status()
        token=self.http.cookies.get('_streamlit_xsrf')
        assert token,'服务未返回XSRF cookie'
        cookie='; '.join(f'{k}={v}' for k,v in self.http.cookies.items())
        self.http.headers.update({'X-Xsrftoken':token})
        self.ws=connect('ws://127.0.0.1:8502/_stcore/stream',origin=BASE,
                        subprotocols=['streamlit',token],additional_headers={'Cookie':cookie},proxy=None,max_size=20_000_000)
        self.states=WidgetStates();self.elements={};self.page='';self.session_id=None

    def send(self,m):self.ws.send(m.SerializeToString())

    def receive(self,until='script_finished'):
        collected=[]
        while True:
            data=self.ws.recv(timeout=90);msg=ForwardMsg();msg.ParseFromString(data)
            kind=msg.WhichOneof('type')
            if kind=='new_session':
                self.session_id=msg.new_session.initialize.session_id or self.session_id
                self.page=msg.new_session.page_script_hash
            if kind=='delta' and msg.delta.HasField('new_element'):
                el=msg.delta.new_element;self.elements[tuple(msg.metadata.delta_path)]=el;collected.append(el)
                if el.HasField('exception'):raise RuntimeError(str(el.exception))
            if kind==until:return msg,collected

    def rerun(self,trigger=None):
        msg=BackMsg();msg.rerun_script.page_script_hash=self.page
        msg.rerun_script.widget_states.CopyFrom(self.states)
        if trigger:msg.rerun_script.widget_states.widgets.add(id=trigger,trigger_value=True)
        self.send(msg);return self.receive()[1]

    def widget(self,kind,suffix=None,label=None):
        for el in self.elements.values():
            if el.HasField(kind):
                v=getattr(el,kind)
                if suffix and v.id.endswith(suffix):return v
                if label and v.label==label:return v
        raise ValueError(f'widget missing {kind} {suffix} {label}')

    def set_text(self,wid,value):
        self.states.widgets.add(id=wid,string_value=value)

    def upload(self,path,name):
        msg=BackMsg();msg.file_urls_request.request_id=uuid.uuid4().hex
        msg.file_urls_request.session_id=self.session_id;msg.file_urls_request.file_names.append(name)
        self.send(msg);reply,_=self.receive('file_urls_response');url=reply.file_urls_response.file_urls[0]
        data=path.read_bytes()
        self.http.put(BASE+url.upload_url,files={'file':(name,data,'image/png')},timeout=30).raise_for_status()
        state=self.states.widgets.add(id=self.widget('file_uploader',suffix='query_image').id)
        info=state.file_uploader_state_value.uploaded_file_info.add(name=name,size=len(data),file_id=url.file_id)
        info.file_urls.CopyFrom(url)

def text(elements):return '\n'.join(str(e) for e in elements)

def main():
    tests=[('hell_04',Path('D:/Users/Desktop/地狱素材/4.png'),7,476),
           ('business_16',ROOT/'benchmark/queries/business20/16.png',8,3850),
           ('business_05',ROOT/'benchmark/queries/business20/5.png',4,1470)]
    report=[]
    for cid,path,correct_rank,gt_time in tests:
        s=Session()
        try:
            initial=s.rerun();visible=text(initial)
            assert all(x in visible for x in ['formal_v1_repaired','319','507','1,843,351'])
            name='candidate_dedup_smoke_'+cid+'.png';s.upload(path,name)
            tick=time.perf_counter();searched=s.rerun(s.widget('button',suffix='image_submit').id)
            elapsed=time.perf_counter()-tick
            assert '搜索未完成' not in text(searched)
            dbpath=ROOT/'benchmark/feedback/search_feedback.db'
            with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
                db.row_factory=sqlite3.Row
                entry=dict(db.execute('SELECT * FROM searches WHERE query_name=? ORDER BY searched_at DESC LIMIT 1',(name,)).fetchone())
            assert entry['status']=='completed',entry['status']
            rows=json.loads(entry['topk_json']);assert len(rows)==10
            assert all(row['asset_id'] and row['video_id'] and row['timestamp']>=0 and Path(row['file_path']).is_file() for row in rows)
            expected=json.loads((OUT/'regression.json').read_text(encoding='utf-8'))
            er=next(c['returned'] for c in expected['cases'] if c['case_id']==cid)
            assert [(r['asset_id'],r['video_id'],r['timestamp']) for r in rows]==[(r['asset_id'],r['video_id'],r['timestamp']) for r in er]
            # HTTP读取实际返回的缩略图媒体，检查客户端可读取。
            urls=[]
            for el in searched:
                if el.HasField('imgs'):
                    urls.extend(i.url for i in el.imgs.imgs)
            for url in urls:
                im=s.http.get(BASE+url,timeout=10);im.raise_for_status()
                with Image.open(BytesIO(im.content)) as pic:pic.verify()
            assert len(urls)>=11
            # 提交带测试备注的既有GT，避免把部署测试误认成新增独立业务案例。
            sid=entry['search_id'];prefix=f'feedback_{sid}_{correct_rank}'
            s.set_text(s.widget('text_input',suffix=prefix+'_time').id,str(gt_time))
            s.set_text(s.widget('text_input',suffix=prefix+'_note').id,'[上线Smoke Test] 既有'+cid+'；仅验证候选去重部署，不是新增独立业务案例。')
            feedback_button=s.widget('button',suffix='FormSubmitter:'+prefix+'-这是正确素材')
            confirmed=s.rerun(feedback_button.id)
            assert '已记录' in text(confirmed)
            with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
                db.row_factory=sqlite3.Row;feedback=dict(db.execute('SELECT * FROM feedback WHERE search_id=?',(sid,)).fetchone())
            assert feedback['selected_rank']==correct_rank and feedback['corrected_timestamp']==gt_time
            preview=s.rerun(s.widget('button',suffix=f'preview_{correct_rank}').id)
            videos=[e.video.url for e in preview if e.HasField('video')];assert videos,text(preview)[-4000:]
            video=s.http.get(BASE+videos[-1],timeout=30);video.raise_for_status()
            clip=OUT/(cid+'_live_preview.mp4');clip.write_bytes(video.content)
            cap=cv2.VideoCapture(str(clip));ok,frame=cap.read();frames=cap.get(cv2.CAP_PROP_FRAME_COUNT);fps=cap.get(cv2.CAP_PROP_FPS);cap.release()
            assert ok and fps>0 and 0<frames/fps<=10
            result={'case_id':cid,'query':str(path),'query_name':name,'search_id':sid,'search_roundtrip_seconds':elapsed,
                    'result_count':len(rows),'results_match_adapter_regression':True,'valid_media_images':len(urls),
                    'feedback':feedback,'preview_url':videos[-1],'preview_duration':frames/fps,
                    'preview_source_timestamp':rows[correct_rank-1]['timestamp'],'preview_start_expected':max(0,rows[correct_rank-1]['timestamp']-1),
                    'preview_decoded':True,'page_labels_verified':True}
            report.append(result)
            (OUT/'live_service_smoke.json').write_text(json.dumps({'status':'PASS' if len(report)==3 else 'RUNNING','mode':'实际8502服务 HTTP上传+WebSocket页面事件；非浏览器文件选择器测试','cases':report},ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(result,ensure_ascii=False),flush=True)
        finally:s.ws.close();s.http.close()

if __name__=='__main__':main()
