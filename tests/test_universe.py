# coding: utf-8
"""股票池过滤与涨跌停价。"""

from momentum_timing.universe import (
    is_excluded_code, is_limit_down, is_limit_up, is_st, limit_prices, limit_ratio,
    market_cap_ok, passes_filters, stock_code,
)


def test_stock_code():
    assert stock_code('600000.SH') == '600000'
    assert stock_code('300750.SZ') == '300750'


def test_limit_ratio_by_board():
    assert limit_ratio('300750.SZ') == 0.20   # 创业板
    assert limit_ratio('301234.SZ') == 0.20
    assert limit_ratio('688356.SH') == 0.20   # 科创板
    assert limit_ratio('600000.SH') == 0.10   # 主板
    assert limit_ratio('000001.SZ') == 0.10


def test_limit_prices_rounding():
    assert limit_prices('600000.SH', 10.0) == (11.0, 9.0)
    assert limit_prices('300750.SZ', 10.0) == (12.0, 8.0)
    assert limit_prices('600000.SH', 0) == (0.0, 0.0)
    assert limit_prices('600000.SH', None) == (0.0, 0.0)


def test_is_limit_down_and_up():
    assert is_limit_down('600000.SH', 9.0, 10.0) is True
    assert is_limit_down('600000.SH', 9.01, 10.0) is False
    # 创业板 20%：跌到 9.0 还没跌停
    assert is_limit_down('300750.SZ', 9.0, 10.0) is False
    assert is_limit_up('300750.SZ', 12.0, 10.0) is True
    assert is_limit_up('600000.SH', 10.99, 10.0) is False


def test_is_st():
    assert is_st('ST康美') is True
    assert is_st('*ST海航') is True
    assert is_st('贵州茅台') is False
    assert is_st('ST康美', exclude_st=False) is False
    assert is_st(None) is False


def test_market_cap_range():
    assert market_cap_ok(100e8) is True
    assert market_cap_ok(20e8) is False       # 低于 30 亿
    assert market_cap_ok(800e8) is False      # 高于 500 亿
    assert market_cap_ok(0) is True           # 取不到市值时放行
    assert market_cap_ok(None) is True


def test_is_excluded_code():
    assert is_excluded_code('300750.SZ', ('300', '301')) is True
    assert is_excluded_code('600000.SH', ('300', '301')) is False
    assert is_excluded_code('300750.SZ') is False   # 默认不屏蔽


def test_passes_filters_happy_path():
    ok, reason = passes_filters('600000.SH', stock_name='浦发银行', total_value=100e8,
                                suspend_flag=0, close=10.0, pre_close=10.0)
    assert ok is True and reason == ''


def test_passes_filters_rejections():
    assert passes_filters('600000.SH', suspend_flag=1)[1] == 'suspended'
    assert passes_filters('600000.SH', stock_name='ST康美')[1] == 'st'
    assert passes_filters('600000.SH', total_value=10e8)[1] == 'market_cap'
    assert passes_filters('600000.SH', close=9.0, pre_close=10.0)[1] == 'limit_down'
    assert passes_filters('300750.SZ', excluded_prefixes=('300',))[1] == 'code_prefix'
