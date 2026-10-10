"""原工作台内的轻量反馈组件，不调用搜索引擎。"""
import streamlit as st


def result_feedback(store, search_id, rank, speech=False):
    if store is None or not search_id:
        return
    prefix = f'feedback_{search_id}_{rank}'
    with st.form(prefix):
        with st.expander('补充时间点 / 备注（可选）'):
            corrected = st.text_input('正确时间点', placeholder='秒数或 00:02:03.500；留空仅确认素材',
                                      key=prefix + '_time')
            note = st.text_input('备注', max_chars=2000, key=prefix + '_note')
        if st.form_submit_button('这条是正确话术' if speech else '这是正确素材', width='stretch'):
            try:
                store.save_feedback(search_id, rank, corrected, note)
                st.success(f'已记录：第 {rank} 个结果是正确素材')
            except Exception as error:
                st.error(f'反馈未保存：{error}')


def search_feedback(store, search_id, result_count, speech=False):
    if store is None or not search_id:
        return
    with st.container(border=True):
        st.caption('搜索反馈')
        with st.expander('反馈记录详情'):
            st.code(search_id,language=None)
        st.caption((f'若前 {min(10, result_count)} 个结果都不对，可记录未命中。' if result_count
                    else '本次没有返回结果，也可以记录未命中。') + '改选会替换本次反馈。')
        with st.form(f'no_correct_{search_id}'):
            note = st.text_input('未命中备注（可选）', max_chars=2000, key=f'no_correct_note_{search_id}')
            if st.form_submit_button('Top10没有找到' if speech else '没有正确结果'):
                try:
                    store.save_feedback(search_id, note=note)
                except Exception as error:
                    st.error(f'反馈未保存：{error}')
        try:
            feedback = store.get_feedback(search_id)
            if feedback:
                if feedback['feedback_status'] == 'no_correct':
                    st.success('已记录：没有正确结果')
                else:
                    timestamp = feedback['corrected_timestamp']
                    label = '时间点未标注' if timestamp is None else f'正确时间 {timestamp:g} 秒'
                    st.success(f"已记录：第 {feedback['selected_rank']} 个结果是正确素材 · {label}")
        except Exception as error:
            st.warning(f'暂时无法读取反馈：{error}')


def export_controls(store):
    with st.expander('搜索反馈 / 导出 CSV'):
        st.caption('每次搜索保存查询与结果；反馈只写入本机独立记录库。')
        if store is None:
            st.warning('反馈库暂不可用')
            return
        if st.button('导出反馈 CSV', key='export_feedback_csv', width='stretch'):
            try:
                path = store.export_csv()
                st.session_state.feedback_export = str(path)
            except Exception as error:
                st.error(f'导出失败：{error}')
        path = st.session_state.get('feedback_export')
        if path:
            from pathlib import Path
            path = Path(path)
            try:
                st.download_button('下载 CSV', path.read_bytes(), file_name=path.name,
                                   mime='text/csv', on_click='ignore')
                st.caption(f'已导出到：{path}')
            except OSError as error:
                st.warning(f'导出文件暂不可用：{error}')
