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


def test_dump_constituents_works_on_empty_data_dir(tmp_path):
    """本地还没有任何行情时，--dump-constituents 也要能跑（自动补下载指数）。"""
    from fake_xtdata import FakeXtdata

    full = build_xt()
    index_bars = full.bars.pop('000300.SH')
    xt = FakeXtdata(full.bars, SECTORS, pending_bars={'000300.SH': index_bars})

    path = str(tmp_path / 'hs300.csv')
    provider = dump_constituents(BACKTEST_START, BACKTEST_END, xt=xt, cache_file=path)

    assert '000300.SH' in xt.downloaded
    assert provider.all_members()


# ---------- 持仓数量可配置 ----------

@pytest.mark.parametrize('holdings', [1, 2, 3, 5])
def test_max_holdings_is_configurable(tmp_path, holdings):
    result, _summary, _files = run(tmp_path, max_holdings=holdings)
    assert max(row['holdings'] for row in result['equity']) <= holdings


def test_target_weight_follows_holdings(tmp_path):
    """单只目标仓位 = 1 / 持仓数，并受 MAX_POSITION_WEIGHT 上限约束。"""
    from hs300_ma_divergence.engine import Backtest

    for holdings, expected in [(2, 0.5), (4, 0.25), (10, 0.1)]:
        backtest = Backtest({}, [], None, max_holdings=holdings)
        assert backtest.target_weight == pytest.approx(expected)


def test_holdings_printed_at_startup(tmp_path, capsys):
    run(tmp_path, max_holdings=3)
    out = capsys.readouterr().out
    assert '持仓 3 只' in out
    assert '33.3%' in out


def test_single_holding_still_capped_by_max_weight(tmp_path, capsys):
    run(tmp_path, max_holdings=1)
    out = capsys.readouterr().out
    assert '持仓 1 只' in out
    assert '受上限' in out          # 1/1=100% 被 50% 上限压下来


def test_invalid_holdings_rejected(tmp_path):
    with pytest.raises(ValueError) as excinfo:
        run(tmp_path, max_holdings=0)
    assert '必须 >= 1' in str(excinfo.value)


# ---------- 排名区间 ----------

def test_rank_range_parsing():
    from hs300_ma_divergence.run import parse_rank_range

    assert parse_rank_range('3-5') == (3, 3)
    assert parse_rank_range('1-2') == (1, 2)
    assert parse_rank_range('4') == (4, 1)

    for bad in ('0-3', '5-2', '-1'):
        with pytest.raises(ValueError):
            parse_rank_range(bad)


def test_rank_start_shifts_the_picked_stocks(tmp_path):
    """同一天，取倒序第 1 名和第 2 名应当是不同的票。"""
    first, _s1, _f1 = run(tmp_path, ascending=False, max_holdings=1, rank_start=1)
    second, _s2, _f2 = run(tmp_path, ascending=False, max_holdings=1, rank_start=2)

    def targets(result):
        return {row['date']: tuple(row['target']) for row in result['daily_signals']
                if row['candidates'] >= 2}

    a, b = targets(first), targets(second)
    shared = set(a) & set(b)
    assert shared, '需要有候选数 >= 2 的交易日'
    assert all(a[day] != b[day] for day in shared), '第 1 名和第 2 名不可能相同'


def test_rank_start_beyond_candidates_means_no_position(tmp_path):
    """候选不够时当天不开仓：排名起点设到 50，整段回测应该一笔都不成交。"""
    result, _summary, _files = run(tmp_path, max_holdings=2, rank_start=50)
    assert result['trades'] == []
    assert all(row['target'] == [] for row in result['daily_signals'])


def test_rank_start_printed_at_startup(tmp_path, capsys):
    run(tmp_path, ascending=False, max_holdings=3, rank_start=3)
    out = capsys.readouterr().out
    assert '发散度倒序第 3~5 名' in out


def test_rank_range_recorded_in_summary(tmp_path):
    _result, _summary, files = run(tmp_path, max_holdings=3, rank_start=3)
    with open(files['summary'], encoding='utf-8') as fp:
        text = fp.read()
    assert 'rank_range' in text and '3-5' in text


def test_invalid_rank_start_rejected(tmp_path):
    with pytest.raises(ValueError) as excinfo:
        run(tmp_path, rank_start=0)
    assert '排名起点' in str(excinfo.value)
