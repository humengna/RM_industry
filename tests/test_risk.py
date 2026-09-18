# coding: utf-8
"""风控指标与否决逻辑。"""

import pytest

from momentum_timing.risk import (
    RiskParams, annualized_volatility, average_amount, average_amplitude, bias_ratio,
    consecutive_limit_up, cumulative_return, evaluate_candidate, gap_ratio,
    history_bars_needed, hit_limit_down, hit_limit_up, limit_down_count, limit_up_count,
    market_is_healthy, moving_average, pick_first_passing, turnover_rate, volume_ratio,
)


def limit_up_series(start, days, ratio=0.10):
    """生成连续涨停的收盘价序列。"""
    closes = [start]
    for _ in range(days):
        closes.append(round(closes[-1] * (1 + ratio), 2))
    return closes[1:]


def with_pre_close(closes, first_pre=None):
    return [first_pre if first_pre is not None else closes[0]] + closes[:-1]


# ---------- 涨跌停识别 ----------

def test_hit_limit_up_main_board():
    assert hit_limit_up('600000.SH', 11.0, 10.0) is True
    assert hit_limit_up('600000.SH', 10.90, 10.0) is False
    # 容差 1 分：差一分钱的"准涨停"也算封板，避免涨停价四舍五入带来的漏判
    assert hit_limit_up('600000.SH', 10.99, 10.0) is True


def test_hit_limit_up_chinext_needs_20_percent():
    assert hit_limit_up('300750.SZ', 11.0, 10.0) is False
    assert hit_limit_up('300750.SZ', 12.0, 10.0) is True


def test_hit_limit_down():
    assert hit_limit_down('600000.SH', 9.0, 10.0) is True
    assert hit_limit_down('600000.SH', 9.02, 10.0) is False
    assert hit_limit_down('688356.SH', 8.0, 10.0) is True


def test_limit_up_count_and_streak():
    closes = [10.0, 10.2, 11.22, 12.34, 12.0]   # 第 3、4 天涨停，第 5 天回落
    pre = with_pre_close(closes)
    assert limit_up_count('600000.SH', closes, pre, 10) == 2
    assert consecutive_limit_up('600000.SH', closes, pre) == 0

    closes = [10.0, 10.0, 11.0, 12.1]           # 最后两天连板
    pre = with_pre_close(closes)
    assert consecutive_limit_up('600000.SH', closes, pre) == 2


def test_limit_down_count_window():
    closes = [10.0, 9.0, 9.5, 10.0, 10.5]       # 第 2 天跌停
    pre = with_pre_close(closes)
    assert limit_down_count('600000.SH', closes, pre, 10) == 1
    assert limit_down_count('600000.SH', closes, pre, 2) == 0


# ---------- 统计指标 ----------

def test_cumulative_return():
    closes = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    assert cumulative_return(closes, 5) == pytest.approx(0.5)
    assert cumulative_return(closes, 10) is None


def test_moving_average_and_bias():
    closes = [10.0] * 19 + [12.0]
    assert moving_average(closes, 20) == pytest.approx(10.1)
    assert bias_ratio(closes, 20) == pytest.approx(12.0 / 10.1 - 1)
    assert bias_ratio([10.0] * 5, 20) is None


def test_average_amplitude():
    highs = [11.0, 12.0]
    lows = [10.0, 10.0]
    pre = [10.0, 10.0]
    assert average_amplitude(highs, lows, pre, 2) == pytest.approx(0.15)


def test_annualized_volatility_zero_for_constant_growth():
    closes = [10.0 * (1.01 ** i) for i in range(25)]
    assert annualized_volatility(closes, 20) == pytest.approx(0.0, abs=1e-9)


def test_annualized_volatility_positive_for_choppy_series():
    closes = [10.0, 11.0, 9.5, 11.5, 9.0, 12.0, 8.5, 12.5, 9.0, 11.0,
              10.0, 12.0, 9.0, 11.0, 10.5, 9.5, 12.0, 8.8, 11.4, 10.2, 9.7]
    assert annualized_volatility(closes, 20) > 1.0


def test_volume_ratio_and_turnover():
    volumes = [100, 100, 100, 100, 100, 500]
    assert volume_ratio(volumes, 5) == pytest.approx(5.0)
    assert volume_ratio([100, 100], 5) is None
    assert turnover_rate(1000, 10000) == pytest.approx(0.1)
    assert turnover_rate(1000, 0) is None


def test_average_amount_and_gap():
    assert average_amount([1e8, 2e8, 3e8], 3) == pytest.approx(2e8)
    assert gap_ratio(10.5, 10.0) == pytest.approx(0.05)
    assert gap_ratio(0, 10.0) is None


def test_history_bars_needed_covers_longest_window():
    params = RiskParams()
    assert history_bars_needed(params) == params.limit_down_window
    assert history_bars_needed(RiskParams(max_limit_down_count=None)) == 21


# ---------- 大盘 ----------

def test_market_is_healthy():
    ok, metrics = market_is_healthy([10.0] * 19 + [12.0], 20)
    assert ok is True and metrics['ma'] == pytest.approx(10.1)

    ok, _ = market_is_healthy([12.0] * 19 + [10.0], 20)
    assert ok is False


def test_market_healthy_when_data_insufficient():
    ok, metrics = market_is_healthy([10.0, 10.1], 20)
    assert ok is True and metrics == {}


# ---------- 总入口 ----------

def normal_history(days=70):
    """一只温和上涨、成交活跃的正常票。"""
    closes = [round(10.0 * (1.003 ** i), 2) for i in range(days)]
    return {
        'close': closes,
        'pre_close': with_pre_close(closes),
        'high': [round(c * 1.01, 2) for c in closes],
        'low': [round(c * 0.99, 2) for c in closes],
        'volume': [1000000] * days,
        'amount': [2e8] * days,
    }


def test_normal_stock_passes():
    history = normal_history()
    result = evaluate_candidate('600000.SH', history,
                                today={'open': history['close'][-1] * 1.005,
                                       'pre_close': history['close'][-1]},
                                listed_days=800, float_volume=5e8, score=1.5)
    assert result.passed, result.reasons
    assert result.describe() == 'PASS'


def test_consecutive_limit_up_is_rejected():
    history = normal_history()
    closes = history['close'][:-2] + limit_up_series(history['close'][-3], 2)
    history['close'] = closes
    history['pre_close'] = with_pre_close(closes)

    result = evaluate_candidate('600000.SH', history, score=99.0)
    assert 'limit_up_streak' in result.reasons


def test_too_many_limit_ups_in_window_is_rejected():
    closes = [10.0] * 60
    # 近 10 日里塞 3 个涨停，但不连板
    for i in (-9, -6, -3):
        closes[i] = round(closes[i - 1] * 1.1, 2)
    history = {'close': closes, 'pre_close': with_pre_close(closes)}

    result = evaluate_candidate('600000.SH', history, score=1.0)
    assert 'limit_up_count' in result.reasons


def test_short_term_surge_is_rejected():
    closes = [10.0] * 55 + [10.0, 11.0, 12.0, 12.6, 13.2]
    history = {'close': closes, 'pre_close': with_pre_close(closes)}

    result = evaluate_candidate('600000.SH', history, score=5.0)
    assert 'gain_short' in result.reasons
    assert 'bias' in result.reasons


def test_recent_limit_down_is_rejected():
    history = normal_history()
    closes = list(history['close'])
    closes[-30] = round(closes[-31] * 0.9, 2)      # 30 个交易日前吃过跌停
    history['close'] = closes
    history['pre_close'] = with_pre_close(closes)

    result = evaluate_candidate('600000.SH', history, score=1.0)
    assert 'limit_down_history' in result.reasons


def test_high_volatility_and_amplitude_rejected():
    closes = [10.0 + (2.5 if i % 2 else -2.5) for i in range(70)]
    history = {
        'close': closes,
        'pre_close': with_pre_close(closes),
        'high': [c * 1.06 for c in closes],
        'low': [c * 0.94 for c in closes],
    }
    result = evaluate_candidate('600000.SH', history, score=1.0)
    assert 'volatility' in result.reasons
    assert 'amplitude' in result.reasons


def test_volume_spike_and_illiquid_rejected():
    history = normal_history()
    history['volume'] = [1000000] * (len(history['close']) - 1) + [9000000]
    history['amount'] = [1e6] * len(history['close'])

    result = evaluate_candidate('600000.SH', history, score=1.0)
    assert 'volume_spike' in result.reasons
    assert 'illiquid' in result.reasons


def test_turnover_rejected():
    history = normal_history()
    result = evaluate_candidate('600000.SH', history, score=1.0, float_volume=2000000)
    assert 'turnover' in result.reasons


def test_new_listing_rejected():
    result = evaluate_candidate('600000.SH', normal_history(), score=1.0, listed_days=30)
    assert 'new_listing' in result.reasons


def test_gap_up_and_gap_down_rejected():
    history = normal_history()
    last = history['close'][-1]

    up = evaluate_candidate('600000.SH', history,
                            today={'open': last * 1.08, 'pre_close': last}, score=1.0)
    assert 'gap_up' in up.reasons

    down = evaluate_candidate('600000.SH', history,
                              today={'open': last * 0.92, 'pre_close': last}, score=1.0)
    assert 'gap_down' in down.reasons


def test_weak_momentum_rejected():
    result = evaluate_candidate('600000.SH', normal_history(), score=0.0)
    assert 'weak_momentum' in result.reasons


def test_data_insufficient_rejected():
    result = evaluate_candidate('600000.SH', {'close': [10.0], 'pre_close': [10.0]})
    assert result.reasons == ['data_insufficient']


def test_params_can_disable_checks():
    history = normal_history()
    closes = history['close'][:-2] + limit_up_series(history['close'][-3], 2)
    history['close'] = closes
    history['pre_close'] = with_pre_close(closes)

    params = RiskParams(max_consecutive_limit_up=None, max_limit_up_count=None,
                        max_gain_short=None, max_bias=None, max_volume_ratio=None)
    result = evaluate_candidate('600000.SH', history, params=params, score=99.0)
    assert result.passed, result.reasons


def test_unknown_param_raises():
    with pytest.raises(TypeError):
        RiskParams(max_gain=0.1)


# ---------- 排名顺延 ----------

def test_pick_first_passing_walks_down_the_ranking():
    from momentum_timing.risk import RiskResult

    verdicts = {
        'A.SH': RiskResult(False, ['limit_up_streak']),
        'B.SH': RiskResult(False, ['gain_short']),
        'C.SH': RiskResult(True),
    }
    ranked = [('A.SH', 9.0), ('B.SH', 5.0), ('C.SH', 2.0)]

    stock, result, rejected = pick_first_passing(ranked, lambda s: verdicts[s])
    assert stock == 'C.SH' and result.passed
    assert [s for s, _ in rejected] == ['A.SH', 'B.SH']


def test_pick_first_passing_respects_max_candidates():
    from momentum_timing.risk import RiskResult

    verdicts = {'A.SH': RiskResult(False, ['x']), 'B.SH': RiskResult(True)}
    ranked = [('A.SH', 9.0), ('B.SH', 5.0)]

    stock, result, rejected = pick_first_passing(ranked, lambda s: verdicts[s],
                                                 max_candidates=1)
    assert stock is None and result is None
    assert len(rejected) == 1
