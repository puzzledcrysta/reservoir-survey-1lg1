from decimal import Decimal
import pytest
from app.errors import DataError
from app.modules.merge.boundary import merge_runs, q3


HEAD = '测段,修订号,提交时间,测站断面,基线日期,原始备注\n'
TS = '2026-11-18T09:30:00+08:00'


def rec(key, stations, line=2, run_id='r1', ordinal=0):
    return {'key': key, 'line': line, 'revision': 1,
            'raw': [], 'fields': {'测站断面': stations, '基线日期': '2026-11-15'}}


def run(run_id, ordinal, role, records):
    # 补全 pipeline 产出的 amount 字段
    from app.modules.domain.rule import evaluate
    accepted = []
    for record in records:
        amount, _ = evaluate(record['fields'])
        accepted.append({**record, 'amount': format(amount, 'f')})
    return {'run_id': run_id, 'ordinal': ordinal, 'role': role, 'accepted': accepted}


def test_single_run_cannot_merge():
    baseline = run('base', 0, '基线', [
        rec('A', '0,4;10,4', run_id='base'),
        rec('B', '20,4;30,4', line=3, run_id='base')])
    with pytest.raises(DataError) as error:
        merge_runs([baseline])
    assert error.value.code == 'MERGE_RUNS'


def test_overlap_counts_bed_once():
    # 基线 A：0→20 等面积 4，挖方 = 20*4 = 80
    baseline = run('base', 0, '基线', [rec('A', '0,4;20,4', run_id='base')])
    # 补测 B 覆盖 10→30 等面积 6（更大值，代表补测新断面）
    supplement = run('sup', 1, '补测', [rec('B', '10,6;30,6', run_id='sup')])
    report = merge_runs([baseline, supplement])
    totals = report['totals']
    # 区间 0-10 归基线 40；10-20 归补测 60；20-30 归补测 60 → 合卷 160
    assert totals['merged_total'] == '160.000'
    # 直接相加为 80+120=200；重叠区 10-20 基线的 40 被去重
    assert totals['original_total'] == '200.000'
    assert totals['removed_overlap'] == '40.000'
    assert totals['delta'] == '-40.000'
    assert totals['closure_residual'] == '0.000'
    statuses = {(row['key']): row['status'] for row in report['adjustments']}
    assert statuses == {'A': 'PARTIAL', 'B': 'EFFECTIVE'}
    row_a = next(row for row in report['adjustments'] if row['key'] == 'A')
    assert (row_a['original_amount'], row_a['retained_amount'], row_a['removed_amount']) == \
           ('80.000', '40.000', '40.000')
    assert row_a['removed_by'][0]['run_id'] == 'sup'
    overlap = [b for b in report['boundaries'] if b['status'] == 'OVERLAP']
    assert [(b['from'], b['to']) for b in overlap] == [('10', '20')]
    assert all(b['owner_run'] == 'sup' for b in overlap)


def test_full_replacement_marks_segment_replaced():
    baseline = run('base', 0, '基线', [rec('A', '0,4;10,4', run_id='base')])
    supplement = run('sup', 1, '补测', [rec('B', '0,8;10,8', run_id='sup')])
    report = merge_runs([baseline, supplement])
    row_a, row_b = report['adjustments']
    assert (row_a['status'], row_b['status']) == ('REPLACED', 'EFFECTIVE')
    assert (row_a['retained_amount'], row_a['removed_amount']) == ('0.000', '40.000')
    assert report['totals']['merged_total'] == '80.000'
    assert report['totals']['overlap_mileage'] == '10.000'


def test_partial_mileage_supplement_leaves_rest_effective():
    # 基线 0→30；补测仅覆盖 10→15；其余里程结论仍有效
    baseline = run('base', 0, '基线', [rec('A', '0,4;30,4', run_id='base')])
    supplement = run('sup', 1, '补测', [rec('B', '10,2;15,2', run_id='sup')])
    report = merge_runs([baseline, supplement])
    row_a = next(row for row in report['adjustments'] if row['key'] == 'A')
    assert row_a['status'] == 'PARTIAL'
    # 保留：0-10 (40) + 15-30 (60) = 100；移除：10-15 (20)
    assert (row_a['retained_amount'], row_a['removed_amount']) == ('100.000', '20.000')
    assert report['totals']['merged_total'] == str(q3(Decimal(100) + Decimal(10)))
    gap = [b for b in report['boundaries'] if b['status'] == 'GAP']
    assert not gap  # 本例里程连续


def test_mileage_gap_is_flagged_not_fabricated():
    baseline = run('base', 0, '基线', [rec('A', '0,4;10,4', run_id='base')])
    supplement = run('sup', 1, '补测', [rec('B', '20,4;30,4', run_id='sup')])
    report = merge_runs([baseline, supplement])
    gap = [b for b in report['boundaries'] if b['status'] == 'GAP']
    assert [(b['from'], b['to']) for b in gap] == [('10', '20')]
    assert report['totals']['gap_mileage'] == '10.000'
    assert report['totals']['merged_total'] == '80.000'


def test_duplicate_run_rejected():
    baseline = run('base', 0, '基线', [rec('A', '0,4;10,4', run_id='base')])
    with pytest.raises(DataError) as error:
        merge_runs([baseline, {**baseline, 'ordinal': 1, 'role': '补测'}])
    assert error.value.code == 'MERGE_DUP_RUN'


def test_empty_supplement_rejected():
    baseline = run('base', 0, '基线', [rec('A', '0,4;10,4', run_id='base')])
    empty = {'run_id': 'sup', 'ordinal': 1, 'role': '补测', 'accepted': []}
    with pytest.raises(DataError) as error:
        merge_runs([baseline, empty])
    assert error.value.code == 'MERGE_EMPTY'


def test_zero_crossing_split_respects_existing_rule():
    # 与 domain.rule 的零点分割一致：0,4 → 10,-4，挖方 10
    baseline = run('base', 0, '基线', [rec('A', '0,4;20,4', run_id='base')])
    supplement = run('sup', 1, '补测', [rec('B', '0,4;10,-4', run_id='sup')])
    report = merge_runs([baseline, supplement])
    # 0-10 归补测（挖 10），10-20 归基线（挖 40）
    assert report['totals']['merged_total'] == '50.000'
