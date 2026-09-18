# coding: utf-8
"""
把回测结果落盘：每次一个带时间戳的目录，方便多次回测横向对比。

    backtests/20240918_103000_hs300_ma/
        summary.txt     指标汇总 + 本次参数
        equity.csv      每日权益曲线
        trades.csv      每笔成交
        signals.csv     每日候选数量与目标组合
"""

import io
import json
import os
import time

from .metrics import format_summary, round_trips


def make_output_dir(base_dir, tag='hs300_ma'):
    """创建带时间戳的输出目录并返回路径。"""
    name = '%s_%s' % (time.strftime('%Y%m%d_%H%M%S'), tag)
    path = os.path.join(base_dir, name)
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def write_csv(path, rows, columns):
    with io.open(path, 'w', encoding='utf-8') as fp:
        fp.write(u','.join(columns) + u'\n')
        for row in rows:
            values = []
            for column in columns:
                value = row.get(column, '')
                if isinstance(value, float):
                    values.append('%.6f' % value)
                elif isinstance(value, (list, tuple)):
                    values.append('|'.join(str(v) for v in value))
                else:
                    values.append(str(value))
            fp.write(u','.join(values) + u'\n')
    return path


def write_report(output_dir, result, summary, params=None):
    """写出全部结果文件，返回 {名称: 路径}。"""
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    files = {}
    files['equity'] = write_csv(
        os.path.join(output_dir, 'equity.csv'), result['equity'],
        ['date', 'cash', 'market_value', 'total', 'holdings'])

    files['trades'] = write_csv(
        os.path.join(output_dir, 'trades.csv'), result['trades'],
        ['date', 'signal_date', 'stock', 'side', 'price', 'volume', 'amount',
         'fee', 'cash_after'])

    files['round_trips'] = write_csv(
        os.path.join(output_dir, 'round_trips.csv'), round_trips(result['trades']),
        ['stock', 'buy_date', 'sell_date', 'volume', 'pnl', 'return'])

    files['signals'] = write_csv(
        os.path.join(output_dir, 'signals.csv'), result['daily_signals'],
        ['date', 'candidates', 'target'])

    summary_path = os.path.join(output_dir, 'summary.txt')
    with io.open(summary_path, 'w', encoding='utf-8') as fp:
        fp.write(u'沪深300 五均线四级发散策略 —— 回测汇总\n')
        fp.write(u'=' * 60 + u'\n')
        fp.write(format_summary(summary) + u'\n')
        if params:
            fp.write(u'\n本次参数\n')
            fp.write(u'-' * 60 + u'\n')
            for key in sorted(params):
                fp.write(u'%-28s = %s\n' % (key, params[key]))
    files['summary'] = summary_path

    with io.open(os.path.join(output_dir, 'summary.json'), 'w', encoding='utf-8') as fp:
        payload = dict(summary)
        payload['params'] = params or {}
        fp.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    files['summary_json'] = os.path.join(output_dir, 'summary.json')

    return files
