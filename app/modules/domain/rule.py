from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from app.errors import DataError
from .values import number, parts

Q = Decimal('.001')


def parse_stations(text):
    """解析 '里程,面积;...' 为按里程排序的 (里程, 面积) 序列。"""
    stations = {}
    for item in parts(text):
        chain, sep, area = item.partition(',')
        if not sep:
            raise DataError('BUSINESS', f'断面缺面积 {item}')
        position = number(chain, 0, 10000000)
        if position in stations:
            raise DataError('BUSINESS', f'里程断面重复 {chain}')
        stations[position] = number(area, -100000, 100000)
    if len(stations) < 2:
        raise DataError('BUSINESS', '至少两个测站')
    return sorted(stations.items())


def interval_cut(a, area_a, b, area_b):
    """单个相邻里程区间的挖方量。遇挖填转换按零点分割，填方不抵销挖方。"""
    width = b - a
    if area_a * area_b < 0:
        positive, negative = max(area_a, area_b), abs(min(area_a, area_b))
        return width * positive ** 2 / (positive + negative) / 2
    return max(Decimal(0), width * (area_a + area_b) / 2)


def interval_fill(a, area_a, b, area_b):
    """单个相邻里程区间的填方量（取正计量）。"""
    width = b - a
    if area_a * area_b < 0:
        positive, negative = max(area_a, area_b), abs(min(area_a, area_b))
        return width * negative ** 2 / (positive + negative) / 2
    return max(Decimal(0), -width * (area_a + area_b) / 2)


def evaluate(row):
    try:
        date.fromisoformat(row['基线日期'])
    except ValueError as error:
        raise DataError('BUSINESS', '基线日期无效') from error
    ordered = parse_stations(row['测站断面'])
    cut, fill = Decimal(0), Decimal(0)
    for (a, first), (b, second) in zip(ordered, ordered[1:]):
        cut += interval_cut(a, first, b, second)
        fill += interval_fill(a, first, b, second)
    return cut.quantize(Q, rounding=ROUND_HALF_UP), [
        ('填方', fill.quantize(Q, rounding=ROUND_HALF_UP), '立方米'),
        ('测量跨度', ordered[-1][0] - ordered[0][0], '米')]
