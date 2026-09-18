# coding: utf-8
"""
概念池 + 对数线性回归动量打分 + 风控过滤 + 大盘/个股择时 + 移动止损与硬止损

momentum_timing 包内是与交易接口无关的纯计算逻辑，
QMT 相关的取数与下单在 qmt/ 目录下。
"""

from . import config, indicators, portfolio, risk, scoring, signals, universe

__all__ = ['config', 'indicators', 'portfolio', 'risk', 'scoring', 'signals', 'universe']
__version__ = '0.1.0'
