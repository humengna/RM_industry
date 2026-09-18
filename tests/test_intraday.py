# coding: utf-8
"""分钟线风控：日内结构与成交金额分布。"""

import pytest

from fake_qmt import concat_sessions, minute_session, trading_minutes

from momentum_timing.intraday import (
    IntradayParams, attach_pre_close, close_position, closed_limit_up, complete_sessions,
    down_amount_ratio, evaluate_sessions, failed_limit_up, group_sessions,
    intraday_drawdown, post_high_amount_ratio, session_metrics, sessions_before,
    tail_amount_ratio, tail_return, total_amount, touched_limit_down, touched_limit_up,
    vwap, vwap_gap,
)

BARS = 240


def make_session(date, closes, **kwargs):
    """由分钟收盘价构造一个交易日的 session（与策略里的结构一致）。"""
    bars = minute_session(date, closes, **kwargs)
    times = bars.pop('time')
    return group_sessions(times, bars)[0]


def ramp(start, end, n=BARS):
    """从 start 线性走到 end 的分钟收盘价序列。"""
    step = (end - start) / float(n - 1)
    return [round(start + step * i, 3) for i in range(n)]


def flat_then_drop(level, drop_to, drop_minutes=30, n=BARS):
    """前面横盘，最后 drop_minutes 分钟直线下砸。"""
    head = [level] * (n - drop_minutes)
    tail = ramp(level, drop_to, drop_minutes)
    return head + tail


# ---------- 切分与前收 ----------

def test_group_sessions_splits_by_day():
    bars = concat_sessions([minute_session('20240110', [10.0] * BARS),
                            minute_session('20240111', [10.5] * BARS)])
    times = bars.pop('time')
    sessions = group_sessions(times, bars)

    assert [s['date'] for s in sessions] == ['20240110', '20240111']
    assert len(sessions[0]['close']) == BARS


def test_sessions_before_drops_current_day():
    sessions = [{'date': '20240110'}, {'date': '20240111'}, {'date': '20240112'}]
    kept = sessions_before(sessions, '20240112150000')
    assert [s['date'] for s in kept] == ['20240110', '20240111']


def test_attach_pre_close_uses_previous_session_close():
    sessions = [make_session('20240110', [10.0] * BARS),
                make_session('20240111', ramp(10.0, 11.0))]
    attach_pre_close(sessions)

    assert sessions[0]['pre_close'] == 10.0        # 没有前一日，退化为当日首根开盘
    assert sessions[1]['pre_close'] == 10.0        # 前一日收盘


def test_complete_sessions_drops_short_days():
    full = make_session('20240110', [10.0] * BARS)
    half = make_session('20240111', [10.0] * 30)
    assert [s['date'] for s in complete_sessions([full, half], 60)] == ['20240110']


# ---------- 日内指标 ----------

def test_close_position_high_and_low():
    up = make_session('20240110', ramp(10.0, 11.0))
    assert close_position(up) == pytest.approx(1.0)

    down = make_session('20240110', ramp(11.0, 10.0))
    assert close_position(down) == pytest.approx(0.0)


def test_vwap_and_gap():
    session = make_session('20240110', [10.0] * BARS)
    assert vwap(session) == pytest.approx(10.0)
    assert vwap_gap(session) == pytest.approx(0.0)

    # 冲高回落：收盘明显低于 VWAP
    session = make_session('20240110', ramp(11.0, 10.0))
    assert vwap_gap(session) < -0.04


def test_intraday_drawdown():
    # 单边上涨：回撤只有一根分钟线内 high->low 的幅度
    session = make_session('20240110', ramp(10.0, 11.0))
    assert intraday_drawdown(session) > -0.001

    session = make_session('20240110', ramp(11.0, 10.0))
    assert intraday_drawdown(session) == pytest.approx(10.0 / 11.0 - 1, abs=1e-3)


def test_tail_return_and_amount_ratio():
    closes = flat_then_drop(10.0, 9.6, 30)
    amounts = [1e6] * (BARS - 30) + [5e6] * 30      # 尾盘放量
    session = make_session('20240110', closes, amounts=amounts)

    assert tail_return(session, 30) == pytest.approx(9.6 / 10.0 - 1, rel=1e-3)
    ratio = tail_amount_ratio(session, 30)
    assert ratio == pytest.approx(5e6 * 30 / (1e6 * 210 + 5e6 * 30), rel=1e-6)
    assert ratio > 0.35


def test_tail_return_needs_enough_bars():
    assert tail_return(make_session('20240110', [10.0] * 10), 30) is None


def test_down_amount_ratio():
    up = make_session('20240110', ramp(10.0, 11.0))
    assert down_amount_ratio(up) == pytest.approx(0.0)

    down = make_session('20240110', ramp(11.0, 10.0))
    assert down_amount_ratio(down) == pytest.approx(1.0)


def test_post_high_amount_ratio_detects_distribution():
    # 开盘 20 分钟冲高，之后一路放量下跌 —— 典型高位派发
    closes = ramp(10.0, 11.0, 20) + ramp(11.0, 10.2, BARS - 20)
    amounts = [1e6] * 20 + [5e6] * (BARS - 20)
    session = make_session('20240110', closes, amounts=amounts)

    assert post_high_amount_ratio(session) > 0.9


def test_total_amount_falls_back_to_close_times_volume():
    session = make_session('20240110', [10.0] * BARS, amounts=[0.0] * BARS)
    session['volume'] = [100.0] * BARS
    assert total_amount(session) == pytest.approx(10.0 * 100.0 * BARS)


# ---------- 涨跌停结构 ----------

def limit_up_touch_session(date, pre_close=10.0, close=10.3):
    """盘中摸到涨停又掉下来（炸板）。"""
    limit_up = round(pre_close * 1.1, 2)
    closes = ramp(pre_close, limit_up, 100) + ramp(limit_up, close, BARS - 100)
    highs = [max(c, limit_up if 90 <= i <= 110 else c) for i, c in enumerate(closes)]
    session = make_session(date, closes, highs=highs)
    session['pre_close'] = pre_close
    return session


def test_failed_limit_up_is_detected():
    session = limit_up_touch_session('20240110')
    assert touched_limit_up('600000.SH', session) is True
    assert closed_limit_up('600000.SH', session) is False
    assert failed_limit_up('600000.SH', session) is True


def test_sealed_limit_up_is_not_failed():
    limit_up = 11.0
    closes = ramp(10.0, limit_up, 60) + [limit_up] * (BARS - 60)
    session = make_session('20240110', closes)
    session['pre_close'] = 10.0

    assert closed_limit_up('600000.SH', session) is True
    assert failed_limit_up('600000.SH', session) is False


def test_limit_ratio_respected_for_chinext():
    session = limit_up_touch_session('20240110')
    # 创业板涨停是 20%，摸到 11.0 不算涨停
    assert touched_limit_up('300750.SZ', session) is False


def test_touched_limit_down():
    closes = ramp(10.0, 9.0)
    session = make_session('20240110', closes)
    session['pre_close'] = 10.0
    assert touched_limit_down('600000.SH', session) is True

    session = make_session('20240110', ramp(10.0, 9.6))
    session['pre_close'] = 10.0
    assert touched_limit_down('600000.SH', session) is False


def test_session_metrics_shape():
    session = make_session('20240110', ramp(10.0, 10.5))
    session['pre_close'] = 10.0
    metrics = session_metrics('600000.SH', session)

    for key in ('date', 'amount', 'close_position', 'vwap_gap', 'drawdown',
                'tail_return', 'tail_amount_ratio', 'down_amount_ratio',
                'post_high_amount_ratio', 'failed_limit_up', 'touched_limit_down'):
        assert key in metrics


# ---------- 总入口 ----------

def healthy_sessions(dates=('20240108', '20240109', '20240110'), start=10.0):
    """温和上涨、量能平稳的几个交易日。"""
    sessions = []
    level = start
    for date in dates:
        sessions.append(make_session(date, ramp(level, level * 1.01)))
        level = round(level * 1.01, 3)
    attach_pre_close(sessions)
    return sessions


def test_healthy_sessions_pass():
    reasons, metrics = evaluate_sessions('600000.SH', healthy_sessions())
    assert reasons == []
    assert metrics['sessions'] == 3


def test_no_sessions_reports_no_data():
    reasons, metrics = evaluate_sessions('600000.SH', [])
    assert reasons == ['intraday_no_data']


def test_failed_limit_up_rejects():
    sessions = healthy_sessions()
    sessions[-1] = limit_up_touch_session('20240110', pre_close=sessions[-2]['close'][-1])
    attach_pre_close(sessions)

    reasons, _ = evaluate_sessions('600000.SH', sessions)
    assert 'failed_limit_up' in reasons


def test_limit_down_touch_rejects():
    sessions = healthy_sessions()
    pre = sessions[-2]['close'][-1]
    sessions[-1] = make_session('20240110', ramp(pre, pre * 0.9))
    attach_pre_close(sessions)

    reasons, _ = evaluate_sessions('600000.SH', sessions)
    assert 'limit_down_touch' in reasons


def test_tail_selloff_rejects():
    sessions = healthy_sessions()
    pre = sessions[-2]['close'][-1]
    sessions[-1] = make_session('20240110', flat_then_drop(pre, pre * 0.955, 30))
    attach_pre_close(sessions)

    reasons, metrics = evaluate_sessions('600000.SH', sessions)
    assert 'tail_selloff' in reasons
    assert metrics['tail_return'] < -0.03


def test_close_at_low_and_below_vwap_reject():
    sessions = healthy_sessions()
    pre = sessions[-2]['close'][-1]
    # 高开冲高后一路阴跌，收在全天最低
    sessions[-1] = make_session('20240110', ramp(pre * 1.08, pre * 1.0))
    attach_pre_close(sessions)

    reasons, _ = evaluate_sessions('600000.SH', sessions)
    assert 'close_at_low' in reasons
    assert 'below_vwap' in reasons


def test_intraday_crash_rejects():
    sessions = healthy_sessions()
    pre = sessions[-2]['close'][-1]
    sessions[-1] = make_session('20240110', ramp(pre * 1.06, pre * 0.92))
    attach_pre_close(sessions)

    reasons, metrics = evaluate_sessions('600000.SH', sessions)
    assert 'intraday_crash' in reasons
    assert metrics['drawdown'] < -0.10


def test_selling_pressure_rejects():
    sessions = healthy_sessions()
    pre = sessions[-2]['close'][-1]
    # 全天阴跌：每一分钟都是下跌分钟，抛压占比 100%
    sessions[-1] = make_session('20240110', ramp(pre, pre * 0.98))
    attach_pre_close(sessions)

    reasons, metrics = evaluate_sessions('600000.SH', sessions)
    assert 'selling_pressure' in reasons
    assert metrics['down_amount_ratio'] > 0.6


def test_tail_dump_rejects():
    sessions = healthy_sessions()
    pre = sessions[-2]['close'][-1]
    closes = flat_then_drop(pre, pre * 0.98, 30)
    amounts = [1e6] * (BARS - 30) + [1e7] * 30
    sessions[-1] = make_session('20240110', closes, amounts=amounts)
    attach_pre_close(sessions)

    reasons, metrics = evaluate_sessions('600000.SH', sessions)
    assert 'tail_dump' in reasons
    assert metrics['tail_amount_ratio'] > 0.35


def test_high_distribution_rejects():
    sessions = healthy_sessions()
    pre = sessions[-2]['close'][-1]
    closes = ramp(pre, pre * 1.03, 20) + ramp(pre * 1.03, pre * 1.005, BARS - 20)
    amounts = [1e6] * 20 + [5e6] * (BARS - 20)
    sessions[-1] = make_session('20240110', closes, amounts=amounts)
    attach_pre_close(sessions)

    reasons, _ = evaluate_sessions('600000.SH', sessions)
    assert 'high_distribution' in reasons


def test_amount_blowoff_rejects():
    sessions = healthy_sessions()
    pre = sessions[-2]['close'][-1]
    sessions[-1] = make_session('20240110', ramp(pre, pre * 1.01),
                                amounts=[8e6] * BARS)    # 前几日是 1e6/分钟
    attach_pre_close(sessions)

    reasons, metrics = evaluate_sessions('600000.SH', sessions)
    assert 'amount_blowoff' in reasons
    assert metrics['amount_spike'] > 3


def test_sealed_limit_up_is_exempt_from_amount_blowoff():
    """封死涨停的放量不算出货，交给日线的连板规则去拦。"""
    sessions = healthy_sessions()
    pre = sessions[-2]['close'][-1]
    limit_up = round(pre * 1.1, 2)
    closes = ramp(pre, limit_up, 30) + [limit_up] * (BARS - 30)
    sessions[-1] = make_session('20240110', closes, amounts=[8e6] * BARS)
    attach_pre_close(sessions)

    reasons, _ = evaluate_sessions('600000.SH', sessions)
    assert 'amount_blowoff' not in reasons


def test_params_can_disable_intraday_checks():
    sessions = healthy_sessions()
    sessions[-1] = limit_up_touch_session('20240110', pre_close=sessions[-2]['close'][-1])
    attach_pre_close(sessions)

    params = IntradayParams(max_failed_limit_up=None, min_close_position=None,
                            min_vwap_gap=None, max_down_amount_ratio=None,
                            max_drawdown=None, max_post_high_amount_ratio=None)
    reasons, _ = evaluate_sessions('600000.SH', sessions, params)
    assert reasons == []


def test_unknown_intraday_param_raises():
    with pytest.raises(TypeError):
        IntradayParams(tail_window=30)


def test_only_recent_days_are_counted():
    """更早的炸板不再影响今天的决策。"""
    old_bad = limit_up_touch_session('20240101')
    sessions = [old_bad] + healthy_sessions(('20240108', '20240109', '20240110'))
    attach_pre_close(sessions)

    reasons, _ = evaluate_sessions('600000.SH', sessions, IntradayParams(days=3))
    assert 'failed_limit_up' not in reasons


def test_trading_minutes_cover_a_full_session():
    times = trading_minutes('20240110')
    assert len(times) == 240
    assert times[0].endswith('093100') and times[-1].endswith('150000')
