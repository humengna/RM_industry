# 策略说明与实现细节

本文档说明每一步的计算口径、与原始 QMT 脚本的对照关系，以及已知的改动点。

## 1. 动量打分

对最近 `LOOKBACK_DAYS`(=5) 个交易日的收盘价取自然对数，做一元最小二乘回归：

```
ln(P_t) = slope * t + intercept
年化收益率 = exp(slope * TRADING_DAYS_PER_YEAR) - 1      # 244 个交易日
动量分数   = 年化收益率 * |R²|
```

- `R² <= 0` 时分数记 0（价格无趋势，例如横盘）。
- 样本不足 2 根、或窗口内存在 `nan` / 非正价格时返回 `None`，该股票不参与排名。
- 实现见 `momentum_timing/indicators.py`。原脚本用 `np.polyfit(x, y, 1)`，
  这里改成闭式最小二乘解，结果在浮点误差内完全一致
  （`tests/test_indicators.py::test_linear_regression_matches_numpy` 做了对照），
  好处是内核不依赖 numpy，可以脱离 QMT 直接测试。

## 2. 取样窗口与未来函数

`get_market_data_ex` 返回的序列里，**最后一根就是当前 bar**。回测中当前 bar 的收盘价
在盘中是不可知的，直接拿来打分就是未来函数。因此所有窗口都统一切掉末尾：

```
offset = 0  ->  closes[-(lookback+1):-1]        # 当前 bar 之前的 5 根
offset = k  ->  closes[-(lookback+1+k):-(k+1)]  # 再往前推 k 根
```

历史分数序列由远及近取 `offset = 5,4,3,2,1,0`，长度 6（`SCORE_HISTORY_DAYS + 1`），
与原脚本 `rank_stock_change` 的切片完全对应
（`tests/test_scoring.py::test_history_matches_original_slicing` 做了对照）。

当前 bar 只在两处使用，都属于当日可观测信息：
- 下单价：当日 `open`（开盘价）；
- 止损判断：当日 `close`（回测无法区分 14:50 的盘中价，原脚本也是这么处理的）。

## 3. 个股择时

从分数序列末尾往回数连续下降的天数：

```
scores[i] < scores[i-1]  ->  计数 +1，否则中断
连续下降天数 >= DECLINE_DAYS_TO_SELL(=2)  ->  SELL
否则                                      ->  BUY
分数序列为空                               ->  KEEP
```

## 4. 大盘择时（RSRS 修正标准分）

以沪深 300（`RSRS_INDEX`）为基准：

1. 每个长度 `RSRS_N`(=21) 的窗口内，用当日 `low` 回归 `high`，得到斜率 `beta` 与 `R²`；
2. 取最近 `RSRS_M`(=600) 个 `beta` 计算 zscore；
3. 修正标准分 = `zscore * 最新窗口 R²`。

`RSRS_ENABLED` 默认为 `False`，与原脚本一致：**只打印、不参与下单决策**。
把它置为 `True` 后，修正标准分低于 `RSRS_BUY_THRESHOLD`(=0.7) 时买入信号会被降级为
`KEEP`（不新开仓），卖出信号不受影响。

## 5. 股票池过滤

顺序：代码前缀 → 停牌(`suspendFlag == 1`) → ST → 总市值 → 跌停。

- 市值取 `get_instrument_detail` 的 `TotalValue`；为 0 时用 `TotalShares × 当日收盘价` 估算；
  仍取不到（<= 0）则放行，与原脚本一致。
- 跌停价按代码前缀确定幅度：创业板 `300/301`、科创板 `688` 为 20%，其余 10%，
  计算后四舍五入到 2 位小数。

## 5.5 候选风控

动量排名之后、下单之前，`momentum_timing/risk.py` 会对候选股做一轮体检：
连板、近期涨停次数、短中期涨幅、乖离率、近期跌停、振幅、波动率、量比、
换手率、成交额、次新股、当日跳空、动量分数下限。第 1 名被否决就沿排名
顺延看第 2 名，最多试 `RISK_MAX_CANDIDATES` 只。

规则清单、默认阈值、为什么这个打分公式会系统性地选出"要跌停的票"，
以及调参与验证方法，见 [risk.md](risk.md)。

## 6. 调仓与风控

| 信号 | 持仓情况 | 动作 |
| --- | --- | --- |
| `SELL` | 有持仓 | 按当日开盘价限价全部卖出 |
| `BUY` | 已持有目标股 | 不动 |
| `BUY` | 持有其他股票 | 先按开盘价卖出旧股，再用可用资金整手买入目标股 |
| `BUY` | 空仓 | 用可用资金整手买入目标股 |
| `KEEP` | 未持有目标股 | 不开仓 |

- 买入量 `= int(可用资金 / 开盘价 / 100) * 100`，不足 1 手放弃；
- 当日最低价 ≥ 涨停价（一字涨停）时放弃买入；
- 止损：`(收盘价 - 成本价) / 成本价 <= -15%` → 市价（`price_type=5`, `price=-1`）清仓；
- 移动止损：相对持仓期间最高价回撤 `TRAILING_STOP_RATIO`(=10%) 也清仓；
- 一字跌停（当日最高价即跌停价）时卖单成交不了，回测中跳过该笔卖出。

下单参数：`passorder(23买/24卖, 1101按股数, 账号, 代码, 价格类型, 价格, 数量,
策略名, 1快速下单, 备注, C)`。

## 7. 相对原脚本的改动

### 已修复的缺陷

1. **`get_price_and_limits` 返回值个数不一致**
   异常与数据缺失分支 `return 0.0, 0.0, 0.0`（3 个），正常分支返回 4 个值，
   而调用方按 4 个解包 —— 任何一次取数失败都会抛 `ValueError`。现统一返回 4 个值。
2. **市值过滤实际失效**
   `get_stock_pool` 中 `total_shares * last_close` 引用了已被注释掉的 `last_close`，
   抛出的 `NameError` 被外层 `except Exception: pass` 吞掉，该股票被无条件放行。
   现改为使用当日收盘价，市值区间真正生效。
3. **`filter_target` 跌停判断写死 10%**
   对创业板/科创板（20% 幅度）会误判。现统一走 `universe.limit_prices`。
4. **重复取数**
   `adjust_position` 里对同一只股票连续两次请求当日行情，现合并为一次。

### 行为差异（有意为之）

- `KEEP` 信号不再买入。原脚本中 `KEEP` 只在"分数序列为空"（取数失败）时出现，
  却仍会照常下单；这里改为不开仓，同时让 RSRS 否决也复用 `KEEP` 语义。
- 卖出改用 `sell_stock` 统一处理：取不到开盘价时退化为市价卖出，
  原脚本在这种情况下会直接抛异常。
- 持仓风控改为每根 K 线都执行。原脚本在"股票池为空 / 未选出目标 / 目标被过滤"
  时直接 `return`，当天的持仓止损被整段跳过。
- 新增候选风控与大盘风控（见 [risk.md](risk.md)），默认开启，会改变选股结果；
  想对照原始行为把 `RISK_ENABLED` 和 `MARKET_FILTER_ENABLED` 设为 `False` 即可。

## 8. 后续接实盘要改的地方

当前脚本是回测版，接实盘时主要改三处（逻辑内核 `momentum_timing/` 不用动）：

1. 驱动方式：`handlebar` 逐 K 线 → `run_time` 定时任务（09:31 调仓、14:50 止损、15:05 复盘）；
2. 取数：`get_market_data_ex(subscribe=False)` → `get_full_tick` 取实时价，
   历史数据仍走 `get_market_data_ex`；
3. 账号：`config.BACKTEST_ACCOUNT` 换成实盘资金账号，并把 14:50 的止损判断
   从"当日收盘价"改为"实时价"。
