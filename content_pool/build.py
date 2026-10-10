"""只合并同asset、同副本、同转写run的连续字幕，不制造新时间。"""
import hashlib
import math

from .classify import RULES, clean
from .schema import ContentSegment


def construct(seed, rows):
    by_id = {r['id']: i for i, r in enumerate(rows)}
    if seed['first_segment_id'] not in by_id or seed['last_segment_id'] not in by_id:
        return None
    left, right = by_id[seed['first_segment_id']], by_id[seed['last_segment_id']]
    original_right = right
    if right < left:
        return None

    def valid(a, b):
        part = rows[a:b + 1]
        return (all(math.isfinite(r['start']) and math.isfinite(r['end']) and 0 <= r['start'] < r['end']
                    and not r.get('timestamp_warning') for r in part)
                and all(x['video_id'] == y['video_id'] and x.get('run_id') == y.get('run_id') and
                        0 <= y['start'] - x['start'] and -.25 <= y['start'] - x['end'] <= RULES['max_gap_seconds']
                        for x, y in zip(part, part[1:]))
                and part[-1]['end'] - part[0]['start'] <= RULES['max_seconds'])

    if not valid(left, right):
        return None
    if clean(rows[left]['text']).startswith(tuple(RULES['dependent_start'])) and left > 0 and valid(left - 1, right):
        left -= 1
    # 最多扩展已读到的2句；补足时长、信息量及悬空句尾。
    while right < original_right + 2 and right + 1 < len(rows) and valid(left, right + 1):
        text = ' '.join(r['text'] for r in rows[left:right + 1])
        if (rows[right]['end'] - rows[left]['start'] >= RULES['min_seconds'] and
                len(clean(text)) >= RULES['min_information_chars'] and
                not clean(text).endswith(tuple(RULES['incomplete_end']))):
            break
        right += 1
    part = rows[left:right + 1]
    text = ' '.join(r['text'].strip() for r in part)
    duration = part[-1]['end'] - part[0]['start']
    meaningful = ''.join(clean(r['text']) for r in part if clean(r['text']) not in RULES['fillers'])
    if duration < RULES['min_seconds'] or len(meaningful) < RULES['min_information_chars']:
        return None
    key = f"{seed['asset_id']}|{part[0]['start']:.6f}|{part[-1]['end']:.6f}|{text}"
    return ContentSegment(segment_id='SEG-' + hashlib.sha256(key.encode()).hexdigest()[:20],
        asset_id=seed['asset_id'], video_id=seed['video_id'], file_name=seed['file_name'], file_path=seed['file_path'],
        source_start=part[0]['start'], source_end=part[-1]['end'], duration=round(duration, 6), transcript=text,
        recommend_metadata=dict(source_video_id=part[0]['video_id'], source_subtitle_ids=[r['id'] for r in part],
            source_window_ids=[seed['window_id']], source_subtitles=part,
            context_before=' '.join(r['text'] for r in rows[max(0, left - 2):left]),
            context_after=' '.join(r['text'] for r in rows[right + 1:right + 3]),
            semantic_score=seed['semantic_score'], recall_queries=seed.get('recall_queries', []),
            boundary_note='原Whisper字幕边界，未做强制对齐；最终剪点须听审'))
