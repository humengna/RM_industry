# coding: utf-8
"""
选股信号：五均线多头排列 + 四级百分比发散同步扩大。

纯函数，只依赖标准库，不碰行情接口，可以直接单测。

四级发散：
    s1 = (MA5  - MA10) / MA10
    s2 = (MA10 - MA20) / MA20
    s3 = (MA20 - MA30) / MA30
    s4 = (MA30 - MA60) / MA60
    总发散 = s1 + s2 + s3 + s4

入选条件（与原脚本一致）：
    1. MA5 > MA10 > MA20 > MA30 > MA60（多头排列）
    2. s1~s4 全部比前一个交易日大（发散同步扩大）
"""

import math

from .config import HISTORY_COUNT, MA_PERIODS, MAX_HOLDINGS, RANK_START, SORT_ASCENDING


def _finite(value):
    return value is not None and not math.isnan(value) and not math.isinf(value)


def moving_average(closes, period):
    """最近 period 根收盘价的均值；数据不足返回 None。"""
    closes = list(closes)
    if len(closes) < period or period <= 0:
        return None
    window = closes[-period:]
    for value in window:
        if not _finite(value):
            return None
    return sum(window) / float(period)


def moving_averages(closes, periods=MA_PERIODS):
    """一次算出多条均线，任意一条取不到就返回 None。"""
    result = {}
    for period in periods:
        value = moving_average(closes, period)
        if value is None:
            return None
        result[period] = value
    return result


def spreads(mas, periods=MA_PERIODS):
    """
    相邻两条均线的百分比发散：(短 - 长) / 长。

    periods 必须由短到长；分母为 0 时返回 None。
    """
    values = []
    for short, long in zip(periods[:-1], periods[1:]):
        base = mas[long]
        if base == 0:
            return None
        values.append((mas[short] - base) / base)
    return values


def divergence(closes, periods=MA_PERIODS):
    """
    计算当日与上一日的均线、四级发散和总发散。

    closes 末尾是当日收盘价；长度不足 max(periods) + 1 返回 None。
    """
    closes = [c for c in closes if _finite(c)]
    if len(closes) < max(periods) + 1:
        return None

    mas = moving_averages(closes, periods)
    prev_mas = moving_averages(closes[:-1], periods)
    if mas is None or prev_mas is None:
        return None

    current = spreads(mas, periods)
    previous = spreads(prev_mas, periods)
    if current is None or previous is None:
        return None

    result = {
        'ma': mas,
        'prev_ma': prev_mas,
        'spreads': current,
        'prev_spreads': previous,
        'score': sum(current),
    }
    for i, value in enumerate(current, 1):
        result['s%d' % i] = value
    for i, value in enumerate(previous, 1):
        result['prev_s%d' % i] = value
    for period in periods:
        result['ma%d' % period] = mas[period]
    return result


def is_bullish_alignment(mas, periods=MA_PERIODS):
    """MA5 > MA10 > MA20 > MA30 > MA60。"""
    values = [mas[p] for p in periods]
    return all(a > b for a, b in zip(values[:-1], values[1:]))


def is_expanding(current, previous):
    """四级发散是否全部比上一日大。"""
    if len(current) != len(previous):
        return False
    return all(now > before for now, before in zip(current, previous))


def is_valid_signal(result, periods=MA_PERIODS):
    """是否满足全部入选条件。"""
    if not result:
        return False
    if not is_bullish_alignment(result['ma'], periods):
        return False
    return is_expanding(result['spreads'], result['prev_spreads'])


def evaluate(stock, closes, periods=MA_PERIODS):
    """
    对单只股票出一条候选记录；不满足条件返回 None。
    """
    result = divergence(closes, periods)
    if not is_valid_signal(result, periods):
        return None

    item = {'stock': stock, 'score': result['score']}
    for key, value in result.items():
        if key.startswith('s') or key.startswith('prev_s') or key.startswith('ma'):
            item[key] = value
    return item


def rank(candidates, top_n=MAX_HOLDINGS, ascending=SORT_ASCENDING, start=RANK_START):
    """
    按总发散度排序，取排名 [start, start + top_n - 1] 这一段（start 从 1 起算）。

    ascending=True 是原脚本的真实行为（reverse=True 被注释掉了），
    即发散度最小的排第 1；改成 False 则发散度最大的排第 1。

    start=1 就是常规的"取前 top_n 名"；start=3、top_n=3 表示跳过前 2 名，
    取第 3、4、5 名。候选不够时返回的就少，甚至为空（当天不开仓）。
    """
    ordered = sorted(candidates, key=lambda item: item['score'], reverse=not ascending)
    begin = max(int(start) - 1, 0)
    if not top_n:
        return ordered[begin:]
    return ordered[begin:begin + top_n]


def select(close_map, top_n=MAX_HOLDINGS, ascending=SORT_ASCENDING, periods=MA_PERIODS,
           start=RANK_START):
    """
    对整个股票池选股。

    close_map: {股票: 截至当日的收盘价序列}
    返回 (选中的记录, 全部有效候选)
    """
    candidates = []
    for stock in sorted(close_map):
        item = evaluate(stock, close_map[stock], periods)
        if item is not None:
            candidates.append(item)
    return rank(candidates, top_n, ascending, start), candidates


def bars_needed(periods=MA_PERIODS):
    """选股需要多少根日线（含当日）。"""
    return max(max(periods) + 1, HISTORY_COUNT)
