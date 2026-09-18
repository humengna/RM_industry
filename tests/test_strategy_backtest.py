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
    """由收盘价生成一套 open/high/low/preClose/volume/amount/suspendFlag 数据。"""
    pre_close = [closes[0]] + closes[:-1]
    return {
        'close': closes,
        'open': [round(c * 0.995, 2) for c in closes],
        'high': [round(c * 1.01, 2) for c in closes],
        'low': [round(c * 0.99, 2) for c in closes],
        'preClose': pre_close,
        'volume': [1000000] * len(closes),
        'amount': [2e8] * len(closes),
        'suspendFlag': [0] * len(closes),
    }


def build_context(**overrides):
    # 温和上涨（+1.5%/日），既能拿第一名又不会被过热风控否决
    up = [round(10 * (1.015 ** i), 2) for i in range(N_BARS)]
    flat = [10.0] * N_BARS
    down = [round(20 * (0.98 ** i), 2) for i in range(N_BARS)]

    prices = {
        '600001.SH': make_prices(up),
        '600002.SH': make_prices(flat),
        '600003.SH': make_prices(down),
    }
    prices.update(overrides.get('prices', {}))

    sector = overrides.get('sector', sorted(prices.keys()))
    return FakeContext(
        prices=prices,
        dates=DATES,
        sectors={'沪深a股': list(sector)},
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
    module.RISK_ENABLED = False  # 单独验证下单环节的一字涨停判断
    locked = make_prices([round(10 * (1.015 ** i), 2) for i in range(N_BARS)])
    # 最后一根 bar 一字涨停：最低价 = 前收 * 1.1
    locked['low'][-1] = round(locked['preClose'][-1] * 1.1, 2)
    locked['open'][-1] = locked['low'][-1]
    context = build_context(prices={'600001.SH': locked}, sector=['600001.SH'])
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
    for fields, stocks, count, end_time, period in context.market_data_calls:
        assert count >= 1
        assert end_time.endswith('150000')
        assert period in ('1d', '1m')


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


# ---------- 风控：候选顺延 ----------

def limit_up_prices(base_days, streak, start=10.0, ratio=0.10):
    """前面横盘、最后连续涨停的收盘价序列（最后一根是当前 bar，与前一日平)。"""
    closes = [start] * base_days
    for _ in range(streak):
        closes.append(round(closes[-1] * (1 + ratio), 2))
    closes.append(closes[-1])   # 当前 bar
    return closes


def test_limit_up_streak_candidate_is_rejected_and_next_one_taken():
    """连板票分数最高，但应被风控否决，改买排名第二的温和上涨票。"""
    module = load_strategy()
    hot = make_prices(limit_up_prices(N_BARS - 3, 2))
    context = build_context(prices={'600004.SH': hot})
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert module.g.today_target == '600001.SH'
    assert 'limit_up_streak' in module.g.reject_stats
    buys = [o for o in broker.orders if o['op_type'] == module.OP_BUY]
    assert len(buys) == 1 and buys[0]['stock'] == '600001.SH'


def test_hot_stock_is_top_ranked_without_risk_module():
    """关掉风控就会买到那只连板票——说明风控确实是拦截点。"""
    module = load_strategy()
    module.RISK_ENABLED = False
    hot = make_prices(limit_up_prices(N_BARS - 3, 2))
    context = build_context(prices={'600004.SH': hot})
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    buys = [o for o in broker.orders if o['op_type'] == module.OP_BUY]
    assert len(buys) == 1 and buys[0]['stock'] == '600004.SH'


def test_no_order_when_every_candidate_is_rejected():
    module = load_strategy()
    hot = make_prices(limit_up_prices(N_BARS - 3, 2))
    context = build_context(prices={'600004.SH': hot}, sector=['600004.SH'])
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert broker.orders == []
    assert module.g.today_target is None


def test_downtrend_only_pool_is_not_bought():
    """全是下跌票时 weak_momentum 会拦住，不再"矮子里拔将军"。"""
    module = load_strategy()
    context = build_context(sector=['600002.SH', '600003.SH'])
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert broker.orders == []


def test_gap_up_candidate_is_rejected():
    module = load_strategy()
    gapped = make_prices([round(10 * (1.015 ** i), 2) for i in range(N_BARS)])
    gapped['open'][-1] = round(gapped['preClose'][-1] * 1.08, 2)   # 高开 8%
    context = build_context(prices={'600001.SH': gapped}, sector=['600001.SH'])
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert broker.orders == []
    assert 'gap_up' in module.g.reject_stats


# ---------- 风控：大盘 ----------

def index_prices(closes):
    return {'close': closes, 'open': closes, 'high': closes, 'low': closes,
            'preClose': [closes[0]] + closes[:-1]}


def test_weak_market_blocks_new_position():
    module = load_strategy()
    falling = [round(4000 * (0.995 ** i), 2) for i in range(N_BARS)]
    context = build_context(prices={module.MARKET_INDEX: index_prices(falling)})
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert [o for o in broker.orders if o['op_type'] == module.OP_BUY] == []


def test_strong_market_allows_new_position():
    module = load_strategy()
    rising = [round(4000 * (1.002 ** i), 2) for i in range(N_BARS)]
    context = build_context(prices={module.MARKET_INDEX: index_prices(rising)})
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert [o for o in broker.orders if o['op_type'] == module.OP_BUY]


def test_weak_market_exit_all_closes_positions():
    module = load_strategy()
    module.MARKET_FILTER_ACTION = 'exit_all'
    falling = [round(4000 * (0.995 ** i), 2) for i in range(N_BARS)]
    context = build_context(prices={module.MARKET_INDEX: index_prices(falling)})
    broker = FakeBroker(available=0.0,
                        positions=[FakePosition('600001.SH', 1000, 10.0)])
    run_bar(module, context, broker)

    assert len(broker.orders) == 1
    assert broker.orders[0]['op_type'] == module.OP_SELL
    assert '大盘风控' in broker.orders[0]['msg']


# ---------- 风控：持仓 ----------

def test_trailing_stop_exits_after_drawdown_from_peak():
    module = load_strategy()
    context = build_context()
    last_close = context.prices['600001.SH']['close'][-1]
    broker = FakeBroker(available=0.0,
                        positions=[FakePosition('600001.SH', 500, last_close * 0.9)])
    install_fake_qmt(module, context, broker)
    module.init(context)
    module.g.position_peak['600001.SH'] = last_close * 1.5   # 曾经冲高 50%

    module.check_lose_backtest(context, DATES[-1] + '150000')

    assert len(broker.orders) == 1
    assert '移动止损' in broker.orders[0]['msg']
    assert broker.orders[0]['price_type'] == module.PRICE_TYPE_MARKET


def test_trailing_stop_not_triggered_on_small_pullback():
    module = load_strategy()
    context = build_context()
    last_close = context.prices['600001.SH']['close'][-1]
    broker = FakeBroker(available=0.0,
                        positions=[FakePosition('600001.SH', 500, last_close * 0.9)])
    install_fake_qmt(module, context, broker)
    module.init(context)
    module.g.position_peak['600001.SH'] = last_close * 1.05   # 只回撤 5%

    module.check_lose_backtest(context, DATES[-1] + '150000')
    assert broker.orders == []


def test_position_peak_is_tracked_and_cleaned():
    module = load_strategy()
    context = build_context()
    broker = FakeBroker(available=0.0,
                        positions=[FakePosition('600001.SH', 500, 10.0)])
    install_fake_qmt(module, context, broker)
    module.init(context)

    module.update_position_peaks(context, DATES[-1] + '150000')
    assert module.g.position_peak['600001.SH'] == context.prices['600001.SH']['high'][-1]

    broker.positions = []
    module.update_position_peaks(context, DATES[-1] + '150000')
    assert module.g.position_peak == {}


def test_limit_down_locked_position_is_not_sold():
    module = load_strategy()
    closes = [round(20 * (0.98 ** i), 2) for i in range(N_BARS)]
    locked = make_prices(closes)
    # 当前 bar 一字跌停：最高价 = 前收 * 0.9
    locked['high'][-1] = round(locked['preClose'][-1] * 0.9, 2)
    locked['low'][-1] = locked['high'][-1]
    locked['close'][-1] = locked['high'][-1]
    context = build_context(prices={'600003.SH': locked})
    broker = FakeBroker(available=0.0,
                        positions=[FakePosition('600003.SH', 500, 100.0)])
    install_fake_qmt(module, context, broker)
    module.init(context)

    module.check_lose_backtest(context, DATES[-1] + '150000')
    assert broker.orders == []   # 跌停封死，卖不掉


def test_position_risk_runs_even_without_target():
    """今天没选出标的，也必须给已有持仓做止损检查。"""
    module = load_strategy()
    context = build_context(sector=[])       # 股票池为空
    broker = FakeBroker(available=0.0,
                        positions=[FakePosition('600003.SH', 500, 100.0)])
    run_bar(module, context, broker)

    assert len(broker.orders) == 1
    assert '硬止损' in broker.orders[0]['msg']


def test_runs_over_many_bars_without_error():
    """连续跑多根 K 线：状态（分数序列、持仓最高价、否决统计）不应出问题。"""
    module = load_strategy()
    hot = make_prices(limit_up_prices(N_BARS - 3, 2))
    context = build_context(prices={'600004.SH': hot})
    broker = FakeBroker(available=100000.0,
                        positions=[FakePosition('600001.SH', 500, 10.0)])
    install_fake_qmt(module, context, broker)
    module.init(context)

    for i in range(module.WARMUP_BARS - 1, N_BARS):
        context.barpos = i
        module.g.bar_count = i
        module.handlebar(context)

    module.stop(context)
    assert module.g.bar_count == N_BARS
    assert set(module.g.position_peak) <= {'600001.SH'}
    assert module.g.reject_stats


# ---------- 分钟线风控 ----------

from fake_qmt import concat_sessions, minute_session   # noqa: E402

MINUTE_BARS = 240


def minute_path(start, end, bars=MINUTE_BARS):
    step = (end - start) / float(bars - 1)
    return [round(start + step * i, 3) for i in range(bars)]


def smooth_minutes(closes, day_indexes, amounts=None):
    """按日线收盘价生成平滑的分钟线（每天从前收线性走到当日收盘）。"""
    sessions = []
    for i in day_indexes:
        sessions.append(minute_session(DATES[i],
                                       minute_path(closes[i - 1], closes[i]),
                                       amounts=amounts))
    return sessions


def hot_stock_daily():
    """最后三天连续大涨（但没涨停）的日线，用来排到第 1 名。"""
    closes = [10.0] * (N_BARS - 4) + [10.6, 11.24, 11.91, 11.91]
    return closes


def build_hot_context(last_session, extra_days=(N_BARS - 5, N_BARS - 4, N_BARS - 3)):
    """第 1 名是 600005，其最后一个完整交易日的分钟线由调用方指定。"""
    closes = hot_stock_daily()
    sessions = smooth_minutes(closes, list(extra_days))
    sessions.append(last_session)

    context = build_context(prices={'600005.SH': make_prices(closes)})
    context.minutes = {'600005.SH': concat_sessions(sessions)}
    return context


def test_failed_limit_up_candidate_is_rejected_by_minute_data():
    """日线看不出问题（收盘没涨停），分钟线能看到炸板。"""
    module = load_strategy()
    closes = hot_stock_daily()
    pre_close = closes[N_BARS - 3]                 # 11.24
    limit_up = round(pre_close * 1.1, 2)           # 12.36
    path = (minute_path(pre_close, limit_up, 100)
            + minute_path(limit_up, closes[N_BARS - 2], MINUTE_BARS - 100))
    highs = [max(c, limit_up if 95 <= i <= 105 else c) for i, c in enumerate(path)]
    blown = minute_session(DATES[N_BARS - 2], path, highs=highs)

    context = build_hot_context(blown)
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert 'failed_limit_up' in module.g.reject_stats
    assert module.g.today_target == '600001.SH'


def test_tail_selloff_candidate_is_rejected_by_minute_data():
    module = load_strategy()
    closes = hot_stock_daily()
    pre_close = closes[N_BARS - 3]
    level = round(pre_close * 1.09, 2)
    path = [level] * (MINUTE_BARS - 30) + minute_path(level, closes[N_BARS - 2], 30)
    amounts = [1e6] * (MINUTE_BARS - 30) + [1e7] * 30      # 尾盘放量砸盘
    dumped = minute_session(DATES[N_BARS - 2], path, amounts=amounts)

    context = build_hot_context(dumped)
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    rejected = module.g.reject_stats
    assert 'tail_selloff' in rejected or 'tail_dump' in rejected
    assert module.g.today_target == '600001.SH'


def test_clean_minute_data_passes():
    module = load_strategy()
    closes = hot_stock_daily()
    sessions = smooth_minutes(closes, [N_BARS - 5, N_BARS - 4, N_BARS - 3, N_BARS - 2])
    context = build_context(prices={'600005.SH': make_prices(closes)})
    context.minutes = {'600005.SH': concat_sessions(sessions)}
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert module.g.today_target == '600005.SH'
    assert [o['stock'] for o in broker.orders if o['op_type'] == module.OP_BUY] \
        == ['600005.SH']


def test_current_day_minutes_are_not_used():
    """当日分钟线在 09:31 还不存在，即使数据里有也不能参与决策。"""
    module = load_strategy()
    closes = hot_stock_daily()
    sessions = smooth_minutes(closes, [N_BARS - 5, N_BARS - 4, N_BARS - 3, N_BARS - 2])
    # 当日盘中一路砸到跌停——如果被误用，600005 会被否决
    crash = minute_session(DATES[N_BARS - 1],
                           minute_path(closes[N_BARS - 2], closes[N_BARS - 2] * 0.9))
    sessions.append(crash)

    context = build_context(prices={'600005.SH': make_prices(closes)})
    context.minutes = {'600005.SH': concat_sessions(sessions)}
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert module.g.today_target == '600005.SH'


def test_missing_minute_data_is_skipped_by_default():
    module = load_strategy()
    context = build_context()            # 没有任何分钟数据
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert module.g.intraday_warned is True
    assert [o for o in broker.orders if o['op_type'] == module.OP_BUY]


def test_missing_minute_data_rejects_when_required():
    module = load_strategy()
    module.INTRADAY_REQUIRE_DATA = True
    context = build_context()
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert broker.orders == []
    assert module.g.reject_stats.get('intraday_no_data')


def test_intraday_can_be_disabled():
    module = load_strategy()
    module.INTRADAY_ENABLED = False
    closes = hot_stock_daily()
    pre_close = closes[N_BARS - 3]
    limit_up = round(pre_close * 1.1, 2)
    path = (minute_path(pre_close, limit_up, 100)
            + minute_path(limit_up, closes[N_BARS - 2], MINUTE_BARS - 100))
    highs = [max(c, limit_up if 95 <= i <= 105 else c) for i, c in enumerate(path)]
    context = build_hot_context(minute_session(DATES[N_BARS - 2], path, highs=highs))
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert module.g.today_target == '600005.SH'   # 关掉分钟线风控就拦不住了


def test_minute_data_is_fetched_with_1m_period():
    module = load_strategy()
    context = build_context()
    broker = FakeBroker(available=100000.0)
    install_fake_qmt(module, context, broker)
    module.init(context)
    module.g.bar_count = module.WARMUP_BARS - 1
    module.handlebar(context)

    minute_calls = [c for c in context.market_data_calls if c[4] == '1m']
    assert minute_calls, '应当用 period=1m 请求过分钟线'
    fields, _stocks, count, _end, _period = minute_calls[0]
    assert 'amount' in fields and 'close' in fields
    assert count == module.INTRADAY_BARS_PER_DAY * (module.INTRADAY_DAYS + 1)


def test_minute_data_not_fetched_for_daily_rejected_candidate():
    """日线就被否决的候选（连板票）不应再去拉分钟线。"""
    module = load_strategy()
    hot = make_prices(limit_up_prices(N_BARS - 3, 2))
    context = build_context(prices={'600004.SH': hot})
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    minute_stocks = set()
    for _fields, stocks, _count, _end, period in context.market_data_calls:
        if period == '1m':
            minute_stocks.update(stocks)

    assert '600004.SH' not in minute_stocks
    assert '600001.SH' in minute_stocks


# ---------- 风控松紧：扣分制与兜底 ----------

def test_mildly_overheated_candidate_still_passes():
    """只是涨得多、偏离均线，扣分没到上限，仍然可以买。"""
    module = load_strategy()
    # 近 5 日 +30%（超过原来 25% 的口径，但在现在的 40% 之内）
    closes = [10.0] * (N_BARS - 5) + [10.8, 11.6, 12.4, 13.0, 13.0]
    context = build_context(prices={'600006.SH': make_prices(closes)},
                            sector=['600006.SH'])
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert module.g.today_target == '600006.SH'


def test_all_rejected_prints_reason_distribution(capsys):
    module = load_strategy()
    hot = make_prices(limit_up_prices(N_BARS - 3, 2))
    context = build_context(prices={'600004.SH': hot}, sector=['600004.SH'])
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    out = capsys.readouterr().out
    assert '全部否决，原因分布' in out
    assert 'limit_up_streak' in out


def test_fallback_buys_lowest_penalty_candidate():
    module = load_strategy()
    module.RISK_FALLBACK_TO_BEST = True
    gapped = make_prices([round(10 * (1.015 ** i), 2) for i in range(N_BARS)])
    gapped['open'][-1] = round(gapped['preClose'][-1] * 1.08, 2)   # 高开 8%，软否决
    context = build_context(prices={'600001.SH': gapped}, sector=['600001.SH'])
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert module.g.today_target == '600001.SH'
    assert [o for o in broker.orders if o['op_type'] == module.OP_BUY]


def test_fallback_never_buys_hard_rejected_candidate():
    """兜底也不碰连板票——硬否决就是硬否决。"""
    module = load_strategy()
    module.RISK_FALLBACK_TO_BEST = True
    hot = make_prices(limit_up_prices(N_BARS - 3, 2))
    context = build_context(prices={'600004.SH': hot}, sector=['600004.SH'])
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert broker.orders == []


def test_candidate_scan_goes_deeper_than_five():
    """排名前几名全是连板票时，要能一直往下找到能买的那只。"""
    module = load_strategy()
    prices = {}
    sector = []
    for i in range(8):                       # 8 只连板票排在前面
        code = '60010%d.SH' % i
        prices[code] = make_prices(limit_up_prices(N_BARS - 3, 2, start=10.0 + i))
        sector.append(code)
    sector.append('600001.SH')               # 温和上涨的那只排在后面

    context = build_context(prices=prices, sector=sector + ['600001.SH'])
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert module.g.today_target == '600001.SH'
    assert module.g.reject_stats['limit_up_streak'] >= 8


def test_debug_prints_metric_detail(capsys):
    module = load_strategy()
    module.RISK_DEBUG = True
    context = build_context()
    broker = FakeBroker(available=100000.0)
    run_bar(module, context, broker)

    assert '[风控明细]' in capsys.readouterr().out
