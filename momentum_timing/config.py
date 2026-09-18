# coding: utf-8
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
