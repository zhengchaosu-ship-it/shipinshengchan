"""剪映导出交接：确定路径及同一注册服务；不实现剪映或发布Worker。"""
from contextlib import closing, contextmanager
from datetime import datetime
from fractions import Fraction
from pathlib import Path
import json
import re
import sqlite3

from .service import StartupPipeline
from publish_planner.storage import ROOT
from xiaovcat_adapter.models import utc_now_iso

SOURCES = {'MANUAL_JIANYING', 'AUTOMATED_JIANYING'}


class TransactionStore:
    """让原register_export使用当前事务，不复制其权限/READY逻辑。"""
    def __init__(self, original, connection):
        self.original, self.connection = original, connection

    def __getattr__(self, name):
        return getattr(self.original, name)

    @contextmanager
    def connect(self, *, write=False):
        yield self.connection


class ExportHandoff:
    def __init__(self, pipeline=None, *, export_root=None):
        self.pipeline = pipeline or StartupPipeline()
        self.store = self.pipeline.store
        if export_root is None:
            value = json.loads((Path(__file__).parent / 'export_config.json').read_text(encoding='utf-8'))['export_root']
            export_root = Path(value)
            if not export_root.is_absolute():
                export_root = ROOT / export_root
        self.export_root = Path(export_root).resolve()
        if str(self.export_root).startswith('\\\\'):
            raise ValueError('LOCAL_EXPORT_ROOT_REQUIRED')

    def migrate(self):
        self.pipeline.migrate()
        with self.store.connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='startup_export_migrations'").fetchone():
                return {'already_applied': True}
            backup = self.store.path.with_name(self.store.path.name + '.export-handoff-' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.bak')
            with closing(sqlite3.connect(backup)) as saved:
                db.backup(saved)
            names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            before = {name: [tuple(r) for r in db.execute('SELECT * FROM "' + name + '" ORDER BY rowid')] for name in names}
            sql = (Path(__file__).parent / 'migrations/002_export_handoff.sql').read_text(encoding='utf-8')
            try:
                db.executescript('BEGIN IMMEDIATE;' + sql)
                db.execute('INSERT INTO startup_export_migrations VALUES(2,?)', (utc_now_iso(),))
                for name, rows in before.items():
                    if rows != [tuple(r) for r in db.execute('SELECT * FROM "' + name + '" ORDER BY rowid')]:
                        raise RuntimeError('EXPORT_MIGRATION_CHANGED_ROWS:' + name)
                if db.execute('PRAGMA foreign_key_check').fetchall():
                    raise RuntimeError('EXPORT_MIGRATION_FOREIGN_KEY_ERROR')
                db.commit()
            except Exception:
                db.rollback()
                raise
        return {'version': 2, 'backup': str(backup), 'existing_rows_unchanged': True}

    def _directory(self, batch_id):
        if not isinstance(batch_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', batch_id) or batch_id in {'.', '..'}:
            raise ValueError('INVALID_SOURCE_BATCH_ID')
        directory = (self.export_root / batch_id).resolve()
        if directory.parent != self.export_root:
            raise PermissionError('EXPORT_DIRECTORY_OUTSIDE_ROOT')
        return directory

    def rows(self, token, batch_id):
        scoped = self.pipeline.contents(token, batch_id)
        if not scoped:
            raise PermissionError('CONTENT_PERMISSION_DENIED')
        ids = {r['content_id'] for r in scoped}
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM startup_exports WHERE batch_id=? ORDER BY video_index', (batch_id,)) if r['content_id'] in ids]

    @staticmethod
    def _source(manifest, row):
        source = next((v for v in manifest['videos'] if v['video_index'] == row['video_index']), None)
        if not source or source.get('status') != 'success' or not row['composition_signature']:
            raise ValueError('SOURCE_PRODUCTION_FAILED')
        if source.get('composition_signature') != row['composition_signature']:
            raise ValueError('SOURCE_MANIFEST_CHANGED')
        if not source.get('draft_name') or not source.get('draft_path'):
            raise ValueError('SOURCE_DRAFT_IDENTITY_MISSING')
        draft = Path(source['draft_path']).resolve()
        if str(draft).startswith('\\\\') or not (draft / 'draft_content.json').is_file():
            raise ValueError('DRAFT_NOT_FOUND')
        return source, draft

    def prepare_batch(self, token, batch_id):
        scoped = self.pipeline.contents(token, batch_id)
        if not scoped:
            raise PermissionError('CONTENT_PERMISSION_DENIED')
        directory = self._directory(batch_id)
        directory.mkdir(parents=True, exist_ok=True)
        with self.store.connect(write=True) as db:
            for item in scoped:
                row = self.pipeline._content(db, token, item['content_id'])
                _, manifest = self.pipeline._manifest(row['manifest_path'])
                source = next(v for v in manifest['videos'] if v['video_index'] == row['video_index'])
                index = row['video_index']
                if not isinstance(index, int) or index < 1:
                    raise ValueError('INVALID_SOURCE_VIDEO_INDEX')
                expected = directory / f'{index:03d}.mp4'
                old = db.execute('SELECT * FROM startup_exports WHERE content_id=?', (row['content_id'],)).fetchone()
                identity = (batch_id, index, row['composition_signature'], source.get('draft_name', ''), source.get('draft_path', ''), str(expected))
                if old:
                    if tuple(old[k] for k in ['batch_id', 'video_index', 'composition_signature', 'draft_name', 'draft_path', 'expected_mp4_path']) != identity:
                        raise PermissionError('EXPORT_IDENTITY_IMMUTABLE')
                    continue
                try:
                    self._source(manifest, row)
                    status, error = 'DRAFT_READY', None
                except ValueError as failure:
                    status, error = 'EXPORT_FAILED', str(failure)
                db.execute('INSERT INTO startup_exports(content_id,batch_id,video_index,composition_signature,draft_name,draft_path,expected_mp4_path,export_status,export_source,created_at,error) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           (row['content_id'], *identity, status, 'MANUAL_JIANYING', row['created_at'], error))
                db.execute('INSERT INTO startup_export_events(content_id,status,event_at,detail) VALUES(?,?,?,?)', (row['content_id'], status, utc_now_iso(), error))
        return self.rows(token, batch_id)

    def begin_export(self, token, content_id, *, source='MANUAL_JIANYING'):
        if source not in SOURCES:
            raise ValueError('INVALID_EXPORT_SOURCE')
        with self.store.connect(write=True) as db:
            row = self.pipeline._content(db, token, content_id)
            if row['publish_status'] != 'NOT_SCHEDULED':
                raise PermissionError('VIDEO_HAS_PUBLISH_TASK')
            _, manifest = self.pipeline._manifest(row['manifest_path'])
            self._source(manifest, row)
            export = db.execute('SELECT * FROM startup_exports WHERE content_id=?', (content_id,)).fetchone()
            if not export or export['export_status'] == 'VALIDATED':
                raise PermissionError('EXPORT_NOT_PREPARED_OR_ALREADY_VALIDATED')
            db.execute("UPDATE startup_exports SET export_status='EXPORTING',export_source=?,export_started_at=?,error=NULL WHERE content_id=?", (source, utc_now_iso(), content_id))
            db.execute('INSERT INTO startup_export_events(content_id,status,event_at,detail) VALUES(?,?,?,?)', (content_id, 'EXPORTING', utc_now_iso(), source))
            return export['expected_mp4_path']

    def register_exported_mp4(self, token, content_id, actual_mp4_path, *, source='MANUAL_JIANYING'):
        if source not in SOURCES:
            raise ValueError('INVALID_EXPORT_SOURCE')
        actual = Path(actual_mp4_path).absolute()
        with self.store.connect() as db:
            content = self.pipeline._content(db, token, content_id)
            export = db.execute('SELECT * FROM startup_exports WHERE content_id=?', (content_id,)).fetchone()
            if not export:
                raise ValueError('EXPORT_NOT_PREPARED')
            expected = Path(export['expected_mp4_path'])
            if actual != expected or actual.resolve() != expected or actual.parent.resolve() != self._directory(export['batch_id']):
                raise PermissionError('EXPORT_PATH_IDENTITY_MISMATCH')
            if content['publish_status'] != 'NOT_SCHEDULED':
                raise PermissionError('VIDEO_HAS_PUBLISH_TASK')
        try:
            with self.store.connect(write=True) as db:
                row = self.pipeline._content(db, token, content_id)
                _, manifest = self.pipeline._manifest(row['manifest_path'])
                source_row, _ = self._source(manifest, row)
                if (source_row['draft_name'], source_row['draft_path']) != (export['draft_name'], export['draft_path']):
                    raise PermissionError('SOURCE_DRAFT_IDENTITY_CHANGED')
                if row['publish_status'] != 'NOT_SCHEDULED':
                    raise PermissionError('VIDEO_HAS_PUBLISH_TASK')
                db.execute("UPDATE startup_exports SET export_status='EXPORTED',actual_mp4_path=?,export_source=? WHERE content_id=?", (str(actual), source, content_id))
                db.execute('INSERT INTO startup_export_events(content_id,status,event_at,detail) VALUES(?,?,?,?)', (content_id, 'EXPORTED', utc_now_iso(), str(actual)))
                original = StartupPipeline(TransactionStore(self.store, db), batch_root=self.pipeline.batch_root, probe=self.pipeline.probe, clock=self.pipeline.clock)
                original.register_export(token, content_id, actual)
                ready = self.pipeline._content(db, token, content_id)
                media = json.loads(ready['media_json'])
                video = next(s for s in media['streams'] if s.get('codec_type') == 'video')
                audio = next((s for s in media['streams'] if s.get('codec_type') == 'audio'), {})
                try:
                    fps = float(Fraction(video.get('avg_frame_rate', '0/1')))
                except (ValueError, ZeroDivisionError):
                    fps = None
                db.execute("UPDATE startup_exports SET export_status='VALIDATED',export_completed_at=?,file_size=?,mtime_ns=?,video_codec=?,audio_codec=?,width=?,height=?,fps=?,duration=?,error=NULL WHERE content_id=?",
                           (utc_now_iso(), ready['size_bytes'], ready['mtime_ns'], video.get('codec_name'), audio.get('codec_name'), video['width'], video['height'], fps, ready['duration_seconds'], content_id))
                db.execute('INSERT INTO startup_export_events(content_id,status,event_at,detail) VALUES(?,?,?,?)', (content_id, 'VALIDATED', utc_now_iso(), source))
            return content_id
        except Exception as error:
            with self.store.connect(write=True) as db:
                row = self.pipeline._content(db, token, content_id)
                if row['publish_status'] == 'NOT_SCHEDULED':
                    db.execute("UPDATE startup_exports SET export_status='EXPORT_FAILED',error=? WHERE content_id=?", (str(error), content_id))
                    db.execute("UPDATE startup_contents SET production_status='FAILED',error=? WHERE content_id=?", (str(error), content_id))
                    db.execute('INSERT INTO startup_export_events(content_id,status,event_at,detail) VALUES(?,?,?,?)', (content_id, 'EXPORT_FAILED', utc_now_iso(), str(error)))
            raise

    def refresh_batch(self, token, batch_id):
        self.prepare_batch(token, batch_id)
        result = {'batch_id': batch_id, 'validated': [], 'waiting': [], 'failed': [], 'protected': [], 'unmapped_files': []}
        directory = self._directory(batch_id)
        exports = self.rows(token, batch_id)
        contents = {r['content_id']: r for r in self.pipeline.contents(token, batch_id)}
        expected = {Path(r['expected_mp4_path']).name for r in exports}
        result['unmapped_files'] = [str(p) for p in sorted(directory.iterdir()) if p.is_file() and p.suffix.lower() == '.mp4' and p.name not in expected]
        for export in exports:
            key = export['content_id']; path = Path(export['expected_mp4_path'])
            if contents[key]['publish_status'] != 'NOT_SCHEDULED':
                result['protected'].append(key)
                continue
            if not path.is_file():
                if export['export_status'] == 'VALIDATED':
                    try:
                        self.register_exported_mp4(token, key, path, source=export['export_source'])
                    except Exception as error:
                        result['failed'].append({'content_id': key, 'error': str(error)})
                else:
                    with self.store.connect(write=True) as db:
                        if export['export_status'] == 'DRAFT_READY':
                            db.execute("UPDATE startup_exports SET export_status='WAITING_EXPORT' WHERE content_id=?", (key,))
                    result['waiting'].append(key)
                continue
            stat = path.stat()
            if export['export_status'] == 'VALIDATED' and contents[key]['production_status'] == 'READY' and (stat.st_size, stat.st_mtime_ns) == (export['file_size'], export['mtime_ns']):
                result['validated'].append(key)
                continue
            try:
                self.register_exported_mp4(token, key, path, source=export['export_source'])
                result['validated'].append(key)
            except Exception as error:
                result['failed'].append({'content_id': key, 'error': str(error)})
        return result
