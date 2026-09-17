# coding: utf-8
"""
纯计算指标：一元线性回归、对数线性回归动量分数、RSRS 修正标准分。

本模块只依赖标准库（math），不依赖 numpy / pandas，
这样同一份逻辑既能在 QMT 里运行，也能被单元测试直接覆盖。
输入统一接受任意可迭代的数值序列（list / tuple / numpy array 均可）。
"""

import math

from .config import TRADING_DAYS_PER_YEAR


def _to_floats(seq):
    """把任意序列转成 float 列表；无法转换的元素变成 nan。"""
    out = []
    for v in seq:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(float('nan'))
    return out


def has_invalid(seq):
    """序列中是否存在 None / nan / inf。"""
    for v in _to_floats(seq):
        if math.isnan(v) or math.isinf(v):
            return True
    return False


def linear_regression(x, y):
    """
    一元最小二乘回归，等价于 numpy.polyfit(x, y, 1)。

    返回 (slope, r_squared)；样本不足或 x 无方差时返回 (0.0, 0.0)。
    """
    xs = _to_floats(x)
    ys = _to_floats(y)
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0, 0.0

    xs, ys = xs[:n], ys[:n]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    sxx = sum((xi - mean_x) ** 2 for xi in xs)
    if sxx == 0:
        return 0.0, 0.0

    sxy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(xs, ys))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x

    ss_res = sum((yi - (slope * xi + intercept)) ** 2 for xi, yi in zip(xs, ys))
    ss_tot = sum((yi - mean_y) ** 2 for yi in ys)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return slope, r2


def momentum_score(close_prices, trading_days_per_year=TRADING_DAYS_PER_YEAR):
    """
    动量分数 = 年化收益率 * |R2|

    对收盘价取对数后做线性回归，斜率年化：exp(slope * 244) - 1。
    R2 <= 0 返回 0.0；样本不足或含非法值返回 None。
    """
    prices = _to_floats(close_prices)
    if len(prices) < 2:
        return None
    for p in prices:
        if math.isnan(p) or math.isinf(p) or p <= 0:
            return None

    log_prices = [math.log(p) for p in prices]
    x = list(range(len(log_prices)))

    slope, r2 = linear_regression(x, log_prices)
    if r2 <= 0:
        return 0.0

    try:
        annual_return = math.exp(slope * trading_days_per_year) - 1
    except OverflowError:
        annual_return = float('inf')

    return annual_return * abs(r2)


def rsrs_betas(highs, lows, n):
    """
    滚动计算 RSRS 斜率序列：每个窗口用 low 回归 high。

    返回 (betas, r2_list)，长度均为 len(highs) - n + 1（跳过含非法值的窗口）。
    """
    hs = _to_floats(highs)
    ls = _to_floats(lows)
    size = min(len(hs), len(ls))
    betas, r2_list = [], []

    for i in range(n - 1, size):
        h = hs[i - n + 1:i + 1]
        l = ls[i - n + 1:i + 1]
        if len(h) < n or has_invalid(h) or has_invalid(l):
            continue
        slope, r2 = linear_regression(l, h)
        betas.append(slope)
        r2_list.append(r2)

    return betas, r2_list


def rsrs_corrected_zscore(highs, lows, n, m):
    """
    RSRS 修正标准分 = 最新斜率的 zscore * 最新窗口的 R2。

    highs / lows 为已剔除当前 bar 的历史数据；样本不足返回 None。
    """
    betas, r2_list = rsrs_betas(highs, lows, n)
    if len(betas) < m:
        return None

    recent = betas[-m:]
    mean_beta = sum(recent) / len(recent)
    var = sum((b - mean_beta) ** 2 for b in recent) / len(recent)
    std_beta = math.sqrt(var)
    if std_beta == 0:
        return 0.0

    zscore = (recent[-1] - mean_beta) / std_beta
    recent_r2 = r2_list[-1] if r2_list else 0.0
    return zscore * recent_r2
