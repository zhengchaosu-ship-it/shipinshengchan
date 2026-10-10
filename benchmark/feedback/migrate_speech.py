"""向后兼容地扩展查询类型；迁移前备份，不改变现有搜索和反馈内容。"""
from contextlib import closing
from pathlib import Path
import sqlite3


def migrate(path):
    path = Path(path)
    if not path.is_file():
        return
    with closing(sqlite3.connect(path, timeout=30)) as db:
        row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='searches'").fetchone()
        if not row or "'speech'" in row[0]:
            return
        old_sql = row[0]
        if "('image','text')" not in old_sql:
            raise RuntimeError('未知反馈库结构，停止自动迁移')
        backup = path.with_name(path.name + '.before-speech.bak')
        if backup.exists():
            raise RuntimeError(f'反馈迁移备份已存在，请先核对：{backup}')
        with closing(sqlite3.connect(backup)) as destination:
            db.backup(destination)
        # 在事务外关闭外键；原 feedback 外键目标始终仍为 searches。
        db.execute('PRAGMA foreign_keys=OFF')
        try:
            db.execute('BEGIN IMMEDIATE')
            original = db.execute('SELECT COUNT(*) FROM searches').fetchone()[0]
            dependent = db.execute("SELECT sql FROM sqlite_master WHERE tbl_name='searches' AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
            sql = old_sql.replace('searches', 'searches_speech_migration', 1).replace("('image','text')", "('image','text','speech')")
            db.execute(sql)
            db.execute('INSERT INTO searches_speech_migration SELECT * FROM searches')
            assert db.execute('SELECT COUNT(*) FROM searches_speech_migration').fetchone()[0] == original
            db.execute('DROP TABLE searches')
            db.execute('ALTER TABLE searches_speech_migration RENAME TO searches')
            for item in dependent:
                db.execute(item[0])
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('反馈迁移外键检查失败')
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.execute('PRAGMA foreign_keys=ON')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database')
    migrate(parser.parse_args().database)
