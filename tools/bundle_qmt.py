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
    parts.append('本文件由 tools/bundle_qmt.py 自动生成，请勿直接修改。')
    parts.append('源码见 momentum_timing/ 与 qmt/strategy_backtest.py。')
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
