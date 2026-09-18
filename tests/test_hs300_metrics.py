# coding: utf-8
"""绩效指标。"""

import pytest

from hs300_ma_divergence import metrics


def equity(totals, start_day=20240102):
    return [{'date': str(start_day + i), 'total': float(t), 'cash': 0.0,
             'market_value': 0.0, 'holdings': 0} for i, t in enumerate(totals)]


def test_total_return():
    assert metrics.total_return(equity([100, 110, 120])) == pytest.approx(0.2)
    assert metrics.total_return([]) == 0.0


def test_daily_returns():
    assert metrics.daily_returns(equity([100, 110, 99])) == pytest.approx([0.1, -0.1])


def test_annualized_return_scales_with_length():
    one_year = equity([100] * 244 + [120])
    assert metrics.annualized_return(one_year) == pytest.approx(0.2, rel=1e-2)


def test_max_drawdown_reports_range():
    drawdown, start, end = metrics.max_drawdown(equity([100, 120, 90, 110]))
    assert drawdown == pytest.approx(90 / 120 - 1)
    assert start == '20240103' and end == '20240104'


def test_no_drawdown_on_monotonic_curve():
    drawdown, _start, _end = metrics.max_drawdown(equity([100, 110, 120]))
    assert drawdown == 0.0


def test_volatility_and_sharpe_zero_for_flat_curve():
    flat = equity([100] * 10)
    assert metrics.volatility(flat) == pytest.approx(0.0)
    assert metrics.sharpe(flat) == 0.0


def test_sharpe_positive_for_rising_noisy_curve():
    curve = equity([100, 101, 100.5, 102, 103, 102.5, 104, 105])
    assert metrics.sharpe(curve) > 0


def test_round_trips_pair_buys_and_sells():
    trades = [
        {'date': '20240102', 'stock': 'A.SH', 'side': 'BUY', 'amount': 10000.0,
         'fee': 5.0, 'volume': 1000},
        {'date': '20240105', 'stock': 'A.SH', 'side': 'SELL', 'amount': 12000.0,
         'fee': 15.0, 'volume': 1000},
    ]
    closed = metrics.round_trips(trades)
    assert len(closed) == 1
    assert closed[0]['pnl'] == pytest.approx(12000 - 15 - 10005)
    assert closed[0]['buy_date'] == '20240102' and closed[0]['sell_date'] == '20240105'


def test_round_trips_handles_partial_sell():
    trades = [
        {'date': '20240102', 'stock': 'A.SH', 'side': 'BUY', 'amount': 10000.0,
         'fee': 0.0, 'volume': 1000},
        {'date': '20240105', 'stock': 'A.SH', 'side': 'SELL', 'amount': 6000.0,
         'fee': 0.0, 'volume': 500},
    ]
    closed = metrics.round_trips(trades)
    assert closed[0]['volume'] == 500
    assert closed[0]['pnl'] == pytest.approx(1000.0)


def test_round_trips_ignores_sell_without_position():
    trades = [{'date': '20240105', 'stock': 'A.SH', 'side': 'SELL', 'amount': 100.0,
               'fee': 0.0, 'volume': 100}]
    assert metrics.round_trips(trades) == []


def test_summarize_and_format():
    result = {
        'equity': equity([100000, 110000, 105000]),
        'trades': [
            {'date': '20240102', 'stock': 'A.SH', 'side': 'BUY', 'amount': 50000.0,
             'fee': 12.5, 'volume': 5000},
            {'date': '20240104', 'stock': 'A.SH', 'side': 'SELL', 'amount': 55000.0,
             'fee': 68.0, 'volume': 5000},
        ],
        'init_cash': 100000.0,
        'final_total': 105000.0,
        'skipped': {'停牌': 3},
    }
    summary = metrics.summarize(result)

    assert summary['trade_count'] == 2 and summary['round_trips'] == 1
    assert summary['win_rate'] == pytest.approx(1.0)
    assert summary['total_fee'] == pytest.approx(80.5)

    text = metrics.format_summary(summary)
    assert '最大回撤' in text and '停牌×3' in text
