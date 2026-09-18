# coding: utf-8
"""端到端：用模拟的 xtdata 跑通完整回测流程。"""

import os

import pytest

from fake_xtdata import (
    FakeXtdata, accelerating_series, flat_series, linear_series, make_bars, trading_days,
)

from hs300_ma_divergence import metrics
from hs300_ma_divergence.run import dump_constituents, run_backtest, shift_date

DAYS = trading_days(2024, 200)
BACKTEST_START = DAYS[120]          # 前面 120 天留给 MA60 热身
BACKTEST_END = DAYS[-1]

SECTORS = {
    '沪深300': [
        ('20240101', ['000001.SZ', '600000.SH', '600001.SH', '600002.SH']),
        (DAYS[150], ['000001.SZ', '600000.SH', '600002.SH', '600003.SH']),
    ]
}


def build_xt():
    """两只加速上涨（会触发信号）、两只匀速、两只横盘，外加指数。"""
    bars = {
        '000300.SH': make_bars(DAYS, linear_series(DAYS, base=3800, step=1.0)),
        '600000.SH': make_bars(DAYS, accelerating_series(DAYS, base=10, accel=0.00005)),
        '600001.SH': make_bars(DAYS, accelerating_series(DAYS, base=20, accel=0.00008)),
        '600002.SH': make_bars(DAYS, linear_series(DAYS, base=15)),
        '600003.SH': make_bars(DAYS, accelerating_series(DAYS, base=8, accel=0.00006)),
        '000001.SZ': make_bars(DAYS, flat_series(DAYS, base=12)),
    }
    return FakeXtdata(bars, SECTORS)


def run(tmp_path, **kwargs):
    params = dict(start=BACKTEST_START, end=BACKTEST_END, cash=1000000.0,
                  xt=build_xt(), cache_file=str(tmp_path / 'hs300.csv'),
                  output_dir=str(tmp_path / 'out'), verbose=False)
    params.update(kwargs)
    return run_backtest(**params)


# ---------- 主流程 ----------

def test_backtest_produces_equity_trades_and_files(tmp_path):
    result, summary, files = run(tmp_path)

    assert len(result['equity']) > 0
    assert result['trades'], '加速上涨的票应该被选出来并成交'
    assert summary['trading_days'] == len(result['equity'])
    for name in ('summary', 'equity', 'trades', 'round_trips', 'signals'):
        assert os.path.exists(files[name])


def test_equity_starts_at_init_cash(tmp_path):
    result, _summary, _files = run(tmp_path, cash=500000.0)
    assert result['equity'][0]['total'] == pytest.approx(500000.0)


def test_holdings_never_exceed_max(tmp_path):
    result, _summary, _files = run(tmp_path, max_holdings=2)
    assert max(row['holdings'] for row in result['equity']) <= 2


def test_trades_happen_one_day_after_signal(tmp_path):
    result, _summary, _files = run(tmp_path)
    days = result['equity']
    order = [row['date'] for row in days]

    for trade in result['trades']:
        assert order.index(trade['date']) == order.index(trade['signal_date']) + 1


def test_point_in_time_universe_is_used(tmp_path):
    """6 月调入的 600003 在调整前不该出现在任何目标组合里。"""
    result, _summary, _files = run(tmp_path)

    for row in result['daily_signals']:
        if row['date'] < DAYS[150]:
            assert '600003.SH' not in row['target']

    later = [row for row in result['daily_signals'] if row['date'] >= DAYS[150]]
    assert any('600003.SH' in row['target'] for row in later), '调入后应能被选中'


def test_ascending_and_descending_pick_different_stocks(tmp_path):
    """
    原脚本 reverse=True 被注释掉，实际取发散度最小的；--descending 取最大的。
    只留 1 个持仓名额，两种排序就能看出差别。
    """
    ascending, _s1, _f1 = run(tmp_path, ascending=True, max_holdings=1)
    descending, _s2, _f2 = run(tmp_path, ascending=False, max_holdings=1)

    def targets_by_day(result):
        return {row['date']: tuple(row['target']) for row in result['daily_signals']
                if row['candidates'] >= 2}

    asc = targets_by_day(ascending)
    desc = targets_by_day(descending)
    shared = set(asc) & set(desc)

    assert shared, '应该存在候选数 >= 2 的交易日'
    assert any(asc[day] != desc[day] for day in shared)


def test_download_is_requested_when_asked(tmp_path):
    xt = build_xt()
    run(tmp_path, xt=xt, download=True)
    assert '000300.SH' in xt.downloaded
    assert '600000.SH' in xt.downloaded


def test_summary_metrics_are_consistent(tmp_path):
    result, summary, _files = run(tmp_path)

    assert summary['final_total'] == pytest.approx(result['equity'][-1]['total'])
    assert summary['total_return'] == pytest.approx(
        metrics.total_return(result['equity']))
    assert summary['max_drawdown'] <= 0


def test_no_files_written_when_disabled(tmp_path):
    _result, _summary, files = run(tmp_path, write_files=False)
    assert files == {}


def test_dump_constituents_writes_cache(tmp_path):
    path = str(tmp_path / 'only_constituents.csv')
    provider = dump_constituents(BACKTEST_START, BACKTEST_END, xt=build_xt(),
                                 cache_file=path)

    assert os.path.exists(path)
    assert provider.all_members()


def test_shift_date():
    assert shift_date('20240301', 1) == '20240229'      # 闰年
    assert shift_date('20240101', 1) == '20231231'
