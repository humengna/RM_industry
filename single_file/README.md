# 单文件版（直接贴进 QMT 内置 Python）

这两个文件由 `python tools/bundle_qmt.py` 自动生成，把 `momentum_timing/` 整个包
和 `qmt/strategy_backtest.py` 拼成一个自包含脚本，**不需要任何 import 配置**。

| 文件 | 编码 | 什么时候用 |
| --- | --- | --- |
| `momentum_timing_qmt_utf8.py` | UTF-8 | **默认用这个**。在 GitHub 网页 / 编辑器里能正常显示中文，适合全选复制后粘贴进 QMT |
| `momentum_timing_qmt_gbk.py` | GBK | 老版本 QMT 以 GBK 保存脚本时用；下载到本地直接打开，别从网页复制（网页会显示成乱码） |

两个文件除第一行 `# coding:` 外内容完全一致。

## 用法

1. 打开 `momentum_timing_qmt_utf8.py`，点 GitHub 页面的 **Raw** 再全选复制
   （直接在代码视图里复制也行，但 Raw 更保险）；
2. 粘贴进 QMT 客户端的策略编辑器；
3. 把 `BACKTEST_ACCOUNT = 'testS'` 改成你 QMT 里实际存在的模拟账号，
   并在回测设置里选**同一个**账号——两处不一致的话 `get_trade_detail_data`
   取不到持仓，策略会一直空转；
4. 默认按最开始的选股逻辑运行（`STRATEGY_MODE = 'original'`，无风控过滤）；
   想启用风控把它改成 `'risk'`；
5. 回测周期选 **日线**（`handlebar` 按日 K 驱动，选分钟周期逻辑会乱），
   主图品种挑一个有连续日线的即可，例如 `000300.SH`；
6. 只有切到 `'risk'` 模式才需要 1 分钟历史数据；`'original'` 模式不读分钟线。

## 报编码错误怎么办

如果 QMT 提示 `SyntaxError: Non-UTF-8 code ...` 或中文注释变乱码，
说明首行声明和 QMT 保存文件时用的编码对不上——把第一行在
`# coding:utf-8` 和 `# coding:gbk` 之间换一下即可，**只改这一行**。

## 改参数

所有参数都集中在文件开头的 `momentum_timing/config.py` 段落里，
直接在单文件里改即可。常用开关：

```python
STRATEGY_MODE = 'original'     # 'original' = 最开始的选股逻辑（当前默认，无风控）
                               # 'risk'     = 叠加日线/分钟线/大盘风控 + 移动止损
CONCEPT_SECTORS = ['沪深a股']   # 换成 ['半导体'] 之类可以大幅加快回测
LOOKBACK_DAYS = 5              # 动量回看天数
STOP_LOSS_RATIO = -0.15        # 硬止损线
DECLINE_DAYS_TO_SELL = 2       # 动量分数连续下降几天卖出
```

`STRATEGY_MODE` 在文件**最后**一段生效（`if STRATEGY_MODE == 'original':` 会统一
覆盖前面的风控开关），所以改这一行就够了，不用逐个去改 `RISK_ENABLED`。

## 重新生成

改了 `momentum_timing/` 或 `qmt/strategy_backtest.py` 之后：

```bash
python tools/bundle_qmt.py -e utf-8 -o single_file/momentum_timing_qmt_utf8.py
python tools/bundle_qmt.py -e gbk   -o single_file/momentum_timing_qmt_gbk.py
```

`tests/test_bundle.py` 里有一条用例会检查仓库里的单文件和当前源码是否一致，
忘了重新生成时测试会失败。
