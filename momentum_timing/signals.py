# coding: utf-8
"""
择时信号与风控判断。

个股择时：动量分数连续下降达到 DECLINE_DAYS_TO_SELL 天 -> SELL，否则 BUY。
大盘择时：RSRS 修正标准分，默认只记录不介入（RSRS_ENABLED=False）。
"""

from .config import (
    DECLINE_DAYS_TO_SELL,
    RSRS_BUY_THRESHOLD,
    RSRS_ENABLED,
    STOP_LOSS_RATIO,
)

SIGNAL_BUY = 'BUY'
SIGNAL_SELL = 'SELL'
SIGNAL_KEEP = 'KEEP'


def consecutive_decline_days(scores):
    """从最新一个分数往回数，连续下降了几天。"""
    scores = list(scores)
    count = 0
    for i in range(len(scores) - 1, 0, -1):
        if scores[i] < scores[i - 1]:
            count += 1
        else:
            break
    return count


def momentum_signal(scores, decline_days_to_sell=DECLINE_DAYS_TO_SELL):
    """
    个股动量择时：分数序列为空 -> KEEP；连续下降达标 -> SELL；否则 BUY。
    """
    if not scores:
        return SIGNAL_KEEP
    return SIGNAL_SELL if consecutive_decline_days(scores) >= decline_days_to_sell else SIGNAL_BUY


def rsrs_allows_buy(rsrs_score, enabled=RSRS_ENABLED, threshold=RSRS_BUY_THRESHOLD):
    """
    大盘 RSRS 是否允许买入。

    enabled=False（默认，与原脚本一致）时恒为 True，RSRS 仅作记录。
    """
    if not enabled:
        return True
    if rsrs_score is None:
        return False
    return rsrs_score >= threshold


def timing_signal(scores, rsrs_score=None, decline_days_to_sell=DECLINE_DAYS_TO_SELL,
                  rsrs_enabled=RSRS_ENABLED, rsrs_threshold=RSRS_BUY_THRESHOLD):
    """综合择时信号：个股动量信号 + （可选的）大盘 RSRS 否决。"""
    signal = momentum_signal(scores, decline_days_to_sell)
    if signal == SIGNAL_BUY and not rsrs_allows_buy(rsrs_score, rsrs_enabled, rsrs_threshold):
        return SIGNAL_KEEP
    return signal


def profit_ratio(cost_price, current_price):
    """持仓盈亏比例；成本价非法返回 None。"""
    try:
        cost_price = float(cost_price)
        current_price = float(current_price)
    except (TypeError, ValueError):
        return None
    if cost_price <= 0 or current_price <= 0:
        return None
    return (current_price - cost_price) / cost_price


def stop_loss_triggered(cost_price, current_price, stop_loss_ratio=STOP_LOSS_RATIO):
    """是否触发硬止损（默认 -15%）。"""
    ratio = profit_ratio(cost_price, current_price)
    if ratio is None:
        return False
    return ratio <= stop_loss_ratio
