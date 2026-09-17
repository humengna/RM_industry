# coding: utf-8
"""单文件打包工具：产物必须能编译，且不残留包内导入。"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))

import bundle_qmt  # noqa: E402


def test_bundle_compiles():
    code = bundle_qmt.build()
    compile(code, 'bundle', 'exec')


def test_bundle_has_no_package_imports():
    code = bundle_qmt.build()
    assert 'from momentum_timing' not in code
    assert 'from .' not in code
    assert '_bootstrap_sys_path' not in code


def test_bundle_keeps_qmt_entrypoints():
    code = bundle_qmt.build()
    for name in ('def init(C)', 'def handlebar(C)', 'def stop(C)', 'def adjust_position'):
        assert name in code


def test_bundle_defines_parameters_once():
    code = bundle_qmt.build()
    assert code.count('STOP_LOSS_RATIO = -0.15') == 1
    assert code.count('LOOKBACK_DAYS = 5') == 1


def test_bundled_script_runs_a_full_bar():
    """打包后的单文件也要能跑通一根 K 线并下单。"""
    from fake_qmt import FakeBroker, FakeContext, install_fake_qmt

    namespace = {'__name__': 'bundled_strategy'}
    exec(compile(bundle_qmt.build(), 'bundle', 'exec'), namespace)

    n_bars = 40
    dates = ['2024%02d%02d' % (1 + i // 28, 1 + i % 28) for i in range(n_bars)]
    closes = [round(10 * (1.02 ** i), 2) for i in range(n_bars)]
    prices = {
        '600001.SH': {
            'close': closes,
            'open': [round(c * 0.995, 2) for c in closes],
            'low': [round(c * 0.99, 2) for c in closes],
            'preClose': [closes[0]] + closes[:-1],
            'suspendFlag': [0] * n_bars,
        }
    }
    context = FakeContext(prices=prices, dates=dates,
                          sectors={'沪深a股': ['600001.SH']})
    broker = FakeBroker(available=100000.0)

    class Module(object):
        pass

    module = Module()
    module.__dict__ = namespace
    install_fake_qmt(module, context, broker)

    namespace['init'](context)
    namespace['g'].bar_count = namespace['WARMUP_BARS'] - 1
    namespace['handlebar'](context)

    buys = [o for o in broker.orders if o['op_type'] == namespace['OP_BUY']]
    assert len(buys) == 1
    assert buys[0]['stock'] == '600001.SH'
