# coding: utf-8
"""下单量与买入可行性。"""

from momentum_timing.portfolio import buy_volume, can_buy


def test_buy_volume_rounds_down_to_lots():
    assert buy_volume(100000, 10.0) == 10000
    assert buy_volume(10550, 10.0) == 1000
    assert buy_volume(1999, 10.0) == 100


def test_buy_volume_insufficient_cash():
    assert buy_volume(999, 10.0) == 0
    assert buy_volume(0, 10.0) == 0
    assert buy_volume(10000, 0) == 0
    assert buy_volume(10000, None) == 0


def test_can_buy_blocks_locked_limit_up():
    ok, reason = can_buy(low_price=12.0, limit_up=12.0)
    assert ok is False and reason == 'limit_up_locked'


def test_can_buy_allows_normal_day():
    assert can_buy(low_price=11.5, limit_up=12.0)[0] is True
    assert can_buy(low_price=0, limit_up=12.0)[0] is True
    assert can_buy(low_price=12.0, limit_up=0)[0] is True
