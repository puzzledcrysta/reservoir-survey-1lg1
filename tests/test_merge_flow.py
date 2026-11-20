import pytest


HEADER = '测段,修订号,提交时间,测站断面,基线日期,原始备注\n'
TS = '2026-11-18T09:30:00+08:00'


def csv_text(rows):
    lines = [HEADER]
    for key, stations in rows:
        lines.append(f'{key},1,{TS},"{stations}",2026-11-15,合卷测试\n')
    return ''.join(lines)


def make_run(client, rows, book='测段,外部记录值(立方米)\n'):
    payload = {'data': csv_text(rows), 'book': book}
    return client.post('/api/runs', json=payload).json()


@pytest.fixture
def merged(client):
    baseline = make_run(client, [('S1', '0,4;20,4'), ('S2', '20,4;30,4')])
    supplement = make_run(client, [('T1', '10,6;30,6')])
    base_id, sup_id = baseline['manifest']['run_id'], supplement['manifest']['run_id']
    response = client.post('/api/merges',
                           json={'run_ids': [base_id, sup_id], 'roles': ['基线', '补测']})
    assert response.status_code == 200
    return response.json(), base_id, sup_id


def test_merge_totals_and_responsibility(merged):
    report, base_id, sup_id = merged
    totals = report['totals']
    # 基线 80+40=120，补测 120，直加 240；重叠区 10-30 内基线 80 被去重 → 合卷 160
    assert totals['original_total'] == '240.000'
    assert totals['removed_overlap'] == '80.000'
    assert totals['merged_total'] == '160.000'
    assert totals['closure_residual'] == '0.000'
    keys = {(row['run_id'], row['key']): row for row in report['adjustments']}
    assert keys[(base_id, 'S1')]['status'] == 'PARTIAL'
    assert keys[(base_id, 'S2')]['status'] == 'REPLACED'
    assert keys[(sup_id, 'T1')]['status'] == 'EFFECTIVE'


def test_idempotent_rerun_does_not_accumulate(client, merged):
    first, base_id, sup_id = merged
    again = client.post('/api/merges',
                        json={'run_ids': [base_id, sup_id], 'roles': ['基线', '补测']})
    assert again.status_code == 200
    second = again.json()
    assert second['merge_id'] == first['merge_id']
    assert second['reused'] is True and first['reused'] is False
    assert second['totals']['merged_total'] == first['totals']['merged_total']
    listing = client.get('/api/merges').json()
    assert len([row for row in listing if row['id'] == first['merge_id']]) == 1


def test_unknown_run_fails_without_half_product(client, merged):
    report, base_id, sup_id = merged
    before = {row['id'] for row in client.get('/api/merges').json()}
    bad = client.post('/api/merges',
                      json={'run_ids': [base_id, 'deadbeef'], 'roles': ['基线', '补测']})
    assert (bad.status_code, bad.json()['code']) == (404, 'RUN_UNKNOWN')
    # 失败后既有合卷原样保留，没有新增半成品
    after = {row['id'] for row in client.get('/api/merges').json()}
    assert after == before
    assert client.get(f"/api/merges/{report['merge_id']}").status_code == 200


def test_merge_review_versioning_and_note(client, merged):
    merge_id = merged[0]['merge_id']
    # 有边界调整却不填意见 → 拒绝
    missing = client.post(f'/api/review/merge/{merge_id}',
                          json={'version': 0, 'decision': '确认', 'note': ' '})
    assert (missing.status_code, missing.json()['code']) == (422, 'REVIEW_NOTE')
    ok = client.post(f'/api/review/merge/{merge_id}',
                     json={'version': 0, 'decision': '确认', 'note': '重叠区以补测为准，已核对'})
    assert ok.status_code == 200 and ok.json()['version'] == 1
    stale = client.post(f'/api/review/merge/{merge_id}',
                        json={'version': 0, 'decision': '退回', 'note': '陈旧提交'})
    assert (stale.status_code, stale.json()['code']) == (409, 'STALE')
    timeline = client.get(f'/api/review/merge/{merge_id}').json()
    assert [row['version'] for row in timeline] == [1]


def test_workbench_and_export_share_same_version(client, merged):
    merge_id = merged[0]['merge_id']
    client.post(f'/api/review/merge/{merge_id}',
                json={'version': 0, 'decision': '确认', 'note': '合卷边界复核通过'})
    workbench = client.get(f'/api/merges/{merge_id}').json()
    exported = client.get(f'/api/export/merge/{merge_id}')
    assert exported.status_code == 200 and 'attachment' in exported.headers['content-disposition']
    payload = exported.json()
    assert payload['totals'] == workbench['totals']
    assert payload['manifest']['merge_id'] == merge_id
    assert payload['review'][0]['decision'] == '确认'
    # 导出可复现
    assert exported.content == client.get(f'/api/export/merge/{merge_id}').content


def test_original_run_reviews_untouched(client, merged):
    report, base_id, sup_id = merged
    # 原测段批次仍可独立复核，合卷不改动其版本链
    first = client.post(f'/api/review/{base_id}',
                        json={'version': 0, 'decision': '确认', 'note': '基线原结论保留'})
    assert first.status_code == 200
    again = client.post(f'/api/review/{base_id}',
                        json={'version': 1, 'decision': '确认', 'note': '再次确认'})
    assert again.status_code == 200


def test_role_sequence_validated(client, merged):
    _, base_id, sup_id = merged
    # 角色顺序不以基线开头 → pydantic 字面量校验拒绝
    bad = client.post('/api/merges',
                      json={'run_ids': [base_id, sup_id], 'roles': ['补测', '基线']})
    assert bad.status_code == 422
    duplicate = client.post('/api/merges',
                            json={'run_ids': [base_id, base_id], 'roles': ['基线', '补测']})
    assert (duplicate.status_code, duplicate.json()['code']) == (422, 'MERGE_DUP_RUN')
    # 角色重复（两个基线）由业务规则拒绝
    same_role = client.post('/api/merges',
                            json={'run_ids': [base_id, sup_id], 'roles': ['基线', '基线']})
    assert (same_role.status_code, same_role.json()['code']) == (422, 'MERGE_ROLE')


def test_partial_coverage_labels_unchanged_conclusions(client):
    baseline = make_run(client, [('S1', '0,4;30,4')])           # 120
    supplement = make_run(client, [('T1', '10,2;15,2')])        # 10，仅 5 米
    report = client.post('/api/merges', json={
        'run_ids': [baseline['manifest']['run_id'], supplement['manifest']['run_id']],
        'roles': ['基线', '补测']}).json()
    row = next(item for item in report['adjustments'] if item['key'] == 'S1')
    assert row['status'] == 'PARTIAL'
    assert (row['original_amount'], row['retained_amount'], row['removed_amount']) == \
           ('120.000', '100.000', '20.000')
    assert report['totals']['gap_mileage'] == '0.000'


def test_closure_failure_rolls_back_no_half_product(client, monkeypatch):
    baseline = make_run(client, [('S1', '0,4;20,4')])
    supplement = make_run(client, [('T1', '10,6;30,6')])
    before = {row['id'] for row in client.get('/api/merges').json()}

    # 注入闭合失败，模拟引擎无法闭合：事务必须回滚，不允许半成品成卷
    from app.modules.merge import repository as repo
    from app.errors import DataError
    original = repo.merge_runs

    def broken(runs):
        original(runs)
        raise DataError('MERGE_CLOSURE', '合卷无法闭合，差额 1.000 立方米')

    monkeypatch.setattr(repo, 'merge_runs', broken)
    failed = client.post('/api/merges', json={
        'run_ids': [baseline['manifest']['run_id'], supplement['manifest']['run_id']],
        'roles': ['基线', '补测']})
    assert (failed.status_code, failed.json()['code']) == (422, 'MERGE_CLOSURE')
    after = {row['id'] for row in client.get('/api/merges').json()}
    assert after == before
