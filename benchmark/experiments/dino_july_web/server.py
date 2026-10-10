"""正式8502入口：原工作台保持原样，只挂载同源生产素材上传代理。"""
from pathlib import Path
import streamlit as st
from starlette.routing import Mount
from production_materials.proxy import MaterialProxy, PREFIX

app = st.App(Path(__file__).with_name('app.py'),routes=[Mount(PREFIX,app=MaterialProxy(frontend_port=st.get_option('server.port')))])
