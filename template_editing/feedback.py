"""独立反馈文件；报告+slot+segment定位，原子更新。"""
from datetime import datetime, timezone
import json
from pathlib import Path
import threading

LOCK = threading.Lock()
VALUES = ['use', 'maybe', 'reject']


def save_feedback(path, report, payload):
    if payload.get('report_id') != report['report_id']:
        raise ValueError('报告已变化，请刷新后再评价')
    slot = next((s for s in report['slots'] if s['id'] == payload.get('slot_id')), None)
    candidate = next((r for r in slot['selected'] if r['segment_id'] == payload.get('segment_id')), None) if slot else None
    if not candidate or payload.get('rating') not in VALUES:
        raise ValueError('候选或评价无效')
    note = payload.get('note', '')
    if not isinstance(note, str) or len(note) > 4000:
        raise ValueError('备注最多4000字')
    key = '|'.join([report['report_id'], slot['id'], candidate['segment_id']])
    row = dict(report_id=report['report_id'], template_id=report['template']['id'], slot_id=slot['id'],
        slot_type=slot['type'], segment_id=candidate['segment_id'], rank=candidate['rank'],
        rating=payload['rating'], note=note, updated_at=datetime.now(timezone.utc).isoformat(),
        asset_id=candidate['segment']['asset_id'], video_id=candidate['segment']['video_id'],
        source_start=candidate['segment']['source_start'], source_end=candidate['segment']['source_end'])
    path = Path(path)
    with LOCK:
        data = json.loads(path.read_text('utf-8')) if path.exists() else dict(schema_version=1, records={})
        data['records'][key] = row
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf-8')
        temporary.replace(path)
    return row
