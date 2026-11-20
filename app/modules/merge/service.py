from app.errors import DataError
from .repository import create, get, list_all

ALLOWED_ROLES = {'基线', '补测'}


def merge(run_ids, roles):
    if len(run_ids) < 2:
        raise DataError('MERGE_RUNS', '合卷至少需要基线与补测两个批次')
    if len(run_ids) != len(roles):
        raise DataError('MERGE_ROLE', '每个批次必须给出角色')
    if any(role not in ALLOWED_ROLES for role in roles):
        raise DataError('MERGE_ROLE', "角色只能是 '基线' 或 '补测'")
    report, reused = create(run_ids, roles)
    report['reused'] = reused   # True 表示命中既有合卷，未发生第二次累加
    return report
