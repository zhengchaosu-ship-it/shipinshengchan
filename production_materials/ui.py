"""8502同源素材入口；文件字节由固定回环代理送至独立上传服务。"""
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen
import ipaddress
import json
import sqlite3

from .config import settings,COMMERCE
from .store import Store

def local_admin_connection():
    # st.context.ip_address把localhost归为None。读取服务端连接原值，拒绝代理转发请求。
    try:
        from streamlit import runtime
        from streamlit.runtime.scriptrunner_utils.script_run_context import get_script_run_ctx
        context=get_script_run_ctx()
        client=runtime.get_instance().get_client(context.session_id)
        connection=client.client_context
        if any(k.lower() in {'forwarded','x-forwarded-for','x-real-ip'} for k,v in connection.headers):return False
        peer=ipaddress.ip_address(connection.remote_ip)
        return (peer.ipv4_mapped or peer).is_loopback if isinstance(peer,ipaddress.IPv6Address) else peer.is_loopback
    except (AttributeError,RuntimeError,ValueError,OSError,TypeError) as error:
        import logging
        logging.warning('Material directory local peer check: %s',error)
        return False

def refresh_catalog_views(st):
    st.markdown('''<style>
    .st-key-studio_generation_route label {padding:7px 15px;border:1px solid #294759;border-radius:7px;margin:0;background:#102536;}
    .st-key-studio_generation_route label:has(input:checked) {border-color:#4dd8ef;background:#17394c;}
    .st-key-studio_generation_route label p {font-size:14px;}
    .st-key-studio_generation_route [data-testid="stRadioOption"]>div>div:first-child {display:none;}
    </style>''',unsafe_allow_html=True)
    path=Path(settings()['database'])
    if not path.is_file():return
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
            revision=db.execute('SELECT revision FROM catalog_state WHERE singleton=1').fetchone()[0]
    except sqlite3.Error:return
    if st.session_state.get('production_material_revision')!=revision:
        st.session_state.pop('studio_generation_sources',None)
        for key in list(st.session_state):
            if str(key).startswith('startup_snapshot:') and str(key).endswith(':catalog'):st.session_state.pop(key,None)
        st.session_state['production_material_revision']=revision

def render(st):
    import streamlit.components.v1 as components
    config=settings()
    origin=urlsplit(st.context.url)
    host=origin.hostname
    if host not in [h.lower() for h in config['allowed_hosts']] or origin.scheme not in {'http','https'}:
        st.warning('请使用工作室的局域网地址访问素材上传入口。');return
    frontend_port=origin.port or (443 if origin.scheme=='https' else 80)
    try:
        # 验证员工实际经过的8502入口，不再仅凭8510回环可用判定成功。
        with urlopen(f"http://127.0.0.1:{frontend_port}/production-materials/health",timeout=3) as response:
            value=json.loads(response.read(4096))
            if response.status!=200 or value.get('status')!='READY' or value.get('service')!='PRODUCTION_MATERIAL_UPLOAD':
                raise OSError('material gateway unavailable')
    except (OSError,ValueError):
        st.title('生产素材库')
        st.warning('素材上传服务暂时不可用。请稍后刷新；已上传分片会保留，重新选择原文件可以继续。')
        return
    url=f"{origin.scheme}://{origin.netloc}/production-materials/"
    with st.expander('大批量上传 / 独立窗口'):
        st.caption('上传中需要切换8502页面时，可在独立窗口操作；该窗口保持打开即可继续上传。')
        st.link_button('在独立窗口上传',url)
    components.iframe(url,height=1100,scrolling=True)

def advanced(st):
    st.subheader('生产素材目录')
    st.caption('带货五类接收目录由正式素材库登记。员工上传时只选择分类，无需选择文件夹。')
    config=settings();store=Store(config)
    if not store.path.exists():st.info('素材服务尚未初始化。');return
    if not local_admin_connection():
        st.info('目录设置仅在服务器本机的8502高级管理中开放。');return
    messages={'EXISTING_LOCAL_DIRECTORY_REQUIRED':'请选择已存在的本地文件夹。','LINKED_POOL_NOT_ALLOWED':'目录不能是快捷链接或目录联接。',
        'PROTECTED_DIRECTORY':'不能使用原始素材目录或上传服务内部目录。','POOL_DIRECTORIES_MUST_BE_SEPARATE':'各生产素材池必须使用互不包含的独立目录。',
        'CONFIGURED_POOL_IN_USE_NO_MOVE':'此目录已有上传记录，不允许在此移动正式素材。'}
    for pool in store.pools(True):
        if pool['pool_id'] not in COMMERCE:continue
        widget_key='root_'+pool['pool_id']
        source_key='registered_'+widget_key
        if st.session_state.get(source_key)!=pool['root']:
            st.session_state[widget_key]=pool['root'] or ''
            st.session_state[source_key]=pool['root']
        with st.form('material_pool_'+pool['pool_id']):
            st.markdown('**'+pool['label']+'**')
            value=st.text_input('接收目录',placeholder='请选择现有的本地生产目录',key=widget_key)
            if st.form_submit_button('保存目录'):
                try:
                    store.configure_pool(pool['pool_id'],value)
                    st.success('目录已保存。员工重新进入上传页面即可选择。')
                except (ValueError,OSError) as error:st.error(messages.get(str(error),'目录保存失败，请检查目录是否存在以及服务是否可写。'))
    with st.expander('产品登记'):
        st.dataframe(store.products(),column_order=['display_name','product_id'],hide_index=True,width='stretch')
        with st.form('production_material_product'):
            key=st.text_input('稳定产品ID',help='只使用英文字母、数字、下划线或短横线；不是产品昵称。')
            name=st.text_input('产品名称')
            if st.form_submit_button('保存产品'):
                try:store.add_product(key,name);st.success('产品已登记，重新进入上传页面即可选择。')
                except ValueError:st.error('请填写有效的产品ID和名称。')
