"""合卷复核：独立版本链，乐观并发控制，旧版本提交返回 409。"""
import json
from datetime import datetime, timezone
from app.errors import DataError
from app.store import connection
from .repository import fetch


def timeline(merge_id):
    fetch(merge_id)
    with connection() as db:
        return list(map(dict, db.execute(
            'SELECT version,decision,note,changed FROM merge_reviews WHERE merge_id=? ORDER BY version DESC',
            (merge_id,))))


def decide(merge_id, version, decision, note):
    note = note.strip()
    if decision not in {'确认', '退回'}:
        raise DataError('REVIEW_DECISION', '复核结论无效')
    report = json.loads(fetch(merge_id)['result'])
    adjusted = any(row['status'] != 'EFFECTIVE' for row in report['adjustments'])
    if (adjusted or decision == '退回') and not note:
        raise DataError('REVIEW_NOTE', '存在边界调整时须填写复核意见')
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute(
            'SELECT COALESCE(MAX(version),0) FROM merge_reviews WHERE merge_id=?',
            (merge_id,)).fetchone()[0]
        if current != version:
            raise DataError('STALE', '合卷复核版本已过期，请刷新', 409)
        record = {'version': current + 1, 'decision': decision, 'note': note,
                  'changed': datetime.now(timezone.utc).isoformat()}
        db.execute('INSERT INTO merge_reviews VALUES (?,?,?,?,?)',
                   (merge_id, *record.values()))
        return record
