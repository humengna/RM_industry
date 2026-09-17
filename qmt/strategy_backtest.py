# coding: utf-8
"""
A股股票策略 [回测版]：热门概念池 + 对数线性回归动量打分 + RSRS修正标准分大盘择时
                       + 动量分数连续下降个股择时 + 固定 -15% 硬止损

与实盘版的主要区别：
  1. 使用 handlebar 逐K线驱动，替代 run_time 定时任务
  2. get_market_data_ex 设置 subscribe=False，读取本地数据
  3. 用 get_market_data_ex 替代 get_full_tick 获取当前价格
  4. 回测使用模拟资金账号（config.BACKTEST_ACCOUNT）
  5. 止损使用当日收盘价判断（回测无法区分 14:50 盘中价）
  6. 选股只用当前 K 线之前的数据，避免未来函数

运行方式：
  A. 项目方式：把整个项目目录放到本机，设置下面的 PROJECT_ROOT，
     在 QMT 客户端 -> 回测 -> 选择主图品种（如沪深300）-> 设置回测参数 -> 运行
  B. 单文件方式：python tools/bundle_qmt.py 生成 dist/momentum_timing_qmt.py，
     直接把该文件贴进 QMT（无需配置 PROJECT_ROOT）
"""

# --BUNDLE-STRIP-START--
import os
import sys

# 项目根目录（即 momentum_timing 的上一级目录）。
# 留空则自动按 __file__ 推断；QMT 里若推断不到，请手工填写，例如：
# PROJECT_ROOT = r'D:\quant\RM_industry'
PROJECT_ROOT = r''


def _bootstrap_sys_path():
    """把项目根目录加入 sys.path，保证能 import momentum_timing。"""
    candidates = []
    if PROJECT_ROOT:
        candidates.append(PROJECT_ROOT)
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.dirname(here))
    except NameError:
        pass
    candidates.append(os.getcwd())

    for root in candidates:
        if root and os.path.isdir(os.path.join(root, 'momentum_timing')):
            if root not in sys.path:
                sys.path.insert(0, root)
            return root
    return None


_bootstrap_sys_path()

from momentum_timing.config import (
    ACCOUNT_TYPE, BACKTEST_ACCOUNT, CONCEPT_SECTORS, DECLINE_DAYS_TO_SELL,
    LOOKBACK_DAYS, MAX_MARKET_CAP, MIN_MARKET_CAP, RSRS_ENABLED, RSRS_INDEX,
    RSRS_M, RSRS_N, SCORE_HISTORY_DAYS, STOP_LOSS_RATIO, STRATEGY_NAME,
    TRADING_DAYS_PER_YEAR, WARMUP_BARS,
)
from momentum_timing.indicators import rsrs_corrected_zscore
from momentum_timing.portfolio import buy_volume, can_buy
from momentum_timing.scoring import (
    bars_needed_for_history, bars_needed_for_rank, momentum_score_history, rank_pool,
)
from momentum_timing.signals import (
    SIGNAL_KEEP, SIGNAL_SELL, profit_ratio, stop_loss_triggered, timing_signal,
)
from momentum_timing.universe import limit_prices, passes_filters
# --BUNDLE-STRIP-END--


# ============================================================
# QMT 下单常量
# ============================================================
OP_BUY = 23               # 股票买入
OP_SELL = 24              # 股票卖出
ORDER_BY_VOLUME = 1101    # 按股数下单
PRICE_TYPE_MARKET = 5     # 市价（最优五档剩余撤销）
PRICE_TYPE_LIMIT = 11     # 指定价


# ============================================================
# 全局变量：保存跨 bar 的状态
# ============================================================
class G(object):
    pass


g = G()


# ============================================================
# 系统函数
# ============================================================

def init(C):
    """回测初始化"""
    g.account = BACKTEST_ACCOUNT
    g.acct_type = ACCOUNT_TYPE
    g.score_history = {}      # {股票: 近 N 日动量分数序列}
    g.today_target = None     # 今日目标股票
    g.bar_count = 0           # 已处理 bar 计数

    print('[动量择时策略-回测版] 初始化完成')
    print('  回测账号: %s, 类型: %s' % (g.account, g.acct_type))
    print('  板块数: %d' % len(CONCEPT_SECTORS))
    print('  动量回看: %d天, 连降卖出: %d天, 止损线: %.0f%%'
          % (LOOKBACK_DAYS, DECLINE_DAYS_TO_SELL, STOP_LOSS_RATIO * 100))


def handlebar(C):
    """
    每根日K线触发一次，模拟完整交易日流程：
      ① 选股 + 动量打分 + 择时 + 调仓（等价于 09:31 my_trade）
      ② 止损检查（等价于 14:50 check_lose，回测用当日收盘价）
      ③ 打印复盘（等价于 15:05 print_trade_info）
    """
    g.bar_count += 1

    bar_date = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')

    # 前几根 bar 数据不足，跳过
    if g.bar_count < WARMUP_BARS:
        return

    print('\n' + '=' * 60)
    print('[回测] Bar#%d 日期: %s' % (g.bar_count, bar_date))
    print('=' * 60)

    # ---------------- ① 选股 + 调仓 ----------------
    # 步骤1：构建股票池
    pool = get_stock_pool(C, bar_date)
    if not pool:
        print('[回测] 股票池为空，跳过今日')
        return
    print('[回测] 步骤1 - 股票池: %d 只' % len(pool))

    # 步骤2：动量打分选股，取第1名
    target_stock = get_rank(pool, C, bar_date)
    if target_stock is None:
        print('[回测] 步骤2 - 未选出目标股票')
        return
    print('[回测] 步骤2 - 目标: %s %s' % (target_stock, C.get_stock_name(target_stock)))

    # 步骤3：计算历史动量分数序列
    g.score_history = rank_stock_change(target_stock, C, bar_date)
    scores = g.score_history.get(target_stock, [])
    print('[回测] 步骤3 - 动量分数序列: %s' % [round(s, 4) for s in scores])

    # 步骤4：过滤候选股（跌停、停牌）
    target_stock = filter_target(target_stock, C, bar_date)
    if target_stock is None:
        print('[回测] 步骤4 - 目标股票被过滤')
        return
    g.today_target = target_stock
    print('[回测] 步骤4 - 过滤通过: %s' % target_stock)

    # 步骤5：计算综合择时信号
    signal = get_timing_signal(target_stock, C, bar_date)
    print('[回测] 步骤5 - 择时信号: %s' % signal)

    # 步骤6：执行调仓
    adjust_position(target_stock, signal, C, bar_date)
    print('[回测] 步骤6 - 调仓执行完毕')

    # ---------------- ② 止损检查 ----------------
    check_lose_backtest(C, bar_date)

    # ---------------- ③ 复盘打印 ----------------
    print_trade_info_backtest(C, bar_date)


def stop(C):
    print('[动量择时策略-回测版] 回测结束，共处理 %d 根K线' % g.bar_count)


# ============================================================
# 行情读取工具
# ============================================================

def get_market_data(C, fields, stocks, bar_date, count, fill_data=True):
    """统一的历史行情读取：period='1d'，不复权，读本地数据。"""
    try:
        return C.get_market_data_ex(
            fields, stocks,
            period='1d',
            end_time=bar_date,
            count=count,
            dividend_type='none',
            fill_data=fill_data,
            subscribe=False
        )
    except Exception as e:
        print('[行情] get_market_data_ex 失败: %s' % e)
        return {}


def series(data, stock, field):
    """从 get_market_data_ex 的返回里取某字段序列（list of float）。"""
    if not data or stock not in data or data[stock] is None:
        return []
    df = data[stock]
    if len(df) == 0 or field not in df.columns:
        return []
    out = []
    for v in df[field].values:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(float('nan'))
    return out


def last_value(data, stock, field, default=0.0):
    """取某字段最新值。"""
    values = series(data, stock, field)
    return values[-1] if values else default


# ============================================================
# 步骤1：构建股票池
# ============================================================

def get_stock_pool(C, bar_date):
    """
    板块成分股 -> 代码前缀 / 停牌 / ST / 市值 / 跌停 过滤。
    行情统一用 get_market_data_ex 读取（回测无 tick）。
    """
    pool_set = set()
    for sector_name in CONCEPT_SECTORS:
        try:
            for s in C.get_stock_list_in_sector(sector_name):
                pool_set.add(s)
        except Exception as e:
            print('[get_stock_pool] 板块 %s 获取失败: %s' % (sector_name, e))

    if not pool_set:
        print('[get_stock_pool] 板块未获取到股票')
        return []

    pool_list = sorted(pool_set)
    data = get_market_data(C, ['close', 'preClose', 'suspendFlag'], pool_list, bar_date, 2)
    if not data:
        return []

    result = []
    for stock in pool_list:
        closes = series(data, stock, 'close')
        if not closes:
            continue

        last_close = closes[-1]
        pre_closes = series(data, stock, 'preClose')
        pre_close = pre_closes[-1] if pre_closes else last_close
        suspend_flags = series(data, stock, 'suspendFlag')
        suspend_flag = suspend_flags[-1] if suspend_flags else 0

        stock_name = ''
        total_value = 0.0
        try:
            detail = C.get_instrument_detail(stock)
            if detail:
                stock_name = detail.get('InstrumentName', '')
                total_value = detail.get('TotalValue', 0) or 0
                if total_value <= 0:
                    total_shares = detail.get('TotalShares', 0) or 0
                    if total_shares > 0 and last_close > 0:
                        total_value = total_shares * last_close
        except Exception:
            pass

        ok, _reason = passes_filters(
            stock,
            stock_name=stock_name,
            total_value=total_value,
            suspend_flag=suspend_flag,
            close=last_close,
            pre_close=pre_close,
            min_cap=MIN_MARKET_CAP,
            max_cap=MAX_MARKET_CAP,
        )
        if ok:
            result.append(stock)

    return result


# ============================================================
# 步骤2：动量打分选股
# ============================================================

def get_rank(pool, C, bar_date):
    """对股票池做动量打分并取第 1 名（打分窗口排除当前 bar）。"""
    if not pool:
        return None

    data = get_market_data(C, ['close'], pool, bar_date, bars_needed_for_rank(LOOKBACK_DAYS))
    if not data:
        return None

    close_map = {}
    for stock in pool:
        closes = series(data, stock, 'close')
        if len(closes) >= LOOKBACK_DAYS + 1:
            close_map[stock] = closes

    ranked = rank_pool(close_map, LOOKBACK_DAYS, TRADING_DAYS_PER_YEAR)
    if not ranked:
        return None

    print('[get_rank] Top3: %s' % [(s, round(sc, 4)) for s, sc in ranked[:3]])
    return ranked[0][0]


# ============================================================
# 步骤3：目标股历史动量分数序列
# ============================================================

def rank_stock_change(stock, C, bar_date):
    """目标股票由远及近的动量分数序列，所有窗口都排除当前 bar。"""
    result = {}
    count = bars_needed_for_history(LOOKBACK_DAYS, SCORE_HISTORY_DAYS)
    data = get_market_data(C, ['close'], [stock], bar_date, count)

    closes = series(data, stock, 'close')
    if len(closes) < LOOKBACK_DAYS + 2:
        return result

    result[stock] = momentum_score_history(
        closes, LOOKBACK_DAYS, SCORE_HISTORY_DAYS, TRADING_DAYS_PER_YEAR)
    return result


# ============================================================
# 步骤4：过滤候选股
# ============================================================

def filter_target(stock, C, bar_date):
    """剔除停牌、跌停的候选股。"""
    if stock is None:
        return None

    data = get_market_data(C, ['close', 'preClose', 'suspendFlag'], [stock], bar_date, 1)
    closes = series(data, stock, 'close')
    if not closes:
        return None

    suspend_flags = series(data, stock, 'suspendFlag')
    if suspend_flags and suspend_flags[-1] == 1:
        print('[filter_target] %s 停牌中' % stock)
        return None

    last_close = closes[-1]
    pre_closes = series(data, stock, 'preClose')
    pre_close = pre_closes[-1] if pre_closes else last_close
    if last_close <= 0:
        return None

    ok, reason = passes_filters(stock, close=last_close, pre_close=pre_close)
    if not ok:
        _, limit_down = limit_prices(stock, pre_close)
        print('[filter_target] %s 未通过(%s) 收盘:%.2f 跌停价:%.2f'
              % (stock, reason, last_close, limit_down))
        return None

    return stock


# ============================================================
# 步骤5：综合择时信号
# ============================================================

def get_timing_signal(stock, C, bar_date):
    """
    个股择时：动量分数连续下降 >= DECLINE_DAYS_TO_SELL 天 -> SELL。
    大盘择时：RSRS 修正标准分，RSRS_ENABLED=False 时仅打印不介入决策。
    """
    rsrs = calc_rsrs(C, bar_date)
    if rsrs is not None:
        print('[择时] RSRS修正标准分: %.4f (参与决策: %s)' % (rsrs, RSRS_ENABLED))
    else:
        print('[择时] RSRS 数据不足')

    scores = g.score_history.get(stock, [])
    if scores:
        print('[择时] 动量分数序列: %s' % [round(s, 4) for s in scores])
        print('[择时] 连续下降天数: %d' % _decline_days(scores))

    return timing_signal(scores, rsrs)


def _decline_days(scores):
    count = 0
    for i in range(len(scores) - 1, 0, -1):
        if scores[i] < scores[i - 1]:
            count += 1
        else:
            break
    return count


def calc_rsrs(C, bar_date):
    """沪深300 的 RSRS 修正标准分：N 根窗口拟合，M 个样本算 zscore。"""
    data = get_market_data(C, ['high', 'low'], [RSRS_INDEX], bar_date, RSRS_M + RSRS_N + 2)
    highs = series(data, RSRS_INDEX, 'high')
    lows = series(data, RSRS_INDEX, 'low')
    if len(highs) < RSRS_M + RSRS_N + 1 or len(lows) < RSRS_M + RSRS_N + 1:
        return None

    # 排除当前 bar
    return rsrs_corrected_zscore(highs[:-1], lows[:-1], RSRS_N, RSRS_M)


# ============================================================
# 步骤6：执行调仓
# ============================================================

def get_price_and_limits(stock, C, bar_date):
    """
    当日开盘价、涨停价、跌停价、最低价。
    取不到时返回 (0.0, 0.0, 0.0, 0.0)。
    """
    data = get_market_data(C, ['open', 'low', 'preClose'], [stock], bar_date, 1)
    opens = series(data, stock, 'open')
    if not opens:
        return 0.0, 0.0, 0.0, 0.0

    open_price = opens[-1]
    lows = series(data, stock, 'low')
    low_price = lows[-1] if lows else open_price
    pre_closes = series(data, stock, 'preClose')
    pre_close = pre_closes[-1] if pre_closes else open_price

    limit_up, limit_down = limit_prices(stock, pre_close)
    return open_price, limit_up, limit_down, low_price


def get_positions(C):
    """当前可用持仓 {股票: 可用股数}。"""
    holdings = get_trade_detail_data(g.account, g.acct_type, 'position') or []
    positions = {}
    for pos in holdings:
        stock = pos.m_strInstrumentID + '.' + pos.m_strExchangeID
        volume = pos.m_nCanUseVolume
        if volume > 0:
            positions[stock] = volume
    return positions


def sell_stock(stock, volume, C, bar_date, msg):
    """按当日开盘价限价卖出。"""
    open_price, _, _, _ = get_price_and_limits(stock, C, bar_date)
    if open_price <= 0:
        print('[调仓] %s 取不到价格，改用市价卖出' % stock)
        passorder(OP_SELL, ORDER_BY_VOLUME, g.account, stock, PRICE_TYPE_MARKET, -1,
                  volume, STRATEGY_NAME, 1, msg, C)
        return
    print('[调仓] %s 价格:%.2f 数量:%d' % (msg, open_price, volume))
    passorder(OP_SELL, ORDER_BY_VOLUME, g.account, stock, PRICE_TYPE_LIMIT, open_price,
              volume, STRATEGY_NAME, 1, msg, C)


def adjust_position(stock, signal, C, bar_date):
    """
    SELL     -> 清仓
    BUY/KEEP -> 持仓已是目标股则持有，否则换仓（先卖旧、再满仓买入）
    """
    positions = get_positions(C)
    print('[调仓] 当前持仓: %s' % positions)

    if signal == SIGNAL_SELL:
        for held, volume in positions.items():
            sell_stock(held, volume, C, bar_date, 'SELL信号 清仓 %s' % held)
        return

    if signal == SIGNAL_KEEP and stock not in positions:
        print('[调仓] KEEP: 不新开仓')
        return

    if positions.get(stock, 0) > 0:
        print('[调仓] KEEP: 继续持有 %s' % stock)
        return

    # 换仓：先卖旧
    for held, volume in positions.items():
        sell_stock(held, volume, C, bar_date, '切换标的 卖出 %s' % held)

    # 再买新
    open_price, limit_up, limit_down, low_price = get_price_and_limits(stock, C, bar_date)
    print('[调仓] %s 开盘:%.2f 涨停:%.2f 跌停:%.2f 最低:%.2f'
          % (stock, open_price, limit_up, limit_down, low_price))
    if open_price <= 0:
        print('[调仓] %s 价格异常: %s' % (stock, open_price))
        return

    ok, _reason = can_buy(low_price, limit_up)
    if not ok:
        print('[调仓] %s 一字涨停，无法买入' % stock)
        return

    account_info = get_trade_detail_data(g.account, g.acct_type, 'account')
    if not account_info:
        print('[调仓] 无法获取账户信息')
        return
    available_cash = int(account_info[0].m_dAvailable)

    volume = buy_volume(available_cash, open_price)
    if volume <= 0:
        print('[调仓] 资金不足买1手，可用:%d 股价:%.2f' % (available_cash, open_price))
        return

    msg = 'BUY信号 买入 %s %d股' % (stock, volume)
    print('[调仓] %s 价格:%.2f' % (msg, open_price))
    passorder(OP_BUY, ORDER_BY_VOLUME, g.account, stock, PRICE_TYPE_LIMIT, open_price,
              volume, STRATEGY_NAME, 1, msg, C)


# ============================================================
# 止损检查（回测版：用当日收盘价）
# ============================================================

def check_lose_backtest(C, bar_date):
    """当日收盘价跌破成本价 STOP_LOSS_RATIO 则市价清仓。"""
    holdings = get_trade_detail_data(g.account, g.acct_type, 'position') or []

    for pos in holdings:
        stock = pos.m_strInstrumentID + '.' + pos.m_strExchangeID
        cost_price = pos.m_dOpenPrice
        volume = pos.m_nCanUseVolume
        if volume <= 0 or cost_price <= 0:
            continue

        data = get_market_data(C, ['close'], [stock], bar_date, 1)
        current_price = last_value(data, stock, 'close', 0.0)
        if current_price <= 0:
            continue

        ratio = profit_ratio(cost_price, current_price)
        print('[止损检查] %s %s 成本:%.2f 收盘:%.2f 盈亏:%.2f%%'
              % (stock, C.get_stock_name(stock), cost_price, current_price, ratio * 100))

        if stop_loss_triggered(cost_price, current_price, STOP_LOSS_RATIO):
            print('[止损检查] %s 触发硬止损，盈亏 %.2f%% <= %.0f%%，强制清仓'
                  % (stock, ratio * 100, STOP_LOSS_RATIO * 100))
            passorder(OP_SELL, ORDER_BY_VOLUME, g.account, stock, PRICE_TYPE_MARKET, -1,
                      volume, STRATEGY_NAME, 1, '硬止损平仓 %s' % stock, C)


# ============================================================
# 复盘打印
# ============================================================

def print_trade_info_backtest(C, bar_date):
    """打印当日成交、持仓、资金。"""
    deals = get_trade_detail_data(g.account, g.acct_type, 'deal') or []
    today_deals = []
    for deal in deals:
        deal_date = deal.m_strTradeDate.replace('-', '')
        if deal_date == bar_date[:8]:
            today_deals.append(deal)

    if today_deals:
        print('--- 今日成交 (%d 笔) ---' % len(today_deals))
        for deal in today_deals:
            print('  %s.%s %s 价格:%.2f 数量:%d'
                  % (deal.m_strInstrumentID, deal.m_strExchangeID,
                     '买入' if deal.m_nDirection == 1 else '卖出',
                     deal.m_dPrice, deal.m_nVolume))

    holdings = get_trade_detail_data(g.account, g.acct_type, 'position') or []
    for pos in holdings:
        stock = pos.m_strInstrumentID + '.' + pos.m_strExchangeID
        cost_price = pos.m_dOpenPrice
        volume = pos.m_nCanUseVolume
        if volume <= 0:
            continue

        data = get_market_data(C, ['close'], [stock], bar_date, 1)
        current_price = last_value(data, stock, 'close', 0.0)
        ratio = profit_ratio(cost_price, current_price)
        ratio = 0.0 if ratio is None else ratio

        print('  持仓: %s %s 成本:%.2f 收盘:%.2f 盈亏:%.2f%% 市值:%.0f'
              % (stock, C.get_stock_name(stock), cost_price, current_price,
                 ratio * 100, current_price * volume))

    acc = get_trade_detail_data(g.account, g.acct_type, 'account')
    if acc:
        print('  资金: 可用=%.0f 总资产=%.0f' % (acc[0].m_dAvailable, acc[0].m_dBalance))
