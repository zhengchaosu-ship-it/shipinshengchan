"""渲染故障的业务提示；不把单草稿错误或导出停机解释成账号发布失败。"""


def render_message(reason, *, render_context=False):
    value=str(reason or '')
    upper=value.upper()
    if not render_context and not any(x in upper for x in ('RENDER','JIANYING','DRAFT_','EXPORT_',
            'UNKNOWN_MODAL','OUTPUT_TRANSFER','RETURN_OUTPUT','渲染','剪映','工作站','成片回传','磁盘空间')):
        return None
    if any(x in upper for x in ('DISK','SPACE','磁盘空间')):
        return '磁盘空间不足'
    if any(x in upper for x in ('RETURNING_OUTPUT','RETURN_OUTPUT','OUTPUT_TRANSFER','WAITING_STORAGE','成片回传')):
        return '成片回传失败，请检查共享目录；保留已有成片，不要重新导出'
    if any(x in upper for x in ('OFFLINE','工作站离线','HEARTBEAT_STALE')):
        return '渲染工作站离线'
    if any(x in upper for x in ('NO_VISIBLE_JIANYING_WINDOW','PROCESS_NOT_FOUND','剪映未启动')):
        return '剪映未启动'
    if 'VERSION_DRIFT' in upper:
        return '剪映版本不符合要求，请恢复正式5.9版本'
    if any(x in upper for x in ('DRAFT_LOAD_TIMEOUT','DRAFT_OPEN_TIMEOUT')):
        return '单个视频渲染异常：草稿加载超时，原任务已隔离'
    if any(x in upper for x in ('UNKNOWN_MODAL','EXPORT_LOCATOR','EXPORT_STATE','EXPORTING','剪映导出','HALTED_NEEDS_MANUAL')):
        return '剪映导出需要处理，请核对窗口和已有成片'
    if 'RENDER_RECOVERED' in upper:
        return '该视频已恢复渲染，成片就绪；托管保持暂停'
    if 'RENDER_WORKSTATION_RECOVERED' in upper:
        return '渲染工作站已恢复，账号托管保持暂停'
    return '单个视频渲染异常，请查看该视频的具体原因'


def content_failure(content):
    value=dict(content)
    reason=value.get('failure_message') or value.get('error') or value.get('failure_code') or 'RENDER_FAILED'
    return render_message(reason,render_context=True)+'：'+str(reason)
