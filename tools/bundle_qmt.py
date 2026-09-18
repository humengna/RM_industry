# coding: utf-8
"""
把 momentum_timing 包与 QMT 策略脚本打包成单文件，方便直接贴进 QMT 客户端。

用法：
    python tools/bundle_qmt.py                    # 生成 dist/momentum_timing_qmt.py (GBK)
    python tools/bundle_qmt.py -o my.py -e utf-8  # 自定义输出路径与编码

原理：按依赖顺序拼接各模块源码，去掉包内相对导入，
并删除策略脚本里 --BUNDLE-STRIP-START-- / --BUNDLE-STRIP-END-- 之间的 sys.path 引导代码。
"""

import argparse
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 依赖顺序：被依赖的在前
MODULES = [
    'config',
    'indicators',
    'universe',
    'risk',
    'intraday',
    'signals',
    'portfolio',
    'scoring',
]

ENTRY = os.path.join('qmt', 'strategy_backtest.py')

STRIP_START = '# --BUNDLE-STRIP-START--'
STRIP_END = '# --BUNDLE-STRIP-END--'

RELATIVE_IMPORT = re.compile(r'^\s*from\s+(\.|momentum_timing)')
CODING_LINE = re.compile(r'^\s*#\s*coding[:=]')


def read_text(path):
    with io.open(path, encoding='utf-8') as fp:
        return fp.read()


def clean_module_source(source):
    """去掉编码声明和包内导入（含括号跨行导入）。"""
    lines = source.splitlines()
    out = []
    skipping_paren_import = False

    for line in lines:
        stripped_import = skipping_paren_import or RELATIVE_IMPORT.match(line)
        if stripped_import and ' as ' in line:
            # 打包后模块被拼在一起，别名不会存在 -> 直接报错而不是产出坏文件
            raise ValueError(
                '包内导入不能使用 as 别名（打包后会变成未定义的名字）: %s' % line.strip())

        if skipping_paren_import:
            if ')' in line:
                skipping_paren_import = False
            continue
        if CODING_LINE.match(line):
            continue
        if stripped_import:
            if '(' in line and ')' not in line:
                skipping_paren_import = True
            continue
        out.append(line)

    return '\n'.join(out).strip('\n')


def strip_bootstrap(source):
    """删除 BUNDLE-STRIP 标记之间的内容。"""
    start = source.find(STRIP_START)
    end = source.find(STRIP_END)
    if start == -1 or end == -1:
        return source
    return source[:start] + source[end + len(STRIP_END):]


def build(encoding='gbk'):
    parts = []
    header_coding = 'gbk' if encoding.lower().replace('-', '') in ('gbk', 'gb2312', 'gb18030') else encoding
    parts.append('# coding:%s' % header_coding)
    parts.append('"""')
    parts.append('动量择时策略 [QMT 回测版] —— 单文件版')
    parts.append('')
    parts.append('本文件由 tools/bundle_qmt.py 自动生成，请勿直接改这里；')
    parts.append('源码在 momentum_timing/ 与 qmt/strategy_backtest.py，改完重新生成即可。')
    parts.append('')
    parts.append('用法：')
    parts.append('  1. 全选复制本文件内容，粘贴进 QMT 客户端的策略编辑器（内置 Python）')
    parts.append('  2. 回测周期必须选「日线」；主图品种挑一个有连续日线的即可，如 000300.SH')
    parts.append('  3. 把下面的 BACKTEST_ACCOUNT 改成你 QMT 里实际存在的模拟账号，')
    parts.append('     并在回测设置里选同一个账号（两处必须一致）')
    parts.append('  4. 首次运行建议先把 INTRADAY_ENABLED 设为 False 跑通流程，')
    parts.append('     补好 1 分钟历史数据后再打开分钟线风控')
    parts.append('  5. 回测起点前至少留 3 年日线数据，否则 RSRS 会一直提示数据不足')
    parts.append('')
    parts.append('编码：若 QMT 报编码相关的 SyntaxError，把第一行的 coding 换成另一种')
    parts.append('     （gbk 与 utf-8 互换），与 QMT 保存文件时使用的编码保持一致。')
    parts.append('"""')
    parts.append('')

    for name in MODULES:
        path = os.path.join(ROOT, 'momentum_timing', name + '.py')
        parts.append('# ' + '=' * 58)
        parts.append('# momentum_timing/%s.py' % name)
        parts.append('# ' + '=' * 58)
        parts.append(clean_module_source(read_text(path)))
        parts.append('')

    entry_source = strip_bootstrap(read_text(os.path.join(ROOT, ENTRY)))
    parts.append('# ' + '=' * 58)
    parts.append('# %s' % ENTRY.replace(os.sep, '/'))
    parts.append('# ' + '=' * 58)
    parts.append(clean_module_source(entry_source))
    parts.append('')

    return '\n'.join(parts)


def main():
    parser = argparse.ArgumentParser(description='生成 QMT 单文件策略脚本')
    parser.add_argument('-o', '--output',
                        default=os.path.join(ROOT, 'dist', 'momentum_timing_qmt.py'),
                        help='输出文件路径')
    parser.add_argument('-e', '--encoding', default='gbk',
                        help='输出文件编码，QMT 客户端一般用 gbk')
    args = parser.parse_args()

    code = build(args.encoding)
    compile(code, args.output, 'exec')  # 语法自检

    out_dir = os.path.dirname(os.path.abspath(args.output))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    with io.open(args.output, 'w', encoding=args.encoding, errors='replace') as fp:
        fp.write(code)

    print('已生成 %s (%s, %d 行)' % (args.output, args.encoding, len(code.splitlines())))


if __name__ == '__main__':
    main()
