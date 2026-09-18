# coding: utf-8
"""回测引擎：T+1 撮合、费用、涨跌停与停牌限制。"""

import pytest

from hs300_ma_divergence.data import Bars
from hs300_ma_divergence.engine import (
    Backtest, Portfolio, buy_cost, limit_prices, limit_ratio, sell_cost, target_volume,
)

DAYS = ['20240102', '20240103', '20240104', '20240105', '20240108']


def bars_from(stock, days, closes, opens=None, highs=None, lows=None):
    values = {
        'close': list(closes),
        'open': list(opens) if opens else [round(c * 0.99, 3) for c in closes],
        'high': list(highs) if highs else [round(c * 1.02, 3) for c in closes],
        'low': list(lows) if lows else [round(c * 0.98, 3) for c in closes],
    }
    return Bars(stock, list(days), values)


class FixedProvider(object):
    """按日期给定成分股/目标的桩。"""

    def __init__(self, members):
        self.members = members

    def members_on(self, day):
        return list(self.members)


class ScriptedBacktest(Backtest):
    """
    选股结果由脚本指定，便于单独验证撮合环节。

    脚本是"粘性"的：某天没写就沿用上一次的目标组合，写成 [] 表示清仓。
    """

    def __init__(self, *args, **kwargs):
        self.script = kwargs.pop('script', {})
        self._last_target = []
        super(ScriptedBacktest, self).__init__(*args, **kwargs)

    def select(self, day, need):
        if day in self.script:
            self._last_target = list(self.script[day])
        target = [{'stock': s, 'score': 0.0, 'spreads': [0, 0, 0, 0]}
                  for s in self._last_target]
        return target, target


def build(script, bars, cash=100000.0, **kwargs):
    return ScriptedBacktest(bars, DAYS, FixedProvider(sorted(bars)), init_cash=cash,
                            verbose=False, script=script, **kwargs)


# ---------- 基础计算 ----------

def test_limit_ratio_by_board():
    assert limit_ratio('600000.SH') == 0.10
    assert limit_ratio('300750.SZ') == 0.20
    assert limit_ratio('688981.SH') == 0.20


def test_limit_prices_rounding():
    assert limit_prices('600000.SH', 10.0) == (11.0, 9.0)
    assert limit_prices('600000.SH', 0) == (0.0, 0.0)


def test_costs():
    # 佣金万2.5、最低5元；卖出多千1印花税
    assert buy_cost(100000) == pytest.approx(100000 * 0.00025 + 100000 * 0.00001)
    assert buy_cost(1000) == pytest.approx(5.0 + 1000 * 0.00001)
    assert sell_cost(100000) == pytest.approx(
        100000 * 0.00025 + 100000 * 0.00001 + 100000 * 0.001)


def test_target_volume_matches_original_formula():
    # min(总资产*20%, 可用/待买数) * 0.98 / 价格，向下取整到手
    assert target_volume(100000, 500000, 10.0, 5) == 1900
    assert target_volume(100000, 500000, 10.0, 1) == 9800
    assert target_volume(500, 500000, 10.0, 1) == 0        # 不足一手


# ---------- 撮合 ----------

def test_signal_executes_at_next_day_open():
    """T 日收盘选出的票，在 T+1 开盘成交，成交价是次日开盘价。"""
    bars = {'600000.SH': bars_from('600000.SH', DAYS, [10, 11, 12, 13, 14])}
    backtest = build({DAYS[0]: ['600000.SH']}, bars)
    backtest.run()

    assert len(backtest.trades) == 1
    trade = backtest.trades[0]
    assert trade['side'] == 'BUY'
    assert trade['signal_date'] == DAYS[0]
    assert trade['date'] == DAYS[1]
    assert trade['price'] == pytest.approx(bars['600000.SH'].field_on(DAYS[1], 'open'))


def test_position_is_not_sold_on_the_buy_day():
    """T+1：当天买入的票当天不能卖，等下一个交易日。"""
    bars = {'600000.SH': bars_from('600000.SH', DAYS, [10, 11, 12, 13, 14])}
    backtest = build({DAYS[0]: ['600000.SH'], DAYS[1]: []}, bars)
    backtest.run()

    sells = [t for t in backtest.trades if t['side'] == 'SELL']
    assert len(sells) == 1
    assert sells[0]['date'] == DAYS[2]          # 买入在 DAYS[1]，卖出顺延到 DAYS[2]


def test_cash_reflects_amount_plus_fee():
    bars = {'600000.SH': bars_from('600000.SH', DAYS, [10, 10, 10, 10, 10])}
    backtest = build({DAYS[0]: ['600000.SH']}, bars, cash=100000.0)
    backtest.run()

    trade = backtest.trades[0]
    expected = 100000.0 - trade['amount'] - trade['fee']
    assert backtest.portfolio.cash == pytest.approx(expected)
    assert trade['fee'] > 0


def test_limit_up_blocks_buy():
    closes = [10, 11, 12, 13, 14]
    lows = [c * 0.98 for c in closes]
    lows[1] = round(10 * 1.1, 2)                # 次日一字涨停
    opens = [round(c * 0.99, 3) for c in closes]
    opens[1] = lows[1]
    bars = {'600000.SH': bars_from('600000.SH', DAYS, closes, opens=opens, lows=lows,
                                   highs=[max(c * 1.02, lows[1]) for c in closes])}
    backtest = build({DAYS[0]: ['600000.SH']}, bars)
    backtest.run()

    assert backtest.skipped.get('一字涨停买不进', 0) >= 1
    # 涨停当天买不进，次日才成交
    assert [t['date'] for t in backtest.trades] == [DAYS[2]]


def test_limit_down_blocks_sell():
    closes = [10.0, 10.0, 9.0, 9.0, 9.0]
    highs = [c * 1.02 for c in closes]
    highs[2] = round(10.0 * 0.9, 2)             # 卖出当日一字跌停
    bars = {'600000.SH': bars_from('600000.SH', DAYS, closes, highs=highs)}
    backtest = build({DAYS[0]: ['600000.SH'], DAYS[1]: []}, bars)
    backtest.run()

    assert backtest.skipped.get('一字跌停卖不掉', 0) >= 1
    sells = [t for t in backtest.trades if t['side'] == 'SELL']
    assert [t['date'] for t in sells] == [DAYS[3]]   # 跌停当天没卖成，顺延一天


def test_suspended_stock_is_skipped():
    """停牌日没有 K 线，既买不进也卖不出。"""
    partial_days = [DAYS[0], DAYS[2], DAYS[3], DAYS[4]]     # 缺 DAYS[1]
    bars = {'600000.SH': bars_from('600000.SH', partial_days, [10, 10, 10, 10])}
    backtest = build({DAYS[0]: ['600000.SH']}, bars)
    backtest.run()

    assert backtest.skipped.get('停牌', 0) >= 1
    assert [t['date'] for t in backtest.trades] == [DAYS[2]]   # 复牌后才买进


def test_rebalance_replaces_holdings():
    bars = {
        '600000.SH': bars_from('600000.SH', DAYS, [10, 10, 10, 10, 10]),
        '600001.SH': bars_from('600001.SH', DAYS, [20, 20, 20, 20, 20]),
    }
    backtest = build({DAYS[0]: ['600000.SH'], DAYS[2]: ['600001.SH']}, bars)
    backtest.run()

    sides = [(t['date'], t['side'], t['stock']) for t in backtest.trades]
    assert sides[0] == (DAYS[1], 'BUY', '600000.SH')
    assert (DAYS[3], 'SELL', '600000.SH') in sides
    assert (DAYS[3], 'BUY', '600001.SH') in sides
    assert list(backtest.portfolio.positions) == ['600001.SH']


def test_max_holdings_is_respected():
    bars = {'60000%d.SH' % i: bars_from('60000%d.SH' % i, DAYS, [10] * 5) for i in range(8)}
    backtest = build({DAYS[0]: sorted(bars)[:5]}, bars, max_holdings=5)
    backtest.run()

    assert len(backtest.portfolio.positions) == 5


def test_equity_curve_marks_to_close():
    bars = {'600000.SH': bars_from('600000.SH', DAYS, [10, 10, 12, 12, 12])}
    backtest = build({DAYS[0]: ['600000.SH']}, bars, cash=100000.0)
    backtest.run()

    assert len(backtest.equity) == len(DAYS)
    assert backtest.equity[0]['total'] == pytest.approx(100000.0)
    # 买入后价格从 10 涨到 12，总资产应上升
    assert backtest.equity[-1]['total'] > backtest.equity[1]['total']
    assert backtest.equity[-1]['holdings'] == 1


def test_portfolio_values_suspended_position_at_last_price():
    bars = {'600000.SH': bars_from('600000.SH', [DAYS[0], DAYS[1]], [10, 11])}
    portfolio = Portfolio(0.0)
    portfolio.positions['600000.SH'] = {'volume': 100, 'available': 100,
                                        'cost': 10.0, 'buy_day': DAYS[0]}

    assert portfolio.market_value(bars, DAYS[1]) == pytest.approx(1100.0)
    assert portfolio.market_value(bars, DAYS[3]) == pytest.approx(1100.0)


def test_insufficient_cash_is_recorded():
    bars = {'600000.SH': bars_from('600000.SH', DAYS, [10] * 5)}
    backtest = build({DAYS[0]: ['600000.SH']}, bars, cash=100.0)
    backtest.run()

    assert backtest.trades == []
    assert backtest.skipped.get('资金不足', 0) >= 1


def test_slippage_moves_price_against_you():
    bars = {'600000.SH': bars_from('600000.SH', DAYS, [10] * 5)}
    backtest = build({DAYS[0]: ['600000.SH']}, bars, slippage=0.01)
    backtest.run()

    open_price = bars['600000.SH'].field_on(DAYS[1], 'open')
    assert backtest.trades[0]['price'] == pytest.approx(open_price * 1.01)
