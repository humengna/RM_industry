# coding: utf-8
"""
分钟线风控：用前几个交易日的日内走势和成交金额分布，提前剔除次日容易跌停的票。

日线只能看到"涨了多少"，看不到"怎么涨的"。真正预告次日跌停的是日内结构：

  炸板       盘中摸到涨停又没封住 —— 接盘资金已经跑了，次日补跌概率最高
  尾盘跳水   最后半小时放量下砸 —— 次日大概率低开，低开就容易奔跌停
  收在低位   全天冲高回落、收盘价贴着当日最低 —— 抛压还没释放完
  跌破 VWAP  当日买入者平均浮亏 —— 次日一有风吹草动就集体离场
  高位派发   日内最高点之后成交额占比过大 —— 主力在高位出货
  触及跌停   盘中摸过跌停 —— 跌停有惯性，次日往往继续

约定（避免未来函数）：只使用"当前交易日之前"的完整交易日分钟数据，
当日分钟线在 09:31 决策时还不存在。
"""

import math

from .config import (
    INTRADAY_DAYS, INTRADAY_MAX_AMOUNT_SPIKE, INTRADAY_MAX_DOWN_AMOUNT_RATIO,
    INTRADAY_MAX_DRAWDOWN, INTRADAY_MAX_FAILED_LIMIT_UP, INTRADAY_MAX_LIMIT_DOWN_TOUCH,
    INTRADAY_MAX_POST_HIGH_AMOUNT_RATIO, INTRADAY_MAX_TAIL_AMOUNT_RATIO,
    INTRADAY_MIN_CLOSE_POSITION, INTRADAY_MIN_SESSION_BARS, INTRADAY_MIN_TAIL_RETURN,
    INTRADAY_MIN_VWAP_GAP, INTRADAY_TAIL_MINUTES,
)
from .universe import limit_prices

# 与日线保持一致的封板容差（元）
LIMIT_TOLERANCE = 0.011

INTRADAY_FIELDS = ('open', 'high', 'low', 'close', 'volume', 'amount')


def _floats(seq):
    out = []
    for v in seq or []:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(float('nan'))
    return out


def _valid(value):
    return value is not None and not math.isnan(value) and not math.isinf(value)


def _clean(values):
    return [v for v in values if _valid(v)]


# ============================================================
# 分钟线 -> 交易日切分
# ============================================================

def group_sessions(times, fields):
    """
    把连续的分钟线按交易日切分。

    times:  ['20240110093100', '20240110093200', ...]
    fields: {'close': [...], 'amount': [...], ...}，与 times 等长
    返回 [{'date': '20240110', 'close': [...], ...}, ...]，按时间升序
    """
    sessions = []
    current = None

    for i, timestamp in enumerate(times or []):
        day = str(timestamp)[:8]
        if len(day) != 8:
            continue
        if current is None or current['date'] != day:
            current = {'date': day}
            for name in INTRADAY_FIELDS:
                current[name] = []
            sessions.append(current)
        for name in INTRADAY_FIELDS:
            values = fields.get(name)
            if values is not None and i < len(values):
                try:
                    current[name].append(float(values[i]))
                except (TypeError, ValueError):
                    current[name].append(float('nan'))

    return sessions


def attach_pre_close(sessions, first_pre_close=None):
    """
    给每个交易日补上前收盘价：前一个交易日的最后一根分钟线收盘价。

    第一个交易日没有前一日可用，取 first_pre_close，取不到就用当日第一根开盘价。
    """
    prev_close = first_pre_close
    for session in sessions:
        closes = _clean(session.get('close'))
        opens = _clean(session.get('open'))
        if prev_close is not None and prev_close > 0:
            session['pre_close'] = prev_close
        elif opens:
            session['pre_close'] = opens[0]
        else:
            session['pre_close'] = None
        if closes:
            prev_close = closes[-1]
    return sessions


def complete_sessions(sessions, min_bars=INTRADAY_MIN_SESSION_BARS):
    """只保留分钟 bar 数量正常的交易日（半日市、停牌半天的数据直接丢掉）。"""
    return [s for s in sessions if len(_clean(s.get('close'))) >= min_bars]


def sessions_before(sessions, date):
    """只保留 date 之前的完整交易日（当日分钟线在 09:31 还看不到）。"""
    return [s for s in sessions if s.get('date') and s['date'] < str(date)[:8]]


# ============================================================
# 单个交易日的日内指标
# ============================================================

def session_amounts(session):
    """分钟成交额序列；没有 amount 字段时用 close * volume 估算。"""
    amounts = _floats(session.get('amount'))
    if amounts and any(_valid(a) and a > 0 for a in amounts):
        return amounts

    closes = _floats(session.get('close'))
    volumes = _floats(session.get('volume'))
    out = []
    for i in range(min(len(closes), len(volumes))):
        if _valid(closes[i]) and _valid(volumes[i]):
            out.append(closes[i] * volumes[i])
        else:
            out.append(float('nan'))
    return out


def total_amount(session):
    """当日成交金额合计。"""
    return sum(_clean(session_amounts(session)))


def vwap(session):
    """成交额加权均价；拿不到成交量时退化为分钟收盘价均值。"""
    amounts = _clean(session_amounts(session))
    volumes = _clean(_floats(session.get('volume')))
    if amounts and volumes and sum(volumes) > 0 and len(amounts) == len(volumes):
        return sum(amounts) / sum(volumes)

    closes = _clean(_floats(session.get('close')))
    return sum(closes) / len(closes) if closes else None


def close_position(session):
    """
    收盘价在当日振幅区间中的位置，0 = 收在最低价，1 = 收在最高价。

    收在下沿说明全天是被卖出去的，次日低开概率大。
    """
    highs = _clean(_floats(session.get('high')))
    lows = _clean(_floats(session.get('low')))
    closes = _clean(_floats(session.get('close')))
    if not highs or not lows or not closes:
        return None

    high, low, close = max(highs), min(lows), closes[-1]
    if high <= low:
        return None
    return (close - low) / (high - low)


def vwap_gap(session):
    """收盘价相对当日 VWAP 的偏离；为负说明当日买入者整体浮亏。"""
    price = vwap(session)
    closes = _clean(_floats(session.get('close')))
    if price is None or price <= 0 or not closes:
        return None
    return closes[-1] / price - 1


def intraday_drawdown(session):
    """当日盘中最大回撤：从已出现的最高点到之后最低点的最大跌幅（负数）。"""
    highs = _floats(session.get('high'))
    lows = _floats(session.get('low'))
    n = min(len(highs), len(lows))
    if n == 0:
        return None

    peak = None
    worst = 0.0
    for i in range(n):
        if _valid(highs[i]):
            peak = highs[i] if peak is None else max(peak, highs[i])
        if peak and peak > 0 and _valid(lows[i]):
            worst = min(worst, lows[i] / peak - 1)
    return worst


def tail_return(session, minutes=INTRADAY_TAIL_MINUTES):
    """尾盘涨跌幅：最后 minutes 根分钟线的收盘 / 起点 - 1。"""
    closes = _clean(_floats(session.get('close')))
    if len(closes) < minutes + 1:
        return None
    start = closes[-(minutes + 1)]
    if start <= 0:
        return None
    return closes[-1] / start - 1


def tail_amount_ratio(session, minutes=INTRADAY_TAIL_MINUTES):
    """尾盘成交额占全天的比例。"""
    amounts = _clean(session_amounts(session))
    if len(amounts) < minutes:
        return None
    total = sum(amounts)
    if total <= 0:
        return None
    return sum(amounts[-minutes:]) / total


def down_amount_ratio(session):
    """
    下跌分钟的成交额占比，作为"主动性抛压"的代理指标。

    超过 0.6 说明当天的成交金额主要是在往下砸的过程中打出来的。
    """
    closes = _floats(session.get('close'))
    amounts = session_amounts(session)
    n = min(len(closes), len(amounts))
    if n < 2:
        return None

    total, down = 0.0, 0.0
    for i in range(1, n):
        if not _valid(closes[i]) or not _valid(closes[i - 1]) or not _valid(amounts[i]):
            continue
        total += amounts[i]
        if closes[i] < closes[i - 1]:
            down += amounts[i]
    if total <= 0:
        return None
    return down / total


def post_high_amount_ratio(session):
    """
    日内最高点之后的成交额占比：高位派发的直接证据。

    冲高之后如果大部分成交金额是在回落过程中打出来的，就是主力在出货。
    """
    highs = _floats(session.get('high'))
    amounts = session_amounts(session)
    n = min(len(highs), len(amounts))
    if n < 2:
        return None

    peak_idx, peak = None, None
    for i in range(n):
        if _valid(highs[i]) and (peak is None or highs[i] > peak):
            peak, peak_idx = highs[i], i
    if peak_idx is None:
        return None

    total = sum(a for a in amounts[:n] if _valid(a))
    if total <= 0:
        return None
    after = sum(a for a in amounts[peak_idx + 1:n] if _valid(a))
    return after / total


def touched_limit_up(stock, session, pre_close=None):
    """当日盘中是否摸到过涨停价。"""
    pre_close = pre_close if pre_close is not None else session.get('pre_close')
    limit_up, _ = limit_prices(stock, pre_close)
    highs = _clean(_floats(session.get('high')))
    if limit_up <= 0 or not highs:
        return False
    return max(highs) >= limit_up - LIMIT_TOLERANCE


def closed_limit_up(stock, session, pre_close=None):
    """当日是否以涨停价收盘。"""
    pre_close = pre_close if pre_close is not None else session.get('pre_close')
    limit_up, _ = limit_prices(stock, pre_close)
    closes = _clean(_floats(session.get('close')))
    if limit_up <= 0 or not closes:
        return False
    return closes[-1] >= limit_up - LIMIT_TOLERANCE


def failed_limit_up(stock, session, pre_close=None):
    """炸板：盘中摸到涨停但收盘没封住。"""
    return (touched_limit_up(stock, session, pre_close)
            and not closed_limit_up(stock, session, pre_close))


def touched_limit_down(stock, session, pre_close=None):
    """当日盘中是否摸到过跌停价。"""
    pre_close = pre_close if pre_close is not None else session.get('pre_close')
    _, limit_down = limit_prices(stock, pre_close)
    lows = _clean(_floats(session.get('low')))
    if limit_down <= 0 or not lows:
        return False
    return min(lows) <= limit_down + LIMIT_TOLERANCE


def session_metrics(stock, session, tail_minutes=INTRADAY_TAIL_MINUTES):
    """把一个交易日的日内指标算成一个 dict，用于否决判断与日志。"""
    return {
        'date': session.get('date'),
        'amount': total_amount(session),
        'close_position': close_position(session),
        'vwap_gap': vwap_gap(session),
        'drawdown': intraday_drawdown(session),
        'tail_return': tail_return(session, tail_minutes),
        'tail_amount_ratio': tail_amount_ratio(session, tail_minutes),
        'down_amount_ratio': down_amount_ratio(session),
        'post_high_amount_ratio': post_high_amount_ratio(session),
        'failed_limit_up': failed_limit_up(stock, session),
        'closed_limit_up': closed_limit_up(stock, session),
        'touched_limit_down': touched_limit_down(stock, session),
    }


# ============================================================
# 参数与总入口
# ============================================================

class IntradayParams(object):
    """分钟线风控阈值，None 表示关闭该项。"""

    def __init__(self, **kwargs):
        self.days = INTRADAY_DAYS
        self.tail_minutes = INTRADAY_TAIL_MINUTES
        self.min_session_bars = INTRADAY_MIN_SESSION_BARS
        self.max_failed_limit_up = INTRADAY_MAX_FAILED_LIMIT_UP
        self.max_limit_down_touch = INTRADAY_MAX_LIMIT_DOWN_TOUCH
        self.min_tail_return = INTRADAY_MIN_TAIL_RETURN
        self.min_close_position = INTRADAY_MIN_CLOSE_POSITION
        self.min_vwap_gap = INTRADAY_MIN_VWAP_GAP
        self.max_down_amount_ratio = INTRADAY_MAX_DOWN_AMOUNT_RATIO
        self.max_drawdown = INTRADAY_MAX_DRAWDOWN
        self.max_tail_amount_ratio = INTRADAY_MAX_TAIL_AMOUNT_RATIO
        self.max_post_high_amount_ratio = INTRADAY_MAX_POST_HIGH_AMOUNT_RATIO
        self.max_amount_spike = INTRADAY_MAX_AMOUNT_SPIKE

        for key, value in kwargs.items():
            if not hasattr(self, key):
                raise TypeError('未知分钟线风控参数: %s' % key)
            setattr(self, key, value)


def evaluate_sessions(stock, sessions, params=None):
    """
    对最近几个完整交易日的分钟线做体检。

    sessions: 已按时间升序、已 attach_pre_close 的交易日列表（不含当日）
    返回 (reasons, metrics)：reasons 为空表示通过。

    判定口径：
      炸板 / 触及跌停   统计最近 params.days 天的次数
      日内结构与成交额  只看最近一个交易日（对次日最有预测力）
    """
    params = params or IntradayParams()
    sessions = complete_sessions(sessions or [], params.min_session_bars)
    if not sessions:
        return ['intraday_no_data'], {}

    recent = sessions[-params.days:] if params.days else sessions
    last = recent[-1]
    metrics = session_metrics(stock, last, params.tail_minutes)
    metrics['sessions'] = len(recent)

    reasons = []

    # ---------- 炸板与跌停（统计最近几天）----------
    failed = sum(1 for s in recent if failed_limit_up(stock, s))
    metrics['failed_limit_up_count'] = failed
    if params.max_failed_limit_up is not None and failed > params.max_failed_limit_up:
        reasons.append('failed_limit_up')

    touched_down = sum(1 for s in recent if touched_limit_down(stock, s))
    metrics['limit_down_touch_count'] = touched_down
    if params.max_limit_down_touch is not None and touched_down > params.max_limit_down_touch:
        reasons.append('limit_down_touch')

    # ---------- 最近一个交易日的日内结构 ----------
    value = metrics.get('tail_return')
    if params.min_tail_return is not None and value is not None:
        if value < params.min_tail_return:
            reasons.append('tail_selloff')

    value = metrics.get('close_position')
    if params.min_close_position is not None and value is not None:
        if value < params.min_close_position:
            reasons.append('close_at_low')

    value = metrics.get('vwap_gap')
    if params.min_vwap_gap is not None and value is not None:
        if value < params.min_vwap_gap:
            reasons.append('below_vwap')

    value = metrics.get('drawdown')
    if params.max_drawdown is not None and value is not None:
        if value < params.max_drawdown:
            reasons.append('intraday_crash')

    # ---------- 成交金额分布 ----------
    value = metrics.get('down_amount_ratio')
    if params.max_down_amount_ratio is not None and value is not None:
        if value > params.max_down_amount_ratio:
            reasons.append('selling_pressure')

    tail_ratio = metrics.get('tail_amount_ratio')
    tail_ret = metrics.get('tail_return')
    if (params.max_tail_amount_ratio is not None and tail_ratio is not None
            and tail_ratio > params.max_tail_amount_ratio
            and tail_ret is not None and tail_ret < 0):
        reasons.append('tail_dump')

    value = metrics.get('post_high_amount_ratio')
    if params.max_post_high_amount_ratio is not None and value is not None:
        if value > params.max_post_high_amount_ratio:
            reasons.append('high_distribution')

    # ---------- 成交额放大（天量滞涨）----------
    if params.max_amount_spike is not None and len(recent) >= 2:
        history = [total_amount(s) for s in recent[:-1]]
        history = [a for a in history if a > 0]
        last_amount = metrics.get('amount') or 0.0
        if history and last_amount > 0:
            spike = last_amount / (sum(history) / len(history))
            metrics['amount_spike'] = spike
            if spike > params.max_amount_spike and not metrics.get('closed_limit_up'):
                reasons.append('amount_blowoff')

    return reasons, metrics
