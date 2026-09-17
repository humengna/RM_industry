# 动量择时策略（QMT 回测版）

A 股单标的轮动策略：**概念/全市场股票池 → 对数线性回归动量打分 → 取第 1 名 →
动量分数连续下降择时 + RSRS 大盘择时（默认只记录）→ 满仓换股 → -15% 硬止损**。

策略逻辑与参数来自原始的 QMT 单文件脚本（存档于
[`reference/original_qmt_backtest.py`](reference/original_qmt_backtest.py)），
本项目把它拆成"可测试的纯计算内核"和"QMT 接口层"两部分。

## 目录结构

```
momentum_timing/          纯计算内核（只依赖标准库，可单元测试）
├── config.py             全部参数，唯一的参数来源
├── indicators.py         一元线性回归 / 动量分数 / RSRS 修正标准分
├── scoring.py            打分窗口（排除当前 bar）、历史分数序列、排名
├── signals.py            连续下降择时、RSRS 否决、止损判断
├── universe.py           涨跌停价、停牌 / ST / 市值 / 代码前缀过滤
└── portfolio.py          整手下单量、一字涨停买不进判断
qmt/
└── strategy_backtest.py  QMT 回测脚本：init / handlebar / stop + 取数 + 下单
tools/
└── bundle_qmt.py         打包成单文件，方便直接贴进 QMT 客户端
tests/                    74 个单元测试 + 模拟 QMT 环境的端到端测试
reference/                原始脚本存档
```

## 运行方式

### 方式 A：单文件（推荐，QMT 客户端里最省事）

```bash
python tools/bundle_qmt.py          # 生成 dist/momentum_timing_qmt.py（GBK 编码）
```

把生成的文件内容贴进 QMT 的策略编辑器 → 点击"回测" → 选择主图品种（如沪深 300）
→ 设置回测区间与初始资金 → 运行。生成的文件是自包含的，不需要配置任何路径。

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
python -m pytest            # 74 passed
```

测试不需要 QMT：`tests/fake_qmt.py` 模拟了 `ContextInfo`、`passorder`、
`get_trade_detail_data`，可以在本地把 `handlebar` 整条链路跑通。

## 策略流程（每根日 K 线）

| 步骤 | 做什么 | 代码位置 |
| --- | --- | --- |
| 0 | 前 `WARMUP_BARS`(=15) 根 K 线数据不足，直接跳过 | `handlebar` |
| 1 | 取板块成分股，过滤停牌 / ST / 市值不在 30~500 亿 / 跌停 | `get_stock_pool` + `universe.passes_filters` |
| 2 | 对每只股票的对数收盘价做线性回归，按 `年化收益率 × R² 绝对值` 打分，取第 1 名 | `get_rank` + `scoring.rank_pool` |
| 3 | 计算目标股由远及近的 6 个历史动量分数 | `rank_stock_change` + `scoring.momentum_score_history` |
| 4 | 目标股停牌 / 跌停则放弃 | `filter_target` |
| 5 | 分数连续下降 ≥ 2 天 → `SELL`，否则 `BUY`；RSRS 只打印 | `get_timing_signal` + `signals.timing_signal` |
| 6 | `SELL` 清仓；持仓已是目标股则持有；否则先卖旧、再用可用资金整手买入 | `adjust_position` |
| 7 | 收盘价相对成本跌破 -15% → 市价强制清仓 | `check_lose_backtest` |
| 8 | 打印当日成交、持仓、资金 | `print_trade_info_backtest` |

**避免未来函数**：所有打分窗口都排除当前这根 K 线
（`closes[-(lookback+1):-1]`），当前 bar 只用于取开盘价下单和收盘价判断止损。
`tests/test_scoring.py::test_score_ignores_current_bar` 和
`tests/test_strategy_backtest.py::test_current_bar_does_not_affect_selection`
专门锁住了这一点。

## 参数一览（`momentum_timing/config.py`）

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
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
4. `KEEP` 信号（分数序列取不到，或开启 RSRS 后被大盘否决）不再新开仓，
   原脚本此时会照常买入。
