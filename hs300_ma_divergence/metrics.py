# coding: utf-8
"""回测绩效指标。纯函数，输入是引擎产出的权益曲线与成交记录。"""

import math

TRADING_DAYS_PER_YEAR = 244


def daily_returns(equity):
    """权益曲线 -> 日收益率序列。"""
    totals = [row['total'] for row in equity]
    returns = []
    for prev, cur in zip(totals[:-1], totals[1:]):
        if prev > 0:
            returns.append(cur / prev - 1)
    return returns


def total_return(equity):
    if not equity:
        return 0.0
    start, end = equity[0]['total'], equity[-1]['total']
    return end / start - 1 if start > 0 else 0.0


def annualized_return(equity, trading_days_per_year=TRADING_DAYS_PER_YEAR):
    if len(equity) < 2:
        return 0.0
    years = (len(equity) - 1) / float(trading_days_per_year)
    if years <= 0:
        return 0.0
    growth = 1 + total_return(equity)
    if growth <= 0:
        return -1.0
    return growth ** (1 / years) - 1


def max_drawdown(equity):
    """最大回撤（负数）与其发生区间。"""
    peak = None
    worst = 0.0
    peak_day = start_day = end_day = ''
    for row in equity:
        total = row['total']
        if peak is None or total > peak:
            peak, peak_day = total, row['date']
        if peak and peak > 0:
            drawdown = total / peak - 1
            if drawdown < worst:
                worst, start_day, end_day = drawdown, peak_day, row['date']
    return worst, start_day, end_day


def volatility(equity, trading_days_per_year=TRADING_DAYS_PER_YEAR):
    returns = daily_returns(equity)
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(var) * math.sqrt(trading_days_per_year)


def sharpe(equity, risk_free=0.0, trading_days_per_year=TRADING_DAYS_PER_YEAR):
    returns = daily_returns(equity)
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    daily_rf = risk_free / trading_days_per_year
    return (mean - daily_rf) / std * math.sqrt(trading_days_per_year)


def round_trips(trades):
    """
    把成交配成一笔笔平仓记录（移动平均成本）。

    返回 [{'stock', 'buy_date', 'sell_date', 'volume', 'pnl', 'return'}]
    """
    books = {}
    closed = []

    for trade in trades:
        stock = trade['stock']
        book = books.setdefault(stock, {'volume': 0, 'cost': 0.0, 'first_day': trade['date']})

        if trade['side'] == 'BUY':
            if book['volume'] == 0:
                book['first_day'] = trade['date']
            book['cost'] += trade['amount'] + trade['fee']
            book['volume'] += trade['volume']
        else:
            if book['volume'] <= 0:
                continue
            volume = min(trade['volume'], book['volume'])
            cost = book['cost'] * (volume / float(book['volume']))
            proceeds = trade['amount'] - trade['fee']
            if volume < trade['volume']:
                proceeds *= volume / float(trade['volume'])

            closed.append({
                'stock': stock,
                'buy_date': book['first_day'],
                'sell_date': trade['date'],
                'volume': volume,
                'pnl': round(proceeds - cost, 2),
                'return': (proceeds / cost - 1) if cost > 0 else 0.0,
            })
            book['volume'] -= volume
            book['cost'] -= cost
            if book['volume'] <= 0:
                book['volume'], book['cost'] = 0, 0.0

    return closed


def summarize(result, trading_days_per_year=TRADING_DAYS_PER_YEAR):
    """把引擎结果汇总成一份指标字典。"""
    equity = result.get('equity') or []
    trades = result.get('trades') or []
    closed = round_trips(trades)
    wins = [t for t in closed if t['pnl'] > 0]
    drawdown, dd_start, dd_end = max_drawdown(equity)
    fees = sum(t['fee'] for t in trades)

    return {
        'start_date': equity[0]['date'] if equity else '',
        'end_date': equity[-1]['date'] if equity else '',
        'trading_days': len(equity),
        'init_cash': result.get('init_cash', 0.0),
        'final_total': result.get('final_total', 0.0),
        'total_return': total_return(equity),
        'annualized_return': annualized_return(equity, trading_days_per_year),
        'max_drawdown': drawdown,
        'max_drawdown_from': dd_start,
        'max_drawdown_to': dd_end,
        'volatility': volatility(equity, trading_days_per_year),
        'sharpe': sharpe(equity, 0.0, trading_days_per_year),
        'trade_count': len(trades),
        'round_trips': len(closed),
        'win_rate': (len(wins) / float(len(closed))) if closed else 0.0,
        'avg_return_per_trade': (sum(t['return'] for t in closed) / len(closed)) if closed else 0.0,
        'total_fee': round(fees, 2),
        'skipped': result.get('skipped', {}),
    }


def format_summary(summary):
    """控制台用的多行文本。"""
    lines = [
        '区间          : %s ~ %s（%d 个交易日）' % (summary['start_date'], summary['end_date'],
                                                   summary['trading_days']),
        '初始资金      : %.2f' % summary['init_cash'],
        '期末总资产    : %.2f' % summary['final_total'],
        '总收益        : %.2f%%' % (summary['total_return'] * 100),
        '年化收益      : %.2f%%' % (summary['annualized_return'] * 100),
        '最大回撤      : %.2f%%  (%s -> %s)' % (summary['max_drawdown'] * 100,
                                                summary['max_drawdown_from'],
                                                summary['max_drawdown_to']),
        '年化波动      : %.2f%%' % (summary['volatility'] * 100),
        '夏普          : %.2f' % summary['sharpe'],
        '成交笔数      : %d（完整平仓 %d 笔）' % (summary['trade_count'], summary['round_trips']),
        '胜率          : %.2f%%' % (summary['win_rate'] * 100),
        '单笔平均收益  : %.2f%%' % (summary['avg_return_per_trade'] * 100),
        '总手续费      : %.2f' % summary['total_fee'],
    ]
    if summary.get('skipped'):
        items = sorted(summary['skipped'].items(), key=lambda kv: kv[1], reverse=True)
        lines.append('未成交统计    : %s' % ', '.join('%s×%d' % (k, v) for k, v in items))
    return '\n'.join(lines)
