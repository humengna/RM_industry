# coding: utf-8
"""
动量打分与排名。

关键点：所有取样窗口都排除"当前这根 K 线"，避免回测里出现未来函数。
序列末尾是当前 bar，因此 offset=0 表示当前 bar 之前的 LOOKBACK_DAYS 根收盘价。
"""

from .config import LOOKBACK_DAYS, SCORE_HISTORY_DAYS, TRADING_DAYS_PER_YEAR
from .indicators import has_invalid, momentum_score


def window_excluding_current(closes, lookback=LOOKBACK_DAYS, offset=0):
    """
    取 lookback 根收盘价，排除当前 bar 以及再往前 offset 根。

    offset=0 -> closes[-(lookback+1):-1]
    offset=k -> closes[-(lookback+1+k):-(k+1)]
    数据不足时返回空列表。
    """
    closes = list(closes)
    end = -(offset + 1)
    start = end - lookback
    if len(closes) < lookback + offset + 1:
        return []
    return closes[start:end]


def bars_needed_for_rank(lookback=LOOKBACK_DAYS):
    """选股打分需要向 QMT 请求的 K 线根数（含当前 bar）。"""
    return lookback + 2


def bars_needed_for_history(lookback=LOOKBACK_DAYS, history_days=SCORE_HISTORY_DAYS):
    """历史动量分数序列需要向 QMT 请求的 K 线根数（含当前 bar）。"""
    return lookback + history_days + 2


def score_for_offset(closes, lookback=LOOKBACK_DAYS, offset=0,
                     trading_days_per_year=TRADING_DAYS_PER_YEAR):
    """指定 offset 处的动量分数，数据不足或含非法值返回 None。"""
    window = window_excluding_current(closes, lookback, offset)
    if len(window) < lookback or has_invalid(window):
        return None
    return momentum_score(window, trading_days_per_year)


def momentum_score_history(closes, lookback=LOOKBACK_DAYS,
                           history_days=SCORE_HISTORY_DAYS,
                           trading_days_per_year=TRADING_DAYS_PER_YEAR):
    """
    由远及近的动量分数序列：offset = history_days ... 1, 0。

    与原脚本一致，长度为 history_days + 1（默认 6 个分数，最后一个是最新值）。
    取不到的位置补 0.0。
    """
    scores = []
    for offset in range(history_days, -1, -1):
        score = score_for_offset(closes, lookback, offset, trading_days_per_year)
        scores.append(score if score is not None else 0.0)
    return scores


def rank_pool(close_map, lookback=LOOKBACK_DAYS,
              trading_days_per_year=TRADING_DAYS_PER_YEAR):
    """
    对股票池打分并按分数从高到低排序。

    close_map: {股票代码: 收盘价序列}（序列末尾为当前 bar）
    返回 [(股票代码, 分数), ...]
    """
    scores = {}
    for stock, closes in close_map.items():
        if closes is None:
            continue
        score = score_for_offset(closes, lookback, 0, trading_days_per_year)
        if score is not None:
            scores[stock] = score
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def pick_top(close_map, lookback=LOOKBACK_DAYS,
             trading_days_per_year=TRADING_DAYS_PER_YEAR):
    """取动量分数第 1 名，池子为空时返回 None。"""
    ranked = rank_pool(close_map, lookback, trading_days_per_year)
    return ranked[0][0] if ranked else None
