# coding: utf-8
"""择时信号与止损。"""

from momentum_timing.signals import (
    SIGNAL_BUY, SIGNAL_KEEP, SIGNAL_SELL, consecutive_decline_days, momentum_signal,
    profit_ratio, rsrs_allows_buy, stop_loss_triggered, timing_signal,
)


def test_consecutive_decline_days():
    assert consecutive_decline_days([1, 2, 3, 4]) == 0
    assert consecutive_decline_days([1, 2, 3, 2]) == 1
    assert consecutive_decline_days([1, 4, 3, 2]) == 2
    assert consecutive_decline_days([4, 3, 2, 1]) == 3
    assert consecutive_decline_days([]) == 0
    assert consecutive_decline_days([1]) == 0


def test_momentum_signal_sell_after_two_declines():
    assert momentum_signal([1.0, 5.0, 4.0, 3.0]) == SIGNAL_SELL


def test_momentum_signal_buy_when_not_declining_enough():
    assert momentum_signal([5.0, 4.0]) == SIGNAL_BUY       # 只降 1 天
    assert momentum_signal([1.0, 2.0, 3.0]) == SIGNAL_BUY  # 上升


def test_momentum_signal_empty_scores_keeps():
    assert momentum_signal([]) == SIGNAL_KEEP


def test_momentum_signal_custom_threshold():
    assert momentum_signal([5.0, 4.0], decline_days_to_sell=1) == SIGNAL_SELL


def test_rsrs_disabled_always_allows():
    assert rsrs_allows_buy(None, enabled=False) is True
    assert rsrs_allows_buy(-5.0, enabled=False) is True


def test_rsrs_enabled_blocks_weak_market():
    assert rsrs_allows_buy(0.9, enabled=True, threshold=0.7) is True
    assert rsrs_allows_buy(0.1, enabled=True, threshold=0.7) is False
    assert rsrs_allows_buy(None, enabled=True, threshold=0.7) is False


def test_timing_signal_default_ignores_rsrs():
    assert timing_signal([1.0, 2.0, 3.0], rsrs_score=-9.0) == SIGNAL_BUY


def test_timing_signal_rsrs_veto_turns_buy_into_keep():
    assert timing_signal([1.0, 2.0, 3.0], rsrs_score=-9.0,
                         rsrs_enabled=True, rsrs_threshold=0.7) == SIGNAL_KEEP


def test_timing_signal_sell_not_blocked_by_rsrs():
    assert timing_signal([5.0, 4.0, 3.0], rsrs_score=9.0,
                         rsrs_enabled=True, rsrs_threshold=0.7) == SIGNAL_SELL


def test_profit_ratio():
    assert profit_ratio(10.0, 8.5) == -0.15
    assert profit_ratio(0, 8.5) is None
    assert profit_ratio(10.0, 0) is None
    assert profit_ratio(None, 8.5) is None


def test_stop_loss_triggered_at_threshold():
    assert stop_loss_triggered(10.0, 8.5) is True    # 正好 -15%
    assert stop_loss_triggered(10.0, 8.4) is True
    assert stop_loss_triggered(10.0, 8.6) is False
    assert stop_loss_triggered(10.0, 12.0) is False


def test_stop_loss_bad_input_does_not_trigger():
    assert stop_loss_triggered(0, 8.5) is False
    assert stop_loss_triggered(10.0, 0) is False
