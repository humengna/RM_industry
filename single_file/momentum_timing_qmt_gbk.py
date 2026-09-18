# coding:gbk
"""
动量择时策略 [QMT 回测版] —— 单文件版

本文件由 tools/bundle_qmt.py 自动生成，请勿直接改这里；
源码在 momentum_timing/ 与 qmt/strategy_backtest.py，改完重新生成即可。

用法：
  1. 全选复制本文件内容，粘贴进 QMT 客户端的策略编辑器（内置 Python）
  2. 回测周期必须选「日线」；主图品种挑一个有连续日线的即可，如 000300.SH
  3. 把下面的 BACKTEST_ACCOUNT 改成你 QMT 里实际存在的模拟账号，
     并在回测设置里选同一个账号（两处必须一致）
  4. 首次运行建议先把 INTRADAY_ENABLED 设为 False 跑通流程，
     补好 1 分钟历史数据后再打开分钟线风控
  5. 回测起点前至少留 3 年日线数据，否则 RSRS 会一直提示数据不足

编码：若 QMT 报编码相关的 SyntaxError，把第一行的 coding 换成另一种
     （gbk 与 utf-8 互换），与 QMT 保存文件时使用的编码保持一致。
"""

# ==========================================================
# momentum_timing/config.py
# ==========================================================
"""
策略参数配置

所有可调参数集中在此文件，核心计算模块与 QMT 策略脚本都从这里读取，
保证回测脚本与后续实盘脚本使用同一套参数。
"""

# ============================================================
# 运行模式（最重要的一个开关，放在最前面）
# ============================================================
# 'original' —— 最开始的选股逻辑：动量第 1 名直接买，不做任何风控过滤，
#               只保留 -15% 硬止损。风控相关的开关会在文件末尾被统一关掉。
# 'risk'     —— 在原逻辑之上叠加日线风控 / 分钟线风控 / 大盘择时 / 移动止损。
#
# 想把风控加回来：改成 'risk' 即可，代码都还在，阈值见下面各段。
STRATEGY_MODE = 'original'


# ============================================================
# 策略与账号
# ============================================================
STRATEGY_NAME = '动量择时策略'

# 回测使用的模拟资金账号
BACKTEST_ACCOUNT = 'testS'
# 账号类型：股票
ACCOUNT_TYPE = 'STOCK'


# ============================================================
# 股票池：概念板块
# ============================================================
# 完整的热门概念板块清单（需要按概念选股时把 CONCEPT_SECTORS 指向它）
CONCEPT_SECTORS_FULL = [
    '锂电池', '芯片', '人工智能', '光伏', '军工', '新能源车', '储能',
    '5G', '半导体', '国产软件', '云计算', '大数据', '物联网', '机器人',
    '氢能源', '风能', '核电', '特高压', '充电桩', '智能电网', '工业互联网',
    '数字货币', '区块链', '元宇宙', 'VR', '消费电子', '汽车电子', '无人驾驶',
    '高端装备', '新材料', '稀土永磁', '石墨烯', '碳纤维', '降解塑料',
    '医美', '创新药', '生物疫苗', '基因测序', '医疗器械', '中药',
    '白酒', '食品饮料', '免税', '电商', '网红经济', '在线教育',
    '卫星导航', '大飞机', '军民融合', '一带一路', '雄安新区', '海南自贸',
    '碳中和', '环保', '固废处理', '污水处理', '垃圾分类',
    '网络安全', '信创', '东数西算', '量子科技', '脑机接口',
]

# 当前生效的板块列表（与原脚本一致：默认整个沪深 A 股）
# 想回到概念池，改成 CONCEPT_SECTORS = CONCEPT_SECTORS_FULL 即可
CONCEPT_SECTORS = ['沪深a股']


# ============================================================
# 股票池过滤条件
# ============================================================
MIN_MARKET_CAP = 30e8     # 总市值下限 30 亿
MAX_MARKET_CAP = 500e8    # 总市值上限 500 亿
EXCLUDE_ST = True         # 剔除 ST / *ST
# 需要剔除的代码前缀，例如 ('300', '301', '688') 可屏蔽创业板与科创板
EXCLUDED_CODE_PREFIXES = ()


# ============================================================
# 动量打分参数
# ============================================================
LOOKBACK_DAYS = 5              # 动量回归窗口（原脚本注释中的备选值为 29）
TRADING_DAYS_PER_YEAR = 244    # 年化系数
SCORE_HISTORY_DAYS = 5         # 额外回溯多少天的历史动量分数


# ============================================================
# RSRS 大盘择时参数
# ============================================================
RSRS_N = 21              # 单次 high~low 回归的窗口长度
RSRS_M = 600             # 计算 zscore 的样本长度
RSRS_INDEX = '000300.SH' # 择时基准指数：沪深 300
# 原脚本中 RSRS 只做记录、不参与下单决策；改成 True 后才会否决买入信号
RSRS_ENABLED = False
RSRS_BUY_THRESHOLD = 0.7    # RSRS_ENABLED=True 时，修正标准分低于该值不买入


# ============================================================
# 个股择时与风控
# ============================================================
DECLINE_DAYS_TO_SELL = 2   # 动量分数连续下降达到该天数则卖出
STOP_LOSS_RATIO = -0.15    # 硬止损线 -15%
# KEEP 信号（分数序列取不到，或开启大盘风控后被否决）时是否照常买入。
# True = 原脚本行为；False = 不新开仓
BUY_ON_KEEP = True


# ============================================================
# 风控模块（momentum_timing/risk.py）
# ============================================================
# 动量打分天然偏好"连板 + 垂直拉升"的情绪票，这类票次日最容易一字跌停。
# 下面的阈值用于在下单前否决过热标的；设为 None 即关闭该项检查。
RISK_ENABLED = True

# 沿动量排名往下最多试几只候选股（第 1 名被风控否决就看第 2 名）。
# 这个值必须够大：打分公式天然把连板票排在最前面，只看前 5 名基本全是过热票，
# 结果就是天天没票可买。30 只大约对应"排名前 0.6% 里挑一只能买的"。
RISK_MAX_CANDIDATES = 30

# 动量分数下限：分数 <= 该值说明标的本身没有上涨趋势，不买
RISK_MIN_SCORE = 0.0

# --- 硬否决 vs 扣分 ---
# 二十多条规则如果全用"命中即否决"，任何一只票都过不了（每条都只有 80% 通过率，
# 连乘下来就是 0）。所以只有少数高精度规则硬否决，其余命中一次扣若干分，
# 扣分累计到 RISK_PENALTY_LIMIT 才否决。
#
# 想放松：调大 RISK_PENALTY_LIMIT（或改 RISK_PRESET = 'loose'）
# 想收紧：调小 RISK_PENALTY_LIMIT（=1 时等价于"命中任何一条就否决"）
RISK_PENALTY_LIMIT = 4

# 硬否决规则：命中即出局，不看扣分
RISK_HARD_RULES = (
    'data_insufficient',    # 数据不够，没法判断
    'weak_momentum',        # 分数 <= 0，本来就没有上涨趋势
    'limit_up_streak',      # 连板，次日跌停的头号来源
    'failed_limit_up',      # 炸板（分钟线）
    'limit_down_touch',     # 近几日盘中触及跌停（分钟线）
    'illiquid',             # 成交额太小，跌停时卖不掉
    'new_listing',          # 次新股
    'intraday_no_data',     # 分钟数据缺失且 INTRADAY_REQUIRE_DATA=True
)

# 软规则扣分权重，未列出的按 RISK_DEFAULT_PENALTY 计
RISK_RULE_PENALTY = {
    'gap_up': 4,            # 开盘就跳空，单条即可否决
    'gap_down': 4,
    'tail_selloff': 4,      # 前一日尾盘跳水
    'intraday_crash': 2,
    'tail_dump': 2,
    'high_distribution': 2,
    'limit_down_history': 2,
}
RISK_DEFAULT_PENALTY = 1

# 所有候选都被否决时，是否退而求其次买"扣分最低且无硬否决"的那只。
# 默认 False：宁可空仓也不买体检没过的票
RISK_FALLBACK_TO_BEST = False

# 打印每只候选的风控指标明细，用于按真实数据校准阈值（回测日志会很长）
RISK_DEBUG = False

# --- 过热：涨停与连板 ---
RISK_MAX_CONSECUTIVE_LIMIT_UP = 0   # 允许的连板数上限，0 = 前一日涨停就不碰【硬否决】
RISK_MAX_LIMIT_UP_COUNT = 3         # 近 RISK_LIMIT_UP_WINDOW 日涨停次数上限
RISK_LIMIT_UP_WINDOW = 10

# --- 过热：累计涨幅与乖离 ---
# 注意：本策略选的就是动量最强的票，涨幅和乖离天然偏高，
# 这几个阈值卡太死会和选股逻辑直接打架
RISK_MAX_GAIN_SHORT = 0.40          # 近 5 日累计涨幅上限 40%
RISK_GAIN_SHORT_WINDOW = 5
RISK_MAX_GAIN_LONG = 1.00           # 近 20 日累计涨幅上限 100%
RISK_GAIN_LONG_WINDOW = 20
RISK_MAX_BIAS = 0.30                # 相对 20 日均线的乖离率上限 30%
RISK_BIAS_WINDOW = 20

# --- 已在砸盘：近期出现过跌停 ---
RISK_MAX_LIMIT_DOWN_COUNT = 1       # 近 RISK_LIMIT_DOWN_WINDOW 日允许的跌停次数
RISK_LIMIT_DOWN_WINDOW = 60

# --- 波动 ---
RISK_MAX_AMPLITUDE = 0.12           # 近 5 日平均振幅上限 12%
RISK_AMPLITUDE_WINDOW = 5
RISK_MAX_VOLATILITY = 1.20          # 近 20 日收益率的年化波动率上限 120%
RISK_VOLATILITY_WINDOW = 20

# --- 资金异动与流动性 ---
RISK_MAX_VOLUME_RATIO = 5.0         # 量比（最新量 / 近 5 日均量）上限
RISK_VOLUME_WINDOW = 5
RISK_MAX_TURNOVER = 0.40            # 换手率上限 40%（需要流通股本，取不到则跳过）
RISK_MIN_AMOUNT = 5e7               # 近 5 日日均成交额下限 5000 万【硬否决】
RISK_AMOUNT_WINDOW = 5

# --- 结构 ---
RISK_MIN_LISTED_DAYS = 90           # 上市不足 90 个自然日的次新股不碰【硬否决】

# --- 当日开盘（09:31 可观测）---
RISK_MAX_GAP_UP = 0.07              # 高开超过 7% 不追
RISK_MAX_GAP_DOWN = 0.07            # 低开超过 7% 不接

# ============================================================
# 分钟线风控（momentum_timing/intraday.py）
# ============================================================
# 用"当前交易日之前"几天的分钟线和成交金额分布，识别次日容易跌停的结构：
# 炸板、尾盘跳水、收在日内低位、跌破 VWAP、高位派发、盘中触及跌停、天量滞涨。
INTRADAY_ENABLED = True
INTRADAY_DAYS = 3                       # 回看最近几个完整交易日
INTRADAY_BARS_PER_DAY = 245             # 取数时每天按多少根分钟线估算
INTRADAY_MIN_SESSION_BARS = 60          # 分钟 bar 少于该值的交易日视为数据异常，丢弃
# 分钟数据缺失时是否直接否决。QMT 默认不下载分钟数据，设 True 前先确认本地有数据
INTRADAY_REQUIRE_DATA = False

INTRADAY_TAIL_MINUTES = 30              # "尾盘"取最后多少分钟

# --- 涨跌停结构（统计最近 INTRADAY_DAYS 天）---
INTRADAY_MAX_FAILED_LIMIT_UP = 0        # 炸板（摸到涨停没封住）次数上限
INTRADAY_MAX_LIMIT_DOWN_TOUCH = 0       # 盘中触及跌停次数上限

# --- 最近一个交易日的日内结构 ---
INTRADAY_MIN_TAIL_RETURN = -0.04        # 尾盘 30 分钟跌幅下限 -4%
INTRADAY_MIN_CLOSE_POSITION = 0.15      # 收盘价在当日振幅区间中的最低位置
INTRADAY_MIN_VWAP_GAP = -0.025          # 收盘价相对 VWAP 的最低偏离 -2.5%
INTRADAY_MAX_DRAWDOWN = -0.10           # 日内最大回撤下限 -10%

# --- 成交金额分布 ---
INTRADAY_MAX_DOWN_AMOUNT_RATIO = 0.70   # 下跌分钟成交额占比上限（抛压主导）
INTRADAY_MAX_TAIL_AMOUNT_RATIO = 0.45   # 尾盘成交额占比上限（配合尾盘下跌才否决）
INTRADAY_MAX_POST_HIGH_AMOUNT_RATIO = 0.75  # 日内最高点之后的成交额占比上限
INTRADAY_MAX_AMOUNT_SPIKE = 5.0         # 最近一日成交额 / 前几日均额（天量滞涨）

# ============================================================
# 大盘风控
# ============================================================
MARKET_FILTER_ENABLED = True
MARKET_INDEX = '000300.SH'          # 基准指数
MARKET_MA_WINDOW = 20               # 指数收盘价跌破该均线视为大盘走弱
# 大盘走弱时的动作：'no_new' 只是不开新仓，'exit_all' 直接清仓
MARKET_FILTER_ACTION = 'no_new'

# ============================================================
# 持仓风控
# ============================================================
# 从持仓期间最高价回撤超过该比例就止盈/止损离场，None = 关闭
TRAILING_STOP_RATIO = 0.10
# 一字跌停（当日最高价即跌停价）时卖单其实成交不了，回测中跳过该笔卖出
ASSUME_LIMIT_DOWN_UNSELLABLE = True

# ============================================================
# 涨跌停与下单
# ============================================================
# 代码前缀 -> 涨跌停幅度，未命中的走 DEFAULT_LIMIT_RATIO
LIMIT_RATIO_BY_PREFIX = {
    '300': 0.20,
    '301': 0.20,
    '688': 0.20,
}
DEFAULT_LIMIT_RATIO = 0.10
LOT_SIZE = 100             # 一手股数


# ============================================================
# 回测运行参数
# ============================================================
# 前 WARMUP_BARS 根 K 线数据不足，不做任何交易
WARMUP_BARS = LOOKBACK_DAYS + 10


# ============================================================
# 风控档位（放在最后统一覆盖上面的阈值）
# ============================================================
# 'normal' 默认；'loose' 只保留硬否决类规则，软规则基本不拦；
# 'strict' 回到"命中任何一条就否决"的严格口径（容易天天空仓，调参时用来对照）
RISK_PRESET = 'normal'

if RISK_PRESET == 'loose':
    RISK_PENALTY_LIMIT = 8
    RISK_MAX_CANDIDATES = 50
    RISK_MAX_GAIN_SHORT = 0.60
    RISK_MAX_GAIN_LONG = 1.50
    RISK_MAX_BIAS = 0.45
    RISK_MAX_LIMIT_UP_COUNT = 5
    RISK_MAX_VOLUME_RATIO = 8.0
    RISK_MAX_TURNOVER = 0.60
    RISK_MAX_VOLATILITY = 1.80
    RISK_MAX_AMPLITUDE = 0.16
    RISK_MAX_GAP_UP = 0.09
    RISK_MAX_GAP_DOWN = 0.09
    INTRADAY_MIN_TAIL_RETURN = -0.06
    INTRADAY_MIN_CLOSE_POSITION = 0.10
    INTRADAY_MIN_VWAP_GAP = -0.04
    INTRADAY_MAX_DRAWDOWN = -0.14
    INTRADAY_MAX_DOWN_AMOUNT_RATIO = 0.80
    INTRADAY_MAX_AMOUNT_SPIKE = 8.0

elif RISK_PRESET == 'strict':
    RISK_PENALTY_LIMIT = 1
    RISK_MAX_CANDIDATES = 10
    RISK_MAX_GAIN_SHORT = 0.25
    RISK_MAX_GAIN_LONG = 0.60
    RISK_MAX_BIAS = 0.20
    RISK_MAX_LIMIT_UP_COUNT = 2
    RISK_MAX_LIMIT_DOWN_COUNT = 0
    RISK_MAX_VOLUME_RATIO = 3.0
    RISK_MAX_TURNOVER = 0.25
    RISK_MAX_VOLATILITY = 0.80
    RISK_MAX_AMPLITUDE = 0.09
    RISK_MAX_GAP_UP = 0.05
    RISK_MAX_GAP_DOWN = 0.05
    RISK_MIN_LISTED_DAYS = 120
    INTRADAY_MIN_TAIL_RETURN = -0.03
    INTRADAY_MIN_CLOSE_POSITION = 0.20
    INTRADAY_MIN_VWAP_GAP = -0.015
    INTRADAY_MAX_DRAWDOWN = -0.07
    INTRADAY_MAX_DOWN_AMOUNT_RATIO = 0.60
    INTRADAY_MAX_TAIL_AMOUNT_RATIO = 0.35
    INTRADAY_MAX_POST_HIGH_AMOUNT_RATIO = 0.65
    INTRADAY_MAX_AMOUNT_SPIKE = 3.0


# ============================================================
# 运行模式覆盖（放在最后，优先级高于上面所有设置）
# ============================================================
if STRATEGY_MODE == 'original':
    # 回到最开始的选股逻辑：买动量第 1 名，不做任何过滤
    RISK_ENABLED = False                    # 关掉日线风控（连板/涨幅/乖离/跳空…）
    INTRADAY_ENABLED = False                # 关掉分钟线风控（炸板/尾盘跳水/成交额…）
    MARKET_FILTER_ENABLED = False           # 关掉大盘均线择时
    TRAILING_STOP_RATIO = None              # 关掉移动止损，只留 -15% 硬止损
    ASSUME_LIMIT_DOWN_UNSELLABLE = False    # 一字跌停也照常发卖单（与原脚本一致）
    BUY_ON_KEEP = True                      # KEEP 信号照常买入（与原脚本一致）

# ==========================================================
# momentum_timing/indicators.py
# ==========================================================
"""
纯计算指标：一元线性回归、对数线性回归动量分数、RSRS 修正标准分。

本模块只依赖标准库（math），不依赖 numpy / pandas，
这样同一份逻辑既能在 QMT 里运行，也能被单元测试直接覆盖。
输入统一接受任意可迭代的数值序列（list / tuple / numpy array 均可）。
"""

import math



def _to_floats(seq):
    """把任意序列转成 float 列表；无法转换的元素变成 nan。"""
    out = []
    for v in seq:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(float('nan'))
    return out


def has_invalid(seq):
    """序列中是否存在 None / nan / inf。"""
    for v in _to_floats(seq):
        if math.isnan(v) or math.isinf(v):
            return True
    return False


def linear_regression(x, y):
    """
    一元最小二乘回归，等价于 numpy.polyfit(x, y, 1)。

    返回 (slope, r_squared)；样本不足或 x 无方差时返回 (0.0, 0.0)。
    """
    xs = _to_floats(x)
    ys = _to_floats(y)
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0, 0.0

    xs, ys = xs[:n], ys[:n]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    sxx = sum((xi - mean_x) ** 2 for xi in xs)
    if sxx == 0:
        return 0.0, 0.0

    sxy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(xs, ys))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x

    ss_res = sum((yi - (slope * xi + intercept)) ** 2 for xi, yi in zip(xs, ys))
    ss_tot = sum((yi - mean_y) ** 2 for yi in ys)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return slope, r2


def momentum_score(close_prices, trading_days_per_year=TRADING_DAYS_PER_YEAR):
    """
    动量分数 = 年化收益率 * |R2|

    对收盘价取对数后做线性回归，斜率年化：exp(slope * 244) - 1。
    R2 <= 0 返回 0.0；样本不足或含非法值返回 None。
    """
    prices = _to_floats(close_prices)
    if len(prices) < 2:
        return None
    for p in prices:
        if math.isnan(p) or math.isinf(p) or p <= 0:
            return None

    log_prices = [math.log(p) for p in prices]
    x = list(range(len(log_prices)))

    slope, r2 = linear_regression(x, log_prices)
    if r2 <= 0:
        return 0.0

    try:
        annual_return = math.exp(slope * trading_days_per_year) - 1
    except OverflowError:
        annual_return = float('inf')

    return annual_return * abs(r2)


def rsrs_betas(highs, lows, n):
    """
    滚动计算 RSRS 斜率序列：每个窗口用 low 回归 high。

    返回 (betas, r2_list)，长度均为 len(highs) - n + 1（跳过含非法值的窗口）。
    """
    hs = _to_floats(highs)
    ls = _to_floats(lows)
    size = min(len(hs), len(ls))
    betas, r2_list = [], []

    for i in range(n - 1, size):
        h = hs[i - n + 1:i + 1]
        l = ls[i - n + 1:i + 1]
        if len(h) < n or has_invalid(h) or has_invalid(l):
            continue
        slope, r2 = linear_regression(l, h)
        betas.append(slope)
        r2_list.append(r2)

    return betas, r2_list


def rsrs_corrected_zscore(highs, lows, n, m):
    """
    RSRS 修正标准分 = 最新斜率的 zscore * 最新窗口的 R2。

    highs / lows 为已剔除当前 bar 的历史数据；样本不足返回 None。
    """
    betas, r2_list = rsrs_betas(highs, lows, n)
    if len(betas) < m:
        return None

    recent = betas[-m:]
    mean_beta = sum(recent) / len(recent)
    var = sum((b - mean_beta) ** 2 for b in recent) / len(recent)
    std_beta = math.sqrt(var)
    if std_beta == 0:
        return 0.0

    zscore = (recent[-1] - mean_beta) / std_beta
    recent_r2 = r2_list[-1] if r2_list else 0.0
    return zscore * recent_r2

# ==========================================================
# momentum_timing/universe.py
# ==========================================================
"""
股票池过滤：涨跌停价、停牌、ST、市值、板块代码前缀。

这里全部是纯函数，行情由调用方（QMT 脚本）取好后传进来。
"""



def stock_code(stock):
    """'600000.SH' -> '600000'"""
    return str(stock).split('.')[0]


def limit_ratio(stock):
    """
    按代码前缀确定涨跌停幅度：
      创业板(300/301)、科创板(688) -> 20%
      其余（主板 60/00 等）        -> 10%
    """
    code = stock_code(stock)
    for prefix, ratio in LIMIT_RATIO_BY_PREFIX.items():
        if code.startswith(prefix):
            return ratio
    return DEFAULT_LIMIT_RATIO


def limit_prices(stock, pre_close):
    """返回 (涨停价, 跌停价)；pre_close 非法时返回 (0.0, 0.0)。"""
    try:
        pre_close = float(pre_close)
    except (TypeError, ValueError):
        return 0.0, 0.0
    if pre_close <= 0:
        return 0.0, 0.0

    ratio = limit_ratio(stock)
    return round(pre_close * (1 + ratio), 2), round(pre_close * (1 - ratio), 2)


def is_limit_down(stock, price, pre_close):
    """当前价是否已到跌停。"""
    _, down = limit_prices(stock, pre_close)
    return bool(down > 0 and price > 0 and price <= down)


def is_limit_up(stock, price, pre_close):
    """当前价是否已到涨停。"""
    up, _ = limit_prices(stock, pre_close)
    return bool(up > 0 and price > 0 and price >= up)


def is_excluded_code(stock, excluded_prefixes=EXCLUDED_CODE_PREFIXES):
    """代码前缀是否在屏蔽名单里。"""
    code = stock_code(stock)
    return any(code.startswith(p) for p in excluded_prefixes)


def is_st(stock_name, exclude_st=EXCLUDE_ST):
    """股票名称是否包含 ST。"""
    if not exclude_st or not stock_name:
        return False
    return 'ST' in str(stock_name).upper()


def market_cap_ok(total_value, min_cap=MIN_MARKET_CAP, max_cap=MAX_MARKET_CAP):
    """
    总市值是否落在区间内。

    取不到市值（<=0）时放行，与原脚本保持一致。
    """
    try:
        total_value = float(total_value)
    except (TypeError, ValueError):
        return True
    if total_value <= 0:
        return True
    return min_cap <= total_value <= max_cap


def passes_filters(stock, stock_name=None, total_value=0, suspend_flag=0,
                   close=0.0, pre_close=0.0,
                   excluded_prefixes=EXCLUDED_CODE_PREFIXES,
                   exclude_st=EXCLUDE_ST,
                   min_cap=MIN_MARKET_CAP, max_cap=MAX_MARKET_CAP):
    """
    股票池的完整过滤：代码前缀 -> 停牌 -> ST -> 市值 -> 跌停。

    返回 (是否通过, 未通过的原因)。
    """
    if is_excluded_code(stock, excluded_prefixes):
        return False, 'code_prefix'
    if suspend_flag == 1:
        return False, 'suspended'
    if is_st(stock_name, exclude_st):
        return False, 'st'
    if not market_cap_ok(total_value, min_cap, max_cap):
        return False, 'market_cap'
    if close and pre_close and is_limit_down(stock, close, pre_close):
        return False, 'limit_down'
    return True, ''

# ==========================================================
# momentum_timing/risk.py
# ==========================================================
"""
风控模块：把"已经涨疯了"的票在下单前拦掉。

背景：LOOKBACK_DAYS=5 的对数回归 + 244 天年化，会让连板/垂直拉升的票
拿到极高分数，排名第一的几乎必然是情绪最亢奋的那只——也正是次日容易
一字跌停、卖都卖不掉的那只。本模块按"过热 / 波动 / 流动性 / 结构"四类
指标给候选股打否决票。

约定（避免未来函数）：
  history  只包含"当前 bar 之前"的历史数据，是 09:31 决策时真实可见的；
  today    只包含当日开盘即可观测的信息（开盘价、前收），不含当日收盘价。
"""

import math


# 判断是否触及涨跌停的容差（元）：收盘价与涨跌停价相差 1 分以内即算封板
LIMIT_TOLERANCE = 0.011


# ============================================================
# 基础指标
# ============================================================

def _floats(seq):
    out = []
    for v in seq or []:
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = float('nan')
        out.append(f)
    return out


def _valid(value):
    return value is not None and not math.isnan(value) and not math.isinf(value)


def hit_limit_up(stock, close, pre_close):
    """当日是否涨停收盘。"""
    limit_up, _ = limit_prices(stock, pre_close)
    return bool(limit_up > 0 and close > 0 and close >= limit_up - LIMIT_TOLERANCE)


def hit_limit_down(stock, close, pre_close):
    """当日是否跌停收盘。"""
    _, limit_down = limit_prices(stock, pre_close)
    return bool(limit_down > 0 and close > 0 and close <= limit_down + LIMIT_TOLERANCE)


def limit_up_count(stock, closes, pre_closes, window):
    """最近 window 个交易日里涨停收盘的次数。"""
    closes, pre_closes = _floats(closes), _floats(pre_closes)
    n = min(len(closes), len(pre_closes), window)
    if n <= 0:
        return 0
    return sum(1 for i in range(-n, 0) if hit_limit_up(stock, closes[i], pre_closes[i]))


def limit_down_count(stock, closes, pre_closes, window):
    """最近 window 个交易日里跌停收盘的次数。"""
    closes, pre_closes = _floats(closes), _floats(pre_closes)
    n = min(len(closes), len(pre_closes), window)
    if n <= 0:
        return 0
    return sum(1 for i in range(-n, 0) if hit_limit_down(stock, closes[i], pre_closes[i]))


def consecutive_limit_up(stock, closes, pre_closes):
    """从最近一个交易日往回数，连续涨停（连板）的天数。"""
    closes, pre_closes = _floats(closes), _floats(pre_closes)
    n = min(len(closes), len(pre_closes))
    count = 0
    for i in range(n - 1, -1, -1):
        if hit_limit_up(stock, closes[i], pre_closes[i]):
            count += 1
        else:
            break
    return count


def cumulative_return(closes, window):
    """最近 window 个交易日的累计涨幅，数据不足返回 None。"""
    closes = _floats(closes)
    if len(closes) < window + 1:
        return None
    start, end = closes[-(window + 1)], closes[-1]
    if not _valid(start) or not _valid(end) or start <= 0:
        return None
    return end / start - 1


def moving_average(values, window):
    """最近 window 个值的均值，数据不足或含非法值返回 None。"""
    values = _floats(values)
    if len(values) < window or window <= 0:
        return None
    tail = values[-window:]
    if any(not _valid(v) for v in tail):
        return None
    return sum(tail) / window


def bias_ratio(closes, window):
    """乖离率 = (最新收盘 - MA) / MA，衡量偏离均线的程度。"""
    ma = moving_average(closes, window)
    closes = _floats(closes)
    if ma is None or ma <= 0 or not closes:
        return None
    return closes[-1] / ma - 1


def average_amplitude(highs, lows, pre_closes, window):
    """最近 window 日的平均振幅 = mean((high - low) / pre_close)。"""
    highs, lows, pre_closes = _floats(highs), _floats(lows), _floats(pre_closes)
    n = min(len(highs), len(lows), len(pre_closes), window)
    if n <= 0:
        return None

    values = []
    for i in range(-n, 0):
        high, low, pre_close = highs[i], lows[i], pre_closes[i]
        if not _valid(high) or not _valid(low) or not _valid(pre_close) or pre_close <= 0:
            continue
        values.append((high - low) / pre_close)
    return sum(values) / len(values) if values else None


def annualized_volatility(closes, window, trading_days=TRADING_DAYS_PER_YEAR):
    """最近 window 日收益率的年化波动率。"""
    closes = _floats(closes)
    if len(closes) < window + 1:
        return None

    tail = closes[-(window + 1):]
    returns = []
    for prev, cur in zip(tail[:-1], tail[1:]):
        if not _valid(prev) or not _valid(cur) or prev <= 0:
            return None
        returns.append(cur / prev - 1)
    if len(returns) < 2:
        return None

    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(var) * math.sqrt(trading_days)


def average_amount(amounts, window):
    """最近 window 日的平均成交额（元）。"""
    return moving_average(amounts, window)


def volume_ratio(volumes, window):
    """量比 = 最新成交量 / 最近 window 日均量。"""
    volumes = _floats(volumes)
    if len(volumes) < window + 1:
        return None
    base = moving_average(volumes[:-1], window)
    if base is None or base <= 0 or not _valid(volumes[-1]):
        return None
    return volumes[-1] / base


def turnover_rate(volume, float_volume):
    """换手率 = 成交量 / 流通股本；拿不到流通股本返回 None。"""
    try:
        volume = float(volume)
        float_volume = float(float_volume)
    except (TypeError, ValueError):
        return None
    if float_volume <= 0 or volume < 0:
        return None
    return volume / float_volume


def gap_ratio(open_price, pre_close):
    """跳空幅度 = 开盘价 / 前收 - 1。"""
    try:
        open_price = float(open_price)
        pre_close = float(pre_close)
    except (TypeError, ValueError):
        return None
    if open_price <= 0 or pre_close <= 0:
        return None
    return open_price / pre_close - 1


# ============================================================
# 风控参数与结果
# ============================================================

class RiskParams(object):
    """
    风控阈值。None 表示关闭该项检查。

    默认值取自 config，可在回测里临时覆盖：RiskParams(max_gap_up=0.03)
    """

    def __init__(self, **kwargs):
        self.max_consecutive_limit_up = RISK_MAX_CONSECUTIVE_LIMIT_UP
        self.max_limit_up_count = RISK_MAX_LIMIT_UP_COUNT
        self.limit_up_window = RISK_LIMIT_UP_WINDOW
        self.max_limit_down_count = RISK_MAX_LIMIT_DOWN_COUNT
        self.limit_down_window = RISK_LIMIT_DOWN_WINDOW
        self.max_gain_short = RISK_MAX_GAIN_SHORT
        self.gain_short_window = RISK_GAIN_SHORT_WINDOW
        self.max_gain_long = RISK_MAX_GAIN_LONG
        self.gain_long_window = RISK_GAIN_LONG_WINDOW
        self.max_bias = RISK_MAX_BIAS
        self.bias_window = RISK_BIAS_WINDOW
        self.max_amplitude = RISK_MAX_AMPLITUDE
        self.amplitude_window = RISK_AMPLITUDE_WINDOW
        self.max_volatility = RISK_MAX_VOLATILITY
        self.volatility_window = RISK_VOLATILITY_WINDOW
        self.max_turnover = RISK_MAX_TURNOVER
        self.max_volume_ratio = RISK_MAX_VOLUME_RATIO
        self.volume_window = RISK_VOLUME_WINDOW
        self.min_amount = RISK_MIN_AMOUNT
        self.amount_window = RISK_AMOUNT_WINDOW
        self.min_listed_days = RISK_MIN_LISTED_DAYS
        self.max_gap_up = RISK_MAX_GAP_UP
        self.max_gap_down = RISK_MAX_GAP_DOWN
        self.min_score = RISK_MIN_SCORE

        for key, value in kwargs.items():
            if not hasattr(self, key):
                raise TypeError('未知风控参数: %s' % key)
            setattr(self, key, value)


def rule_penalty(reason, weights=None, default=None):
    """单条软规则的扣分。"""
    weights = RISK_RULE_PENALTY if weights is None else weights
    default = RISK_DEFAULT_PENALTY if default is None else default
    return weights.get(reason, default)


class RiskResult(object):
    """
    风控结论。

    判定分两层，避免"二十条规则全用命中即否决"导致谁都过不了：
      硬否决  命中 RISK_HARD_RULES 里的任意一条 -> 直接出局
      扣分制  其余规则各自扣分，累计 >= RISK_PENALTY_LIMIT 才出局

    passed 显式传入时以传入值为准（构造已知结论的场景）；
    调用 add() 追加原因后一律按上面的规则重新判定。
    """

    def __init__(self, passed=None, reasons=None, metrics=None,
                 hard_rules=None, weights=None, limit=None, default_penalty=None):
        self.hard_rules = RISK_HARD_RULES if hard_rules is None else hard_rules
        self.weights = RISK_RULE_PENALTY if weights is None else weights
        self.limit = RISK_PENALTY_LIMIT if limit is None else limit
        self.default_penalty = (RISK_DEFAULT_PENALTY if default_penalty is None
                                else default_penalty)
        self.reasons = list(reasons or [])
        self.metrics = dict(metrics or {})

        self.recompute()
        if passed is not None:
            self.passed = passed

    def recompute(self):
        """按硬否决 + 扣分重新判定。"""
        self.hard = [r for r in self.reasons if r in self.hard_rules]
        self.penalty = sum(rule_penalty(r, self.weights, self.default_penalty)
                           for r in self.reasons if r not in self.hard_rules)
        self.passed = not self.hard and self.penalty < self.limit
        return self.passed

    def add(self, reasons=None, metrics=None):
        """追加否决原因与指标（例如把分钟线的结论并进来），并重新判定。"""
        for reason in reasons or []:
            if reason not in self.reasons:
                self.reasons.append(reason)
        if metrics:
            self.metrics.update(metrics)
        return self.recompute()

    def __repr__(self):
        return ('RiskResult(passed=%s, penalty=%s, reasons=%s)'
                % (self.passed, self.penalty, self.reasons))

    def describe(self):
        """给日志用的一行说明。"""
        if self.passed:
            return 'PASS' if not self.reasons else 'PASS(扣分%d/%d: %s)' % (
                self.penalty, self.limit, ','.join(self.reasons))
        if self.hard:
            return 'REJECT[硬否决: %s]' % ','.join(self.hard)
        return 'REJECT[扣分%d>=%d: %s]' % (
            self.penalty, self.limit, ','.join(self.reasons))


# ============================================================
# 总入口
# ============================================================

def history_bars_needed(params=None):
    """风控需要多少根历史 K 线（不含当前 bar），供取数时确定 count。"""
    params = params or RiskParams()
    needs = [2]
    if params.max_limit_up_count is not None:
        needs.append(params.limit_up_window)
    if params.max_limit_down_count is not None:
        needs.append(params.limit_down_window)
    if params.max_gain_short is not None:
        needs.append(params.gain_short_window + 1)
    if params.max_gain_long is not None:
        needs.append(params.gain_long_window + 1)
    if params.max_bias is not None:
        needs.append(params.bias_window)
    if params.max_amplitude is not None:
        needs.append(params.amplitude_window)
    if params.max_volatility is not None:
        needs.append(params.volatility_window + 1)
    if params.max_volume_ratio is not None:
        needs.append(params.volume_window + 1)
    if params.min_amount is not None:
        needs.append(params.amount_window)
    return max(needs)


def evaluate_candidate(stock, history, today=None, params=None, listed_days=None,
             float_volume=None, score=None):
    """
    对候选股做风控体检。

    history: 排除当前 bar 的历史行情，dict of list：
             close / pre_close 必需，high / low / volume / amount 可选
    today:   当日开盘即可见的信息，dict：open / pre_close
    listed_days: 上市天数（由 get_instrument_detail 的 OpenDate 推算）
    float_volume: 流通股本，用于算换手率
    score:   该股的动量分数，用于过滤没有上涨趋势的标的

    返回 RiskResult。
    """
    params = params or RiskParams()
    today = today or {}

    closes = _floats(history.get('close'))
    pre_closes = _floats(history.get('pre_close'))
    highs = _floats(history.get('high'))
    lows = _floats(history.get('low'))
    volumes = _floats(history.get('volume'))
    amounts = _floats(history.get('amount'))

    reasons = []
    metrics = {}

    if score is not None:
        metrics['score'] = score
        if params.min_score is not None and score <= params.min_score:
            reasons.append('weak_momentum')

    if len(closes) < 2 or len(pre_closes) < 2:
        reasons.append('data_insufficient')
        return RiskResult(reasons=reasons, metrics=metrics)

    # ---------- 过热：连板 / 涨停次数 / 累计涨幅 / 乖离 ----------
    streak = consecutive_limit_up(stock, closes, pre_closes)
    metrics['consecutive_limit_up'] = streak
    if params.max_consecutive_limit_up is not None and streak > params.max_consecutive_limit_up:
        reasons.append('limit_up_streak')

    if params.max_limit_up_count is not None:
        count = limit_up_count(stock, closes, pre_closes, params.limit_up_window)
        metrics['limit_up_count'] = count
        if count > params.max_limit_up_count:
            reasons.append('limit_up_count')

    if params.max_gain_short is not None:
        gain = cumulative_return(closes, params.gain_short_window)
        metrics['gain_short'] = gain
        if gain is not None and gain > params.max_gain_short:
            reasons.append('gain_short')

    if params.max_gain_long is not None:
        gain = cumulative_return(closes, params.gain_long_window)
        metrics['gain_long'] = gain
        if gain is not None and gain > params.max_gain_long:
            reasons.append('gain_long')

    if params.max_bias is not None:
        bias = bias_ratio(closes, params.bias_window)
        metrics['bias'] = bias
        if bias is not None and bias > params.max_bias:
            reasons.append('bias')

    # ---------- 已经在砸盘：近期出现过跌停 ----------
    if params.max_limit_down_count is not None:
        count = limit_down_count(stock, closes, pre_closes, params.limit_down_window)
        metrics['limit_down_count'] = count
        if count > params.max_limit_down_count:
            reasons.append('limit_down_history')

    # ---------- 波动 ----------
    if params.max_amplitude is not None and highs and lows:
        amplitude = average_amplitude(highs, lows, pre_closes, params.amplitude_window)
        metrics['amplitude'] = amplitude
        if amplitude is not None and amplitude > params.max_amplitude:
            reasons.append('amplitude')

    if params.max_volatility is not None:
        vol = annualized_volatility(closes, params.volatility_window)
        metrics['volatility'] = vol
        if vol is not None and vol > params.max_volatility:
            reasons.append('volatility')

    # ---------- 资金异动与流动性 ----------
    if params.max_volume_ratio is not None and volumes:
        ratio = volume_ratio(volumes, params.volume_window)
        metrics['volume_ratio'] = ratio
        if ratio is not None and ratio > params.max_volume_ratio:
            reasons.append('volume_spike')

    if params.max_turnover is not None and volumes and float_volume:
        turnover = turnover_rate(volumes[-1], float_volume)
        metrics['turnover'] = turnover
        if turnover is not None and turnover > params.max_turnover:
            reasons.append('turnover')

    if params.min_amount is not None and amounts:
        amount = average_amount(amounts, params.amount_window)
        metrics['amount'] = amount
        if amount is not None and amount < params.min_amount:
            reasons.append('illiquid')

    # ---------- 次新股 ----------
    if params.min_listed_days is not None and listed_days is not None:
        metrics['listed_days'] = listed_days
        if listed_days < params.min_listed_days:
            reasons.append('new_listing')

    # ---------- 当日开盘：追高 / 低开 ----------
    gap = gap_ratio(today.get('open'), today.get('pre_close'))
    if gap is not None:
        metrics['gap'] = gap
        if params.max_gap_up is not None and gap > params.max_gap_up:
            reasons.append('gap_up')
        if params.max_gap_down is not None and gap < -abs(params.max_gap_down):
            reasons.append('gap_down')

    return RiskResult(reasons=reasons, metrics=metrics)


def market_is_healthy(index_closes, ma_window):
    """
    大盘风控：指数收盘价站上 ma_window 日均线才算健康。

    返回 (是否健康, {'close':…, 'ma':…})；数据不足时按"健康"处理，
    避免回测初期因为数据不够而整段空仓。
    """
    closes = _floats(index_closes)
    ma = moving_average(closes, ma_window)
    if ma is None or not closes or not _valid(closes[-1]):
        return True, {}
    return closes[-1] >= ma, {'close': closes[-1], 'ma': ma}


def pick_first_passing(ranked, evaluator, max_candidates=None):
    """
    沿动量排名从高到低找第一只通过风控的股票。

    ranked:    [(股票, 分数), ...]，已按分数降序
    evaluator: 函数 stock -> RiskResult
    返回 (股票, RiskResult, 被否决的 [(股票, RiskResult), ...])；全被否决时股票为 None
    """
    rejected = []
    for i, item in enumerate(ranked):
        if max_candidates is not None and i >= max_candidates:
            break
        stock = item[0] if isinstance(item, (tuple, list)) else item
        result = evaluator(stock)
        if result.passed:
            return stock, result, rejected
        rejected.append((stock, result))
    return None, None, rejected


def best_of_rejected(rejected):
    """
    全部被否决时，挑扣分最低且没有硬否决的那只。

    给 RISK_FALLBACK_TO_BEST 用；没有可选的返回 (None, None)。
    """
    candidates = [(stock, result) for stock, result in rejected if not result.hard]
    if not candidates:
        return None, None
    return min(candidates, key=lambda item: item[1].penalty)


def reason_counts(rejected):
    """把否决原因汇总成 {原因: 次数}，用于定位"是哪条规则把票全拦了"。"""
    counts = {}
    for _stock, result in rejected:
        for reason in result.reasons:
            counts[reason] = counts.get(reason, 0) + 1
    return counts

# ==========================================================
# momentum_timing/intraday.py
# ==========================================================
"""
分钟线风控：用前几个交易日的日内走势和成交金额分布，提前剔除次日容易跌停的票。

日线只能看到"涨了多少"，看不到"怎么涨的"。真正预告次日跌停的是日内结构：

  炸板       盘中摸到涨停又没封住 —— 接盘资金已经跑了，次日补跌概率最高
  尾盘跳水   最后半小时放量下砸 —— 次日大概率低开，低开就容易奔跌停
  收在低位   全天冲高回落、收盘价贴着当日最低 —— 抛压还没释放完
  跌破 VWAP  当日买入者平均浮亏 —— 次日一有风吹草动就集体离场
  高位派发   日内最高点之后成交额占比过大 —— 主力在高位出货
  触及跌停   盘中摸过跌停 —— 跌停有惯性，次日往往继续

约定（避免未来函数）：只使用"当前交易日之前"的完整交易日分钟数据，
当日分钟线在 09:31 决策时还不存在。
"""

import math


# 与日线保持一致的封板容差（元）
LIMIT_TOLERANCE = 0.011

INTRADAY_FIELDS = ('open', 'high', 'low', 'close', 'volume', 'amount')


def _floats(seq):
    out = []
    for v in seq or []:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(float('nan'))
    return out


def _valid(value):
    return value is not None and not math.isnan(value) and not math.isinf(value)


def _clean(values):
    return [v for v in values if _valid(v)]


# ============================================================
# 分钟线 -> 交易日切分
# ============================================================

def group_sessions(times, fields):
    """
    把连续的分钟线按交易日切分。

    times:  ['20240110093100', '20240110093200', ...]
    fields: {'close': [...], 'amount': [...], ...}，与 times 等长
    返回 [{'date': '20240110', 'close': [...], ...}, ...]，按时间升序
    """
    sessions = []
    current = None

    for i, timestamp in enumerate(times or []):
        day = str(timestamp)[:8]
        if len(day) != 8:
            continue
        if current is None or current['date'] != day:
            current = {'date': day}
            for name in INTRADAY_FIELDS:
                current[name] = []
            sessions.append(current)
        for name in INTRADAY_FIELDS:
            values = fields.get(name)
            if values is not None and i < len(values):
                try:
                    current[name].append(float(values[i]))
                except (TypeError, ValueError):
                    current[name].append(float('nan'))

    return sessions


def attach_pre_close(sessions, first_pre_close=None):
    """
    给每个交易日补上前收盘价：前一个交易日的最后一根分钟线收盘价。

    第一个交易日没有前一日可用，取 first_pre_close，取不到就用当日第一根开盘价。
    """
    prev_close = first_pre_close
    for session in sessions:
        closes = _clean(session.get('close'))
        opens = _clean(session.get('open'))
        if prev_close is not None and prev_close > 0:
            session['pre_close'] = prev_close
        elif opens:
            session['pre_close'] = opens[0]
        else:
            session['pre_close'] = None
        if closes:
            prev_close = closes[-1]
    return sessions


def complete_sessions(sessions, min_bars=INTRADAY_MIN_SESSION_BARS):
    """只保留分钟 bar 数量正常的交易日（半日市、停牌半天的数据直接丢掉）。"""
    return [s for s in sessions if len(_clean(s.get('close'))) >= min_bars]


def sessions_before(sessions, date):
    """只保留 date 之前的完整交易日（当日分钟线在 09:31 还看不到）。"""
    return [s for s in sessions if s.get('date') and s['date'] < str(date)[:8]]


# ============================================================
# 单个交易日的日内指标
# ============================================================

def session_amounts(session):
    """分钟成交额序列；没有 amount 字段时用 close * volume 估算。"""
    amounts = _floats(session.get('amount'))
    if amounts and any(_valid(a) and a > 0 for a in amounts):
        return amounts

    closes = _floats(session.get('close'))
    volumes = _floats(session.get('volume'))
    out = []
    for i in range(min(len(closes), len(volumes))):
        if _valid(closes[i]) and _valid(volumes[i]):
            out.append(closes[i] * volumes[i])
        else:
            out.append(float('nan'))
    return out


def total_amount(session):
    """当日成交金额合计。"""
    return sum(_clean(session_amounts(session)))


def vwap(session):
    """成交额加权均价；拿不到成交量时退化为分钟收盘价均值。"""
    amounts = _clean(session_amounts(session))
    volumes = _clean(_floats(session.get('volume')))
    if amounts and volumes and sum(volumes) > 0 and len(amounts) == len(volumes):
        return sum(amounts) / sum(volumes)

    closes = _clean(_floats(session.get('close')))
    return sum(closes) / len(closes) if closes else None


def close_position(session):
    """
    收盘价在当日振幅区间中的位置，0 = 收在最低价，1 = 收在最高价。

    收在下沿说明全天是被卖出去的，次日低开概率大。
    """
    highs = _clean(_floats(session.get('high')))
    lows = _clean(_floats(session.get('low')))
    closes = _clean(_floats(session.get('close')))
    if not highs or not lows or not closes:
        return None

    high, low, close = max(highs), min(lows), closes[-1]
    if high <= low:
        return None
    return (close - low) / (high - low)


def vwap_gap(session):
    """收盘价相对当日 VWAP 的偏离；为负说明当日买入者整体浮亏。"""
    price = vwap(session)
    closes = _clean(_floats(session.get('close')))
    if price is None or price <= 0 or not closes:
        return None
    return closes[-1] / price - 1


def intraday_drawdown(session):
    """当日盘中最大回撤：从已出现的最高点到之后最低点的最大跌幅（负数）。"""
    highs = _floats(session.get('high'))
    lows = _floats(session.get('low'))
    n = min(len(highs), len(lows))
    if n == 0:
        return None

    peak = None
    worst = 0.0
    for i in range(n):
        if _valid(highs[i]):
            peak = highs[i] if peak is None else max(peak, highs[i])
        if peak and peak > 0 and _valid(lows[i]):
            worst = min(worst, lows[i] / peak - 1)
    return worst


def tail_return(session, minutes=INTRADAY_TAIL_MINUTES):
    """尾盘涨跌幅：最后 minutes 根分钟线的收盘 / 起点 - 1。"""
    closes = _clean(_floats(session.get('close')))
    if len(closes) < minutes + 1:
        return None
    start = closes[-(minutes + 1)]
    if start <= 0:
        return None
    return closes[-1] / start - 1


def tail_amount_ratio(session, minutes=INTRADAY_TAIL_MINUTES):
    """尾盘成交额占全天的比例。"""
    amounts = _clean(session_amounts(session))
    if len(amounts) < minutes:
        return None
    total = sum(amounts)
    if total <= 0:
        return None
    return sum(amounts[-minutes:]) / total


def down_amount_ratio(session):
    """
    下跌分钟的成交额占比，作为"主动性抛压"的代理指标。

    超过 0.6 说明当天的成交金额主要是在往下砸的过程中打出来的。
    """
    closes = _floats(session.get('close'))
    amounts = session_amounts(session)
    n = min(len(closes), len(amounts))
    if n < 2:
        return None

    total, down = 0.0, 0.0
    for i in range(1, n):
        if not _valid(closes[i]) or not _valid(closes[i - 1]) or not _valid(amounts[i]):
            continue
        total += amounts[i]
        if closes[i] < closes[i - 1]:
            down += amounts[i]
    if total <= 0:
        return None
    return down / total


def post_high_amount_ratio(session):
    """
    日内最高点之后的成交额占比：高位派发的直接证据。

    冲高之后如果大部分成交金额是在回落过程中打出来的，就是主力在出货。
    """
    highs = _floats(session.get('high'))
    amounts = session_amounts(session)
    n = min(len(highs), len(amounts))
    if n < 2:
        return None

    peak_idx, peak = None, None
    for i in range(n):
        if _valid(highs[i]) and (peak is None or highs[i] > peak):
            peak, peak_idx = highs[i], i
    if peak_idx is None:
        return None

    total = sum(a for a in amounts[:n] if _valid(a))
    if total <= 0:
        return None
    after = sum(a for a in amounts[peak_idx + 1:n] if _valid(a))
    return after / total


def touched_limit_up(stock, session, pre_close=None):
    """当日盘中是否摸到过涨停价。"""
    pre_close = pre_close if pre_close is not None else session.get('pre_close')
    limit_up, _ = limit_prices(stock, pre_close)
    highs = _clean(_floats(session.get('high')))
    if limit_up <= 0 or not highs:
        return False
    return max(highs) >= limit_up - LIMIT_TOLERANCE


def closed_limit_up(stock, session, pre_close=None):
    """当日是否以涨停价收盘。"""
    pre_close = pre_close if pre_close is not None else session.get('pre_close')
    limit_up, _ = limit_prices(stock, pre_close)
    closes = _clean(_floats(session.get('close')))
    if limit_up <= 0 or not closes:
        return False
    return closes[-1] >= limit_up - LIMIT_TOLERANCE


def failed_limit_up(stock, session, pre_close=None):
    """炸板：盘中摸到涨停但收盘没封住。"""
    return (touched_limit_up(stock, session, pre_close)
            and not closed_limit_up(stock, session, pre_close))


def touched_limit_down(stock, session, pre_close=None):
    """当日盘中是否摸到过跌停价。"""
    pre_close = pre_close if pre_close is not None else session.get('pre_close')
    _, limit_down = limit_prices(stock, pre_close)
    lows = _clean(_floats(session.get('low')))
    if limit_down <= 0 or not lows:
        return False
    return min(lows) <= limit_down + LIMIT_TOLERANCE


def session_metrics(stock, session, tail_minutes=INTRADAY_TAIL_MINUTES):
    """把一个交易日的日内指标算成一个 dict，用于否决判断与日志。"""
    return {
        'date': session.get('date'),
        'amount': total_amount(session),
        'close_position': close_position(session),
        'vwap_gap': vwap_gap(session),
        'drawdown': intraday_drawdown(session),
        'tail_return': tail_return(session, tail_minutes),
        'tail_amount_ratio': tail_amount_ratio(session, tail_minutes),
        'down_amount_ratio': down_amount_ratio(session),
        'post_high_amount_ratio': post_high_amount_ratio(session),
        'failed_limit_up': failed_limit_up(stock, session),
        'closed_limit_up': closed_limit_up(stock, session),
        'touched_limit_down': touched_limit_down(stock, session),
    }


# ============================================================
# 参数与总入口
# ============================================================

class IntradayParams(object):
    """分钟线风控阈值，None 表示关闭该项。"""

    def __init__(self, **kwargs):
        self.days = INTRADAY_DAYS
        self.tail_minutes = INTRADAY_TAIL_MINUTES
        self.min_session_bars = INTRADAY_MIN_SESSION_BARS
        self.max_failed_limit_up = INTRADAY_MAX_FAILED_LIMIT_UP
        self.max_limit_down_touch = INTRADAY_MAX_LIMIT_DOWN_TOUCH
        self.min_tail_return = INTRADAY_MIN_TAIL_RETURN
        self.min_close_position = INTRADAY_MIN_CLOSE_POSITION
        self.min_vwap_gap = INTRADAY_MIN_VWAP_GAP
        self.max_down_amount_ratio = INTRADAY_MAX_DOWN_AMOUNT_RATIO
        self.max_drawdown = INTRADAY_MAX_DRAWDOWN
        self.max_tail_amount_ratio = INTRADAY_MAX_TAIL_AMOUNT_RATIO
        self.max_post_high_amount_ratio = INTRADAY_MAX_POST_HIGH_AMOUNT_RATIO
        self.max_amount_spike = INTRADAY_MAX_AMOUNT_SPIKE

        for key, value in kwargs.items():
            if not hasattr(self, key):
                raise TypeError('未知分钟线风控参数: %s' % key)
            setattr(self, key, value)


def evaluate_sessions(stock, sessions, params=None):
    """
    对最近几个完整交易日的分钟线做体检。

    sessions: 已按时间升序、已 attach_pre_close 的交易日列表（不含当日）
    返回 (reasons, metrics)：reasons 为空表示通过。

    判定口径：
      炸板 / 触及跌停   统计最近 params.days 天的次数
      日内结构与成交额  只看最近一个交易日（对次日最有预测力）
    """
    params = params or IntradayParams()
    sessions = complete_sessions(sessions or [], params.min_session_bars)
    if not sessions:
        return ['intraday_no_data'], {}

    recent = sessions[-params.days:] if params.days else sessions
    last = recent[-1]
    metrics = session_metrics(stock, last, params.tail_minutes)
    metrics['sessions'] = len(recent)

    reasons = []

    # ---------- 炸板与跌停（统计最近几天）----------
    failed = sum(1 for s in recent if failed_limit_up(stock, s))
    metrics['failed_limit_up_count'] = failed
    if params.max_failed_limit_up is not None and failed > params.max_failed_limit_up:
        reasons.append('failed_limit_up')

    touched_down = sum(1 for s in recent if touched_limit_down(stock, s))
    metrics['limit_down_touch_count'] = touched_down
    if params.max_limit_down_touch is not None and touched_down > params.max_limit_down_touch:
        reasons.append('limit_down_touch')

    # ---------- 最近一个交易日的日内结构 ----------
    value = metrics.get('tail_return')
    if params.min_tail_return is not None and value is not None:
        if value < params.min_tail_return:
            reasons.append('tail_selloff')

    value = metrics.get('close_position')
    if params.min_close_position is not None and value is not None:
        if value < params.min_close_position:
            reasons.append('close_at_low')

    value = metrics.get('vwap_gap')
    if params.min_vwap_gap is not None and value is not None:
        if value < params.min_vwap_gap:
            reasons.append('below_vwap')

    value = metrics.get('drawdown')
    if params.max_drawdown is not None and value is not None:
        if value < params.max_drawdown:
            reasons.append('intraday_crash')

    # ---------- 成交金额分布 ----------
    value = metrics.get('down_amount_ratio')
    if params.max_down_amount_ratio is not None and value is not None:
        if value > params.max_down_amount_ratio:
            reasons.append('selling_pressure')

    tail_ratio = metrics.get('tail_amount_ratio')
    tail_ret = metrics.get('tail_return')
    if (params.max_tail_amount_ratio is not None and tail_ratio is not None
            and tail_ratio > params.max_tail_amount_ratio
            and tail_ret is not None and tail_ret < 0):
        reasons.append('tail_dump')

    value = metrics.get('post_high_amount_ratio')
    if params.max_post_high_amount_ratio is not None and value is not None:
        if value > params.max_post_high_amount_ratio:
            reasons.append('high_distribution')

    # ---------- 成交额放大（天量滞涨）----------
    if params.max_amount_spike is not None and len(recent) >= 2:
        history = [total_amount(s) for s in recent[:-1]]
        history = [a for a in history if a > 0]
        last_amount = metrics.get('amount') or 0.0
        if history and last_amount > 0:
            spike = last_amount / (sum(history) / len(history))
            metrics['amount_spike'] = spike
            if spike > params.max_amount_spike and not metrics.get('closed_limit_up'):
                reasons.append('amount_blowoff')

    return reasons, metrics

# ==========================================================
# momentum_timing/signals.py
# ==========================================================
"""
择时信号与风控判断。

个股择时：动量分数连续下降达到 DECLINE_DAYS_TO_SELL 天 -> SELL，否则 BUY。
大盘择时：RSRS 修正标准分，默认只记录不介入（RSRS_ENABLED=False）。
"""


SIGNAL_BUY = 'BUY'
SIGNAL_SELL = 'SELL'
SIGNAL_KEEP = 'KEEP'


def consecutive_decline_days(scores):
    """从最新一个分数往回数，连续下降了几天。"""
    scores = list(scores)
    count = 0
    for i in range(len(scores) - 1, 0, -1):
        if scores[i] < scores[i - 1]:
            count += 1
        else:
            break
    return count


def momentum_signal(scores, decline_days_to_sell=DECLINE_DAYS_TO_SELL):
    """
    个股动量择时：分数序列为空 -> KEEP；连续下降达标 -> SELL；否则 BUY。
    """
    if not scores:
        return SIGNAL_KEEP
    return SIGNAL_SELL if consecutive_decline_days(scores) >= decline_days_to_sell else SIGNAL_BUY


def rsrs_allows_buy(rsrs_score, enabled=RSRS_ENABLED, threshold=RSRS_BUY_THRESHOLD):
    """
    大盘 RSRS 是否允许买入。

    enabled=False（默认，与原脚本一致）时恒为 True，RSRS 仅作记录。
    """
    if not enabled:
        return True
    if rsrs_score is None:
        return False
    return rsrs_score >= threshold


def timing_signal(scores, rsrs_score=None, decline_days_to_sell=DECLINE_DAYS_TO_SELL,
                  rsrs_enabled=RSRS_ENABLED, rsrs_threshold=RSRS_BUY_THRESHOLD):
    """综合择时信号：个股动量信号 + （可选的）大盘 RSRS 否决。"""
    signal = momentum_signal(scores, decline_days_to_sell)
    if signal == SIGNAL_BUY and not rsrs_allows_buy(rsrs_score, rsrs_enabled, rsrs_threshold):
        return SIGNAL_KEEP
    return signal


def profit_ratio(cost_price, current_price):
    """持仓盈亏比例；成本价非法返回 None。"""
    try:
        cost_price = float(cost_price)
        current_price = float(current_price)
    except (TypeError, ValueError):
        return None
    if cost_price <= 0 or current_price <= 0:
        return None
    return (current_price - cost_price) / cost_price


def stop_loss_triggered(cost_price, current_price, stop_loss_ratio=STOP_LOSS_RATIO):
    """是否触发硬止损（默认 -15%）。"""
    ratio = profit_ratio(cost_price, current_price)
    if ratio is None:
        return False
    return ratio <= stop_loss_ratio


def trailing_stop_triggered(peak_price, current_price,
                            drawdown_ratio=TRAILING_STOP_RATIO):
    """
    移动止损：从持仓期间最高价回撤超过 drawdown_ratio 就离场。

    盈利单冲高回落时能比固定 -15% 硬止损更早离场，
    避免"涨上去又被一路砸到跌停"。drawdown_ratio 为 None 表示关闭。
    """
    if drawdown_ratio is None:
        return False
    try:
        peak_price = float(peak_price)
        current_price = float(current_price)
    except (TypeError, ValueError):
        return False
    if peak_price <= 0 or current_price <= 0:
        return False
    return (current_price - peak_price) / peak_price <= -abs(drawdown_ratio)


def exit_reason(cost_price, current_price, peak_price=None,
                stop_loss_ratio=STOP_LOSS_RATIO,
                trailing_ratio=TRAILING_STOP_RATIO):
    """
    持仓是否该离场，返回原因字符串；不需要离场返回 None。

    'hard_stop'     相对成本价跌破 STOP_LOSS_RATIO
    'trailing_stop' 相对持仓期间最高价回撤超过 TRAILING_STOP_RATIO
    """
    if stop_loss_triggered(cost_price, current_price, stop_loss_ratio):
        return 'hard_stop'
    if peak_price and trailing_stop_triggered(peak_price, current_price, trailing_ratio):
        return 'trailing_stop'
    return None

# ==========================================================
# momentum_timing/portfolio.py
# ==========================================================
"""下单量计算与买入可行性判断。"""



def buy_volume(available_cash, price, lot_size=LOT_SIZE):
    """
    用可用资金按整手买入的股数；资金不足 1 手返回 0。
    """
    try:
        available_cash = float(available_cash)
        price = float(price)
    except (TypeError, ValueError):
        return 0
    if available_cash <= 0 or price <= 0:
        return 0

    volume = int(available_cash / price / lot_size) * lot_size
    return volume if volume >= lot_size else 0


def can_buy(low_price, limit_up):
    """
    是否买得进：全天最低价已经在涨停价上（一字涨停）则买不到。

    返回 (是否可买, 原因)。
    """
    try:
        low_price = float(low_price)
        limit_up = float(limit_up)
    except (TypeError, ValueError):
        return True, ''

    if limit_up > 0 and low_price > 0 and low_price >= limit_up:
        return False, 'limit_up_locked'
    return True, ''


def can_sell(high_price, limit_down):
    """
    是否卖得掉：全天最高价都在跌停价上（一字跌停）时卖单排不上。

    返回 (是否可卖, 原因)。
    """
    try:
        high_price = float(high_price)
        limit_down = float(limit_down)
    except (TypeError, ValueError):
        return True, ''

    if limit_down > 0 and high_price > 0 and high_price <= limit_down:
        return False, 'limit_down_locked'
    return True, ''

# ==========================================================
# momentum_timing/scoring.py
# ==========================================================
"""
动量打分与排名。

关键点：所有取样窗口都排除"当前这根 K 线"，避免回测里出现未来函数。
序列末尾是当前 bar，因此 offset=0 表示当前 bar 之前的 LOOKBACK_DAYS 根收盘价。
"""



def window_excluding_current(closes, lookback=LOOKBACK_DAYS, offset=0):
    """
    取 lookback 根收盘价，排除当前 bar 以及再往前 offset 根。

    offset=0 -> closes[-(lookback+1):-1]
    offset=k -> closes[-(lookback+1+k):-(k+1)]
    数据不足时返回空列表。
    """
    closes = list(closes)
    end = -(offset + 1)
    start = end - lookback
    if len(closes) < lookback + offset + 1:
        return []
    return closes[start:end]


def bars_needed_for_rank(lookback=LOOKBACK_DAYS):
    """选股打分需要向 QMT 请求的 K 线根数（含当前 bar）。"""
    return lookback + 2


def bars_needed_for_history(lookback=LOOKBACK_DAYS, history_days=SCORE_HISTORY_DAYS):
    """历史动量分数序列需要向 QMT 请求的 K 线根数（含当前 bar）。"""
    return lookback + history_days + 2


def score_for_offset(closes, lookback=LOOKBACK_DAYS, offset=0,
                     trading_days_per_year=TRADING_DAYS_PER_YEAR):
    """指定 offset 处的动量分数，数据不足或含非法值返回 None。"""
    window = window_excluding_current(closes, lookback, offset)
    if len(window) < lookback or has_invalid(window):
        return None
    return momentum_score(window, trading_days_per_year)


def momentum_score_history(closes, lookback=LOOKBACK_DAYS,
                           history_days=SCORE_HISTORY_DAYS,
                           trading_days_per_year=TRADING_DAYS_PER_YEAR):
    """
    由远及近的动量分数序列：offset = history_days ... 1, 0。

    与原脚本一致，长度为 history_days + 1（默认 6 个分数，最后一个是最新值）。
    取不到的位置补 0.0。
    """
    scores = []
    for offset in range(history_days, -1, -1):
        score = score_for_offset(closes, lookback, offset, trading_days_per_year)
        scores.append(score if score is not None else 0.0)
    return scores


def rank_pool(close_map, lookback=LOOKBACK_DAYS,
              trading_days_per_year=TRADING_DAYS_PER_YEAR):
    """
    对股票池打分并按分数从高到低排序。

    close_map: {股票代码: 收盘价序列}（序列末尾为当前 bar）
    返回 [(股票代码, 分数), ...]
    """
    scores = {}
    for stock, closes in close_map.items():
        if closes is None:
            continue
        score = score_for_offset(closes, lookback, 0, trading_days_per_year)
        if score is not None:
            scores[stock] = score
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def pick_top(close_map, lookback=LOOKBACK_DAYS,
             trading_days_per_year=TRADING_DAYS_PER_YEAR):
    """取动量分数第 1 名，池子为空时返回 None。"""
    ranked = rank_pool(close_map, lookback, trading_days_per_year)
    return ranked[0][0] if ranked else None

# ==========================================================
# qmt/strategy_backtest.py
# ==========================================================
"""
A股股票策略 [回测版]：概念/全市场池 + 对数线性回归动量打分 + 风控过滤
                       + RSRS / 均线大盘择时 + 动量分数连续下降个股择时
                       + 移动止损 + 固定 -15% 硬止损

与实盘版的主要区别：
  1. 使用 handlebar 逐K线驱动，替代 run_time 定时任务
  2. get_market_data_ex 设置 subscribe=False，读取本地数据
  3. 用 get_market_data_ex 替代 get_full_tick 获取当前价格
  4. 回测使用模拟资金账号（config.BACKTEST_ACCOUNT）
  5. 止损使用当日收盘价判断（回测无法区分 14:50 盘中价）
  6. 选股只用当前 K 线之前的数据，避免未来函数

运行方式：
  A. 项目方式：把整个项目目录放到本机，设置下面的 PROJECT_ROOT，
     在 QMT 客户端 -> 回测 -> 选择主图品种（如沪深300）-> 设置回测参数 -> 运行
  B. 单文件方式：python tools/bundle_qmt.py 生成 dist/momentum_timing_qmt.py，
     直接把该文件贴进 QMT（无需配置 PROJECT_ROOT）
"""




# ============================================================
# QMT 下单常量
# ============================================================
OP_BUY = 23               # 股票买入
OP_SELL = 24              # 股票卖出
ORDER_BY_VOLUME = 1101    # 按股数下单
PRICE_TYPE_MARKET = 5     # 市价（最优五档剩余撤销）
PRICE_TYPE_LIMIT = 11     # 指定价

# 风控取数用到的字段
RISK_FIELDS = ['open', 'high', 'low', 'close', 'preClose', 'volume', 'amount']


# ============================================================
# 全局变量：保存跨 bar 的状态
# ============================================================
class G(object):
    pass


g = G()


# ============================================================
# 系统函数
# ============================================================

def init(C):
    """回测初始化"""
    g.account = BACKTEST_ACCOUNT
    g.acct_type = ACCOUNT_TYPE
    g.score_history = {}      # {股票: 近 N 日动量分数序列}
    g.today_target = None     # 今日目标股票
    g.bar_count = 0           # 已处理 bar 计数
    g.risk_params = RiskParams()
    g.risk_bars = history_bars_needed(g.risk_params)
    g.intraday_params = IntradayParams()
    g.intraday_bars = INTRADAY_BARS_PER_DAY * (INTRADAY_DAYS + 1)
    g.intraday_warned = False
    g.position_peak = {}      # {股票: 持仓期间最高价}，用于移动止损
    g.reject_stats = {}       # {否决原因: 次数}，回测结束时汇总

    print('[动量择时策略-回测版] 初始化完成')
    print('  运行模式: %s' % ('original 最初的选股逻辑（无风控过滤）'
                              if STRATEGY_MODE == 'original' else STRATEGY_MODE))
    print('  回测账号: %s, 类型: %s' % (g.account, g.acct_type))
    print('  板块数: %d' % len(CONCEPT_SECTORS))
    print('  动量回看: %d天, 连降卖出: %d天, 止损线: %.0f%%'
          % (LOOKBACK_DAYS, DECLINE_DAYS_TO_SELL, STOP_LOSS_RATIO * 100))
    print('  风控: %s 档位=%s 候选顺延 %d 只, 扣分上限 %d, 需要 %d 根历史K线'
          % ('开' if RISK_ENABLED else '关', RISK_PRESET, RISK_MAX_CANDIDATES,
             RISK_PENALTY_LIMIT, g.risk_bars))
    print('  分钟线风控: %s (回看 %d 个交易日, 取 %d 根1分钟K线)'
          % ('开' if INTRADAY_ENABLED else '关', INTRADAY_DAYS, g.intraday_bars))
    print('  大盘风控: %s (%s 跌破 MA%d -> %s)'
          % ('开' if MARKET_FILTER_ENABLED else '关', MARKET_INDEX,
             MARKET_MA_WINDOW, MARKET_FILTER_ACTION))
    print('  移动止损: %s' % ('%.0f%%' % (TRAILING_STOP_RATIO * 100)
                              if TRAILING_STOP_RATIO else '关'))


def handlebar(C):
    """
    每根日K线触发一次，模拟完整交易日流程：
      ① 大盘风控
      ② 选股 + 动量打分 + 个股风控 + 择时 + 调仓（等价于 09:31 my_trade）
      ③ 持仓风控：硬止损 + 移动止损（等价于 14:50 check_lose）
      ④ 打印复盘（等价于 15:05 print_trade_info）

    注意：无论今天是否选出标的，③ 持仓风控都会执行——空仓日也要保护已有持仓。
    """
    g.bar_count += 1

    bar_date = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')

    # 前几根 bar 数据不足，跳过
    if g.bar_count < WARMUP_BARS:
        return

    print('\n' + '=' * 60)
    print('[回测] Bar#%d 日期: %s' % (g.bar_count, bar_date))
    print('=' * 60)

    update_position_peaks(C, bar_date)

    # ---------------- ① 大盘风控 ----------------
    market_ok = check_market(C, bar_date)
    if not market_ok and MARKET_FILTER_ACTION == 'exit_all':
        print('[回测] 大盘走弱 -> 清仓离场')
        close_all_positions(C, bar_date, '大盘风控清仓')
        print_trade_info_backtest(C, bar_date)
        return

    # ---------------- ② 选股 + 调仓 ----------------
    target_stock = trade_once(C, bar_date, market_ok)

    # ---------------- ③ 持仓风控 ----------------
    check_lose_backtest(C, bar_date)

    # ---------------- ④ 复盘打印 ----------------
    print_trade_info_backtest(C, bar_date)

    return target_stock


def trade_once(C, bar_date, market_ok=True):
    """当日选股与调仓，返回最终的目标股票（没有则 None）。"""
    # 步骤1：构建股票池
    pool = get_stock_pool(C, bar_date)
    if not pool:
        print('[回测] 步骤1 - 股票池为空，今日不开新仓')
        return None
    print('[回测] 步骤1 - 股票池: %d 只' % len(pool))

    # 步骤2：动量打分 + 风控，沿排名顺延取第一只通过的
    target_stock, risk_result = select_target(pool, C, bar_date)
    if target_stock is None:
        print('[回测] 步骤2 - 没有通过风控的候选股，今日不开新仓')
        return None
    print('[回测] 步骤2 - 目标: %s %s 风控:%s'
          % (target_stock, C.get_stock_name(target_stock),
             risk_result.describe() if risk_result else 'SKIP'))

    # 步骤3：计算历史动量分数序列
    g.score_history = rank_stock_change(target_stock, C, bar_date)
    scores = g.score_history.get(target_stock, [])
    print('[回测] 步骤3 - 动量分数序列: %s' % [round(s, 4) for s in scores])

    # 步骤4：过滤候选股（跌停、停牌）
    target_stock = filter_target(target_stock, C, bar_date)
    if target_stock is None:
        print('[回测] 步骤4 - 目标股票被过滤')
        return None
    g.today_target = target_stock
    print('[回测] 步骤4 - 过滤通过: %s' % target_stock)

    # 步骤5：计算综合择时信号
    signal = get_timing_signal(target_stock, C, bar_date)
    if signal == SIGNAL_BUY and not market_ok:
        print('[择时] 大盘走弱，买入信号降级为 KEEP')
        signal = SIGNAL_KEEP
    print('[回测] 步骤5 - 择时信号: %s' % signal)

    # 步骤6：执行调仓
    adjust_position(target_stock, signal, C, bar_date)
    print('[回测] 步骤6 - 调仓执行完毕')
    return target_stock


def stop(C):
    print('[动量择时策略-回测版] 回测结束，共处理 %d 根K线' % g.bar_count)
    if getattr(g, 'reject_stats', None):
        items = sorted(g.reject_stats.items(), key=lambda kv: kv[1], reverse=True)
        print('[风控汇总] 候选股被否决次数: %s' % items)


# ============================================================
# 行情读取工具
# ============================================================

def get_market_data(C, fields, stocks, bar_date, count, fill_data=True, period='1d'):
    """统一的历史行情读取：默认日线，不复权，读本地数据。"""
    try:
        return C.get_market_data_ex(
            fields, stocks,
            period=period,
            end_time=bar_date,
            count=count,
            dividend_type='none',
            fill_data=fill_data,
            subscribe=False
        )
    except Exception as e:
        print('[行情] get_market_data_ex 失败: %s' % e)
        return {}


def series(data, stock, field):
    """从 get_market_data_ex 的返回里取某字段序列（list of float）。"""
    if not data or stock not in data or data[stock] is None:
        return []
    df = data[stock]
    if len(df) == 0 or field not in df.columns:
        return []
    out = []
    for v in df[field].values:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(float('nan'))
    return out


def bar_times(data, stock):
    """
    取每根 K 线的时间戳，格式 'YYYYMMDDHHMMSS'。

    QMT 的 get_market_data_ex 把时间放在 DataFrame 的 index 上；
    部分版本额外给一列毫秒时间戳 time，这里都兼容。
    """
    if not data or stock not in data or data[stock] is None:
        return []
    df = data[stock]
    if len(df) == 0:
        return []

    try:
        times = [str(t) for t in df.index]
        if times and len(times[0]) >= 8 and times[0][:8].isdigit():
            return times
    except (AttributeError, TypeError):
        pass

    if 'time' in df.columns:
        out = []
        for value in df['time'].values:
            try:
                out.append(timetag_to_datetime(int(value), '%Y%m%d%H%M%S'))
            except Exception:
                out.append('')
        return out

    return []


def last_value(data, stock, field, default=0.0):
    """取某字段最新值。"""
    values = series(data, stock, field)
    return values[-1] if values else default


# ============================================================
# 大盘风控
# ============================================================

def check_market(C, bar_date):
    """指数收盘价站上 MA(MARKET_MA_WINDOW) 才允许开新仓。"""
    if not MARKET_FILTER_ENABLED:
        return True

    data = get_market_data(C, ['close'], [MARKET_INDEX], bar_date, MARKET_MA_WINDOW + 2)
    closes = series(data, MARKET_INDEX, 'close')
    if len(closes) < 2:
        print('[大盘风控] %s 数据不足，按放行处理' % MARKET_INDEX)
        return True

    # 排除当前 bar，用昨日收盘判断
    ok, metrics = market_is_healthy(closes[:-1], MARKET_MA_WINDOW)
    if metrics:
        print('[大盘风控] %s 收盘:%.2f MA%d:%.2f -> %s'
              % (MARKET_INDEX, metrics['close'], MARKET_MA_WINDOW, metrics['ma'],
                 '健康' if ok else '走弱'))
    return ok


# ============================================================
# 步骤1：构建股票池
# ============================================================

def get_stock_pool(C, bar_date):
    """
    板块成分股 -> 代码前缀 / 停牌 / ST / 市值 / 跌停 过滤。
    行情统一用 get_market_data_ex 读取（回测无 tick）。
    """
    pool_set = set()
    for sector_name in CONCEPT_SECTORS:
        try:
            for s in C.get_stock_list_in_sector(sector_name):
                pool_set.add(s)
        except Exception as e:
            print('[get_stock_pool] 板块 %s 获取失败: %s' % (sector_name, e))

    if not pool_set:
        print('[get_stock_pool] 板块未获取到股票')
        return []

    pool_list = sorted(pool_set)
    data = get_market_data(C, ['close', 'preClose', 'suspendFlag'], pool_list, bar_date, 2)
    if not data:
        return []

    result = []
    for stock in pool_list:
        closes = series(data, stock, 'close')
        if not closes:
            continue

        last_close = closes[-1]
        pre_closes = series(data, stock, 'preClose')
        pre_close = pre_closes[-1] if pre_closes else last_close
        suspend_flags = series(data, stock, 'suspendFlag')
        suspend_flag = suspend_flags[-1] if suspend_flags else 0

        stock_name, total_value, _float_volume, _open_date = get_detail(C, stock, last_close)

        ok, _reason = passes_filters(
            stock,
            stock_name=stock_name,
            total_value=total_value,
            suspend_flag=suspend_flag,
            close=last_close,
            pre_close=pre_close,
            min_cap=MIN_MARKET_CAP,
            max_cap=MAX_MARKET_CAP,
        )
        if ok:
            result.append(stock)

    return result


def get_detail(C, stock, last_close=0.0):
    """
    读取合约基础信息，返回 (名称, 总市值, 流通股本, 上市日期)。
    任一字段取不到就给默认值，不让异常打断选股。
    """
    stock_name, total_value, float_volume, open_date = '', 0.0, None, None
    try:
        detail = C.get_instrument_detail(stock)
        if detail:
            stock_name = detail.get('InstrumentName', '')
            total_value = detail.get('TotalValue', 0) or 0
            if total_value <= 0:
                total_shares = detail.get('TotalShares', 0) or 0
                if total_shares > 0 and last_close > 0:
                    total_value = total_shares * last_close
            float_volume = detail.get('FloatVolume') or detail.get('FloatVolumn')
            open_date = detail.get('OpenDate')
    except Exception:
        pass
    return stock_name, total_value, float_volume, open_date


def listed_days(open_date, bar_date):
    """由上市日期与当前日期计算上市天数（自然日）；无法计算返回 None。"""
    if not open_date:
        return None
    try:
        open_date = str(int(open_date))
        if len(open_date) != 8 or open_date == '19700101':
            return None
        import datetime
        start = datetime.date(int(open_date[:4]), int(open_date[4:6]), int(open_date[6:8]))
        today = datetime.date(int(bar_date[:4]), int(bar_date[4:6]), int(bar_date[6:8]))
        return (today - start).days
    except (TypeError, ValueError):
        return None


# ============================================================
# 步骤2：动量打分 + 风控筛选
# ============================================================

def rank_candidates(pool, C, bar_date):
    """对股票池打分并按分数降序排列（打分窗口排除当前 bar）。"""
    if not pool:
        return []

    data = get_market_data(C, ['close'], pool, bar_date, bars_needed_for_rank(LOOKBACK_DAYS))
    if not data:
        return []

    close_map = {}
    for stock in pool:
        closes = series(data, stock, 'close')
        if len(closes) >= LOOKBACK_DAYS + 1:
            close_map[stock] = closes

    return rank_pool(close_map, LOOKBACK_DAYS, TRADING_DAYS_PER_YEAR)


def get_rank(pool, C, bar_date):
    """动量第 1 名（不含风控），保留给需要对照原始逻辑的场景。"""
    ranked = rank_candidates(pool, C, bar_date)
    return ranked[0][0] if ranked else None


def select_target(pool, C, bar_date):
    """
    动量排名 + 风控：从第 1 名开始逐个体检，返回第一只通过的股票。

    返回 (股票, RiskResult)；全部被否决时返回 (None, None)。
    """
    ranked = rank_candidates(pool, C, bar_date)
    if not ranked:
        return None, None

    print('[选股] Top3: %s' % [(s, round(sc, 4)) for s, sc in ranked[:3]])

    if not RISK_ENABLED:
        return ranked[0][0], RiskResult(True, [], {'score': ranked[0][1]})

    candidates = ranked[:RISK_MAX_CANDIDATES]
    scores = dict(candidates)
    stocks = [s for s, _ in candidates]
    risk_data = get_market_data(C, RISK_FIELDS, stocks, bar_date, g.risk_bars + 1)
    minute_cache = {}   # 分钟线按需拉取：日线就被否决的候选不必再取

    def evaluator(stock):
        return check_risk(stock, C, bar_date, risk_data, scores.get(stock), minute_cache)

    target, result, rejected = pick_first_passing(candidates, evaluator, RISK_MAX_CANDIDATES)

    for stock, rejected_result in rejected:
        print('[风控] %s %s %s' % (stock, C.get_stock_name(stock),
                                   rejected_result.describe()))
        if RISK_DEBUG:
            print('[风控明细] %s %s' % (stock, format_metrics(rejected_result.metrics)))
        for reason in rejected_result.reasons:
            g.reject_stats[reason] = g.reject_stats.get(reason, 0) + 1

    if target is None and rejected:
        # 今天一只都没过：把原因汇总打出来，方便定位是哪条规则拦死了全场
        counts = sorted(reason_counts(rejected).items(), key=lambda kv: kv[1], reverse=True)
        print('[风控] %d 只候选全部否决，原因分布: %s' % (len(rejected), counts))

        if RISK_FALLBACK_TO_BEST:
            target, result = best_of_rejected(rejected)
            if target is not None:
                print('[风控] 兜底买入扣分最低的 %s %s' % (target, result.describe()))

    if target is not None and RISK_DEBUG and result is not None:
        print('[风控明细] %s %s' % (target, format_metrics(result.metrics)))

    return target, result


def format_metrics(metrics):
    """把风控指标格式化成一行，便于按真实数据校准阈值（RISK_DEBUG=True 时打印）。"""
    parts = []
    for key in sorted(metrics):
        value = metrics[key]
        if isinstance(value, float):
            parts.append('%s=%.4g' % (key, value))
        else:
            parts.append('%s=%s' % (key, value))
    return ' '.join(parts)


def check_risk(stock, C, bar_date, risk_data, score=None, minute_cache=None):
    """
    对单只候选股做风控体检。

    历史序列一律切掉当前 bar；当前 bar 只用开盘价和前收（09:31 可观测）判断跳空。
    """
    closes = series(risk_data, stock, 'close')
    pre_closes = series(risk_data, stock, 'preClose')
    if len(closes) < 3 or len(pre_closes) < 3:
        return RiskResult(False, ['data_insufficient'], {'score': score})

    history = {
        'close': closes[:-1],
        'pre_close': pre_closes[:-1],
        'high': series(risk_data, stock, 'high')[:-1],
        'low': series(risk_data, stock, 'low')[:-1],
        'volume': series(risk_data, stock, 'volume')[:-1],
        'amount': series(risk_data, stock, 'amount')[:-1],
    }
    opens = series(risk_data, stock, 'open')
    today = {'open': opens[-1] if opens else None, 'pre_close': pre_closes[-1]}

    _name, _total_value, float_volume, open_date = get_detail(C, stock, closes[-1])

    result = evaluate_candidate(
        stock, history,
        today=today,
        params=g.risk_params,
        listed_days=listed_days(open_date, bar_date),
        float_volume=float_volume,
        score=score,
    )

    # 日线就没过的候选不必再拉分钟线（分钟数据量大，能省则省）
    if INTRADAY_ENABLED and result.passed:
        reasons, metrics = check_intraday(stock, C, bar_date, minute_cache)
        result.add(reasons, metrics)

    return result


def get_minute_data(stock, C, bar_date, cache=None):
    """按需拉取单只股票的分钟线，同一根 bar 内复用。"""
    if cache is not None and stock in cache:
        return cache[stock]

    data = get_market_data(C, list(INTRADAY_FIELDS), [stock], bar_date,
                           g.intraday_bars, period='1m')
    if cache is not None:
        cache[stock] = data
    return data


def check_intraday(stock, C, bar_date, minute_cache=None):
    """
    分钟线风控：只用当前交易日之前的完整交易日数据。

    返回 (reasons, metrics)。分钟数据缺失时按 INTRADAY_REQUIRE_DATA 决定是否否决——
    QMT 默认不下载分钟线，贸然否决会让策略整段空仓。
    """
    minute_data = get_minute_data(stock, C, bar_date, minute_cache)
    times = bar_times(minute_data, stock)
    if not times:
        warn_missing_intraday(stock)
        return (['intraday_no_data'] if INTRADAY_REQUIRE_DATA else []), {}

    fields = {}
    for name in INTRADAY_FIELDS:
        fields[name] = series(minute_data, stock, name)

    sessions = sessions_before(group_sessions(times, fields), bar_date)
    attach_pre_close(sessions)

    reasons, metrics = evaluate_sessions(stock, sessions, g.intraday_params)
    if 'intraday_no_data' in reasons:
        warn_missing_intraday(stock)
        if not INTRADAY_REQUIRE_DATA:
            reasons = [r for r in reasons if r != 'intraday_no_data']
    return reasons, metrics


def warn_missing_intraday(stock):
    """分钟数据缺失只提示一次，避免刷屏。"""
    if g.intraday_warned:
        return
    g.intraday_warned = True
    print('[分钟线风控] %s 取不到分钟数据，%s。'
          '请在 QMT 中补下载 1 分钟历史数据，或把 INTRADAY_ENABLED 设为 False'
          % (stock, '直接否决' if INTRADAY_REQUIRE_DATA else '本项检查跳过'))


# ============================================================
# 步骤3：目标股历史动量分数序列
# ============================================================

def rank_stock_change(stock, C, bar_date):
    """目标股票由远及近的动量分数序列，所有窗口都排除当前 bar。"""
    result = {}
    count = bars_needed_for_history(LOOKBACK_DAYS, SCORE_HISTORY_DAYS)
    data = get_market_data(C, ['close'], [stock], bar_date, count)

    closes = series(data, stock, 'close')
    if len(closes) < LOOKBACK_DAYS + 2:
        return result

    result[stock] = momentum_score_history(
        closes, LOOKBACK_DAYS, SCORE_HISTORY_DAYS, TRADING_DAYS_PER_YEAR)
    return result


# ============================================================
# 步骤4：过滤候选股
# ============================================================

def filter_target(stock, C, bar_date):
    """剔除停牌、跌停的候选股。"""
    if stock is None:
        return None

    data = get_market_data(C, ['close', 'preClose', 'suspendFlag'], [stock], bar_date, 1)
    closes = series(data, stock, 'close')
    if not closes:
        return None

    suspend_flags = series(data, stock, 'suspendFlag')
    if suspend_flags and suspend_flags[-1] == 1:
        print('[filter_target] %s 停牌中' % stock)
        return None

    last_close = closes[-1]
    pre_closes = series(data, stock, 'preClose')
    pre_close = pre_closes[-1] if pre_closes else last_close
    if last_close <= 0:
        return None

    ok, reason = passes_filters(stock, close=last_close, pre_close=pre_close)
    if not ok:
        _, limit_down = limit_prices(stock, pre_close)
        print('[filter_target] %s 未通过(%s) 收盘:%.2f 跌停价:%.2f'
              % (stock, reason, last_close, limit_down))
        return None

    return stock


# ============================================================
# 步骤5：综合择时信号
# ============================================================

def get_timing_signal(stock, C, bar_date):
    """
    个股择时：动量分数连续下降 >= DECLINE_DAYS_TO_SELL 天 -> SELL。
    大盘择时：RSRS 修正标准分，RSRS_ENABLED=False 时仅打印不介入决策。
    """
    rsrs = calc_rsrs(C, bar_date)
    if rsrs is not None:
        print('[择时] RSRS修正标准分: %.4f (参与决策: %s)' % (rsrs, RSRS_ENABLED))
    else:
        print('[择时] RSRS 数据不足')

    scores = g.score_history.get(stock, [])
    if scores:
        print('[择时] 动量分数序列: %s' % [round(s, 4) for s in scores])
        print('[择时] 连续下降天数: %d' % _decline_days(scores))

    return timing_signal(scores, rsrs)


def _decline_days(scores):
    count = 0
    for i in range(len(scores) - 1, 0, -1):
        if scores[i] < scores[i - 1]:
            count += 1
        else:
            break
    return count


def calc_rsrs(C, bar_date):
    """沪深300 的 RSRS 修正标准分：N 根窗口拟合，M 个样本算 zscore。"""
    data = get_market_data(C, ['high', 'low'], [RSRS_INDEX], bar_date, RSRS_M + RSRS_N + 2)
    highs = series(data, RSRS_INDEX, 'high')
    lows = series(data, RSRS_INDEX, 'low')
    if len(highs) < RSRS_M + RSRS_N + 1 or len(lows) < RSRS_M + RSRS_N + 1:
        return None

    # 排除当前 bar
    return rsrs_corrected_zscore(highs[:-1], lows[:-1], RSRS_N, RSRS_M)


# ============================================================
# 步骤6：执行调仓
# ============================================================

def get_price_and_limits(stock, C, bar_date):
    """
    当日开盘价、涨停价、跌停价、最低价。
    取不到时返回 (0.0, 0.0, 0.0, 0.0)。
    """
    data = get_market_data(C, ['open', 'low', 'preClose'], [stock], bar_date, 1)
    opens = series(data, stock, 'open')
    if not opens:
        return 0.0, 0.0, 0.0, 0.0

    open_price = opens[-1]
    lows = series(data, stock, 'low')
    low_price = lows[-1] if lows else open_price
    pre_closes = series(data, stock, 'preClose')
    pre_close = pre_closes[-1] if pre_closes else open_price

    limit_up, limit_down = limit_prices(stock, pre_close)
    return open_price, limit_up, limit_down, low_price


def get_positions(C):
    """当前可用持仓 {股票: 可用股数}。"""
    holdings = get_trade_detail_data(g.account, g.acct_type, 'position') or []
    positions = {}
    for pos in holdings:
        stock = pos.m_strInstrumentID + '.' + pos.m_strExchangeID
        volume = pos.m_nCanUseVolume
        if volume > 0:
            positions[stock] = volume
    return positions


def sell_stock(stock, volume, C, bar_date, msg, market_price=False):
    """
    卖出。一字跌停（当日最高价 <= 跌停价）时挂单成交不了，直接跳过。
    """
    if ASSUME_LIMIT_DOWN_UNSELLABLE:
        data = get_market_data(C, ['high', 'preClose'], [stock], bar_date, 1)
        highs = series(data, stock, 'high')
        pre_closes = series(data, stock, 'preClose')
        if highs and pre_closes:
            _, limit_down = limit_prices(stock, pre_closes[-1])
            ok, _reason = can_sell(highs[-1], limit_down)
            if not ok:
                print('[调仓] %s 一字跌停，卖单无法成交，顺延到下一交易日' % stock)
                return False

    if market_price:
        passorder(OP_SELL, ORDER_BY_VOLUME, g.account, stock, PRICE_TYPE_MARKET, -1,
                  volume, STRATEGY_NAME, 1, msg, C)
        print('[调仓] %s 市价 数量:%d' % (msg, volume))
        return True

    open_price, _, _, _ = get_price_and_limits(stock, C, bar_date)
    if open_price <= 0:
        print('[调仓] %s 取不到价格，改用市价卖出' % stock)
        passorder(OP_SELL, ORDER_BY_VOLUME, g.account, stock, PRICE_TYPE_MARKET, -1,
                  volume, STRATEGY_NAME, 1, msg, C)
        return True

    print('[调仓] %s 价格:%.2f 数量:%d' % (msg, open_price, volume))
    passorder(OP_SELL, ORDER_BY_VOLUME, g.account, stock, PRICE_TYPE_LIMIT, open_price,
              volume, STRATEGY_NAME, 1, msg, C)
    return True


def close_all_positions(C, bar_date, msg_prefix):
    """清空所有持仓。"""
    for stock, volume in get_positions(C).items():
        sell_stock(stock, volume, C, bar_date, '%s %s' % (msg_prefix, stock))


def adjust_position(stock, signal, C, bar_date):
    """
    SELL     -> 清仓
    BUY      -> 持仓已是目标股则持有，否则换仓（先卖旧、再满仓买入）
    KEEP     -> 已持有目标股则继续持有，空仓则不开新仓
    """
    positions = get_positions(C)
    print('[调仓] 当前持仓: %s' % positions)

    if signal == SIGNAL_SELL:
        close_all_positions(C, bar_date, 'SELL信号 清仓')
        return

    if positions.get(stock, 0) > 0:
        print('[调仓] KEEP: 继续持有 %s' % stock)
        return

    if signal == SIGNAL_KEEP and not BUY_ON_KEEP:
        print('[调仓] KEEP: 不新开仓')
        return

    # 换仓：先卖旧
    for held, volume in positions.items():
        sell_stock(held, volume, C, bar_date, '切换标的 卖出 %s' % held)

    # 再买新
    open_price, limit_up, limit_down, low_price = get_price_and_limits(stock, C, bar_date)
    print('[调仓] %s 开盘:%.2f 涨停:%.2f 跌停:%.2f 最低:%.2f'
          % (stock, open_price, limit_up, limit_down, low_price))
    if open_price <= 0:
        print('[调仓] %s 价格异常: %s' % (stock, open_price))
        return

    ok, _reason = can_buy(low_price, limit_up)
    if not ok:
        print('[调仓] %s 一字涨停，无法买入' % stock)
        return

    account_info = get_trade_detail_data(g.account, g.acct_type, 'account')
    if not account_info:
        print('[调仓] 无法获取账户信息')
        return
    available_cash = int(account_info[0].m_dAvailable)

    volume = buy_volume(available_cash, open_price)
    if volume <= 0:
        print('[调仓] 资金不足买1手，可用:%d 股价:%.2f' % (available_cash, open_price))
        return

    msg = 'BUY信号 买入 %s %d股' % (stock, volume)
    print('[调仓] %s 价格:%.2f' % (msg, open_price))
    passorder(OP_BUY, ORDER_BY_VOLUME, g.account, stock, PRICE_TYPE_LIMIT, open_price,
              volume, STRATEGY_NAME, 1, msg, C)
    g.position_peak[stock] = open_price


# ============================================================
# 持仓风控：硬止损 + 移动止损
# ============================================================

def update_position_peaks(C, bar_date):
    """维护每只持仓股的持仓期间最高价（用当日最高价更新），并清掉已平仓的记录。"""
    positions = get_positions(C)
    for stock in list(g.position_peak.keys()):
        if stock not in positions:
            del g.position_peak[stock]

    for stock in positions:
        data = get_market_data(C, ['high', 'close'], [stock], bar_date, 1)
        high = last_value(data, stock, 'high', 0.0)
        if high <= 0:
            high = last_value(data, stock, 'close', 0.0)
        if high > 0:
            g.position_peak[stock] = max(g.position_peak.get(stock, 0.0), high)


def check_lose_backtest(C, bar_date):
    """
    持仓风控（回测用当日收盘价判断）：
      硬止损   相对成本价跌破 STOP_LOSS_RATIO
      移动止损 相对持仓期间最高价回撤超过 TRAILING_STOP_RATIO
    """
    holdings = get_trade_detail_data(g.account, g.acct_type, 'position') or []

    for pos in holdings:
        stock = pos.m_strInstrumentID + '.' + pos.m_strExchangeID
        cost_price = pos.m_dOpenPrice
        volume = pos.m_nCanUseVolume
        if volume <= 0 or cost_price <= 0:
            continue

        data = get_market_data(C, ['close'], [stock], bar_date, 1)
        current_price = last_value(data, stock, 'close', 0.0)
        if current_price <= 0:
            continue

        peak = max(g.position_peak.get(stock, 0.0), current_price)
        g.position_peak[stock] = peak

        ratio = profit_ratio(cost_price, current_price) or 0.0
        drawdown = (current_price - peak) / peak if peak > 0 else 0.0
        print('[持仓风控] %s %s 成本:%.2f 收盘:%.2f 盈亏:%.2f%% 最高:%.2f 回撤:%.2f%%'
              % (stock, C.get_stock_name(stock), cost_price, current_price,
                 ratio * 100, peak, drawdown * 100))

        reason = exit_reason(cost_price, current_price, peak,
                             STOP_LOSS_RATIO, TRAILING_STOP_RATIO)
        if reason == 'hard_stop':
            print('[持仓风控] %s 触发硬止损，盈亏 %.2f%% <= %.0f%%，强制清仓'
                  % (stock, ratio * 100, STOP_LOSS_RATIO * 100))
            sell_stock(stock, volume, C, bar_date, '硬止损平仓 %s' % stock,
                       market_price=True)
        elif reason == 'trailing_stop':
            print('[持仓风控] %s 触发移动止损，回撤 %.2f%% <= -%.0f%%，清仓'
                  % (stock, drawdown * 100, TRAILING_STOP_RATIO * 100))
            sell_stock(stock, volume, C, bar_date, '移动止损平仓 %s' % stock,
                       market_price=True)


# ============================================================
# 复盘打印
# ============================================================

def print_trade_info_backtest(C, bar_date):
    """打印当日成交、持仓、资金。"""
    deals = get_trade_detail_data(g.account, g.acct_type, 'deal') or []
    today_deals = []
    for deal in deals:
        deal_date = deal.m_strTradeDate.replace('-', '')
        if deal_date == bar_date[:8]:
            today_deals.append(deal)

    if today_deals:
        print('--- 今日成交 (%d 笔) ---' % len(today_deals))
        for deal in today_deals:
            print('  %s.%s %s 价格:%.2f 数量:%d'
                  % (deal.m_strInstrumentID, deal.m_strExchangeID,
                     '买入' if deal.m_nDirection == 1 else '卖出',
                     deal.m_dPrice, deal.m_nVolume))

    holdings = get_trade_detail_data(g.account, g.acct_type, 'position') or []
    for pos in holdings:
        stock = pos.m_strInstrumentID + '.' + pos.m_strExchangeID
        cost_price = pos.m_dOpenPrice
        volume = pos.m_nCanUseVolume
        if volume <= 0:
            continue

        data = get_market_data(C, ['close'], [stock], bar_date, 1)
        current_price = last_value(data, stock, 'close', 0.0)
        ratio = profit_ratio(cost_price, current_price)
        ratio = 0.0 if ratio is None else ratio

        print('  持仓: %s %s 成本:%.2f 收盘:%.2f 盈亏:%.2f%% 市值:%.0f'
              % (stock, C.get_stock_name(stock), cost_price, current_price,
                 ratio * 100, current_price * volume))

    acc = get_trade_detail_data(g.account, g.acct_type, 'account')
    if acc:
        print('  资金: 可用=%.0f 总资产=%.0f' % (acc[0].m_dAvailable, acc[0].m_dBalance))
