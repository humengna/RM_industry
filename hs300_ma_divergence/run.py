# coding: utf-8
"""
命令行入口：xtdata 取数 + 本地回测。

    # 第一次：补下载行情（需要 QMT / MiniQMT 客户端已登录）
    python -m hs300_ma_divergence --start 20230101 --end 20241231 --download

    # 之后直接回测，读本地数据
    python -m hs300_ma_divergence --start 20230101 --end 20241231

    # 只生成历史成分股缓存
    python -m hs300_ma_divergence --start 20200101 --end 20241231 --dump-constituents
"""

import argparse
import time

from . import config
from .constituents import ConstituentProvider
from .data import MarketData, import_xtdata
from .engine import Backtest
from .metrics import format_summary, summarize
from .report import make_output_dir, write_report

# 回测起点之前要多留一段历史，才够算 MA60
WARMUP_CALENDAR_DAYS = 200


def shift_date(date, days):
    """'YYYYMMDD' 往前推 days 个自然日。"""
    date = str(date)[:8]
    stamp = time.mktime((int(date[:4]), int(date[4:6]), int(date[6:8]), 12, 0, 0, 0, 0, -1))
    return time.strftime('%Y%m%d', time.localtime(stamp - days * 86400))


def run_backtest(start=config.START_DATE, end=config.END_DATE, cash=config.INIT_CASH,
                 xt=None, download=False, output_dir=config.OUTPUT_DIR,
                 cache_file=config.CONSTITUENT_CACHE,
                 granularity=config.CONSTITUENT_GRANULARITY,
                 allow_current_fallback=config.ALLOW_CURRENT_CONSTITUENTS_FALLBACK,
                 ascending=config.SORT_ASCENDING, max_holdings=config.MAX_HOLDINGS,
                 dividend_type=config.DIVIDEND_TYPE, verbose=config.PRINT_DAILY,
                 print_all_candidates=config.PRINT_ALL_CANDIDATES,
                 respect_limits=config.RESPECT_PRICE_LIMITS, slippage=config.SLIPPAGE,
                 max_weight=config.MAX_POSITION_WEIGHT, rank_start=config.RANK_START,
                 write_files=True):
    """跑一次完整回测，返回 (result, summary, files)。"""
    if not max_holdings or max_holdings < 1:
        raise ValueError('持仓股票数量必须 >= 1，当前为 %s' % max_holdings)
    if not rank_start or rank_start < 1:
        raise ValueError('排名起点必须 >= 1，当前为 %s' % rank_start)

    target_weight = 1.0 / max_holdings
    effective_weight = target_weight if max_weight is None else min(target_weight, max_weight)

    print('[配置] 持仓 %d 只（%s第 %d~%d 名），单只目标仓位 %.1f%%%s；初始资金 %.0f'
          % (max_holdings,
             '发散度升序' if ascending else '发散度倒序',
             rank_start, rank_start + max_holdings - 1,
             effective_weight * 100,
             '（受上限 %.0f%% 约束）' % (max_weight * 100)
             if max_weight is not None and target_weight > max_weight else '',
             cash))

    market = MarketData(xt=xt, dividend_type=dividend_type)
    data_start = shift_date(start, WARMUP_CALENDAR_DAYS)

    print('[1/5] 读取交易日历 %s ~ %s' % (data_start, end))
    if download:
        market.download([config.INDEX_CODE], data_start, end)
    all_days = market.trading_days(config.INDEX_CODE, data_start, end,
                                   download_if_missing=download)
    days = [d for d in all_days if d >= str(start)[:8]]
    if not days:
        raise ValueError('区间 %s ~ %s 内没有交易日' % (start, end))
    print('      交易日 %d 个，其中回测区间 %d 个' % (len(all_days), len(days)))

    print('[2/5] 准备历史成分股（%s 粒度）' % granularity)
    provider = ConstituentProvider(
        sector=config.INDEX_SECTOR, index_code=config.INDEX_CODE, xt=market.xt,
        cache_file=cache_file, granularity=granularity,
        allow_current_fallback=allow_current_fallback)
    source = provider.load(days)
    universe = provider.all_members()
    print('      数据来源: %s，区间内出现过 %d 只股票' % (source, len(universe)))

    if download:
        print('[3/5] 补下载 %d 只股票的日线' % len(universe))
        market.download(universe, data_start, end)
    else:
        print('[3/5] 跳过下载，直接读本地数据（首次运行请加 --download）')

    print('[4/5] 读取行情')
    bars = market.get_bars(universe, data_start, end)
    print('      取到 %d 只股票的日线' % len(bars))
    if not bars:
        raise ValueError('没有读到任何行情数据，请先用 --download 补下载')

    print('[5/5] 开始回测')
    backtest = Backtest(bars, days, provider, init_cash=cash, max_holdings=max_holdings,
                        ascending=ascending, verbose=verbose,
                        print_all_candidates=print_all_candidates,
                        respect_limits=respect_limits, slippage=slippage,
                        max_weight=max_weight, rank_start=rank_start)
    result = backtest.run()
    summary = summarize(result)

    params = {
        'start': start, 'end': end, 'init_cash': cash, 'max_holdings': max_holdings,
        'max_position_weight': max_weight, 'sort_ascending': ascending,
        'rank_start': rank_start, 'rank_range': '%d-%d' % (rank_start,
                                                           rank_start + max_holdings - 1),
        'dividend_type': dividend_type,
        'ma_periods': config.MA_PERIODS, 'constituent_source': source,
        'constituent_granularity': granularity, 'respect_price_limits': respect_limits,
        'slippage': slippage, 'commission_rate': config.COMMISSION_RATE,
        'stamp_tax_rate': config.STAMP_TAX_RATE,
    }

    print('')
    print('=' * 60)
    print(format_summary(summary))
    print('=' * 60)

    files = {}
    if write_files:
        path = make_output_dir(output_dir)
        files = write_report(path, result, summary, params)
        print('结果已写入 %s' % path)

    return result, summary, files


def dump_constituents(start, end, xt=None, cache_file=config.CONSTITUENT_CACHE,
                      granularity=config.CONSTITUENT_GRANULARITY, download=True):
    """
    只抓历史成分股并写缓存。

    需要一份交易日历来决定查哪些日期；本地还没有指数日线时会自动补下载。
    """
    market = MarketData(xt=xt)
    days = market.trading_days(config.INDEX_CODE, shift_date(start, 10), end,
                               download_if_missing=download)
    days = [d for d in days if d >= str(start)[:8]]
    provider = ConstituentProvider(
        sector=config.INDEX_SECTOR, index_code=config.INDEX_CODE, xt=market.xt,
        cache_file=cache_file, granularity=granularity, allow_current_fallback=False)
    source = provider.load(days)
    print('成分股来源: %s，快照 %d 个，覆盖 %d 只股票'
          % (source, len(provider.snapshots), len(provider.all_members())))
    return provider


def build_parser():
    parser = argparse.ArgumentParser(description='沪深300 五均线四级发散策略 · xtdata 本地回测')
    parser.add_argument('--start', default=config.START_DATE, help='回测开始日 YYYYMMDD')
    parser.add_argument('--end', default=config.END_DATE, help='回测结束日 YYYYMMDD')
    parser.add_argument('--cash', type=float, default=config.INIT_CASH, help='初始资金')
    parser.add_argument('--max-holdings', '-n', type=int, default=config.MAX_HOLDINGS,
                        help='持仓股票数量，默认 %d（单只目标仓位 = 1/该值）'
                             % config.MAX_HOLDINGS)
    parser.add_argument('--max-weight', type=float, default=config.MAX_POSITION_WEIGHT,
                        help='单只票的仓位上限，默认 %.2f' % config.MAX_POSITION_WEIGHT)
    parser.add_argument('--rank-start', type=int, default=config.RANK_START,
                        help='从排名第几位开始取（1 起算），默认 %d' % config.RANK_START)
    parser.add_argument('--rank', default=None, metavar='N-M',
                        help='排名区间简写，等价于同时设置 --rank-start 和 --max-holdings。'
                             '例：--rank 3-5 表示取第 3、4、5 名')
    parser.add_argument('--download', action='store_true',
                        help='先补下载行情（首次运行必须加）')
    parser.add_argument('--out', default=config.OUTPUT_DIR, help='结果输出目录')
    parser.add_argument('--cache', default=config.CONSTITUENT_CACHE,
                        help='历史成分股缓存 CSV')
    parser.add_argument('--granularity', default=config.CONSTITUENT_GRANULARITY,
                        choices=['day', 'month'], help='成分股快照粒度')
    parser.add_argument('--allow-current-constituents', action='store_true',
                        help='取不到历史成分股时退回当前成分股（结果有幸存者偏差）')
    parser.add_argument('--descending', action='store_true',
                        help='按总发散度从大到小取前 N（原脚本实际是从小到大）')
    parser.add_argument('--dividend', default=config.DIVIDEND_TYPE,
                        choices=['none', 'front', 'back', 'front_ratio', 'back_ratio'],
                        help='复权方式')
    parser.add_argument('--slippage', type=float, default=config.SLIPPAGE, help='滑点比例')
    parser.add_argument('--no-limits', action='store_true',
                        help='不考虑一字涨跌停的成交限制')
    parser.add_argument('--quiet', action='store_true', help='不打印每日明细')
    parser.add_argument('--all-candidates', action='store_true', help='打印全部候选')
    parser.add_argument('--dump-constituents', action='store_true',
                        help='只抓历史成分股写缓存，不回测')
    return parser


def parse_rank_range(text):
    """'3-5' -> (3, 3)：起点 3、取 3 只；'4' -> (4, 1)。"""
    text = str(text).strip()
    if '-' in text:
        start_text, end_text = text.split('-', 1)
        start, end = int(start_text), int(end_text)
    else:
        start = end = int(text)
    if start < 1 or end < start:
        raise ValueError('排名区间不合法：%s（应形如 3-5，且起点 >= 1）' % text)
    return start, end - start + 1


def main(argv=None):
    args = build_parser().parse_args(argv)

    rank_start, max_holdings = args.rank_start, args.max_holdings
    if args.rank:
        rank_start, max_holdings = parse_rank_range(args.rank)

    xt = import_xtdata()

    if args.dump_constituents:
        dump_constituents(args.start, args.end, xt=xt, cache_file=args.cache,
                          granularity=args.granularity, download=True)
        return 0

    run_backtest(
        start=args.start, end=args.end, cash=args.cash, xt=xt, download=args.download,
        output_dir=args.out, cache_file=args.cache, granularity=args.granularity,
        allow_current_fallback=args.allow_current_constituents,
        ascending=not args.descending, max_holdings=max_holdings,
        rank_start=rank_start,
        dividend_type=args.dividend, verbose=not args.quiet,
        print_all_candidates=args.all_candidates,
        respect_limits=not args.no_limits, slippage=args.slippage,
        max_weight=args.max_weight,
    )
    return 0
