"""剪映5.9最底层账号背景。只修改新背景轨，不触碰主体或模板。"""
from .storage import validate_snapshot


def fit_settings(api, width, height, canvas_width, canvas_height, mode):
    # 剪映默认以完整显示为基准；只缩放背景，始终居中，不修改主体。
    contain = min(canvas_width / width, canvas_height / height)
    if mode == 'COVER':
        scale = max(canvas_width / width, canvas_height / height) / contain
        return api.ClipSettings(scale_x=scale, scale_y=scale)
    if mode == 'STRETCH':
        return api.ClipSettings(scale_x=canvas_width / (width * contain), scale_y=canvas_height / (height * contain))
    if mode != 'CONTAIN':
        raise ValueError('ACCOUNT_BACKGROUND_FIT_INVALID')
    return api.ClipSettings()


def add_background(script, main_track, snapshot, duration_us, api, *, width=1080, height=1920):
    validate_snapshot(snapshot, snapshot['business_account_id'])
    if not snapshot.get('enabled'):
        return dict(snapshot, duration_us=duration_us, track_name=None, segments=0)
    material = api.VideoMaterial(snapshot['background_path'])
    settings = fit_settings(api, material.width, material.height, width, height, snapshot['fit_mode'])
    track = script.insert_track(api.TrackSpec(api.TrackType.video, name='账号背景'), at_index=0)
    cursor, count = 0, 0
    while cursor < duration_us:
        # 图片借助静帧延长；视频每段都从0重新播放，最后一段精确截断。
        length = duration_us - cursor if snapshot['background_type'] == 'IMAGE' else min(material.duration, duration_us - cursor)
        if length <= 0:
            raise ValueError('ACCOUNT_BACKGROUND_INVALID_DURATION')
        source_length = min(length, material.duration)
        segment = api.VideoSegment(material, api.Timerange(cursor, length),
                                   source_timerange=api.Timerange(0, source_length), volume=0., clip_settings=settings)
        script.add_segment(segment, track=track)
        cursor += length
        count += 1
    return dict(snapshot, duration_us=duration_us, track_name='账号背景', track_index=0,
                segments=count, video_policy='LOOP_VIDEO_BACKGROUND')
