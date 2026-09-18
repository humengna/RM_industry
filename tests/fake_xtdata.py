# coding: utf-8
"""
模拟 xtquant.xtdata，用来在没有 QMT 客户端的机器上跑单元测试。

只实现策略用到的那几个接口：
    get_market_data_ex / get_stock_list_in_sector /
    download_history_data2 / download_history_data
"""

import math
import time


class FakeSeries(object):
    def __init__(self, values):
        self.values = list(values)

    def __len__(self):
        return len(self.values)


class FakeFrame(object):
    """只实现 df.columns / df.index / df[field].values。"""

    def __init__(self, columns_map, index):
        self._data = dict(columns_map)
        self.columns = list(columns_map.keys())
        self.index = list(index)

    def __len__(self):
        return len(self.index)

    def __getitem__(self, field):
        return FakeSeries(self._data[field])


def trading_days(start_year=2024, count=200):
    """生成一串连续的"交易日"（跳过周末，够用就行）。"""
    days = []
    stamp = time.mktime((start_year, 1, 1, 12, 0, 0, 0, 0, -1))
    while len(days) < count:
        parts = time.localtime(stamp)
        if parts.tm_wday < 5:
            days.append(time.strftime('%Y%m%d', parts))
        stamp += 86400
    return days


def accelerating_series(days, base=10.0, drift=0.001, accel=0.00005):
    """加速上涨：均线会持续多头发散，能触发选股信号。"""
    return [base * math.exp(drift * i + accel * i * i) for i in range(len(days))]


def linear_series(days, base=10.0, step=0.01):
    """匀速上涨：多头排列但发散不扩大，不会触发信号。"""
    return [base + step * i for i in range(len(days))]


def flat_series(days, base=10.0):
    return [base] * len(days)


def make_bars(days, closes, open_ratio=0.999, high_ratio=1.01, low_ratio=0.99):
    """由收盘价生成 open/high/low/close/volume/amount。"""
    return {
        'days': list(days),
        'open': [round(c * open_ratio, 3) for c in closes],
        'high': [round(c * high_ratio, 3) for c in closes],
        'low': [round(c * low_ratio, 3) for c in closes],
        'close': [round(c, 3) for c in closes],
        'volume': [1000000.0] * len(closes),
        'amount': [1000000.0 * c for c in closes],
    }


class FakeXtdata(object):
    """
    bars:     {股票: make_bars(...) 的结果}
    sectors:  {板块: [(生效日 'YYYYMMDD', [股票])]}，按时间点返回不同成分
    """

    def __init__(self, bars, sectors=None, sector_supports_timetag=True,
                 pending_bars=None, trading_dates=None):
        self.bars = dict(bars)
        self.sectors = sectors or {}
        self.sector_supports_timetag = sector_supports_timetag
        # 还没下载到本地的数据：download 之后才出现，模拟空的数据目录
        self.pending_bars = dict(pending_bars or {})
        # None 表示这个版本的 xtquant 没有 get_trading_dates
        self._trading_dates = trading_dates
        if trading_dates is None:
            self.get_trading_dates = None
        self.downloaded = []
        self.market_data_calls = []

    def get_trading_dates(self, market, start_time='', end_time='', count=-1):
        days = [d for d in (self._trading_dates or [])
                if (not start_time or d >= str(start_time)[:8])
                and (not end_time or d <= str(end_time)[:8])]
        return [self._timetag(d) for d in days]

    # ---------- 行情 ----------

    def get_market_data_ex(self, field_list, stock_list, period='1d', start_time='',
                           end_time='', count=-1, dividend_type='none', fill_data=True):
        self.market_data_calls.append((tuple(field_list), tuple(stock_list), period,
                                       start_time, end_time, dividend_type))
        result = {}
        for stock in stock_list:
            bars = self.bars.get(stock)
            if not bars:
                continue

            keep = []
            for i, day in enumerate(bars['days']):
                if start_time and day < str(start_time)[:8]:
                    continue
                if end_time and day > str(end_time)[:8]:
                    continue
                keep.append(i)
            if count and count > 0:
                keep = keep[-count:]
            if not keep:
                continue

            columns = {}
            for field in field_list:
                if field == 'time':
                    columns['time'] = [self._timetag(bars['days'][i]) for i in keep]
                elif field in bars:
                    columns[field] = [bars[field][i] for i in keep]
            result[stock] = FakeFrame(columns, [bars['days'][i] for i in keep])
        return result

    @staticmethod
    def _timetag(day):
        stamp = time.mktime((int(day[:4]), int(day[4:6]), int(day[6:8]), 15, 0, 0, 0, 0, -1))
        return int(stamp * 1000)

    # ---------- 板块 ----------

    def get_stock_list_in_sector(self, sector_name, real_timetag=None):
        snapshots = self.sectors.get(sector_name, [])
        if not snapshots:
            return []

        if real_timetag is None:
            return list(snapshots[-1][1])

        if not self.sector_supports_timetag:
            raise TypeError('get_stock_list_in_sector() takes 1 positional argument')

        day = time.strftime('%Y%m%d', time.localtime(real_timetag / 1000.0))
        chosen = snapshots[0][1]
        for effective_day, members in snapshots:
            if effective_day <= day:
                chosen = members
            else:
                break
        return list(chosen)

    # ---------- 下载 ----------

    def download_history_data2(self, stock_list, period='1d', start_time='', end_time='',
                               callback=None):
        self.downloaded.extend(stock_list)
        for stock in stock_list:
            if stock in self.pending_bars:
                self.bars[stock] = self.pending_bars.pop(stock)
        return len(stock_list)
