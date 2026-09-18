# coding: utf-8
"""xtdata 取数封装与 Bars 容器。"""

import pytest

from fake_xtdata import FakeXtdata, make_bars, trading_days

from hs300_ma_divergence.data import Bars, MarketData, frame_to_series, import_xtdata

DAYS = trading_days(2024, 30)


def build_xt():
    bars = {
        '000300.SH': make_bars(DAYS, [3800 + i for i in range(len(DAYS))]),
        '600000.SH': make_bars(DAYS, [10 + 0.1 * i for i in range(len(DAYS))]),
        '600001.SH': make_bars(DAYS[:5], [20.0] * 5),      # 只有前 5 天有数据
    }
    return FakeXtdata(bars, {'沪深300': [('20240101', sorted(bars))]})


# ---------- 转换 ----------

def test_frame_to_series_from_dict_with_timetag():
    frame = {'time': [1704164400000, 1704250800000], 'close': [10.0, 10.5]}
    dates, values = frame_to_series(frame, ('time', 'close'))
    assert len(dates) == 2 and all(len(d) == 8 for d in dates)
    assert values['close'] == [10.0, 10.5]


def test_frame_to_series_prefers_dataframe_index():
    xt = build_xt()
    frame = xt.get_market_data_ex(['close'], ['600000.SH'], end_time=DAYS[4])['600000.SH']
    dates, values = frame_to_series(frame, ('close',))
    assert dates == DAYS[:5]
    assert len(values['close']) == 5


def test_frame_to_series_handles_none_and_empty():
    assert frame_to_series(None) == ([], {})
    assert frame_to_series({'close': [1.0]}, ('close',)) == ([], {})   # 没有时间信息


def test_frame_to_series_drops_unparsable_rows():
    frame = {'time': [1704164400000, 'x'], 'close': [10.0, 11.0]}
    dates, values = frame_to_series(frame, ('time', 'close'))
    assert len(dates) == 1 and values['close'] == [10.0]


# ---------- Bars ----------

def test_bars_lookup():
    bars = Bars('600000.SH', DAYS[:3], {'close': [10.0, 11.0, 12.0],
                                        'open': [9.9, 10.9, 11.9]})
    assert len(bars) == 3
    assert bars.has(DAYS[1]) and not bars.has('20991231')
    assert bars.field_on(DAYS[1], 'open') == pytest.approx(10.9)
    assert bars.field_on('20991231', 'open') is None
    assert bars.prev_close(DAYS[1]) == pytest.approx(10.0)
    assert bars.prev_close(DAYS[0]) is None


def test_bars_closes_until_is_empty_on_suspended_day():
    bars = Bars('600000.SH', [DAYS[0], DAYS[2]], {'close': [10.0, 12.0]})
    assert bars.closes_until(DAYS[2]) == [10.0, 12.0]
    assert bars.closes_until(DAYS[1]) == []       # 当天停牌，不参与选股
    assert bars.closes_until(DAYS[2], 1) == [12.0]


def test_bars_skips_nan_close():
    bars = Bars('600000.SH', DAYS[:3], {'close': [10.0, float('nan'), 12.0]})
    assert bars.closes_until(DAYS[2]) == [10.0, 12.0]
    assert bars.field_on(DAYS[1], 'close') is None


# ---------- MarketData ----------

def test_get_bars_returns_only_stocks_with_data():
    market = MarketData(xt=build_xt())
    bars = market.get_bars(['600000.SH', '600001.SH', '999999.SH'], DAYS[0], DAYS[-1])
    assert sorted(bars) == ['600000.SH', '600001.SH']
    assert len(bars['600001.SH']) == 5


def test_get_bars_batches_large_requests():
    xt = build_xt()
    market = MarketData(xt=xt, batch_size=1)
    market.get_bars(['600000.SH', '600001.SH'], DAYS[0], DAYS[-1])
    assert len(xt.market_data_calls) == 2


def test_trading_days_uses_index():
    market = MarketData(xt=build_xt())
    assert market.trading_days('000300.SH', DAYS[0], DAYS[-1]) == DAYS


def test_trading_days_missing_index_raises():
    market = MarketData(xt=build_xt())
    with pytest.raises(ValueError) as excinfo:
        market.trading_days('999999.SH', DAYS[0], DAYS[-1])
    assert 'download' in str(excinfo.value)


def test_download_uses_batch_api():
    xt = build_xt()
    MarketData(xt=xt).download(['600000.SH', '600001.SH'], DAYS[0], DAYS[-1])
    assert xt.downloaded == ['600000.SH', '600001.SH']


def test_import_xtdata_message_is_actionable():
    try:
        import xtquant  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError) as excinfo:
            import_xtdata()
        assert 'QMT' in str(excinfo.value)


# ---------- 交易日历 ----------

def test_calendar_prefers_get_trading_dates_api():
    """有 get_trading_dates 就用它，不依赖本地已下载的指数日线。"""
    xt = FakeXtdata({}, trading_dates=DAYS)
    market = MarketData(xt=xt)

    assert market.calendar_from_api(DAYS[0], DAYS[-1]) == DAYS
    assert market.trading_days('000300.SH', DAYS[0], DAYS[-1]) == DAYS
    assert xt.market_data_calls == []      # 完全没读行情


def test_calendar_api_respects_range():
    xt = FakeXtdata({}, trading_dates=DAYS)
    market = MarketData(xt=xt)
    assert market.calendar_from_api(DAYS[2], DAYS[5]) == DAYS[2:6]


def test_calendar_falls_back_to_index_bars():
    """旧版没有 get_trading_dates 时，退回用指数日线当日历。"""
    market = MarketData(xt=build_xt())          # 该 fake 没有 get_trading_dates
    assert market.trading_days('000300.SH', DAYS[0], DAYS[-1]) == DAYS


def test_trading_days_downloads_index_when_missing():
    """本地数据目录是空的时候，自动补下载指数日线再建日历。"""
    xt = FakeXtdata({}, pending_bars={'000300.SH': make_bars(DAYS, [3800.0] * len(DAYS))})
    market = MarketData(xt=xt)

    with pytest.raises(ValueError):
        market.trading_days('000300.SH', DAYS[0], DAYS[-1])   # 不允许下载就报错

    assert market.trading_days('000300.SH', DAYS[0], DAYS[-1],
                               download_if_missing=True) == DAYS
    assert '000300.SH' in xt.downloaded


def test_missing_index_error_mentions_download_flag():
    market = MarketData(xt=FakeXtdata({}))
    with pytest.raises(ValueError) as excinfo:
        market.trading_days('000300.SH', DAYS[0], DAYS[-1])
    assert '--download' in str(excinfo.value)
