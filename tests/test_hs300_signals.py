# coding: utf-8
"""五均线四级发散选股信号。"""

import math

import pytest

from hs300_ma_divergence import signals


def accelerating(n=200, base=10.0, drift=0.001, accel=0.00005):
    return [base * math.exp(drift * i + accel * i * i) for i in range(n)]


def linear(n=200, base=10.0, step=0.01):
    return [base + step * i for i in range(n)]


def decelerating(n=200, base=10.0, drift=0.004, accel=-0.00003):
    return [base * math.exp(drift * i + accel * i * i) for i in range(n)]


# ---------- 均线 ----------

def test_moving_average():
    assert signals.moving_average([1, 2, 3, 4, 5], 5) == pytest.approx(3.0)
    assert signals.moving_average([1, 2, 3], 5) is None
    assert signals.moving_average([1, float('nan'), 3, 4, 5], 5) is None


def test_moving_averages_needs_longest_period():
    closes = list(range(1, 62))
    mas = signals.moving_averages(closes)
    assert set(mas) == {5, 10, 20, 30, 60}
    assert signals.moving_averages(closes[:30]) is None


# ---------- 发散 ----------

def test_spreads_are_short_minus_long_over_long():
    mas = {5: 11.0, 10: 10.0, 20: 8.0, 30: 5.0, 60: 4.0}
    values = signals.spreads(mas)
    assert values[0] == pytest.approx(0.1)          # (11-10)/10
    assert values[1] == pytest.approx(0.25)         # (10-8)/8
    assert values[2] == pytest.approx(0.6)          # (8-5)/5
    assert values[3] == pytest.approx(0.25)         # (5-4)/4


def test_spreads_guard_zero_denominator():
    assert signals.spreads({5: 1.0, 10: 0.0, 20: 1.0, 30: 1.0, 60: 1.0}) is None


def test_divergence_needs_61_bars():
    assert signals.divergence(linear(60)) is None
    assert signals.divergence(linear(61)) is not None


def test_divergence_score_is_sum_of_four_spreads():
    result = signals.divergence(accelerating())
    assert result['score'] == pytest.approx(sum(result['spreads']))
    assert len(result['spreads']) == 4 and len(result['prev_spreads']) == 4
    assert result['s1'] == result['spreads'][0]


# ---------- 入选条件 ----------

def test_accelerating_uptrend_is_valid():
    result = signals.divergence(accelerating())
    assert signals.is_bullish_alignment(result['ma']) is True
    assert signals.is_expanding(result['spreads'], result['prev_spreads']) is True
    assert signals.is_valid_signal(result) is True


def test_linear_uptrend_is_bullish_but_not_expanding():
    """匀速上涨：多头排列成立，但发散不再扩大，不入选。"""
    result = signals.divergence(linear())
    assert signals.is_bullish_alignment(result['ma']) is True
    assert signals.is_expanding(result['spreads'], result['prev_spreads']) is False
    assert signals.is_valid_signal(result) is False


def test_decelerating_uptrend_is_rejected():
    result = signals.divergence(decelerating())
    assert signals.is_valid_signal(result) is False


def test_downtrend_is_rejected():
    closes = [20 * math.exp(-0.002 * i) for i in range(200)]
    assert signals.is_valid_signal(signals.divergence(closes)) is False


def test_evaluate_returns_none_for_invalid():
    assert signals.evaluate('600000.SH', linear()) is None
    item = signals.evaluate('600000.SH', accelerating())
    assert item['stock'] == '600000.SH'
    assert 'score' in item and 's1' in item and 'ma60' in item


# ---------- 排序 ----------

def test_rank_ascending_matches_original_script():
    """原脚本 reverse=True 被注释掉了，实际取的是发散度最小的几只。"""
    items = [{'stock': 'A', 'score': 0.9}, {'stock': 'B', 'score': 0.1},
             {'stock': 'C', 'score': 0.5}]
    assert [x['stock'] for x in signals.rank(items, 2, ascending=True)] == ['B', 'C']


def test_rank_descending_option():
    items = [{'stock': 'A', 'score': 0.9}, {'stock': 'B', 'score': 0.1},
             {'stock': 'C', 'score': 0.5}]
    assert [x['stock'] for x in signals.rank(items, 2, ascending=False)] == ['A', 'C']


def test_select_filters_then_ranks():
    close_map = {
        'A.SH': accelerating(drift=0.001, accel=0.00005),
        'B.SH': accelerating(drift=0.002, accel=0.00008),
        'C.SH': linear(),                      # 不满足发散扩大
        'D.SH': linear(30),                    # 数据不足
    }
    target, candidates = signals.select(close_map, top_n=1)
    assert [x['stock'] for x in candidates] == ['A.SH', 'B.SH']
    # 升序：总发散小的 A 在前
    assert [x['stock'] for x in target] == ['A.SH']


def test_bars_needed():
    assert signals.bars_needed() == 61
