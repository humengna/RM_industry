# coding: utf-8
"""
历史成分股（point-in-time）。

回测里用"今天的沪深300成分股"去跑历史，会引入严重的幸存者偏差——
当年被调出指数的票（往往是走弱的）不在池子里，当年还没调入的票（往往是走强的）
却提前出现在池子里，回测收益会系统性偏高。所以每个交易日都要用"当时"的成分股。

取数优先级：
  1. 本地缓存 CSV（date,stock），最可靠，也便于离线复现；
  2. xtdata.get_stock_list_in_sector(板块, real_timetag)  —— 新版 xtquant 支持
     传毫秒时间戳取历史成分；旧版没有这个参数，会自动跳过；
  3. 退回"当前成分股"（默认不允许，需显式打开 ALLOW_CURRENT_CONSTITUENTS_FALLBACK）。

注意：第 2 条依赖本机 QMT/MiniQMT 客户端的板块数据，不同版本支持程度不一样。
拿不到时最稳的做法是自己准备一份 CSV 喂给缓存（格式见 save_cache）。
"""

import io
import os
import time


class ConstituentError(Exception):
    """拿不到历史成分股。"""


def to_timetag(date, hour=15):
    """'YYYYMMDD' -> 毫秒时间戳（当日 15:00）。"""
    date = str(date)[:8]
    stamp = time.mktime((int(date[:4]), int(date[4:6]), int(date[6:8]),
                         hour, 0, 0, 0, 0, -1))
    return int(stamp * 1000)


def sample_dates(trading_days, granularity='month'):
    """
    按粒度挑出需要查询的日期。

    'day'   每个交易日都查
    'month' 每个自然月的第一个交易日查一次（沪深300 每年 6/12 月调整两次，够用）
    """
    trading_days = sorted(str(d)[:8] for d in trading_days)
    if granularity == 'day' or not trading_days:
        return list(trading_days)

    picked = []
    seen = set()
    for day in trading_days:
        key = day[:6]
        if key not in seen:
            seen.add(key)
            picked.append(day)
    return picked


class ConstituentProvider(object):
    """
    负责回答"某个交易日，指数成分股是哪些"。

    用法：
        provider = ConstituentProvider(xt=xtdata)
        provider.load(trading_days)
        provider.members_on('20240115')
    """

    def __init__(self, sector='沪深300', index_code='000300.SH', xt=None,
                 cache_file=None, granularity='month', allow_current_fallback=False):
        self.sector = sector
        self.index_code = index_code
        self.xt = xt
        self.cache_file = cache_file
        self.granularity = granularity
        self.allow_current_fallback = allow_current_fallback

        self.snapshots = {}     # {查询日: [股票]}
        self._sorted_dates = []
        self.source = None

    # ---------- 载入 ----------

    def load(self, trading_days):
        """准备好覆盖 trading_days 的成分股快照，返回本次使用的数据来源。"""
        trading_days = [str(d)[:8] for d in trading_days]
        if not trading_days:
            raise ConstituentError('交易日历为空，无法确定成分股区间')

        if self.cache_file and os.path.exists(self.cache_file):
            self.snapshots = read_cache(self.cache_file)
            if self._covers(trading_days):
                self.source = 'cache:%s' % self.cache_file
                self._index()
                return self.source
            print('[成分股] 缓存 %s 覆盖区间不足，尝试从 xtdata 补取' % self.cache_file)

        wanted = sample_dates(trading_days, self.granularity)
        fetched = self._fetch_from_xtdata(wanted)

        if fetched:
            self.snapshots.update(fetched)
            self.source = 'xtdata:sector_timetag'
            self._index()
            if self.cache_file:
                save_cache(self.cache_file, self.snapshots)
                print('[成分股] 已写入缓存 %s（%d 个快照）'
                      % (self.cache_file, len(self.snapshots)))
            return self.source

        if self.allow_current_fallback:
            current = self._current_members()
            if current:
                print('[成分股] 警告：取不到历史成分股，退回"当前成分股"。'
                      '回测结果会有幸存者偏差，仅供流程验证，不可用于评估策略收益。')
                self.snapshots = {trading_days[0]: current}
                self.source = 'xtdata:current(有幸存者偏差)'
                self._index()
                return self.source

        raise ConstituentError(
            '取不到 %s 的历史成分股。可选办法：\n'
            '  1) 自己准备一份 CSV（两列 date,stock，date 为 YYYYMMDD）放到 %s；\n'
            '  2) 升级 xtquant 到支持 get_stock_list_in_sector(板块, real_timetag) 的版本，'
            '并在 QMT 客户端补下载板块数据；\n'
            '  3) 确实只是想跑通流程，就把 ALLOW_CURRENT_CONSTITUENTS_FALLBACK 设为 True'
            '（结果带幸存者偏差）。'
            % (self.sector, self.cache_file or 'data/hs300_constituents.csv'))

    def _covers(self, trading_days):
        """缓存是否覆盖了回测区间的起点。"""
        if not self.snapshots:
            return False
        first_snapshot = min(self.snapshots)
        return first_snapshot <= trading_days[0]

    def _fetch_from_xtdata(self, dates):
        """逐个查询日取历史成分股；接口不支持时返回 {}。"""
        if self.xt is None:
            return {}

        getter = getattr(self.xt, 'get_stock_list_in_sector', None)
        if getter is None:
            return {}

        snapshots = {}
        for day in dates:
            try:
                members = getter(self.sector, to_timetag(day))
            except TypeError:
                # 旧版接口不接受 real_timetag，说明拿不到历史成分
                print('[成分股] 当前 xtquant 的 get_stock_list_in_sector 不支持历史时间点')
                return {}
            except Exception as e:
                print('[成分股] %s 查询失败: %s' % (day, e))
                continue

            members = sorted(set(members or []))
            if members:
                snapshots[day] = members

        if snapshots and len(set(tuple(v) for v in snapshots.values())) == 1 and len(snapshots) > 3:
            # 所有日期返回同一份名单：接口其实忽略了时间参数
            print('[成分股] 警告：不同日期返回的成分股完全相同，'
                  'xtdata 可能忽略了时间参数，按取不到历史成分处理')
            return {}

        return snapshots

    def _current_members(self):
        if self.xt is None:
            return []
        try:
            return sorted(set(self.xt.get_stock_list_in_sector(self.sector) or []))
        except Exception as e:
            print('[成分股] 取当前成分股失败: %s' % e)
            return []

    def _index(self):
        self._sorted_dates = sorted(self.snapshots)

    # ---------- 查询 ----------

    def members_on(self, day):
        """某个交易日的成分股：取不晚于该日的最近一个快照（前向填充）。"""
        day = str(day)[:8]
        chosen = None
        for snapshot_day in self._sorted_dates:
            if snapshot_day <= day:
                chosen = snapshot_day
            else:
                break
        if chosen is None:
            chosen = self._sorted_dates[0] if self._sorted_dates else None
        return list(self.snapshots.get(chosen, [])) if chosen else []

    def all_members(self):
        """回测区间内出现过的全部股票（用于一次性下载行情）。"""
        seen = set()
        for members in self.snapshots.values():
            seen.update(members)
        return sorted(seen)


# ============================================================
# 缓存读写
# ============================================================

def read_cache(path):
    """读 CSV 缓存，返回 {日期: [股票]}。"""
    snapshots = {}
    with io.open(path, encoding='utf-8') as fp:
        for line_no, line in enumerate(fp):
            line = line.strip()
            if not line:
                continue
            if line_no == 0 and line.lower().startswith('date'):
                continue
            parts = [p.strip() for p in line.split(',')]
            if len(parts) < 2:
                continue
            day = parts[0][:8]
            if not day.isdigit():
                continue
            snapshots.setdefault(day, []).append(parts[1])

    for day in snapshots:
        snapshots[day] = sorted(set(snapshots[day]))
    return snapshots


def save_cache(path, snapshots):
    """写 CSV 缓存：两列 date,stock，每个成分股一行。"""
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)

    with io.open(path, 'w', encoding='utf-8') as fp:
        fp.write(u'date,stock\n')
        for day in sorted(snapshots):
            for stock in sorted(snapshots[day]):
                fp.write(u'%s,%s\n' % (day, stock))
    return path
