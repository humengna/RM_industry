# 动量择时策略（QMT 回测版）

A 股单标的轮动策略：**概念/全市场股票池 → 对数线性回归动量打分 → 取第 1 名 →
动量分数连续下降择时 → 满仓换股 → -15% 硬止损**。

> **默认按最开始的选股逻辑运行**（`config.STRATEGY_MODE = 'original'`），
> 不做任何风控过滤。风控模块（日线 / 分钟线 / 大盘 / 移动止损）代码都还在，
> 把这一行改成 `'risk'` 就能整套加回来，阈值见 [`docs/risk.md`](docs/risk.md)。

策略逻辑与参数来自原始的 QMT 单文件脚本（存档于
[`reference/original_qmt_backtest.py`](reference/original_qmt_backtest.py)），
本项目把它拆成"可测试的纯计算内核"和"QMT 接口层"两部分。

## 目录结构

```
momentum_timing/          纯计算内核（只依赖标准库，可单元测试）
├── config.py             全部参数，唯一的参数来源
├── indicators.py         一元线性回归 / 动量分数 / RSRS 修正标准分
├── scoring.py            打分窗口（排除当前 bar）、历史分数序列、排名
├── risk.py               日线风控：过热/波动/流动性/结构指标与否决逻辑、大盘均线
├── intraday.py           分钟线风控：炸板/尾盘跳水/VWAP/高位派发/成交额分布
├── signals.py            连续下降择时、RSRS 否决、硬止损与移动止损
├── universe.py           涨跌停价、停牌 / ST / 市值 / 代码前缀过滤
└── portfolio.py          整手下单量、一字涨停买不进 / 一字跌停卖不掉判断
qmt/
└── strategy_backtest.py  QMT 回测脚本：init / handlebar / stop + 取数 + 下单
tools/
└── bundle_qmt.py         打包成单文件，方便直接贴进 QMT 客户端
single_file/              生成好的单文件（UTF-8 / GBK 两版），复制即用
tests/                    191 个单元测试 + 模拟 QMT 环境的端到端测试
reference/                原始脚本存档
```

## 运行方式

### 方式 A：单文件（推荐，QMT 客户端里最省事）

仓库里已经放好了生成好的单文件，直接取用即可：

- [`single_file/momentum_timing_qmt_utf8.py`](single_file/momentum_timing_qmt_utf8.py)（UTF-8，**默认用这个**，适合网页复制）
- [`single_file/momentum_timing_qmt_gbk.py`](single_file/momentum_timing_qmt_gbk.py)（GBK，老版本 QMT 用，下载后本地打开）

全选复制 → 粘贴进 QMT 的策略编辑器 → 点击"回测" → 选择主图品种（如沪深 300）
→ 回测周期选**日线** → 设置回测区间与初始资金 → 运行。
文件是自包含的，不需要配置任何路径。用法细节见
[`single_file/README.md`](single_file/README.md)。

改了源码之后重新生成：

```bash
python tools/bundle_qmt.py -e utf-8 -o single_file/momentum_timing_qmt_utf8.py
python tools/bundle_qmt.py -e gbk   -o single_file/momentum_timing_qmt_gbk.py
```

### 方式 B：项目方式

把整个项目目录放到本机（例如 `D:\quant\RM_industry`），打开
`qmt/strategy_backtest.py`，把顶部的 `PROJECT_ROOT` 改成项目根目录：

```python
PROJECT_ROOT = r'D:\quant\RM_industry'
```

然后在 QMT 里加载该脚本运行。留空时脚本会按 `__file__` / 当前工作目录自动推断。

> 回测账号默认是模拟资金账号 `testS`（`config.BACKTEST_ACCOUNT`），
> 请改成自己 QMT 里实际存在的模拟账号。

### 跑测试

```bash
pip install -r requirements-dev.txt
python -m pytest            # 191 passed
```

测试不需要 QMT：`tests/fake_qmt.py` 模拟了 `ContextInfo`、`passorder`、
`get_trade_detail_data`，可以在本地把 `handlebar` 整条链路跑通。

## 策略流程（每根日 K 线）

| 步骤 | 做什么 | 代码位置 |
| --- | --- | --- |
| 0 | 前 `WARMUP_BARS`(=15) 根 K 线数据不足，直接跳过 | `handlebar` |
| 1 | 取板块成分股，过滤停牌 / ST / 市值不在 30~500 亿 / 跌停 | `get_stock_pool` + `universe.passes_filters` |
| 2 | 对每只股票的对数收盘价做线性回归，按 `年化收益率 × R² 绝对值` 打分，取第 1 名 | `select_target` + `scoring.rank_pool` |
| 3 | 计算目标股由远及近的 6 个历史动量分数 | `rank_stock_change` + `scoring.momentum_score_history` |
| 4 | 目标股停牌 / 跌停则放弃 | `filter_target` |
| 5 | 分数连续下降 ≥ 2 天 → `SELL`，否则 `BUY`；RSRS 只打印 | `get_timing_signal` + `signals.timing_signal` |
| 6 | `SELL` 清仓；持仓已是目标股则持有；否则先卖旧、再用可用资金整手买入 | `adjust_position` |
| 7 | 持仓风控：-15% 硬止损（**每根 K 线都执行**） | `check_lose_backtest` + `signals.exit_reason` |
| 8 | 打印当日成交、持仓、资金 | `print_trade_info_backtest` |

`STRATEGY_MODE = 'risk'` 时，步骤 2 之后会插入日线风控与分钟线风控
（沿排名顺延取第一只通过体检的），并启用大盘均线择时和移动止损。

**避免未来函数**：所有打分窗口都排除当前这根 K 线
（`closes[-(lookback+1):-1]`），当前 bar 只用于取开盘价下单和收盘价判断止损。
`tests/test_scoring.py::test_score_ignores_current_bar` 和
`tests/test_strategy_backtest.py::test_current_bar_does_not_affect_selection`
专门锁住了这一点。

## 参数一览（`momentum_timing/config.py`）

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `STRATEGY_MODE` | `'original'` | `'original'` = 最开始的选股逻辑，无风控；`'risk'` = 叠加全部风控 |
| `BUY_ON_KEEP` | `True` | KEEP 信号是否照常买入（原脚本行为） |
| `CONCEPT_SECTORS` | `['沪深a股']` | 股票池板块；改成 `CONCEPT_SECTORS_FULL` 即切回 62 个热门概念 |
| `MIN_MARKET_CAP` / `MAX_MARKET_CAP` | 30 亿 / 500 亿 | 总市值区间 |
| `EXCLUDED_CODE_PREFIXES` | `()` | 想屏蔽创业板/科创板时填 `('300', '301', '688')` |
| `LOOKBACK_DAYS` | 5 | 动量回归窗口（原脚本注释中的备选值 29） |
| `TRADING_DAYS_PER_YEAR` | 244 | 年化系数 |
| `SCORE_HISTORY_DAYS` | 5 | 额外回溯的历史分数天数（序列长度 = 该值 + 1） |
| `DECLINE_DAYS_TO_SELL` | 2 | 动量分数连续下降几天就卖出 |
| `STOP_LOSS_RATIO` | -0.15 | 硬止损线 |
| `RSRS_N` / `RSRS_M` | 21 / 600 | RSRS 回归窗口 / zscore 样本数 |
| `RSRS_INDEX` | `000300.SH` | 大盘择时基准 |
| `RSRS_ENABLED` | `False` | 保持原逻辑：RSRS 只打印不介入；置 `True` 后低于 `RSRS_BUY_THRESHOLD` 不买入 |
| `LIMIT_RATIO_BY_PREFIX` | 300/301/688 → 20% | 涨跌停幅度，其余 10% |
| `RISK_ENABLED` | 由 `STRATEGY_MODE` 决定 | 风控总开关；单条阈值设为 `None` 即关闭该项 |
| `RISK_PRESET` | `'normal'` | 三档预设：`loose` / `normal` / `strict`，一行切换整套阈值 |
| `RISK_PENALTY_LIMIT` | 4 | 软规则扣分累计达到该值才否决（`=1` 即"命中一条就否决"） |
| `RISK_MAX_CANDIDATES` | 30 | 第 1 名被否决后，沿排名往下最多再试几只 |
| `RISK_MAX_CONSECUTIVE_LIMIT_UP` | 0 | 前一日涨停就不碰（硬否决，拦跌停最有效的一条） |
| `RISK_MAX_GAIN_SHORT` / `LONG` | 40% / 100% | 近 5 日、近 20 日累计涨幅上限 |
| `RISK_MAX_BIAS` | 30% | 相对 MA20 的乖离率上限 |
| `RISK_MAX_GAP_UP` / `DOWN` | 7% / 7% | 当日高开、低开超过该幅度不买 |
| `RISK_FALLBACK_TO_BEST` | `False` | 全被否决时是否兜底买扣分最低的那只 |
| `RISK_DEBUG` | `False` | 打印每只候选的风控指标明细，用于按真实数据校准阈值 |
| `INTRADAY_ENABLED` | 由 `STRATEGY_MODE` 决定 | 分钟线风控总开关，回看 `INTRADAY_DAYS`(=3) 个完整交易日 |
| `INTRADAY_MAX_FAILED_LIMIT_UP` | 0 | 近 3 日炸板（摸涨停没封住）次数上限 |
| `INTRADAY_MIN_TAIL_RETURN` | -4% | 最近一日尾盘 30 分钟跌幅下限 |
| `INTRADAY_MAX_DOWN_AMOUNT_RATIO` | 0.70 | 下跌分钟成交额占比上限 |
| `INTRADAY_MAX_POST_HIGH_AMOUNT_RATIO` | 0.75 | 日内最高点之后的成交额占比上限 |
| `INTRADAY_REQUIRE_DATA` | `False` | 分钟数据缺失时是否直接否决（QMT 默认没下载分钟数据） |
| `MARKET_FILTER_ENABLED` | 由 `STRATEGY_MODE` 决定 | 沪深 300 跌破 MA20 时 `no_new`（或 `exit_all`） |
| `TRAILING_STOP_RATIO` | `None`（`risk` 档为 10%） | 从持仓期间最高价回撤该比例即离场 |

风控的完整规则表、默认阈值和调参建议见 [`docs/risk.md`](docs/risk.md)。
| `LOT_SIZE` | 100 | 一手股数 |
| `WARMUP_BARS` | 15 | 热身 K 线数 |

## 与原脚本的差异

行为上保持一致，只修了会直接报错或明显不符合意图的地方，详见
[`docs/strategy.md`](docs/strategy.md)：

1. `get_price_and_limits` 异常分支原本返回 3 个值、正常分支返回 4 个值，
   拿不到行情时解包会抛异常 —— 统一成 4 个返回值。
2. 市值过滤里引用了被注释掉的 `last_close`，`NameError` 被外层 `except` 吞掉，
   导致市值条件实际失效 —— 改为使用当日收盘价，过滤真正生效。
3. `filter_target` 的跌停判断写死 10%，对创业板/科创板不成立 ——
   改为按代码前缀取 20%/10%。
5. 股票池为空或候选被过滤时原逻辑直接 `return`，当天持仓就没人做止损了 ——
   现在持仓风控每根 K 线都执行。
4. `KEEP` 信号的处理由 `BUY_ON_KEEP` 控制，默认 `True`（与原脚本一致，照常买入）；
   设为 `False` 则不新开仓。
