"""账号背景设置与人工一次性覆盖；普通页面只读本地编目。"""
from pathlib import Path
from .storage import AccountBackgroundStore, FIT_LABELS


def preview(st, asset, *, width=110):
    thumbnail = asset.get('thumbnail_path') if asset else None
    if thumbnail and Path(thumbnail).is_file():
        st.image(thumbnail, width=width)


def render_account_background(st, planner, token, business_account_id):
    store = AccountBackgroundStore(planner.path)
    binding = store.binding(business_account_id)
    dialog_key = 'account_background_dialog:' + business_account_id
    status = binding['filename'] if binding and binding['enabled'] else '尚未设置账号背景'
    with st.expander('账号设置 · 账号背景 · ' + status, expanded=False):
        if binding and binding['enabled']:
            cols = st.columns([1, 3])
            preview(cols[0], binding)
            cols[1].write(binding['filename'])
            cols[1].caption(FIT_LABELS[binding['fit_mode']] + ' · ' + ('视频循环' if binding['background_type'] == 'VIDEO' else '图片覆盖全片'))
            if not Path(binding['background_path']).is_file():
                st.warning('账号背景文件不可用，请重新选择。')
        else:
            st.info('尚未设置账号背景')
        st.caption('独立绑定当前业务账号，只用于以后新生成的视频。')
        if store.required(business_account_id):
            st.caption('此账号生成必须有背景')
        def open_picker():
            # 关闭即取消；重新打开以正式绑定为准，不残留上次预览的未保存选择。
            st.session_state['account_background_asset:' + business_account_id] = binding['background_asset_id'] if binding and binding['enabled'] else None
            st.session_state['account_background_fit:' + business_account_id] = binding['fit_mode'] if binding and binding['enabled'] else 'COVER'
            st.session_state['account_background_required:' + business_account_id] = store.required(business_account_id)
            st.session_state[dialog_key] = True
        # on_click只处理本次点击，避免父fragment重跑时重复重置弹窗的选择。
        st.button('选择背景', key='account_background_choose:' + business_account_id, on_click=open_picker)
        if st.session_state.get(dialog_key):
            def close():
                st.session_state.pop(dialog_key, None)
            @st.dialog('选择账号背景', width='large', on_dismiss=close)
            def choose():
                assets = store.catalog()
                with planner.connect() as db:
                    account = db.execute('SELECT display_name FROM xiaovcat_accounts WHERE account_id=?', (business_account_id,)).fetchone()
                st.caption('当前账号：' + (account[0] if account else business_account_id))
                state = store.catalog_state()
                if state:
                    st.caption('背景素材目录：' + state['root'])
                if st.button('刷新背景素材池', key='account_background_scan:' + business_account_id):
                    try:
                        # 显式点击才扫描，普通下拉/页面切换不会调用ffmpeg。
                        with planner.connect() as db:
                            actor = planner._principal(db, token)
                            if business_account_id not in {a['account_id'] for a in planner._generation_accounts(db, actor, 'STARTUP')}:
                                raise PermissionError('ACCOUNT_BACKGROUND_ACCOUNT_SCOPE_REQUIRED')
                        from .catalog import scan
                        result = scan(store)
                        st.session_state['background_catalog_notice'] = f"已发现 {result['unique']} 个独立背景"
                        if result['errors']:
                            st.warning('部分素材无法读取，已保留上次记录。')
                        assets = store.catalog()
                    except Exception as error:
                        st.error(str(error))
                if st.session_state.get('background_catalog_notice'):
                    st.caption(st.session_state.pop('background_catalog_notice'))
                lookup = {a['background_asset_id']: a for a in assets}
                choices = [None] + list(lookup)
                default = binding['background_asset_id'] if binding and binding['enabled'] and binding['background_asset_id'] in lookup else None
                preview_column, settings_column = st.columns([1, 3])
                with settings_column:
                    asset_key = 'account_background_asset:' + business_account_id
                    if st.session_state.get(asset_key) not in choices:
                        st.session_state[asset_key] = default
                    selected = st.selectbox('背景素材', choices,
                                            format_func=lambda k: lookup[k]['filename'] if k else '不使用背景',
                                            key=asset_key)
                if selected:
                    preview(preview_column, lookup[selected], width=150)
                    a = lookup[selected]
                    preview_column.caption(f"{a['width']} × {a['height']} · " + ('图片' if a['type'] == 'IMAGE' else f"视频 {a['duration']:.1f}秒 · 自动循环"))
                else:
                    preview_column.caption('选择素材后预览')
                fit = settings_column.radio('显示方式', list(FIT_LABELS), horizontal=True, format_func=FIT_LABELS.get,
                               key='account_background_fit:' + business_account_id)
                required = settings_column.checkbox('生成必须有背景',
                                       help='开启后，无背景将阻止人工起号与AI托管的新草稿生成。', key='account_background_required:' + business_account_id)
                if settings_column.button('保存账号背景', type='primary', key='account_background_save:' + business_account_id):
                    try:
                        if required and not selected:
                            raise ValueError('生成必须有背景时，请选择一个背景素材。')
                        store.save(planner, token, business_account_id, selected, fit_mode=fit, enabled=bool(selected), required=required)
                        close()
                        st.rerun()
                    except Exception as error:
                        st.error(str(error))
            choose()


def manual_override(st, planner, business_account_id):
    """返回一次性覆盖选项，绝不写账号绑定。"""
    if not business_account_id:
        return None, None
    store = AccountBackgroundStore(planner.path)
    binding = store.binding(business_account_id)
    st.caption('账号背景：' + (binding['filename'] + ' · ' + FIT_LABELS[binding['fit_mode']] if binding and binding['enabled'] else '尚未设置账号背景'))
    override, fit = None, None
    with st.expander('本次使用其它背景', expanded=False):
        st.caption('默认使用账号绑定背景；本次选择不改变账号背景或视频模板。')
        lookup = {a['background_asset_id']: a for a in store.catalog()}
        key = 'generation_background_override:' + business_account_id
        if st.session_state.get(key) not in [None] + list(lookup):
            st.session_state[key] = None
        override = st.selectbox('本次背景', [None] + list(lookup), key=key,
                                format_func=lambda k: lookup[k]['filename'] if k else '使用账号绑定背景')
        if override:
            preview(st, lookup[override])
            fit = st.selectbox('本次背景显示方式', list(FIT_LABELS), format_func=FIT_LABELS.get,
                               key='generation_background_fit:' + business_account_id)
    return override, fit
