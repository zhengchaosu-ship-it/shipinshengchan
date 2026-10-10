"""搜索快照、人工标注与导出；仅使用标准库。"""
from contextlib import contextmanager
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from uuid import uuid4
from benchmark.feedback.migrate_speech import migrate

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE / 'search_feedback.db'
CSV_FIELDS = ('search_id', 'searched_at', 'query_type', 'query_text', 'query_name',
              'query_image_path', 'query_sha256', 'index_version', 'search_status',
              'error', 'encoded_prompt', 'notes_json', 'feedback_status', 'selected_rank',
              'asset_id', 'video_id', 'file_path', 'predicted_timestamp',
              'corrected_timestamp', 'note', 'feedback_at', 'topk_json')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def parse_timestamp(value):
    """空值保留为未标注；接受秒数、分:秒、时:分:秒。"""
    if value is None or str(value).strip() == '':
        return None
    try:
        parts = [float(part) for part in str(value).strip().split(':')]
    except ValueError as error:
        raise ValueError('正确时间点请输入非负秒数或 时:分:秒') from error
    if (len(parts) not in (1, 2, 3) or
            any(not math.isfinite(part) or part < 0 for part in parts) or
            (len(parts) > 1 and (any(part >= 60 for part in parts[1:]) or
                                any(not part.is_integer() for part in parts[:-1])))):
        raise ValueError('正确时间点请输入非负秒数或 时:分:秒')
    return sum(part * 60 ** power for power, part in enumerate(reversed(parts)))


class FeedbackStore:
    def __init__(self, path=None):
        self.path = Path(path if path is not None else DEFAULT_DB).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        migrate(self.path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS searches (
                    search_id TEXT PRIMARY KEY, searched_at TEXT NOT NULL,
                    query_type TEXT NOT NULL CHECK(query_type IN ('image','text','speech')),
                    query_text TEXT, query_name TEXT, query_image BLOB, query_sha256 TEXT,
                    index_version TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    error TEXT, encoded_prompt TEXT, notes_json TEXT,
                    topk_json TEXT NOT NULL DEFAULT '[]');
                CREATE TABLE IF NOT EXISTS feedback (
                    search_id TEXT PRIMARY KEY REFERENCES searches(search_id),
                    feedback_status TEXT NOT NULL CHECK(feedback_status IN ('correct','no_correct')),
                    selected_rank INTEGER, asset_id TEXT, video_id INTEGER, file_path TEXT,
                    predicted_timestamp REAL, corrected_timestamp REAL,
                    note TEXT NOT NULL, feedback_at TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def begin_search(self, query_type, query, index_version, image_bytes=None):
        if query_type not in ('image', 'text', 'speech') or not query.strip() or not index_version:
            raise ValueError('搜索类型、查询信息或索引名称无效')
        if query_type == 'image' and not image_bytes:
            raise ValueError('图片搜索必须保存查询原图')
        search_id = uuid4().hex
        with self.connect() as db:
            db.execute('''INSERT INTO searches
                (search_id,searched_at,query_type,query_text,query_name,query_image,
                 query_sha256,index_version) VALUES (?,?,?,?,?,?,?,?)''',
                (search_id, now(), query_type, query if query_type in ('text', 'speech') else None,
                 query if query_type == 'image' else None, image_bytes,
                 hashlib.sha256(image_bytes).hexdigest() if image_bytes else None, index_version))
        return search_id

    def finish_search(self, search_id, rows, prompt='', notes=(), error=None):
        # 缩略图是展示缓存，不属于 benchmark 标签；不保存大块重复画面。
        fields = ('asset_id', 'video_id', 'file_path', 'file_name', 'timestamp',
                  'similarity', 'index_id', 'frame_id', 'frame_number', 'window_id',
                  'source_video_id', 'first_segment_id', 'last_segment_id',
                  'start_time', 'end_time', 'matched_text', 'semantic_rank', 'semantic_score',
                  'timestamp_warning', 'context_before', 'context_after')
        snapshot = [dict(rank=rank, **{key: row.get(key) for key in fields})
                    for rank, row in enumerate(rows, 1)]
        with self.connect() as db:
            updated = db.execute('''UPDATE searches SET status=?,error=?,encoded_prompt=?,
                notes_json=?,topk_json=? WHERE search_id=? AND status='pending' ''',
                ('error' if error else 'completed', error, prompt,
                 json.dumps(list(notes), ensure_ascii=False),
                 json.dumps(snapshot, ensure_ascii=False, allow_nan=False), search_id))
            if updated.rowcount != 1:
                raise ValueError('搜索不存在或已保存，不能改写搜索快照')

    def save_feedback(self, search_id, rank=None, corrected_timestamp=None, note=''):
        corrected = parse_timestamp(corrected_timestamp)
        if rank is None and corrected is not None:
            raise ValueError('没有正确结果时不能填写正确时间点')
        with self.connect() as db:
            search = db.execute('SELECT * FROM searches WHERE search_id=?', (search_id,)).fetchone()
            if search is None or search['status'] != 'completed':
                raise ValueError('搜索快照未完成，无法保存反馈')
            rows = json.loads(search['topk_json'])
            if rank is not None and (type(rank) is not int or not 1 <= rank <= len(rows)):
                raise ValueError('选择的排名不在本次搜索结果中')
            row = rows[rank - 1] if rank is not None else {}
            # 同次搜索只保留最新标注，重复点击和改选不会重复计入 benchmark。
            db.execute('''INSERT INTO feedback VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(search_id) DO UPDATE SET
                feedback_status=excluded.feedback_status,selected_rank=excluded.selected_rank,
                asset_id=excluded.asset_id,video_id=excluded.video_id,file_path=excluded.file_path,
                predicted_timestamp=excluded.predicted_timestamp,
                corrected_timestamp=excluded.corrected_timestamp,note=excluded.note,
                feedback_at=excluded.feedback_at''',
                (search_id, 'correct' if rank is not None else 'no_correct', rank,
                 row.get('asset_id'), row.get('video_id'), row.get('file_path'),
                 row.get('timestamp'), corrected, note.strip(), now()))

    def get_feedback(self, search_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM feedback WHERE search_id=?', (search_id,)).fetchone()
        return dict(row) if row else None

    def records(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('''SELECT s.*,
                s.status AS search_status,COALESCE(f.feedback_status,'unreviewed') AS feedback_status,
                f.selected_rank,f.asset_id,f.video_id,f.file_path,f.predicted_timestamp,
                f.corrected_timestamp,f.note,f.feedback_at
                FROM searches s LEFT JOIN feedback f ON s.search_id=f.search_id
                ORDER BY s.searched_at,s.search_id''')]

    def materialize_query(self, row):
        if row['query_type'] != 'image':
            return ''
        folder = self.path.parent / 'queries'
        folder.mkdir(exist_ok=True)
        path = folder / (row['query_sha256'] + '.img')
        # 原始字节保存在SQLite中；仅导出时落盘，PIL按内容识别图片格式。
        if not path.exists():
            path.write_bytes(row['query_image'])
        return str(path)

    def export_csv(self):
        folder = self.path.parent / 'exports'
        folder.mkdir(exist_ok=True)
        path = folder / ('search_feedback_' + datetime.now().strftime('%Y%m%d_%H%M%S')
                         + '_' + uuid4().hex[:8] + '.csv')
        with path.open('x', encoding='utf-8-sig', newline='') as output:
            writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, extrasaction='ignore')
            writer.writeheader()
            for row in self.records():
                row['query_image_path'] = self.materialize_query(row)
                writer.writerow(row)
        return path

    def export_cases(self):
        """只转换人工确认素材且明确填写时间的图片案例；不推断真值。"""
        cases, pending = [], []
        for row in self.records():
            if (row['feedback_status'] == 'correct' and row['query_type'] == 'image'
                    and row['corrected_timestamp'] is not None):
                cases.append(dict(id=row['search_id'], image=self.materialize_query(row),
                    acceptable_video_ids=[row['video_id']],
                    expected_timestamp=row['corrected_timestamp'],
                    source_index_version=row['index_version'], asset_id=row['asset_id'],
                    note=row['note']))
            else:
                pending.append(dict(search_id=row['search_id'], query_type=row['query_type'],
                    feedback_status=row['feedback_status']))
        folder = self.path.parent / 'exports'
        folder.mkdir(exist_ok=True)
        path = folder / ('benchmark_cases_' + uuid4().hex[:8] + '.json')
        path.write_text(json.dumps(dict(schema_version=1, time_tolerance_seconds=2.0,
            cases=cases, pending=pending), ensure_ascii=False, indent=2), encoding='utf-8')
        return path


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', action='store_true', help='导出已确认时间的图片 benchmark JSON')
    args = parser.parse_args()
    store = FeedbackStore()
    print(store.export_cases() if args.cases else store.export_csv())
