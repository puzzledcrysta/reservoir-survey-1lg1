import json
from .repository import get
from .decisions import timeline


def bundle(merge_id):
    """工作台与导出共用同一份定版报告，复核版本一并随包导出。"""
    report = get(merge_id)
    return json.dumps({**report, 'review': timeline(merge_id)},
                      ensure_ascii=False, indent=2)
