# coding: utf-8
"""Excel 历史成分股导入工具。"""

import datetime
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))

import import_constituents_xlsx as importer  # noqa: E402

openpyxl = pytest.importorskip('openpyxl')


# ---------- 代码标准化 ----------

def test_normalize_code_keeps_qmt_format():
    assert importer.normalize_code('600000.SH') == '600000.SH'
    assert importer.normalize_code(' 300750.sz ') == '300750.SZ'


def test_normalize_code_infers_suffix():
    assert importer.normalize_code('600000') == '600000.SH'
    assert importer.normalize_code('688981') == '688981.SH'
    assert importer.normalize_code('000001') == '000001.SZ'
    assert importer.normalize_code('300750') == '300750.SZ'
    assert importer.normalize_code('430047') == '430047.BJ'


def test_normalize_code_handles_prefix_form():
    assert importer.normalize_code('SH600000') == '600000.SH'
    assert importer.normalize_code('sz.000001') == '000001.SZ'


def test_normalize_code_pads_numeric_cells():
    """Excel 常把 000001 存成数字 1。"""
    assert importer.normalize_code(1) == '000001.SZ'
    assert importer.normalize_code(600000) == '600000.SH'


def test_normalize_code_rejects_garbage():
    assert importer.normalize_code(None) is None
    assert importer.normalize_code('') is None
    assert importer.normalize_code('合计') is None
    assert importer.normalize_code('779999') is None      # 前缀认不出市场


# ---------- 日期 ----------

def test_to_date_accepts_datetime_and_text():
    assert importer.to_date(datetime.datetime(2024, 6, 17)) == '20240617'
    assert importer.to_date('2024-06-17') == '20240617'
    assert importer.to_date('20240617') == '20240617'
    assert importer.to_date(None) == ''
    assert importer.to_date('无') == ''


# ---------- 表头与快照 ----------

def test_find_header_skips_title_rows():
    rows = [('沪深300历史成分股',), ('说明……',), (None,),
            ('生效日期', '失效日期', '证券代码', '证券简称')]
    index, mapping = importer.find_header(rows)
    assert index == 3
    assert mapping['effective'] == 0 and mapping['code'] == 2


def test_find_header_accepts_aliases():
    rows = [('start_date', 'end_date', 'code')]
    index, mapping = importer.find_header(rows)
    assert index == 0 and mapping['code'] == 2


def test_build_snapshots_expands_long_intervals():
    """一只票只写一条长区间时，也要出现在区间内的每个快照里。"""
    intervals = [
        ('20200101', '20201231', 'A.SH'),
        ('20200101', '', 'B.SH'),          # 失效日为空 = 至今有效
        ('20200701', '', 'C.SH'),
    ]
    snapshots = importer.build_snapshots(intervals)

    assert sorted(snapshots) == ['20200101', '20200701']
    assert snapshots['20200101'] == ['A.SH', 'B.SH']
    assert snapshots['20200701'] == ['A.SH', 'B.SH', 'C.SH']


def test_build_snapshots_drops_expired_members():
    intervals = [('20200101', '20200630', 'A.SH'), ('20200701', '', 'B.SH')]
    snapshots = importer.build_snapshots(intervals)
    assert snapshots['20200701'] == ['B.SH']


# ---------- 端到端 ----------

def make_workbook(path, rows, sheet_name='历史成分'):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(['沪深300历史成分股'])
    sheet.append(['每行代表一只证券在一个有效区间内属于沪深300'])
    sheet.append([])
    sheet.append(['生效日期', '失效日期', '证券代码', '证券简称'])
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


def test_end_to_end_writes_cache_csv(tmp_path):
    xlsx = make_workbook(str(tmp_path / 'in.xlsx'), [
        (datetime.datetime(2020, 1, 2), datetime.datetime(2020, 6, 30), '600000.SH', '浦发'),
        (datetime.datetime(2020, 1, 2), None, '000001.SZ', '平安银行'),
        (datetime.datetime(2020, 7, 1), None, '300750.SZ', '宁德时代'),
        (None, None, '合计', None),                     # 脏行，应被跳过
    ])
    output = str(tmp_path / 'out.csv')

    importer.main([xlsx, '-o', output])

    from hs300_ma_divergence.constituents import read_cache
    snapshots = read_cache(output)
    assert sorted(snapshots) == ['20200102', '20200701']
    assert snapshots['20200102'] == ['000001.SZ', '600000.SH']
    # 600000 的失效日是 20200630，7 月的快照里就不该有它了
    assert snapshots['20200701'] == ['000001.SZ', '300750.SZ']


def test_output_is_readable_by_the_backtest_provider(tmp_path):
    xlsx = make_workbook(str(tmp_path / 'in.xlsx'), [
        (datetime.datetime(2020, 1, 2), None, '600000.SH', '浦发'),
        (datetime.datetime(2020, 7, 1), None, '000001.SZ', '平安银行'),
    ])
    output = str(tmp_path / 'out.csv')
    importer.main([xlsx, '-o', output])

    from hs300_ma_divergence.constituents import ConstituentProvider
    provider = ConstituentProvider(xt=None, cache_file=output)
    source = provider.load(['20200102', '20200601', '20200701', '20201201'])

    assert source.startswith('cache:')
    assert provider.members_on('20200601') == ['600000.SH']
    assert provider.members_on('20201201') == ['000001.SZ', '600000.SH']


def test_missing_header_raises(tmp_path):
    workbook = openpyxl.Workbook()
    workbook.active.append(['随便', '什么'])
    path = str(tmp_path / 'bad.xlsx')
    workbook.save(path)

    with pytest.raises(SystemExit):
        importer.read_intervals(path)


def test_sheet_selection_prefers_constituent_sheet(tmp_path):
    workbook = openpyxl.Workbook()
    workbook.active.title = '概览'
    workbook.create_sheet('历史成分')
    workbook.create_sheet('调整明细')
    assert importer.pick_sheet(workbook).title == '历史成分'
    assert importer.pick_sheet(workbook, '调整明细').title == '调整明细'


# ---------- 仓库里那份真实数据 ----------

def test_shipped_cache_is_sane():
    path = os.path.join(ROOT, 'data', 'hs300_constituents.csv')
    if not os.path.exists(path):
        pytest.skip('该分支没有附带成分股缓存')

    from hs300_ma_divergence.constituents import read_cache
    snapshots = read_cache(path)

    assert len(snapshots) >= 10
    for day, members in snapshots.items():
        assert len(members) == 300, '%s 成分数应为 300，实际 %d' % (day, len(members))
        assert len(set(members)) == 300

    days = sorted(snapshots)
    first, last = set(snapshots[days[0]]), set(snapshots[days[-1]])
    # 几年下来必然有大量调整，这条能挡住"所有快照其实是同一份名单"的情况
    assert len(first - last) > 50 and len(last - first) > 50
