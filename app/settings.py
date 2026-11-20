import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ROOT = ROOT / 'sample_data'
DB = Path(os.getenv('WORKBENCH_DB', str(ROOT/'state/ledger.sqlite3')))
TITLE = '河道断面测方'
SLUG = 'reservoir-survey'
KEY = '测段'
FIELDS = ('测站断面', '基线日期')
ROLE = '航道测量员'
UNIT = '立方米'
SIGNATURE = '断面标尺'
RULE_VERSION = 'reservoir-survey-1.0'
TABS = {'intake': '来源采信', 'contract': '字段解释', 'quality': '隔离裁决', 'domain': '断面测方', 'reconcile': '独立对账', 'runs': '批次复算', 'merge': '合卷边界', 'review': '交付复核'}
