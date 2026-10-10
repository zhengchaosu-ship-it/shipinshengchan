"""只读有限重新观察；绝不包裹/重试Invoke、Toggle、SetValue等写动作。"""
import time


def is_stale(error):
    code=getattr(error,'hresult',None)
    if code is not None and (code & 0xffffffff)==0x80040201:
        return True
    message=str(error).lower()
    return any(word in message for word in ('stale_element','stale element','element disappeared',
        'element not available','control no longer exists','控件已消失','elementnotavailable'))


def fresh_read(reader, *, label, accept=lambda value:True, timeout=0, audit=lambda event:None):
    """每次reader必须自行从当前窗口/root重观察；最多2次stale恢复，总预算非每轮重置。"""
    deadline=time.monotonic()+timeout
    retries=0
    while True:
        try:
            value=reader()
            if accept(value):
                audit(dict(label=label,reobservations=retries,result='VERIFIED',write_replays=0))
                return value
            if time.monotonic()>=deadline:
                raise RuntimeError('UI_STATE_UNSTABLE:'+label)
        except Exception as error:
            if not is_stale(error):raise
            if retries==2:
                audit(dict(label=label,reobservations=retries,result='UI_STATE_UNSTABLE',write_replays=0))
                raise RuntimeError('UI_STATE_UNSTABLE:'+label) from error
            retries+=1
            audit(dict(label=label,reobservations=retries,result='STALE_REOBSERVE',write_replays=0))
        time.sleep(.1)  # 有界轮询真实回读条件，不以sleep冒充成功。
