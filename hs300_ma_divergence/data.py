# coding: utf-8
"""
行情读取：xtdata 的薄封装 + 一个按日期索引的 Bars 容器。

xtdata 需要本机装有 QMT / MiniQMT 客户端并保持登录（数据由客户端提供）。
第一次跑某个区间要先 download 一次，之后就能离线读本地数据。

这里把 xtdata 返回的 DataFrame 统一转成普通的 {字段: [数值]} + 日期列表，
下游引擎与单元测试都不依赖 pandas。
"""

import time

from .config import BATCH_SIZE, DIVIDEND_TYPE, FIELDS, PERIOD


def import_xtdata():
    """延迟导入 xtquant，方便在没装 QMT 的机器上跑单元测试。"""
    try:
        from xtquant import xtdata
    except ImportError as e:
        raise ImportError(
            ' 没有找到 xtquant。xtdata 版回测需要本机安装 QMT / MiniQMT 客户端，'
            '并把客户端自带的 xtquant 加入 Python 环境（原始错误：%s）' % e)
    return xtdata


def _to_float(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float('nan')
    return result


def _timetag_to_date(value):
    """毫秒时间戳 -> 'YYYYMMDD'。"""
    try:
        seconds = float(value) / 1000.0
    except (TypeError, ValueError):
        return ''
    return time.strftime('%Y%m%d', time.localtime(seconds))


def frame_to_series(frame, fields=FIELDS):
    """
    把 xtdata 返回的单只股票数据转成 (日期列表, {字段: [数值]})。

    兼容三种形态：
      * pandas DataFrame，index 是 'YYYYMMDD'
      * pandas DataFrame，带一列毫秒时间戳 time
      * 普通 dict，{字段: [数值]}（单元测试里用）
    """
    if frame is None:
        return [], {}

    columns = getattr(frame, 'columns', None)
    if columns is None and isinstance(frame, dict):
        columns = list(frame.keys())
    if columns is None:
        return [], {}

    values = {}
    for field in fields:
        if field not in columns:
            continue
        column = frame[field]
        raw = getattr(column, 'values', column)
        values[field] = [_to_float(v) for v in raw]

    dates = []
    index = getattr(frame, 'index', None)
    if index is not None and not isinstance(frame, dict):
        for item in index:
            text = str(item)
            dates.append(text[:8] if len(text) >= 8 and text[:8].isdigit() else '')

    if not dates or not all(dates):
        if 'time' in columns:
            column = frame['time']
            raw = getattr(column, 'values', column)
            dates = [_timetag_to_date(v) for v in raw]

    if not dates:
        return [], {}

    # 去掉日期解析失败的行
    keep = [i for i, day in enumerate(dates) if day]
    dates = [dates[i] for i in keep]
    for field in list(values):
        series = values[field]
        values[field] = [series[i] for i in keep if i < len(series)]

    return dates, values


class Bars(object):
    """单只股票的日线序列，按日期索引。"""

    def __init__(self, stock, dates, values):
        self.stock = stock
        self.dates = list(dates)
        self.values = dict(values)
        self._pos = {}
        for i, day in enumerate(self.dates):
            self._pos[day] = i

    def __len__(self):
        return len(self.dates)

    def has(self, day):
        """当日是否有成交（停牌日不会出现在序列里）。"""
        return str(day)[:8] in self._pos

    def index_of(self, day):
        return self._pos.get(str(day)[:8])

    def field_on(self, day, field):
        """当日某字段；当日无数据或字段缺失返回 None。"""
        i = self.index_of(day)
        if i is None:
            return None
        series = self.values.get(field)
        if series is None or i >= len(series):
            return None
        value = series[i]
        return None if value != value else value      # nan 判断

    def prev_close(self, day):
        """前一个有成交日的收盘价。"""
        i = self.index_of(day)
        if i is None or i == 0:
            return None
        series = self.values.get('close') or []
        if i - 1 >= len(series):
            return None
        value = series[i - 1]
        return None if value != value else value

    def closes_until(self, day, count=None):
        """
        截至 day（含当日）的收盘价序列。

        当日没有成交时返回空列表——停牌的票不参与当日选股。
        """
        i = self.index_of(day)
        if i is None:
            return []
        series = self.values.get('close') or []
        window = [v for v in series[:i + 1] if v == v]
        if count:
            window = window[-count:]
        return window


class MarketData(object):
    """xtdata 取数封装。"""

    def __init__(self, xt=None, period=PERIOD, dividend_type=DIVIDEND_TYPE,
                 fields=FIELDS, batch_size=BATCH_SIZE):
        self.xt = xt if xt is not None else import_xtdata()
        self.period = period
        self.dividend_type = dividend_type
        self.fields = list(fields)
        self.batch_size = batch_size

    def download(self, stocks, start, end, callback=None):
        """
        补下载历史行情。第一次跑某个区间必须先下载，否则本地没有数据。

        优先用 download_history_data2（批量），没有就退回逐只 download_history_data。
        """
        stocks = list(stocks)
        batch = getattr(self.xt, 'download_history_data2', None)
        if batch is not None:
            try:
                batch(stocks, period=self.period, start_time=start, end_time=end,
                      callback=callback)
                return len(stocks)
            except TypeError:
                batch(stocks, self.period, start, end)
                return len(stocks)

        single = getattr(self.xt, 'download_history_data', None)
        if single is None:
            print('[行情] xtdata 没有提供下载接口，假定本地已有数据')
            return 0

        for i, stock in enumerate(stocks, 1):
            try:
                single(stock, self.period, start, end)
            except Exception as e:
                print('[行情] %s 下载失败: %s' % (stock, e))
            if i % 100 == 0:
                print('[行情] 已下载 %d/%d' % (i, len(stocks)))
        return len(stocks)

    def get_bars(self, stocks, start, end):
        """读取行情，返回 {股票: Bars}。股票多时自动分批。"""
        stocks = list(stocks)
        result = {}

        for i in range(0, len(stocks), self.batch_size):
            chunk = stocks[i:i + self.batch_size]
            data = self.xt.get_market_data_ex(
                self.fields, chunk,
                period=self.period,
                start_time=start,
                end_time=end,
                dividend_type=self.dividend_type,
                fill_data=False,
            ) or {}

            for stock in chunk:
                dates, values = frame_to_series(data.get(stock), self.fields)
                if dates:
                    result[stock] = Bars(stock, dates, values)

        return result

    def calendar_from_api(self, start, end):
        """
        优先用 xtdata 的交易日历接口，它不依赖本地已下载的行情。

        不同版本的 xtquant 接口签名和返回值不一样（毫秒时间戳或日期字符串），
        这里都兼容；接口不存在或取不到就返回 []，由调用方退回指数日线。
        """
        getter = getattr(self.xt, 'get_trading_dates', None)
        if getter is None:
            return []

        start, end = str(start)[:8], str(end)[:8]
        for market in ('SH', 'SZ'):
            raw = None
            for call in (lambda: getter(market, start, end),
                         lambda: getter(market, start_time=start, end_time=end)):
                try:
                    raw = call()
                    break
                except TypeError:
                    continue
                except Exception as e:
                    print('[日历] get_trading_dates(%s) 失败: %s' % (market, e))
                    break

            days = set()
            for item in raw or []:
                if isinstance(item, (int, float)):
                    day = _timetag_to_date(item)
                else:
                    text = str(item)[:8]
                    day = text if text.isdigit() else ''
                if day and start <= day <= end:
                    days.add(day)

            if days:
                return sorted(days)

        return []

    def trading_days(self, index_code, start, end, download_if_missing=False):
        """
        交易日历：先用 xtdata 的日历接口，取不到再退回指数日线。

        download_if_missing=True 时会自动补下载指数日线，
        方便在本地数据目录还是空的时候直接用。
        """
        days = self.calendar_from_api(start, end)
        if days:
            return days

        bars = self.get_bars([index_code], start, end)
        if index_code not in bars and download_if_missing:
            print('[日历] 本地没有 %s 的日线，正在补下载' % index_code)
            self.download([index_code], start, end)
            bars = self.get_bars([index_code], start, end)

        if index_code not in bars:
            raise ValueError(
                '取不到 %s 的日线，无法构建交易日历。\n'
                '  * 首次使用请加 --download，会自动补下载指数与成分股行情；\n'
                '  * 或在 QMT / MiniQMT 客户端里手动补充 %s 的日线数据；\n'
                '  * 也确认一下客户端已登录、xtdata 数据路径指向的是同一个目录。'
                % (index_code, index_code))
        return list(bars[index_code].dates)
