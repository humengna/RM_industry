# coding: utf-8
"""下单量计算与买入可行性判断。"""

from .config import LOT_SIZE


def buy_volume(available_cash, price, lot_size=LOT_SIZE):
    """
    用可用资金按整手买入的股数；资金不足 1 手返回 0。
    """
    try:
        available_cash = float(available_cash)
        price = float(price)
    except (TypeError, ValueError):
        return 0
    if available_cash <= 0 or price <= 0:
        return 0

    volume = int(available_cash / price / lot_size) * lot_size
    return volume if volume >= lot_size else 0


def can_buy(low_price, limit_up):
    """
    是否买得进：全天最低价已经在涨停价上（一字涨停）则买不到。

    返回 (是否可买, 原因)。
    """
    try:
        low_price = float(low_price)
        limit_up = float(limit_up)
    except (TypeError, ValueError):
        return True, ''

    if limit_up > 0 and low_price > 0 and low_price >= limit_up:
        return False, 'limit_up_locked'
    return True, ''
