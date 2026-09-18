# coding: utf-8
"""历史成分股（point-in-time）。"""

import os

import pytest

from fake_xtdata import FakeXtdata, make_bars, trading_days

from hs300_ma_divergence.constituents import (
    ConstituentError, ConstituentProvider, read_cache, sample_dates, save_cache, to_timetag,
)

DAYS = trading_days(2024, 200)
SECTORS = {
    '沪深300': [
        ('20240101', ['600000.SH', '600001.SH', '600002.SH']),
        ('20240601', ['600001.SH', '600002.SH', '600003.SH']),   # 调入 003，调出 000
    ]
}


def make_xt(**kwargs):
    bars = {stock: make_bars(DAYS, [10.0] * len(DAYS))
            for stock in ('600000.SH', '600001.SH', '600002.SH', '600003.SH')}
    return FakeXtdata(bars, SECTORS, **kwargs)


# ---------- 工具 ----------

def test_to_timetag_round_trip():
    assert to_timetag('20240102') > 0
    assert to_timetag('20240103') > to_timetag('20240102')


def test_sample_dates_month_takes_first_trading_day():
    days = ['20240102', '20240103', '20240201', '20240202', '20240301']
    assert sample_dates(days, 'month') == ['20240102', '20240201', '20240301']
    assert sample_dates(days, 'day') == days


# ---------- 取数 ----------

def test_loads_point_in_time_members_from_xtdata():
    provider = ConstituentProvider(xt=make_xt(), cache_file=None)
    provider.load(DAYS)

    assert '600000.SH' in provider.members_on('20240301')
    assert '600003.SH' not in provider.members_on('20240301')
    # 6 月调整之后
    assert '600003.SH' in provider.members_on('20240701')
    assert '600000.SH' not in provider.members_on('20240701')


def test_all_members_covers_both_snapshots():
    provider = ConstituentProvider(xt=make_xt(), cache_file=None)
    provider.load(DAYS)
    assert provider.all_members() == ['600000.SH', '600001.SH', '600002.SH', '600003.SH']


def test_members_forward_filled_between_snapshots():
    provider = ConstituentProvider(xt=make_xt(), cache_file=None, granularity='month')
    provider.load(DAYS)
    # 月中没有快照，应沿用月初那一份
    assert provider.members_on('20240315') == provider.members_on('20240301')


def test_old_xtquant_without_timetag_raises_by_default():
    """旧版接口不支持历史时间点时，默认报错而不是偷偷用当前成分股。"""
    provider = ConstituentProvider(xt=make_xt(sector_supports_timetag=False),
                                   cache_file=None)
    with pytest.raises(ConstituentError) as excinfo:
        provider.load(DAYS)
    assert '历史成分股' in str(excinfo.value)


def test_fallback_to_current_when_explicitly_allowed():
    provider = ConstituentProvider(xt=make_xt(sector_supports_timetag=False),
                                   cache_file=None, allow_current_fallback=True)
    source = provider.load(DAYS)
    assert 'current' in source and '幸存者偏差' in source
    assert provider.members_on('20240301') == ['600001.SH', '600002.SH', '600003.SH']


def test_identical_snapshots_treated_as_unsupported():
    """接口忽略时间参数、每次都返回同一份名单时，不能当成历史成分股用。"""
    sectors = {'沪深300': [('20240101', ['600000.SH', '600001.SH'])]}
    xt = FakeXtdata({}, sectors)
    provider = ConstituentProvider(xt=xt, cache_file=None)
    with pytest.raises(ConstituentError):
        provider.load(DAYS)


# ---------- 缓存 ----------

def test_cache_round_trip(tmp_path):
    path = str(tmp_path / 'hs300.csv')
    snapshots = {'20240101': ['600000.SH', '600001.SH'], '20240601': ['600002.SH']}
    save_cache(path, snapshots)

    assert read_cache(path) == snapshots
    with open(path, encoding='utf-8') as fp:
        assert fp.readline().strip() == 'date,stock'


def test_load_writes_cache_then_reuses_it(tmp_path):
    path = str(tmp_path / 'hs300.csv')

    first = ConstituentProvider(xt=make_xt(), cache_file=path)
    first.load(DAYS)
    assert os.path.exists(path)

    # 第二次没有 xtdata 也能跑，说明确实走了缓存
    second = ConstituentProvider(xt=None, cache_file=path)
    source = second.load(DAYS)
    assert source.startswith('cache:')
    assert second.members_on('20240701') == first.members_on('20240701')


def test_cache_not_covering_start_falls_back_to_xtdata(tmp_path):
    path = str(tmp_path / 'hs300.csv')
    save_cache(path, {'20241201': ['600009.SH']})     # 只覆盖区间末尾

    provider = ConstituentProvider(xt=make_xt(), cache_file=path)
    provider.load(DAYS)
    assert '600000.SH' in provider.members_on('20240301')


def test_empty_trading_days_raises():
    provider = ConstituentProvider(xt=make_xt(), cache_file=None)
    with pytest.raises(ConstituentError):
        provider.load([])
