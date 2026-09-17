# coding: utf-8
"""
股票池过滤：涨跌停价、停牌、ST、市值、板块代码前缀。

这里全部是纯函数，行情由调用方（QMT 脚本）取好后传进来。
"""

from .config import (
    DEFAULT_LIMIT_RATIO,
    EXCLUDE_ST,
    EXCLUDED_CODE_PREFIXES,
    LIMIT_RATIO_BY_PREFIX,
    MAX_MARKET_CAP,
    MIN_MARKET_CAP,
)


def stock_code(stock):
    """'600000.SH' -> '600000'"""
    return str(stock).split('.')[0]


def limit_ratio(stock):
    """
    按代码前缀确定涨跌停幅度：
      创业板(300/301)、科创板(688) -> 20%
      其余（主板 60/00 等）        -> 10%
    """
    code = stock_code(stock)
    for prefix, ratio in LIMIT_RATIO_BY_PREFIX.items():
        if code.startswith(prefix):
            return ratio
    return DEFAULT_LIMIT_RATIO


def limit_prices(stock, pre_close):
    """返回 (涨停价, 跌停价)；pre_close 非法时返回 (0.0, 0.0)。"""
    try:
        pre_close = float(pre_close)
    except (TypeError, ValueError):
        return 0.0, 0.0
    if pre_close <= 0:
        return 0.0, 0.0

    ratio = limit_ratio(stock)
    return round(pre_close * (1 + ratio), 2), round(pre_close * (1 - ratio), 2)


def is_limit_down(stock, price, pre_close):
    """当前价是否已到跌停。"""
    _, down = limit_prices(stock, pre_close)
    return bool(down > 0 and price > 0 and price <= down)


def is_limit_up(stock, price, pre_close):
    """当前价是否已到涨停。"""
    up, _ = limit_prices(stock, pre_close)
    return bool(up > 0 and price > 0 and price >= up)


def is_excluded_code(stock, excluded_prefixes=EXCLUDED_CODE_PREFIXES):
    """代码前缀是否在屏蔽名单里。"""
    code = stock_code(stock)
    return any(code.startswith(p) for p in excluded_prefixes)


def is_st(stock_name, exclude_st=EXCLUDE_ST):
    """股票名称是否包含 ST。"""
    if not exclude_st or not stock_name:
        return False
    return 'ST' in str(stock_name).upper()


def market_cap_ok(total_value, min_cap=MIN_MARKET_CAP, max_cap=MAX_MARKET_CAP):
    """
    总市值是否落在区间内。

    取不到市值（<=0）时放行，与原脚本保持一致。
    """
    try:
        total_value = float(total_value)
    except (TypeError, ValueError):
        return True
    if total_value <= 0:
        return True
    return min_cap <= total_value <= max_cap


def passes_filters(stock, stock_name=None, total_value=0, suspend_flag=0,
                   close=0.0, pre_close=0.0,
                   excluded_prefixes=EXCLUDED_CODE_PREFIXES,
                   exclude_st=EXCLUDE_ST,
                   min_cap=MIN_MARKET_CAP, max_cap=MAX_MARKET_CAP):
    """
    股票池的完整过滤：代码前缀 -> 停牌 -> ST -> 市值 -> 跌停。

    返回 (是否通过, 未通过的原因)。
    """
    if is_excluded_code(stock, excluded_prefixes):
        return False, 'code_prefix'
    if suspend_flag == 1:
        return False, 'suspended'
    if is_st(stock_name, exclude_st):
        return False, 'st'
    if not market_cap_ok(total_value, min_cap, max_cap):
        return False, 'market_cap'
    if close and pre_close and is_limit_down(stock, close, pre_close):
        return False, 'limit_down'
    return True, ''
