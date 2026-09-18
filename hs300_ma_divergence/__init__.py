# coding: utf-8
"""
沪深300 五均线四级发散策略 —— xtdata 本地回测版。

与 QMT 内置 Python 版的区别：
  * 用 xtquant.xtdata 取数，不依赖 ContextInfo / passorder
  * 自带撮合引擎：T 日收盘选股、T+1 开盘成交、T+1 卖出限制、手续费与涨跌停限制
  * 成分股按当时的历史名单取（point-in-time），避免幸存者偏差
  * 每次回测输出一个带时间戳的结果目录（权益曲线 / 成交明细 / 指标汇总）
"""

from . import config, constituents, data, engine, metrics, report, signals

__all__ = ['config', 'constituents', 'data', 'engine', 'metrics', 'report', 'signals']
__version__ = '0.1.0'
