import json
from datetime import datetime, timezone
from hashlib import sha256
from app.errors import DataError
from app.store import connection
from app.settings import RULE_VERSION
from app.modules.domain.rule import parse_stations
from app.modules.domain.values import union
from app.modules.runs.repository import lookup
from app.pipeline import stages
from .boundary import merge_runs


def identify(run_ids, roles):
    # 指纹同时包含批次序列与角色，角色不同不得复用同一合卷
    payload = '|'.join(f'{run_id}:{role}' for run_id, role in zip(run_ids, roles))
    return sha256(f'{RULE_VERSION}:merge:{payload}'.encode()).hexdigest()


def fetch(merge_id):
    with connection() as db:
        row = db.execute('SELECT * FROM merges WHERE id=?', (merge_id,)).fetchone()
        if row is None:
            raise DataError('MERGE_UNKNOWN', '没有此合卷成果', 404)
        return row


def get(merge_id):
    return json.loads(fetch(merge_id)['result'])


def list_all():
    with connection() as db:
        return [dict(row) for row in
                db.execute('SELECT id,created,status FROM merges ORDER BY created DESC,id DESC LIMIT 50')]


def _coverage(accepted):
    spans_ = []
    for record in accepted:
        stations = parse_stations(record['fields']['测站断面'])
        spans_.append((stations[0][0], stations[-1][0]))
    return [{'from': str(a), 'to': str(b)} for a, b in union(spans_)]


def create(run_ids, roles):
    """全量前置校验通过后才落库；同一 run 序列返回同一合卷（幂等，不重复累加）。

    任何校验失败都在 INSERT 之前抛出，旧版合卷与原批次结论原样保留，不产生半成品。
    """
    merge_id = identify(run_ids, roles)
    with connection() as db:
        existing = db.execute('SELECT result FROM merges WHERE id=?', (merge_id,)).fetchone()
        if existing is not None:
            return json.loads(existing['result']), True

        db.execute('BEGIN IMMEDIATE')
        for run_id in run_ids:
            lookup(db, run_id)  # 来源批次缺失即整体失败
        if roles[0] != '基线' or any(role != '补测' for role in roles[1:]):
            raise DataError('MERGE_ROLE', "角色序列须为一个 '基线' 后接若干 '补测'")

        runs, fingerprints, coverage = [], [], []
        for ordinal, (run_id, role) in enumerate(zip(run_ids, roles)):
            row = lookup(db, run_id)
            # quality 阶段的 ready 记录保留归一业务字段，供边界引擎解析断面
            accepted = stages(row['source'])['quality']['ready']
            runs.append({'run_id': run_id, 'role': role, 'ordinal': ordinal, 'accepted': accepted})
            fingerprints.append(sha256(row['source']).hexdigest())
            coverage.append({'run_id': run_id, 'role': role, 'coverage': _coverage(accepted)})

        report = merge_runs(runs)  # 闭合校验失败在此抛出，事务随 with 回滚
        report['merge_id'] = merge_id
        report['manifest'] = {
            'merge_id': merge_id,
            'rule_version': RULE_VERSION,
            'mode': '合卷边界',
            'run_ids': run_ids,
            'run_roles': roles,
            'run_fingerprints': fingerprints,
            'coverage': coverage,
            'created': datetime.now(timezone.utc).isoformat(),
        }
        db.execute('INSERT INTO merges (id,run_ids,roles,result,created,status) VALUES (?,?,?,?,?,?)',
                   (merge_id, json.dumps(run_ids), json.dumps(roles, ensure_ascii=False),
                    json.dumps(report, ensure_ascii=False), report['manifest']['created'], '定版'))
        return report, False
