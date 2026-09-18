# coding: utf-8
"""
模拟 QMT 的 ContextInfo / 交易接口，用于在本地跑通策略脚本。

只实现策略用到的那部分接口：
  ContextInfo.get_market_data_ex / get_stock_list_in_sector /
              get_stock_name / get_instrument_detail / get_bar_timetag / barpos
  全局函数    passorder / get_trade_detail_data / timetag_to_datetime
"""


class FakeSeries(object):
    def __init__(self, values):
        self.values = list(values)

    def __len__(self):
        return len(self.values)


class FakeDataFrame(object):
    """只实现 df.columns / df.index / len(df) / df[field].values 这几种用法。"""

    def __init__(self, columns_map, index=None):
        self._data = dict(columns_map)
        self.columns = list(columns_map.keys())
        self.index = list(index) if index is not None else []

    def __len__(self):
        if not self._data:
            return 0
        return len(next(iter(self._data.values())))

    def __getitem__(self, field):
        return FakeSeries(self._data[field])


class FakePosition(object):
    def __init__(self, stock, volume, open_price):
        code, exchange = stock.split('.')
        self.m_strInstrumentID = code
        self.m_strExchangeID = exchange
        self.m_nCanUseVolume = volume
        self.m_dOpenPrice = open_price


class FakeAccount(object):
    def __init__(self, available, balance=None):
        self.m_dAvailable = available
        self.m_dBalance = balance if balance is not None else available


class FakeDeal(object):
    def __init__(self, stock, direction, price, volume, trade_date):
        code, exchange = stock.split('.')
        self.m_strInstrumentID = code
        self.m_strExchangeID = exchange
        self.m_nDirection = direction
        self.m_dPrice = price
        self.m_nVolume = volume
        self.m_strTradeDate = trade_date


def trading_minutes(date, count=240):
    """生成某个交易日的分钟时间戳：9:31~11:30 + 13:01~15:00。"""
    out = []
    hour, minute = 9, 31
    while len(out) < count:
        out.append('%s%02d%02d00' % (date, hour, minute))
        minute += 1
        if minute == 60:
            hour, minute = hour + 1, 0
        if hour == 11 and minute == 31:
            hour, minute = 13, 1
        if hour == 15 and minute == 1:
            break
    return out


def minute_session(date, closes, amounts=None, highs=None, lows=None, opens=None):
    """
    由分钟收盘价序列生成一个交易日的分钟线。

    返回 {'time': [...], 'open': [...], 'high': [...], 'low': [...],
          'close': [...], 'volume': [...], 'amount': [...]}
    """
    closes = [float(c) for c in closes]
    n = len(closes)
    opens = list(opens) if opens else [closes[0]] + closes[:-1]
    highs = list(highs) if highs else [max(o, c) for o, c in zip(opens, closes)]
    lows = list(lows) if lows else [min(o, c) for o, c in zip(opens, closes)]
    amounts = list(amounts) if amounts else [1e6] * n
    volumes = [a / c if c > 0 else 0.0 for a, c in zip(amounts, closes)]
    return {
        'time': trading_minutes(date, n),
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes,
        'amount': amounts,
    }


def concat_sessions(sessions):
    """把多个交易日的分钟线按时间顺序拼成一条序列。"""
    merged = {}
    for session in sessions:
        for key, values in session.items():
            merged.setdefault(key, []).extend(values)
    return merged


class FakeContext(object):
    """
    prices:  {股票: {字段: [按时间升序的值]}}   日线
    dates:   ['20240102', ...]，与日线价格序列一一对应
    minutes: {股票: {'time': [...], '字段': [...]}}  分钟线，可选
    """

    def __init__(self, prices, dates, sectors=None, details=None, names=None,
                 minutes=None):
        self.prices = prices
        self.dates = list(dates)
        self.sectors = sectors or {}
        self.details = details or {}
        self.names = names or {}
        self.minutes = minutes or {}
        self.barpos = len(self.dates) - 1
        self.market_data_calls = []

    # ---------- 行情 ----------
    def get_bar_timetag(self, barpos):
        return barpos

    def get_market_data_ex(self, fields, stocks, period='1d', end_time='', count=1,
                           dividend_type='none', fill_data=True, subscribe=True):
        assert subscribe is False, '回测必须使用 subscribe=False 读本地数据'
        self.market_data_calls.append(
            (tuple(fields), tuple(stocks), count, end_time, period))

        if period == '1m':
            return self._minute_data(fields, stocks, end_time, count)

        end_day = end_time[:8]
        end_idx = self.dates.index(end_day) if end_day in self.dates else len(self.dates) - 1
        start_idx = max(0, end_idx + 1 - count) if count > 0 else 0

        result = {}
        for stock in stocks:
            if stock not in self.prices:
                continue
            columns = {}
            for field in fields:
                values = self.prices[stock].get(field)
                if values is None:
                    continue
                columns[field] = list(values[start_idx:end_idx + 1])
            if columns:
                result[stock] = FakeDataFrame(columns)
        return result

    def _minute_data(self, fields, stocks, end_time, count):
        """分钟线：取 end_time 当天收盘之前的最后 count 根。"""
        end_day = end_time[:8]
        result = {}
        for stock in stocks:
            bars = self.minutes.get(stock)
            if not bars:
                continue

            keep = [i for i, t in enumerate(bars['time']) if str(t)[:8] <= end_day]
            keep = keep[-count:] if count > 0 else keep
            if not keep:
                continue

            columns = {}
            for field in fields:
                values = bars.get(field)
                if values is None:
                    continue
                columns[field] = [values[i] for i in keep]
            if columns:
                result[stock] = FakeDataFrame(
                    columns, index=[bars['time'][i] for i in keep])
        return result

    # ---------- 基础信息 ----------
    def get_stock_list_in_sector(self, sector_name):
        return list(self.sectors.get(sector_name, []))

    def get_stock_name(self, stock):
        return self.names.get(stock, stock)

    def get_instrument_detail(self, stock):
        return self.details.get(stock, {'InstrumentName': stock, 'TotalValue': 100e8})


class FakeBroker(object):
    """记录 passorder 调用，并提供 get_trade_detail_data 的返回值。"""

    def __init__(self, available=100000.0, positions=None, deals=None):
        self.account = FakeAccount(available)
        self.positions = list(positions or [])
        self.deals = list(deals or [])
        self.orders = []

    def passorder(self, op_type, order_type, account, stock, price_type, price,
                  volume, strategy_name, quick_trade, msg, C):
        self.orders.append({
            'op_type': op_type,
            'order_type': order_type,
            'account': account,
            'stock': stock,
            'price_type': price_type,
            'price': price,
            'volume': volume,
            'msg': msg,
        })

    def get_trade_detail_data(self, account, acct_type, data_type):
        if data_type == 'position':
            return list(self.positions)
        if data_type == 'account':
            return [self.account]
        if data_type == 'deal':
            return list(self.deals)
        return []


def timetag_to_datetime(timetag, fmt):
    """测试里 timetag 直接就是 bar 序号，由 install() 绑定的日期表翻译。"""
    raise NotImplementedError('由 install_fake_qmt 覆盖')


def install_fake_qmt(module, context, broker):
    """把模拟的 QMT 全局函数注入策略模块的命名空间。"""
    module.passorder = broker.passorder
    module.get_trade_detail_data = broker.get_trade_detail_data
    module.timetag_to_datetime = lambda timetag, fmt: context.dates[timetag] + '150000'
    return module
