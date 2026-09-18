# coding: utf-8
"""
本地回测引擎：逐日循环 + T+1 撮合。

时序（与原 QMT 脚本的 quickTrade=0 一致）：
    T 日收盘后算信号  ->  T+1 日开盘成交

规则：
    * 当日买入的股票当日不可卖（T+1）
    * 停牌（当日没有K线）既不能买也不能卖
    * 一字涨停买不进、一字跌停卖不掉（RESPECT_PRICE_LIMITS）
    * 佣金双边 + 卖出印花税 + 过户费，佣金有单笔下限
    * 仓位算法与原脚本一致：min(总资产*20%, 可用资金/待买数) * 0.98，向下取整到手
"""

from . import signals
from .config import (
    CASH_BUFFER, COMMISSION_RATE, INIT_CASH, LOT_SIZE, MAX_HOLDINGS,
    MAX_POSITION_WEIGHT, MIN_COMMISSION, RESPECT_PRICE_LIMITS, SLIPPAGE,
    SORT_ASCENDING, STAMP_TAX_RATE, TARGET_WEIGHT, TRANSFER_FEE_RATE, T_PLUS_1,
)

LIMIT_RATIO_BY_PREFIX = {'300': 0.20, '301': 0.20, '688': 0.20, '8': 0.30, '4': 0.30}
DEFAULT_LIMIT_RATIO = 0.10


def limit_ratio(stock):
    """按代码前缀确定涨跌停幅度。"""
    code = str(stock).split('.')[0]
    for prefix, ratio in LIMIT_RATIO_BY_PREFIX.items():
        if code.startswith(prefix):
            return ratio
    return DEFAULT_LIMIT_RATIO


def limit_prices(stock, pre_close):
    """返回 (涨停价, 跌停价)；前收非法时返回 (0, 0)。"""
    if not pre_close or pre_close <= 0:
        return 0.0, 0.0
    ratio = limit_ratio(stock)
    return round(pre_close * (1 + ratio), 2), round(pre_close * (1 - ratio), 2)


def buy_cost(amount, commission_rate=COMMISSION_RATE, min_commission=MIN_COMMISSION,
             transfer_rate=TRANSFER_FEE_RATE):
    """买入费用：佣金（有下限）+ 过户费。"""
    if amount <= 0:
        return 0.0
    return max(amount * commission_rate, min_commission) + amount * transfer_rate


def sell_cost(amount, commission_rate=COMMISSION_RATE, min_commission=MIN_COMMISSION,
              transfer_rate=TRANSFER_FEE_RATE, stamp_rate=STAMP_TAX_RATE):
    """卖出费用：佣金（有下限）+ 过户费 + 印花税。"""
    if amount <= 0:
        return 0.0
    return (max(amount * commission_rate, min_commission)
            + amount * transfer_rate + amount * stamp_rate)


def target_volume(available_cash, total_assets, price, remaining, weight=TARGET_WEIGHT,
                  lot_size=LOT_SIZE, buffer=CASH_BUFFER,
                  max_weight=MAX_POSITION_WEIGHT):
    """
    下单量：与原脚本一致的 min(总资产×目标仓位, 可用资金÷待买只数) × 0.98，
    再额外受单只仓位上限 max_weight 约束，最后向下取整到手。
    """
    if price is None or price <= 0 or available_cash <= 0 or remaining <= 0:
        return 0

    effective_weight = weight if max_weight is None else min(weight, max_weight)
    amount = min(total_assets * effective_weight,
                 available_cash / float(remaining)) * buffer
    volume = int(amount / price / lot_size) * lot_size
    return volume if volume >= lot_size else 0


class Portfolio(object):
    """现金 + 持仓。"""

    def __init__(self, cash=INIT_CASH):
        self.cash = float(cash)
        self.positions = {}     # {股票: {'volume', 'available', 'cost', 'buy_day'}}

    def unlock(self, day):
        """T+1 解禁：当日之前买入的持仓变为可卖。"""
        for stock, position in self.positions.items():
            if not T_PLUS_1 or position['buy_day'] < day:
                position['available'] = position['volume']

    def market_value(self, bars, day, price_field='close'):
        """按指定价格字段估算持仓市值，当日停牌的按最近一次成交价估。"""
        total = 0.0
        for stock, position in self.positions.items():
            series = bars.get(stock)
            if series is None:
                continue
            price = series.field_on(day, price_field)
            if price is None:
                price = last_price_before(series, day)
            if price:
                total += price * position['volume']
        return total

    def total_assets(self, bars, day, price_field='close'):
        return self.cash + self.market_value(bars, day, price_field)

    def holdings(self):
        return sorted(self.positions)


def last_price_before(series, day):
    """最近一个不晚于 day 的收盘价（停牌估值用）。"""
    closes = series.closes_until(day)
    if closes:
        return closes[-1]
    for i in range(len(series.dates) - 1, -1, -1):
        if series.dates[i] <= day:
            value = (series.values.get('close') or [None] * len(series.dates))[i]
            if value is not None and value == value:
                return value
    return None


class Backtest(object):
    """
    bars:          {股票: Bars}
    trading_days:  ['YYYYMMDD', ...] 升序
    provider:      ConstituentProvider，负责给出当日成分股
    """

    def __init__(self, bars, trading_days, provider, init_cash=INIT_CASH,
                 max_holdings=MAX_HOLDINGS, ascending=SORT_ASCENDING,
                 execution_price='open', respect_limits=RESPECT_PRICE_LIMITS,
                 slippage=SLIPPAGE, verbose=True, print_all_candidates=False,
                 max_weight=MAX_POSITION_WEIGHT):
        self.bars = bars
        self.trading_days = list(trading_days)
        self.provider = provider
        self.portfolio = Portfolio(init_cash)
        self.init_cash = float(init_cash)
        self.max_holdings = max_holdings
        self.target_weight = 1.0 / max_holdings if max_holdings else TARGET_WEIGHT
        self.max_weight = max_weight
        self.ascending = ascending
        self.execution_price = execution_price
        self.respect_limits = respect_limits
        self.slippage = slippage
        self.verbose = verbose
        self.print_all_candidates = print_all_candidates

        self.trades = []
        self.equity = []
        self.daily_signals = []
        self.skipped = {}       # {原因: 次数}

    # ---------- 主循环 ----------

    def run(self):
        need = signals.bars_needed()
        pending = []
        pending_date = ''

        for day in self.trading_days:
            # ① 先按昨天收盘的信号，在今天开盘调仓
            if pending or self.portfolio.positions:
                self.rebalance(pending, day, pending_date)

            # ② 今天收盘后重新选股，留到明天开盘执行
            target, candidates = self.select(day, need)
            pending = [item['stock'] for item in target]
            pending_date = day
            self.daily_signals.append({
                'date': day,
                'candidates': len(candidates),
                'target': list(pending),
            })

            # ③ 收盘估值
            market_value = self.portfolio.market_value(self.bars, day)
            self.equity.append({
                'date': day,
                'cash': self.portfolio.cash,
                'market_value': market_value,
                'total': self.portfolio.cash + market_value,
                'holdings': len(self.portfolio.positions),
            })

            if self.verbose:
                self.print_day(day, target, candidates)

        return self.result()

    def select(self, day, need):
        """当日选股：成分股 -> 收盘价序列 -> 五均线四级发散。"""
        members = self.provider.members_on(day)
        close_map = {}
        for stock in members:
            series = self.bars.get(stock)
            if series is None:
                continue
            closes = series.closes_until(day, need)
            if len(closes) >= need:
                close_map[stock] = closes

        return signals.select(close_map, self.max_holdings, self.ascending)

    # ---------- 撮合 ----------

    def rebalance(self, targets, day, signal_date):
        self.portfolio.unlock(day)
        targets = list(targets)

        for stock in list(self.portfolio.positions):
            if stock not in targets:
                self.sell(stock, day, signal_date)

        missing = [s for s in targets if s not in self.portfolio.positions]
        if not missing:
            return

        total_assets = self.portfolio.total_assets(self.bars, day, self.execution_price)
        remaining = len(missing)

        for stock in missing:
            price = self.tradable_price(stock, day, 'buy')
            if price is None:
                remaining -= 1
                continue

            volume = target_volume(self.portfolio.cash, total_assets, price, remaining,
                                   weight=self.target_weight, max_weight=self.max_weight)
            if volume <= 0:
                self.skip('资金不足')
                remaining -= 1
                continue

            amount = price * volume
            fee = buy_cost(amount)
            while amount + fee > self.portfolio.cash and volume > 0:
                volume -= LOT_SIZE
                amount = price * volume
                fee = buy_cost(amount)
            if volume <= 0:
                self.skip('资金不足')
                remaining -= 1
                continue

            self.portfolio.cash -= amount + fee
            self.portfolio.positions[stock] = {
                'volume': volume,
                'available': 0 if T_PLUS_1 else volume,
                'cost': (amount + fee) / volume,
                'buy_day': day,
            }
            self.record(day, signal_date, stock, 'BUY', price, volume, amount, fee)
            remaining -= 1

    def sell(self, stock, day, signal_date):
        position = self.portfolio.positions.get(stock)
        if not position:
            return
        if position['available'] <= 0:
            self.skip('T+1未解禁')
            return

        price = self.tradable_price(stock, day, 'sell')
        if price is None:
            return

        volume = position['available']
        amount = price * volume
        fee = sell_cost(amount)
        self.portfolio.cash += amount - fee

        if volume >= position['volume']:
            del self.portfolio.positions[stock]
        else:
            position['volume'] -= volume
            position['available'] = 0

        self.record(day, signal_date, stock, 'SELL', price, volume, amount, fee)

    def tradable_price(self, stock, day, side):
        """当日可成交价；停牌或一字板返回 None。"""
        series = self.bars.get(stock)
        if series is None or not series.has(day):
            self.skip('停牌')
            return None

        price = series.field_on(day, self.execution_price)
        if price is None or price <= 0:
            self.skip('无成交价')
            return None

        if self.respect_limits:
            pre_close = series.prev_close(day)
            limit_up, limit_down = limit_prices(stock, pre_close)
            low = series.field_on(day, 'low')
            high = series.field_on(day, 'high')
            if side == 'buy' and limit_up > 0 and low is not None and low >= limit_up:
                self.skip('一字涨停买不进')
                return None
            if side == 'sell' and limit_down > 0 and high is not None and high <= limit_down:
                self.skip('一字跌停卖不掉')
                return None

        if self.slippage:
            price *= (1 + self.slippage) if side == 'buy' else (1 - self.slippage)
        return price

    # ---------- 记录 ----------

    def skip(self, reason):
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def record(self, day, signal_date, stock, side, price, volume, amount, fee):
        self.trades.append({
            'date': day,
            'signal_date': signal_date,
            'stock': stock,
            'side': side,
            'price': round(price, 4),
            'volume': volume,
            'amount': round(amount, 2),
            'fee': round(fee, 2),
            'cash_after': round(self.portfolio.cash, 2),
        })
        if self.verbose:
            print('  [%s] %s %s %d股 @%.3f 费用%.2f'
                  % (day, side, stock, volume, price, fee))

    def print_day(self, day, target, candidates):
        print('')
        print('-' * 88)
        print('日期: %s  有效信号: %d  持仓: %d  总资产: %.2f'
              % (day, len(candidates), len(self.portfolio.positions),
                 self.equity[-1]['total']))

        shown = candidates if self.print_all_candidates else target
        for i, item in enumerate(shown, 1):
            spread_text = ' '.join('S%d=%7.3f%%' % (n, value * 100)
                                   for n, value in enumerate(item['spreads'], 1))
            print('  #%-2d %-12s 总发散=%8.4f%%  %s'
                  % (i, item['stock'], item['score'] * 100, spread_text))
        if not shown:
            print('  今日没有满足条件的股票')

    def result(self):
        return {
            'equity': self.equity,
            'trades': self.trades,
            'daily_signals': self.daily_signals,
            'skipped': self.skipped,
            'init_cash': self.init_cash,
            'final_total': self.equity[-1]['total'] if self.equity else self.init_cash,
        }
