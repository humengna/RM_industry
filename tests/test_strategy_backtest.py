# coding: utf-8
"""用模拟的 QMT 环境跑通 qmt/strategy_backtest.py 的完整流程。"""

import importlib.util
import os

import pytest

from fake_qmt import FakeContext, FakeBroker, FakePosition, install_fake_qmt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, 'qmt', 'strategy_backtest.py')

N_BARS = 40
DATES = ['2024%02d%02d' % (1 + i // 28, 1 + i % 28) for i in range(N_BARS)]


def load_strategy():
    """每个用例都重新加载一次，避免全局状态 g 串味。"""
    spec = importlib.util.spec_from_file_location('strategy_backtest_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_prices(closes):
    """由收盘价生成一套 open/low/preClose/suspendFlag 数据。"""
    pre_close = [closes[0]] + closes[:-1]
    return {
        'close': closes,
        'open': [round(c * 0.995, 2) for c in closes],
        'high': [round(c * 1.01, 2) for c in closes],
        'low': [round(c * 0.99, 2) for c in closes],
        'preClose': pre_close,
        'suspendFlag': [0] * len(closes),
    }


def build_context(**overrides):
    up = [round(10 * (1.02 ** i), 2) for i in range(N_BARS)]
    flat = [10.0] * N_BARS
    down = [round(20 * (0.98 ** i), 2) for i in range(N_BARS)]

    prices = {
        '600001.SH': make_prices(up),
        '600002.SH': make_prices(flat),
        '600003.SH': make_prices(down),
    }
    prices.update(overrides.get('prices', {}))

    return FakeContext(
        prices=prices,
        dates=DATES,
        sectors={'沪深a股': ['600001.SH', '600002.SH', '600003.SH']},
        names={'600001.SH': '强势股', '600002.SH': '横盘股', '600003.SH': '弱势股'},
    )


def run_bar(module, context, broker, bar_count=None):
    install_fake_qmt(module, context, broker)
    module.init(context)
    module.g.bar_count = (bar_count if bar_count is not None else module.WARMUP_BARS) - 1
    module.handlebar(context)


# ---------- 选股 ----------

def test_picks_strongest_momentum_stock():
    module = load_strategy()
    context = build_context()
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert module.g.today_target == '600001.SH'


def test_warmup_bars_are_skipped():
    module = load_strategy()
    context = build_context()
    broker = FakeBroker(available=100000.0)
    install_fake_qmt(module, context, broker)
    module.init(context)
    module.g.bar_count = 0
    module.handlebar(context)  # bar_count 变成 1，小于 WARMUP_BARS

    assert broker.orders == []
    assert module.g.today_target is None


def test_pool_excludes_st_and_out_of_range_market_cap():
    module = load_strategy()
    context = build_context()
    context.details = {
        '600001.SH': {'InstrumentName': 'ST强势', 'TotalValue': 100e8},
        '600002.SH': {'InstrumentName': '横盘股', 'TotalValue': 10e8},   # 市值过小
        '600003.SH': {'InstrumentName': '弱势股', 'TotalValue': 100e8},
    }
    broker = FakeBroker(available=100000.0)
    install_fake_qmt(module, context, broker)
    module.init(context)

    pool = module.get_stock_pool(context, DATES[-1] + '150000')
    assert pool == ['600003.SH']


def test_pool_excludes_suspended_stock():
    module = load_strategy()
    suspended = make_prices([round(10 * (1.02 ** i), 2) for i in range(N_BARS)])
    suspended['suspendFlag'] = [0] * (N_BARS - 1) + [1]
    context = build_context(prices={'600001.SH': suspended})
    broker = FakeBroker(available=100000.0)
    install_fake_qmt(module, context, broker)
    module.init(context)

    pool = module.get_stock_pool(context, DATES[-1] + '150000')
    assert '600001.SH' not in pool


def test_current_bar_does_not_affect_selection():
    """把当前 bar 的价格拉到天上，选股结果必须不变（无未来函数）。"""
    module = load_strategy()
    spiked = make_prices([10.0] * (N_BARS - 1) + [999.0])
    context = build_context(prices={'600002.SH': spiked})
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert module.g.today_target == '600001.SH'


# ---------- 下单 ----------

def test_buy_order_uses_open_price_and_whole_lots():
    module = load_strategy()
    context = build_context()
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    buys = [o for o in broker.orders if o['op_type'] == module.OP_BUY]
    assert len(buys) == 1
    order = buys[0]
    open_price = context.prices['600001.SH']['open'][-1]
    assert order['stock'] == '600001.SH'
    assert order['price'] == pytest.approx(open_price)
    assert order['price_type'] == module.PRICE_TYPE_LIMIT
    assert order['volume'] % 100 == 0
    assert order['volume'] == int(100000.0 / open_price / 100) * 100


def test_holding_target_is_kept_without_new_order():
    module = load_strategy()
    context = build_context()
    broker = FakeBroker(available=100000.0,
                        positions=[FakePosition('600001.SH', 1000, 10.0)])
    run_bar(module, context, broker)

    assert broker.orders == []


def test_switching_target_sells_old_then_buys_new():
    module = load_strategy()
    context = build_context()
    broker = FakeBroker(available=100000.0,
                        positions=[FakePosition('600003.SH', 500, 20.0)])
    run_bar(module, context, broker)

    kinds = [o['op_type'] for o in broker.orders]
    assert kinds[0] == module.OP_SELL and broker.orders[0]['stock'] == '600003.SH'
    assert module.OP_BUY in kinds


def test_sell_signal_clears_all_positions():
    module = load_strategy()
    context = build_context()
    broker = FakeBroker(available=0.0,
                        positions=[FakePosition('600003.SH', 500, 20.0)])
    install_fake_qmt(module, context, broker)
    module.init(context)
    module.g.score_history = {'600001.SH': [5.0, 4.0, 3.0]}

    bar_date = DATES[-1] + '150000'
    assert module.get_timing_signal('600001.SH', context, bar_date) == 'SELL'

    module.adjust_position('600001.SH', 'SELL', context, bar_date)
    assert len(broker.orders) == 1
    assert broker.orders[0]['op_type'] == module.OP_SELL
    assert broker.orders[0]['stock'] == '600003.SH'
    assert broker.orders[0]['volume'] == 500


def test_no_buy_when_cash_below_one_lot():
    module = load_strategy()
    context = build_context()
    broker = FakeBroker(available=100.0)
    run_bar(module, context, broker)

    assert [o for o in broker.orders if o['op_type'] == module.OP_BUY] == []


def test_no_buy_when_locked_at_limit_up():
    module = load_strategy()
    locked = make_prices([round(10 * (1.02 ** i), 2) for i in range(N_BARS)])
    # 最后一根 bar 一字涨停：最低价 = 前收 * 1.1
    locked['low'][-1] = round(locked['preClose'][-1] * 1.1, 2)
    locked['open'][-1] = locked['low'][-1]
    context = build_context(prices={'600001.SH': locked})
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert broker.orders == []


# ---------- 止损 ----------

def test_stop_loss_clears_position_at_market_price():
    module = load_strategy()
    context = build_context()
    # 成本 100，最新收盘远低于 -15%
    broker = FakeBroker(available=0.0,
                        positions=[FakePosition('600003.SH', 500, 100.0)])
    install_fake_qmt(module, context, broker)
    module.init(context)

    module.check_lose_backtest(context, DATES[-1] + '150000')

    assert len(broker.orders) == 1
    order = broker.orders[0]
    assert order['op_type'] == module.OP_SELL
    assert order['price_type'] == module.PRICE_TYPE_MARKET
    assert order['price'] == -1
    assert '硬止损' in order['msg']


def test_stop_loss_not_triggered_within_threshold():
    module = load_strategy()
    context = build_context()
    last_close = context.prices['600001.SH']['close'][-1]
    broker = FakeBroker(available=0.0,
                        positions=[FakePosition('600001.SH', 500, last_close / 0.95)])
    install_fake_qmt(module, context, broker)
    module.init(context)

    module.check_lose_backtest(context, DATES[-1] + '150000')
    assert broker.orders == []


# ---------- 数据读取 ----------

def test_all_market_data_calls_are_local_and_bounded():
    module = load_strategy()
    context = build_context()
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert context.market_data_calls, '应当读取过行情'
    for fields, stocks, count, end_time in context.market_data_calls:
        assert count >= 1
        assert end_time.endswith('150000')


def test_rsrs_returns_none_when_history_too_short():
    module = load_strategy()
    context = build_context()
    broker = FakeBroker(available=100000.0)
    install_fake_qmt(module, context, broker)
    module.init(context)

    assert module.calc_rsrs(context, DATES[-1] + '150000') is None


def test_rsrs_computed_when_history_is_long_enough():
    module = load_strategy()
    n_bars = module.RSRS_M + module.RSRS_N + 5
    dates = ['%d%02d%02d' % (2000 + i // 336, 1 + (i // 28) % 12, 1 + i % 28)
             for i in range(n_bars)]
    lows = [100.0 + 0.05 * i for i in range(n_bars)]
    index_prices = {
        'high': [l + 1.0 + 0.001 * i for i, l in enumerate(lows)],
        'low': lows,
    }
    context = FakeContext(prices={module.RSRS_INDEX: index_prices}, dates=dates)
    broker = FakeBroker()
    install_fake_qmt(module, context, broker)
    module.init(context)

    score = module.calc_rsrs(context, dates[-1] + '150000')
    assert score is not None
    assert isinstance(score, float)
