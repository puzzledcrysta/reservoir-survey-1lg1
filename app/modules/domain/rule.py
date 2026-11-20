from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from app.errors import DataError
from .values import number, parts


def evaluate(row):
    try:
        date.fromisoformat(row['基线日期'])
    except ValueError as error:
        raise DataError('BUSINESS','基线日期无效') from error
    stations = {}
    for item in parts(row['测站断面']):
        chain, sep, area = item.partition(',')
        if not sep:
            raise DataError('BUSINESS', f'断面缺面积 {item}')
        position = number(chain,0,10000000)
        if position in stations:
            raise DataError('BUSINESS', f'里程断面重复 {chain}')
        stations[position] = number(area,-100000,100000)
    if len(stations) < 2:
        raise DataError('BUSINESS','至少两个测站')
    ordered = sorted(stations.items())
    cut, fill = Decimal(0), Decimal(0)
    for (a,first),(b,second) in zip(ordered,ordered[1:]):
        width = b-a
        if first*second < 0:
            positive, negative = max(first,second), abs(min(first,second))
            cut += width*positive**2/(positive+negative)/2
            fill += width*negative**2/(positive+negative)/2
        else:
            volume = width*(first+second)/2
            cut += max(0,volume)
            fill += max(0,-volume)
    return cut.quantize(Decimal('.001'),rounding=ROUND_HALF_UP), [('填方',fill.quantize(Decimal('.001'),rounding=ROUND_HALF_UP),'立方米'),('测量跨度',ordered[-1][0]-ordered[0][0],'米')]
