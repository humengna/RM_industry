# coding: utf-8
"""
风控模块：把"已经涨疯了"的票在下单前拦掉。

背景：LOOKBACK_DAYS=5 的对数回归 + 244 天年化，会让连板/垂直拉升的票
拿到极高分数，排名第一的几乎必然是情绪最亢奋的那只——也正是次日容易
一字跌停、卖都卖不掉的那只。本模块按"过热 / 波动 / 流动性 / 结构"四类
指标给候选股打否决票。

约定（避免未来函数）：
  history  只包含"当前 bar 之前"的历史数据，是 09:31 决策时真实可见的；
  today    只包含当日开盘即可观测的信息（开盘价、前收），不含当日收盘价。
"""

import math

from .config import (
    RISK_LIMIT_DOWN_WINDOW, RISK_LIMIT_UP_WINDOW, RISK_MAX_AMPLITUDE,
    RISK_MAX_BIAS, RISK_MAX_CONSECUTIVE_LIMIT_UP, RISK_MAX_GAIN_LONG,
    RISK_MAX_GAIN_SHORT, RISK_MAX_GAP_DOWN, RISK_MAX_GAP_UP,
    RISK_MAX_LIMIT_DOWN_COUNT, RISK_MAX_LIMIT_UP_COUNT, RISK_MAX_TURNOVER,
    RISK_MAX_VOLATILITY, RISK_MAX_VOLUME_RATIO, RISK_MIN_AMOUNT,
    RISK_MIN_LISTED_DAYS, RISK_MIN_SCORE, RISK_GAIN_LONG_WINDOW, RISK_GAIN_SHORT_WINDOW,
    RISK_AMPLITUDE_WINDOW, RISK_BIAS_WINDOW, RISK_VOLATILITY_WINDOW,
    RISK_VOLUME_WINDOW, RISK_AMOUNT_WINDOW, TRADING_DAYS_PER_YEAR,
)
from .universe import limit_prices

# 判断是否触及涨跌停的容差（元）：收盘价与涨跌停价相差 1 分以内即算封板
LIMIT_TOLERANCE = 0.011


# ============================================================
# 基础指标
# ============================================================

def _floats(seq):
    out = []
    for v in seq or []:
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = float('nan')
        out.append(f)
    return out


def _valid(value):
    return value is not None and not math.isnan(value) and not math.isinf(value)


def hit_limit_up(stock, close, pre_close):
    """当日是否涨停收盘。"""
    limit_up, _ = limit_prices(stock, pre_close)
    return bool(limit_up > 0 and close > 0 and close >= limit_up - LIMIT_TOLERANCE)


def hit_limit_down(stock, close, pre_close):
    """当日是否跌停收盘。"""
    _, limit_down = limit_prices(stock, pre_close)
    return bool(limit_down > 0 and close > 0 and close <= limit_down + LIMIT_TOLERANCE)


def limit_up_count(stock, closes, pre_closes, window):
    """最近 window 个交易日里涨停收盘的次数。"""
    closes, pre_closes = _floats(closes), _floats(pre_closes)
    n = min(len(closes), len(pre_closes), window)
    if n <= 0:
        return 0
    return sum(1 for i in range(-n, 0) if hit_limit_up(stock, closes[i], pre_closes[i]))


def limit_down_count(stock, closes, pre_closes, window):
    """最近 window 个交易日里跌停收盘的次数。"""
    closes, pre_closes = _floats(closes), _floats(pre_closes)
    n = min(len(closes), len(pre_closes), window)
    if n <= 0:
        return 0
    return sum(1 for i in range(-n, 0) if hit_limit_down(stock, closes[i], pre_closes[i]))


def consecutive_limit_up(stock, closes, pre_closes):
    """从最近一个交易日往回数，连续涨停（连板）的天数。"""
    closes, pre_closes = _floats(closes), _floats(pre_closes)
    n = min(len(closes), len(pre_closes))
    count = 0
    for i in range(n - 1, -1, -1):
        if hit_limit_up(stock, closes[i], pre_closes[i]):
            count += 1
        else:
            break
    return count


def cumulative_return(closes, window):
    """最近 window 个交易日的累计涨幅，数据不足返回 None。"""
    closes = _floats(closes)
    if len(closes) < window + 1:
        return None
    start, end = closes[-(window + 1)], closes[-1]
    if not _valid(start) or not _valid(end) or start <= 0:
        return None
    return end / start - 1


def moving_average(values, window):
    """最近 window 个值的均值，数据不足或含非法值返回 None。"""
    values = _floats(values)
    if len(values) < window or window <= 0:
        return None
    tail = values[-window:]
    if any(not _valid(v) for v in tail):
        return None
    return sum(tail) / window


def bias_ratio(closes, window):
    """乖离率 = (最新收盘 - MA) / MA，衡量偏离均线的程度。"""
    ma = moving_average(closes, window)
    closes = _floats(closes)
    if ma is None or ma <= 0 or not closes:
        return None
    return closes[-1] / ma - 1


def average_amplitude(highs, lows, pre_closes, window):
    """最近 window 日的平均振幅 = mean((high - low) / pre_close)。"""
    highs, lows, pre_closes = _floats(highs), _floats(lows), _floats(pre_closes)
    n = min(len(highs), len(lows), len(pre_closes), window)
    if n <= 0:
        return None

    values = []
    for i in range(-n, 0):
        high, low, pre_close = highs[i], lows[i], pre_closes[i]
        if not _valid(high) or not _valid(low) or not _valid(pre_close) or pre_close <= 0:
            continue
        values.append((high - low) / pre_close)
    return sum(values) / len(values) if values else None


def annualized_volatility(closes, window, trading_days=TRADING_DAYS_PER_YEAR):
    """最近 window 日收益率的年化波动率。"""
    closes = _floats(closes)
    if len(closes) < window + 1:
        return None

    tail = closes[-(window + 1):]
    returns = []
    for prev, cur in zip(tail[:-1], tail[1:]):
        if not _valid(prev) or not _valid(cur) or prev <= 0:
            return None
        returns.append(cur / prev - 1)
    if len(returns) < 2:
        return None

    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(var) * math.sqrt(trading_days)


def average_amount(amounts, window):
    """最近 window 日的平均成交额（元）。"""
    return moving_average(amounts, window)


def volume_ratio(volumes, window):
    """量比 = 最新成交量 / 最近 window 日均量。"""
    volumes = _floats(volumes)
    if len(volumes) < window + 1:
        return None
    base = moving_average(volumes[:-1], window)
    if base is None or base <= 0 or not _valid(volumes[-1]):
        return None
    return volumes[-1] / base


def turnover_rate(volume, float_volume):
    """换手率 = 成交量 / 流通股本；拿不到流通股本返回 None。"""
    try:
        volume = float(volume)
        float_volume = float(float_volume)
    except (TypeError, ValueError):
        return None
    if float_volume <= 0 or volume < 0:
        return None
    return volume / float_volume


def gap_ratio(open_price, pre_close):
    """跳空幅度 = 开盘价 / 前收 - 1。"""
    try:
        open_price = float(open_price)
        pre_close = float(pre_close)
    except (TypeError, ValueError):
        return None
    if open_price <= 0 or pre_close <= 0:
        return None
    return open_price / pre_close - 1


# ============================================================
# 风控参数与结果
# ============================================================

class RiskParams(object):
    """
    风控阈值。None 表示关闭该项检查。

    默认值取自 config，可在回测里临时覆盖：RiskParams(max_gap_up=0.03)
    """

    def __init__(self, **kwargs):
        self.max_consecutive_limit_up = RISK_MAX_CONSECUTIVE_LIMIT_UP
        self.max_limit_up_count = RISK_MAX_LIMIT_UP_COUNT
        self.limit_up_window = RISK_LIMIT_UP_WINDOW
        self.max_limit_down_count = RISK_MAX_LIMIT_DOWN_COUNT
        self.limit_down_window = RISK_LIMIT_DOWN_WINDOW
        self.max_gain_short = RISK_MAX_GAIN_SHORT
        self.gain_short_window = RISK_GAIN_SHORT_WINDOW
        self.max_gain_long = RISK_MAX_GAIN_LONG
        self.gain_long_window = RISK_GAIN_LONG_WINDOW
        self.max_bias = RISK_MAX_BIAS
        self.bias_window = RISK_BIAS_WINDOW
        self.max_amplitude = RISK_MAX_AMPLITUDE
        self.amplitude_window = RISK_AMPLITUDE_WINDOW
        self.max_volatility = RISK_MAX_VOLATILITY
        self.volatility_window = RISK_VOLATILITY_WINDOW
        self.max_turnover = RISK_MAX_TURNOVER
        self.max_volume_ratio = RISK_MAX_VOLUME_RATIO
        self.volume_window = RISK_VOLUME_WINDOW
        self.min_amount = RISK_MIN_AMOUNT
        self.amount_window = RISK_AMOUNT_WINDOW
        self.min_listed_days = RISK_MIN_LISTED_DAYS
        self.max_gap_up = RISK_MAX_GAP_UP
        self.max_gap_down = RISK_MAX_GAP_DOWN
        self.min_score = RISK_MIN_SCORE

        for key, value in kwargs.items():
            if not hasattr(self, key):
                raise TypeError('未知风控参数: %s' % key)
            setattr(self, key, value)


class RiskResult(object):
    """风控结论：是否通过、否决原因、各项指标（用于日志与复盘）。"""

    def __init__(self, passed, reasons=None, metrics=None):
        self.passed = passed
        self.reasons = reasons or []
        self.metrics = metrics or {}

    def __repr__(self):
        return 'RiskResult(passed=%s, reasons=%s)' % (self.passed, self.reasons)

    def describe(self):
        """给日志用的一行说明。"""
        if self.passed:
            return 'PASS'
        return 'REJECT(%s)' % ','.join(self.reasons)


# ============================================================
# 总入口
# ============================================================

def history_bars_needed(params=None):
    """风控需要多少根历史 K 线（不含当前 bar），供取数时确定 count。"""
    params = params or RiskParams()
    needs = [2]
    if params.max_limit_up_count is not None:
        needs.append(params.limit_up_window)
    if params.max_limit_down_count is not None:
        needs.append(params.limit_down_window)
    if params.max_gain_short is not None:
        needs.append(params.gain_short_window + 1)
    if params.max_gain_long is not None:
        needs.append(params.gain_long_window + 1)
    if params.max_bias is not None:
        needs.append(params.bias_window)
    if params.max_amplitude is not None:
        needs.append(params.amplitude_window)
    if params.max_volatility is not None:
        needs.append(params.volatility_window + 1)
    if params.max_volume_ratio is not None:
        needs.append(params.volume_window + 1)
    if params.min_amount is not None:
        needs.append(params.amount_window)
    return max(needs)


def evaluate_candidate(stock, history, today=None, params=None, listed_days=None,
             float_volume=None, score=None):
    """
    对候选股做风控体检。

    history: 排除当前 bar 的历史行情，dict of list：
             close / pre_close 必需，high / low / volume / amount 可选
    today:   当日开盘即可见的信息，dict：open / pre_close
    listed_days: 上市天数（由 get_instrument_detail 的 OpenDate 推算）
    float_volume: 流通股本，用于算换手率
    score:   该股的动量分数，用于过滤没有上涨趋势的标的

    返回 RiskResult。
    """
    params = params or RiskParams()
    today = today or {}

    closes = _floats(history.get('close'))
    pre_closes = _floats(history.get('pre_close'))
    highs = _floats(history.get('high'))
    lows = _floats(history.get('low'))
    volumes = _floats(history.get('volume'))
    amounts = _floats(history.get('amount'))

    reasons = []
    metrics = {}

    if score is not None:
        metrics['score'] = score
        if params.min_score is not None and score <= params.min_score:
            reasons.append('weak_momentum')

    if len(closes) < 2 or len(pre_closes) < 2:
        reasons.append('data_insufficient')
        return RiskResult(False, reasons, metrics)

    # ---------- 过热：连板 / 涨停次数 / 累计涨幅 / 乖离 ----------
    streak = consecutive_limit_up(stock, closes, pre_closes)
    metrics['consecutive_limit_up'] = streak
    if params.max_consecutive_limit_up is not None and streak > params.max_consecutive_limit_up:
        reasons.append('limit_up_streak')

    if params.max_limit_up_count is not None:
        count = limit_up_count(stock, closes, pre_closes, params.limit_up_window)
        metrics['limit_up_count'] = count
        if count > params.max_limit_up_count:
            reasons.append('limit_up_count')

    if params.max_gain_short is not None:
        gain = cumulative_return(closes, params.gain_short_window)
        metrics['gain_short'] = gain
        if gain is not None and gain > params.max_gain_short:
            reasons.append('gain_short')

    if params.max_gain_long is not None:
        gain = cumulative_return(closes, params.gain_long_window)
        metrics['gain_long'] = gain
        if gain is not None and gain > params.max_gain_long:
            reasons.append('gain_long')

    if params.max_bias is not None:
        bias = bias_ratio(closes, params.bias_window)
        metrics['bias'] = bias
        if bias is not None and bias > params.max_bias:
            reasons.append('bias')

    # ---------- 已经在砸盘：近期出现过跌停 ----------
    if params.max_limit_down_count is not None:
        count = limit_down_count(stock, closes, pre_closes, params.limit_down_window)
        metrics['limit_down_count'] = count
        if count > params.max_limit_down_count:
            reasons.append('limit_down_history')

    # ---------- 波动 ----------
    if params.max_amplitude is not None and highs and lows:
        amplitude = average_amplitude(highs, lows, pre_closes, params.amplitude_window)
        metrics['amplitude'] = amplitude
        if amplitude is not None and amplitude > params.max_amplitude:
            reasons.append('amplitude')

    if params.max_volatility is not None:
        vol = annualized_volatility(closes, params.volatility_window)
        metrics['volatility'] = vol
        if vol is not None and vol > params.max_volatility:
            reasons.append('volatility')

    # ---------- 资金异动与流动性 ----------
    if params.max_volume_ratio is not None and volumes:
        ratio = volume_ratio(volumes, params.volume_window)
        metrics['volume_ratio'] = ratio
        if ratio is not None and ratio > params.max_volume_ratio:
            reasons.append('volume_spike')

    if params.max_turnover is not None and volumes and float_volume:
        turnover = turnover_rate(volumes[-1], float_volume)
        metrics['turnover'] = turnover
        if turnover is not None and turnover > params.max_turnover:
            reasons.append('turnover')

    if params.min_amount is not None and amounts:
        amount = average_amount(amounts, params.amount_window)
        metrics['amount'] = amount
        if amount is not None and amount < params.min_amount:
            reasons.append('illiquid')

    # ---------- 次新股 ----------
    if params.min_listed_days is not None and listed_days is not None:
        metrics['listed_days'] = listed_days
        if listed_days < params.min_listed_days:
            reasons.append('new_listing')

    # ---------- 当日开盘：追高 / 低开 ----------
    gap = gap_ratio(today.get('open'), today.get('pre_close'))
    if gap is not None:
        metrics['gap'] = gap
        if params.max_gap_up is not None and gap > params.max_gap_up:
            reasons.append('gap_up')
        if params.max_gap_down is not None and gap < -abs(params.max_gap_down):
            reasons.append('gap_down')

    return RiskResult(not reasons, reasons, metrics)


def market_is_healthy(index_closes, ma_window):
    """
    大盘风控：指数收盘价站上 ma_window 日均线才算健康。

    返回 (是否健康, {'close':…, 'ma':…})；数据不足时按"健康"处理，
    避免回测初期因为数据不够而整段空仓。
    """
    closes = _floats(index_closes)
    ma = moving_average(closes, ma_window)
    if ma is None or not closes or not _valid(closes[-1]):
        return True, {}
    return closes[-1] >= ma, {'close': closes[-1], 'ma': ma}


def pick_first_passing(ranked, evaluator, max_candidates=None):
    """
    沿动量排名从高到低找第一只通过风控的股票。

    ranked:    [(股票, 分数), ...]，已按分数降序
    evaluator: 函数 stock -> RiskResult
    返回 (股票, RiskResult, 被否决的 [(股票, RiskResult), ...])；全被否决时股票为 None
    """
    rejected = []
    for i, item in enumerate(ranked):
        if max_candidates is not None and i >= max_candidates:
            break
        stock = item[0] if isinstance(item, (tuple, list)) else item
        result = evaluator(stock)
        if result.passed:
            return stock, result, rejected
        rejected.append((stock, result))
    return None, None, rejected
