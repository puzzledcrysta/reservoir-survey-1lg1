"""合卷边界引擎。

裁决原则：以所有测站里程的并集切分里程，每个基础区间只归属一个权威来源，
重叠里程由优先级更高的补测取得归属权，因此同一段河床在全卷中只计量一次。
原测段结论不改写，调整以独立边界调整单表达并可逐条回溯。
"""
from decimal import Decimal, ROUND_HALF_UP
from app.errors import DataError
from app.modules.domain.rule import evaluate, parse_stations, interval_cut, interval_fill

Q = Decimal('.001')


def q3(value):
    return value.quantize(Q, rounding=ROUND_HALF_UP)


def build_segments(run_id, ordinal, accepted_records):
    """把一个批次的采信记录展开为带里程序列的测段。"""
    segments = []
    for record in accepted_records:
        stations = parse_stations(record['fields']['测站断面'])
        original, _ = evaluate(record['fields'])  # 与 M4 同规则复算原测段额
        segments.append({
            'run_id': run_id,
            'ordinal': ordinal,
            'key': record['key'],
            'line': record['line'],
            'revision': record['revision'],
            'stations': stations,
            'start': stations[0][0],
            'end': stations[-1][0],
            'original': original,
        })
    if not segments:
        raise DataError('MERGE_EMPTY', f'批次 {run_id[:9]} 没有可采信测段，不能合卷')
    return segments


def merge_runs(runs):
    """runs: [{'run_id','role','ordinal','accepted': 归一采信记录}]，按提交顺序排列。"""
    if len(runs) < 2:
        raise DataError('MERGE_RUNS', '合卷至少需要基线与补测两个批次')
    seen = set()
    segments = []
    run_spans = []
    for run in runs:
        if run['run_id'] in seen:
            raise DataError('MERGE_DUP_RUN', f'批次 {run["run_id"][:9]} 在同一合卷中重复出现')
        seen.add(run['run_id'])
        parts = build_segments(run['run_id'], run['ordinal'], run['accepted'])
        segments.extend(parts)
        run_spans.append({
            'run_id': run['run_id'], 'role': run['role'], 'ordinal': run['ordinal'],
            'span_from': str(min(item['start'] for item in parts)),
            'span_to': str(max(item['end'] for item in parts)),
            'segments': len(parts),
        })

    cut_points = sorted({chain for seg in segments for chain, _ in seg['stations']})
    chains = cut_points

    def area_at(seg, chain):
        stations = seg['stations']
        for (a, va), (b, vb) in zip(stations, stations[1:]):
            if a <= chain <= b:
                if chain == a:
                    return va
                if chain == b:
                    return vb
                return va + (vb - va) * (chain - a) / (b - a)
        raise DataError('MERGE_BOUNDARY', '里程落在测段覆盖范围之外')

    # 每个基础区间只确定一个归属测段：ordinal 大者优先（补测覆盖基线），
    # 同批次内以业务键、行号兜底保证结果确定可复现。
    boundaries = []
    retained = {}        # (run_id,key,line) -> 保留挖方
    removed = {}         # (run_id,key,line) -> {取代批次 run_id -> 被取代挖方}
    merged_cut = merged_fill = Decimal(0)
    overlap_cut = Decimal(0)
    overlap_mileage = Decimal(0)

    for x, y in zip(chains, chains[1:]):
        owners = [seg for seg in segments if seg['start'] <= x and y <= seg['end']]
        if not owners:
            # 批次间的里程空档：不臆造断面、不计量，留给复核员判断
            boundaries.append({'from': str(x), 'to': str(y), 'status': 'GAP',
                               'owner_run': None, 'owner_key': None, 'owner_line': None,
                               'cut': '0.000', 'fill': '0.000', 'covered_by': []})
            continue
        owner = max(owners, key=lambda seg: (seg['ordinal'], seg['run_id'], seg['key'], -seg['line']))
        ax, ay = area_at(owner, x), area_at(owner, y)
        cut = interval_cut(x, ax, y, ay)
        fill = interval_fill(x, ax, y, ay)
        merged_cut += cut
        merged_fill += fill
        token = (owner['run_id'], owner['key'], owner['line'])
        retained[token] = retained.get(token, Decimal(0)) + cut
        covered = [{'run_id': seg['run_id'], 'key': seg['key'], 'line': seg['line'],
                    'ordinal': seg['ordinal']} for seg in owners]
        if len(owners) > 1:
            overlap_mileage += y - x
            for loser in (seg for seg in owners if seg is not owner):
                lx, ly = area_at(loser, x), area_at(loser, y)
                lost = interval_cut(x, lx, y, ly)
                overlap_cut += lost
                bucket = removed.setdefault((loser['run_id'], loser['key'], loser['line']), {})
                bucket[owner['run_id']] = bucket.get(owner['run_id'], Decimal(0)) + lost
        boundaries.append({
            'from': str(x), 'to': str(y),
            'status': 'OVERLAP' if len(owners) > 1 else 'SINGLE',
            'owner_run': owner['run_id'], 'owner_key': owner['key'], 'owner_line': owner['line'],
            'cut': str(q3(cut)), 'fill': str(q3(fill)),
            'covered_by': covered,
        })

    original_total = sum((seg['original'] for seg in segments), Decimal(0))

    adjustments = []
    for seg in sorted(segments, key=lambda item: (item['ordinal'], item['run_id'], item['key'], item['line'])):
        token = (seg['run_id'], seg['key'], seg['line'])
        keep = q3(retained.get(token, Decimal(0)))
        lost_map = {run_id: q3(value) for run_id, value in removed.get(token, {}).items()}
        removed_total = sum(lost_map.values(), Decimal(0))
        if removed_total and keep == 0:
            status = 'REPLACED'          # 全部里程被更高优先级补测取代
        elif removed_total:
            status = 'PARTIAL'           # 部分里程被取代，剩余结论仍有效
        else:
            status = 'EFFECTIVE'         # 原结论完全有效
        adjustments.append({
            'run_id': seg['run_id'], 'role': next(r['role'] for r in runs if r['run_id'] == seg['run_id']),
            'ordinal': seg['ordinal'], 'key': seg['key'], 'line': seg['line'],
            'revision': seg['revision'], 'span_from': str(seg['start']), 'span_to': str(seg['end']),
            'original_amount': str(q3(seg['original'])),
            'retained_amount': str(keep),
            'removed_amount': str(removed_total),
            'removed_by': [{'run_id': run_id, 'amount': str(amount)}
                           for run_id, amount in sorted(lost_map.items())],
            'status': status,
        })

    # 闭合校验：原合计 = 合卷总额 + 重叠去重额；差额非零则拒绝成卷，由事务回滚保证不落库
    closure = original_total - merged_cut - overlap_cut
    if q3(closure) != 0:
        raise DataError('MERGE_CLOSURE', f'合卷无法闭合，差额 {q3(closure)} 立方米')

    statuses = {}
    for row in adjustments:
        statuses[row['status']] = statuses.get(row['status'], 0) + 1
    gap_mileage = sum((Decimal(b['to']) - Decimal(b['from'])
                       for b in boundaries if b['status'] == 'GAP'), Decimal(0))

    return {
        'boundaries': boundaries,
        'adjustments': adjustments,
        'totals': {
            'original_total': str(q3(original_total)),
            'merged_total': str(q3(merged_cut)),
            'fill_total': str(q3(merged_fill)),
            'removed_overlap': str(q3(overlap_cut)),
            'delta': str(q3(merged_cut - original_total)),
            'union_mileage': str(q3(chains[-1] - chains[0])),
            'overlap_mileage': str(q3(overlap_mileage)),
            'gap_mileage': str(q3(gap_mileage)),
            'closure_residual': str(q3(closure)),
        },
        'runs': run_spans,
        'segment_status': statuses,
        'cut_points': [str(chain) for chain in chains],
    }
