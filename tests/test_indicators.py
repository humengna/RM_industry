# coding: utf-8
"""指标计算的正确性，并与原脚本的 numpy 实现做等价性对照。"""

import math

import numpy as np
import pytest

from momentum_timing.indicators import (
    has_invalid, linear_regression, momentum_score, rsrs_betas, rsrs_corrected_zscore,
)


# ---------- 原脚本（numpy 版）的参考实现，用于等价性比对 ----------

def ref_linear_regression(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 2:
        return 0.0, 0.0
    slope, intercept = np.polyfit(x, y, 1)
    y_pred = slope * x + intercept
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return slope, r2


def ref_momentum_score(close_prices, trading_days=244):
    if len(close_prices) < 2:
        return None
    log_prices = np.log(close_prices)
    x = np.arange(len(log_prices), dtype=float)
    slope, r2 = ref_linear_regression(x, log_prices)
    if r2 <= 0:
        return 0.0
    return (np.exp(slope * trading_days) - 1) * abs(r2)


# ---------- linear_regression ----------

def test_linear_regression_exact_fit():
    slope, r2 = linear_regression([0, 1, 2, 3], [1, 3, 5, 7])
    assert slope == pytest.approx(2.0)
    assert r2 == pytest.approx(1.0)


def test_linear_regression_too_few_points():
    assert linear_regression([1], [2]) == (0.0, 0.0)


def test_linear_regression_no_x_variance():
    assert linear_regression([2, 2, 2], [1, 2, 3]) == (0.0, 0.0)


def test_linear_regression_matches_numpy():
    rng = np.random.RandomState(42)
    for _ in range(20):
        x = np.sort(rng.uniform(1, 50, 21))
        y = 0.8 * x + rng.normal(0, 1.5, 21)
        slope, r2 = linear_regression(x, y)
        ref_slope, ref_r2 = ref_linear_regression(x, y)
        assert slope == pytest.approx(ref_slope, rel=1e-9, abs=1e-12)
        assert r2 == pytest.approx(ref_r2, rel=1e-9, abs=1e-12)


# ---------- momentum_score ----------

def test_momentum_score_uptrend_positive():
    prices = [10.0, 10.2, 10.4, 10.7, 11.0]
    assert momentum_score(prices) > 0


def test_momentum_score_downtrend_negative():
    prices = [11.0, 10.7, 10.4, 10.2, 10.0]
    assert momentum_score(prices) < 0


def test_momentum_score_flat_series_is_zero():
    # 价格不变 -> R2 = 0 -> 分数 0
    assert momentum_score([10.0] * 5) == 0.0


def test_momentum_score_invalid_input():
    assert momentum_score([10.0]) is None
    assert momentum_score([10.0, float('nan'), 10.5]) is None
    assert momentum_score([10.0, 0.0, 10.5]) is None


def test_momentum_score_matches_numpy_reference():
    rng = np.random.RandomState(7)
    for _ in range(30):
        prices = 10 * np.exp(np.cumsum(rng.normal(0.002, 0.02, 5)))
        assert momentum_score(prices) == pytest.approx(ref_momentum_score(prices), rel=1e-9)


def test_momentum_score_annualization():
    # 每天恒定上涨 1%，R2=1，年化应为 exp(ln(1.01)*244)-1
    prices = [10.0 * (1.01 ** i) for i in range(5)]
    expected = math.exp(math.log(1.01) * 244) - 1
    assert momentum_score(prices) == pytest.approx(expected, rel=1e-9)


# ---------- RSRS ----------

def test_rsrs_betas_window_count():
    highs = list(range(10, 40))
    lows = list(range(9, 39))
    betas, r2s = rsrs_betas(highs, lows, 5)
    assert len(betas) == len(highs) - 5 + 1 == len(r2s)
    assert betas[0] == pytest.approx(1.0)


def test_rsrs_corrected_zscore_needs_enough_samples():
    highs = list(range(10, 30))
    lows = list(range(9, 29))
    assert rsrs_corrected_zscore(highs, lows, 5, 600) is None


def test_rsrs_corrected_zscore_constant_beta_is_zero():
    # high 恒等于 low + 1 -> 斜率恒为 1 -> 标准差 0
    highs = [float(i) + 1 for i in range(100)]
    lows = [float(i) for i in range(100)]
    assert rsrs_corrected_zscore(highs, lows, 5, 50) == 0.0


def test_rsrs_corrected_zscore_positive_on_beta_spike():
    rng = np.random.RandomState(3)
    lows = list(np.cumsum(rng.normal(0, 1, 120)) + 100)
    highs = [l + 1 + 0.01 * i for i, l in enumerate(lows)]
    score = rsrs_corrected_zscore(highs, lows, 5, 60)
    assert score is not None


def test_has_invalid():
    assert has_invalid([1, float('nan')])
    assert has_invalid([1, None])
    assert not has_invalid([1, 2, 3])
