# 原始脚本（用户提供，仅作存档与对照，不参与运行）
# 本项目的等价实现见 momentum_timing/ 与 qmt/strategy_backtest.py
#coding:gbk
"""
A股股票策略 [回测版]：热门概念池 + 对数线性回归动量打分 + RSRS修正标准分大盘择时
					   + 动量分数连续下降个股择时 + 14:50固定-15%硬止损

回测版与实盘版的主要区别：
  1. 使用 handlebar 逐K线驱动，替代 run_time 定时任务
  2. get_market_data_ex 设置 subscribe=False，读取本地数据
  3. 用 get_market_data_ex 替代 get_full_tick 获取当前价格
  4. 回测使用模拟资金账号 "testS"
  5. 止损使用当日收盘价判断（回测无法区分 14:50 盘中价）
  6. 选股使用上一根K线之前的数据，避免未来函数

运行方式：
  在 QMT 客户端 → 点击"回测" → 选择主图品种（如沪深300）→ 设置回测参数 → 运行
"""

import pandas as pd
import numpy as np

# ============================================================
# 全局变量：保存跨 bar 的状态
# ============================================================
class G:
	pass

g = G()

# 策略名称
STRATEGY_NAME = '动量择时策略'

# 概念板块列表
CONCEPT_SECTORS = [
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
CONCEPT_SECTORS=['沪深a股']
# 过滤条件
MIN_MARKET_CAP = 30e8
MAX_MARKET_CAP = 500e8

# 动量打分参数
LOOKBACK_DAYS = 5   #29
TRADING_DAYS_PER_YEAR = 244

# RSRS 参数
RSRS_N = 21
RSRS_M = 600

# 止损线
STOP_LOSS_RATIO = -0.15


# ============================================================
# 系统函数
# ============================================================

def init(C):
	"""
	回测初始化
	"""
	g.account = "testS"	   # 回测模拟账号
	g.acct_type = "STOCK"	 # 股票账号
	g.stock_df = {}		   # 近5日动量分数序列
	g.today_target = None	 # 今日目标股票
	g.bar_count = 0		   # 已处理 bar 计数

	print('[动量择时策略-回测版] 初始化完成')
	print(f'  回测账号: {g.account}, 类型: {g.acct_type}')
	print(f'  概念板块数: {len(CONCEPT_SECTORS)}')
	print(f'  动量回看: {LOOKBACK_DAYS}天, 止损线: {STOP_LOSS_RATIO:.0%}')


def handlebar(C):
	"""
	每根日K线触发一次，模拟完整交易日流程：
	  ① 选股 + 动量打分 + 择时 + 调仓（等价于 09:31 my_trade）
	  ② 止损检查（等价于 14:50 check_lose，使用当日收盘价）
	  ③ 打印复盘（等价于 15:05 print_trade_info）
	"""
	g.bar_count += 1

	# 获取当前 bar 日期
	bar_date = timetag_to_datetime(C.get_bar_timetag(C.barpos), '%Y%m%d%H%M%S')

	# 前几根 bar 数据不足，跳过
	if g.bar_count < LOOKBACK_DAYS + 10:
		return

	print('\n' + '=' * 60)
	print(f'[回测] Bar#{g.bar_count} 日期: {bar_date}')
	print('=' * 60)

	# ============================================================
	# ① 主选股 + 主调仓（等价于 09:31 my_trade）
	# ============================================================
	# 步骤1：构建股票池
	pool = get_stock_pool(C, bar_date)
	#pool.append('688356.SH')
	if not pool:
		print('[回测] 股票池为空，跳过今日')
		return
	print(f'[回测] 步骤1 - 股票池: {len(pool)} 只')

	# 步骤2：动量打分选股，取第1名
	target_stock = get_rank(pool, C, bar_date)
	if target_stock is None:
		print('[回测] 步骤2 - 未选出目标股票')
		return
	print(f'[回测] 步骤2 - 目标: {target_stock} {C.get_stock_name(target_stock)}')

	# 步骤3：计算近5日动量分数序列
	g.stock_df = rank_stock_change(target_stock, C, bar_date)
	scores = g.stock_df.get(target_stock, [])
	print(f'[回测] 步骤3 - 近5日动量分数: {[round(s, 4) for s in scores]}')

	# 步骤4：过滤候选股（跌停、停牌）
	target_stock = filter_target(target_stock, C, bar_date)
	if target_stock is None:
		print('[回测] 步骤4 - 目标股票被过滤')
		return
	g.today_target = target_stock
	print(f'[回测] 步骤4 - 过滤通过: {target_stock}')

	# 步骤5：计算综合择时信号
	signal = get_timing_signal(target_stock, C, bar_date)
	print(f'[回测] 步骤5 - 择时信号: {signal}')

	# 步骤6：执行调仓
	adjust_position(target_stock, signal, C, bar_date)
	print('[回测] 步骤6 - 调仓执行完毕')

	# ============================================================
	# ② 止损检查（等价于 14:50 check_lose）
	#   回测中使用当日收盘价判断
	# ============================================================
	check_lose_backtest(C, bar_date)

	# ============================================================
	# ③ 打印复盘（等价于 15:05 print_trade_info）
	# ============================================================
	print_trade_info_backtest(C, bar_date)

def get_limit_ratio(stock):
	"""
	根据代码前缀确定涨跌停幅度：
	  创业板(300/301)、科创板(688) → 20%
	  主板(60/00) → 10%
	"""
	code = stock.split('.')[0]
	if code.startswith(('300', '301', '688')):
		return 0.20
	return 0.10


def get_price_and_limits(stock, C, bar_date):
	"""
	获取某股票当日开盘价、涨停价、跌停价。
	涨跌停比例按代码前缀动态确定。
	返回 (open, limit_up, limit_down)，拿不到时返回 (0.0, 0.0, 0.0)。
	"""
	try:
		data = C.get_market_data_ex(
			['open','low', 'preClose'], [stock],
			period='1d',
			end_time=bar_date,
			count=1,
			dividend_type='none',
			fill_data=True,
			subscribe=False
		)
	except Exception:
		return 0.0, 0.0, 0.0

	if stock not in data or data[stock] is None or len(data[stock]) == 0:
		return 0.0, 0.0, 0.0

	df = data[stock]
	open_price = float(df['open'].iloc[-1])
	pre_close = float(df['preClose'].iloc[-1]) if 'preClose' in df.columns else open_price
	low_price=float(df['low'].iloc[-1])
	if pre_close <= 0:
		return open_price, 0.0, 0.0

	ratio = get_limit_ratio(stock)
	limit_up = round(pre_close * (1 + ratio), 2)
	limit_down = round(pre_close * (1 - ratio), 2)
	return open_price, limit_up, limit_down,low_price




# ============================================================
# 回测版止损检查
# ============================================================

def check_lose_backtest(C, bar_date):
	"""
	回测版止损：使用当日收盘价判断是否触发 -15% 硬止损
	"""
	holdings = get_trade_detail_data(g.account, g.acct_type, 'position')
	if not holdings:
		return

	for pos in holdings:
		stock = pos.m_strInstrumentID + '.' + pos.m_strExchangeID
		cost_price = pos.m_dOpenPrice
		volume = pos.m_nCanUseVolume
		if volume <= 0 or cost_price <= 0:
			continue

		# 回测中用 get_market_data_ex 获取当日收盘价
		try:
			data = C.get_market_data_ex(
				['close'], [stock],
				period='1d',
				end_time=bar_date,
				count=1,
				dividend_type='none',
				fill_data=True,
				subscribe=False
			)
		except Exception:
			continue

		if stock not in data or data[stock] is None or len(data[stock]) == 0:
			continue

		current_price = data[stock]['close'].iloc[-1]
		if current_price <= 0:
			continue

		profit_ratio = (current_price - cost_price) / cost_price
		print(f'[止损检查] {stock} {C.get_stock_name(stock)} '
			  f'成本:{cost_price:.2f} 收盘:{current_price:.2f} 盈亏:{profit_ratio:.2%}')

		if profit_ratio <= STOP_LOSS_RATIO:
			print(f'[止损检查] ? {stock} 触发硬止损！盈亏 {profit_ratio:.2%} <= -15%，强制清仓')
			msg = f'硬止损平仓 {stock}'
			passorder(24, 1101, g.account, stock, 5, -1, volume,
					  STRATEGY_NAME, 1, msg, C)


# ============================================================
# 回测版复盘打印
# ============================================================

def print_trade_info_backtest(C, bar_date):
	"""
	回测版复盘：打印当日成交、持仓、资金
	"""
	# 成交记录
	deals = get_trade_detail_data(g.account, g.acct_type, 'deal')
	if deals:
		# 只打印当天的成交
		today_deals = []
		for deal in deals:
			deal_date = deal.m_strTradeDate.replace('-', '') if '-' in deal.m_strTradeDate else deal.m_strTradeDate
			if deal_date == bar_date[:8]:
				today_deals.append(deal)
		if today_deals:
			print(f'--- 今日成交 ({len(today_deals)} 笔) ---')
			for deal in today_deals:
				print(f'  {deal.m_strInstrumentID}.{deal.m_strExchangeID} '
					  f'{"买入" if deal.m_nDirection == 1 else "卖出"} '
					  f'价格:{deal.m_dPrice:.2f} 数量:{deal.m_nVolume}')

	# 持仓信息
	holdings = get_trade_detail_data(g.account, g.acct_type, 'position')
	if holdings:
		total_mv = 0
		for pos in holdings:
			stock = pos.m_strInstrumentID + '.' + pos.m_strExchangeID
			cost_price = pos.m_dOpenPrice
			volume = pos.m_nCanUseVolume
			if volume <= 0:
				continue

			try:
				data = C.get_market_data_ex(
					['close'], [stock],
					period='1d',
					end_time=bar_date,
					count=1,
					dividend_type='none',
					subscribe=False
				)
				current_price = data[stock]['close'].iloc[-1] if stock in data else 0
			except Exception:
				current_price = 0

			market_value = current_price * volume
			total_mv += market_value
			profit_ratio = (current_price - cost_price) / cost_price if cost_price > 0 else 0

			print(f'  持仓: {stock} {C.get_stock_name(stock)} '
				  f'成本:{cost_price:.2f} 收盘:{current_price:.2f} '
				  f'盈亏:{profit_ratio:.2%} 市值:{market_value:.0f}')

	# 账户资金
	acc = get_trade_detail_data(g.account, g.acct_type, 'account')
	if acc:
		acc = acc[0]
		print(f'  资金: 可用={acc.m_dAvailable:.0f} 总资产={acc.m_dBalance:.0f}')


# ============================================================
# 步骤1：构建股票池 get_stock_pool()
# ============================================================

def get_stock_pool(C, bar_date):
	"""
	回测版股票池构建
	使用 bar_date 之前的行情数据，避免未来函数
	"""
	pool_set = set()

	for sector_name in CONCEPT_SECTORS:
		try:
			stocks = C.get_stock_list_in_sector(sector_name)
			for s in stocks:
				pool_set.add(s)
		except Exception:
			pass

	if not pool_set:
		print('[get_stock_pool] 概念板块未获取到股票')
		return []

	# 代码前缀过滤
	pool_list = []
	for stock in pool_set:
		code = stock.split('.')[0]
		#if code.startswith('300') or code.startswith('301'):
			#continue
		#if code.startswith('688'):
			#continue
		pool_list.append(stock)

	if not pool_list:
		return []

	# 回测版：用 get_market_data_ex 替代 get_full_tick
	# 获取前一日收盘价、停牌状态
	try:
		data = C.get_market_data_ex(
			['close', 'preClose', 'suspendFlag'],
			pool_list,
			period='1d',
			end_time=bar_date,
			count=2,
			dividend_type='none',
			fill_data=True,
			subscribe=False
		)
		#print('get_stock_pool',data)
	except Exception as e:
		print(f'[get_stock_pool] 批量获取行情失败: {e}')
		return []

	result = []
	#print('get_stock_pool',pool_list,data)
	for stock in pool_list:
		if stock not in data or data[stock] is None:
			continue
		df = data[stock]
		if len(df) < 1:
			continue

		# 停牌过滤：suspendFlag == 1
		if 'suspendFlag' in df.columns and len(df) >= 1:
			if df['suspendFlag'].iloc[-1] == 1:
				continue

		# 当日收盘价和前收盘价
		#last_close = df['close'].iloc[-1] if 'close' in df.columns else 0
		#pre_close = df['preClose'].iloc[-1] if 'preClose' in df.columns and len(df) >= 1 else last_close

		# 跌停过滤
		#if last_close > 0 and pre_close > 0:
			#limit_down = round(pre_close * 0.9, 2)
			#if last_close <= limit_down:
				#continue

		# ST 过滤 + 市值过滤
		try:
			detail = C.get_instrument_detail(stock)
			if not detail:
				continue

			stock_name = detail.get('InstrumentName', '')
			if 'ST' in stock_name.upper():
				continue

			total_value = detail.get('TotalValue', 0)
			if total_value <= 0:
				total_shares = detail.get('TotalShares', 0)
				if total_shares > 0 and last_close > 0:
					total_value = total_shares * last_close
			if total_value > 0 and (total_value < MIN_MARKET_CAP or total_value > MAX_MARKET_CAP):
				continue
		except Exception:
			pass

		result.append(stock)

	return result


# ============================================================
# 步骤2：动量打分选股 get_rank()
# ============================================================

def get_rank(pool, C, bar_date):
	"""
	回测版动量打分：使用 bar_date 之前的数据，选第1名
	count 多取 1 根，切片排除当前 bar，避免未来函数
	"""
	if not pool:
		return None

	scores = {}
	try:
		data = C.get_market_data_ex(
			['close'], pool,
			period='1d',
			end_time=bar_date,
			count=LOOKBACK_DAYS + 2,  # 多取1根，排除当前bar
			dividend_type='none',
			fill_data=True,
			subscribe=False
		)
	except Exception as e:
		print(f'[get_rank] 批量获取行情失败: {e}')
		return None

	for stock in pool:
		if stock not in data or data[stock] is None:
			continue
		df = data[stock]
		if len(df) < LOOKBACK_DAYS + 1:
			continue

		close_prices = df['close'].values
		# 排除当前 bar（最后1根），使用前 LOOKBACK_DAYS 根
		hist = close_prices[-(LOOKBACK_DAYS + 1):-1]
		#print(bar_date,df,hist)
		if len(hist) < LOOKBACK_DAYS or np.any(np.isnan(hist)):
			continue

		score = calc_momentum_score(hist)
		if score is not None:
			scores[stock] = score

	if not scores:
		return None

	sorted_stocks = sorted(scores.items(), key=lambda x: x[1], reverse=True)
	print('sorted_stocks',sorted_stocks)
	best = sorted_stocks[0]
	print(f'[get_rank] Top3: {[(s, round(sc, 4)) for s, sc in sorted_stocks[:3]]}')
	return best[0]


# ============================================================
# 线性回归工具函数
# ============================================================

def linear_regression(x, y):
	"""numpy.polyfit 一元线性回归，返回 (slope, r_squared)"""
	x = np.asarray(x, dtype=float)
	y = np.asarray(y, dtype=float)
	if len(x) < 2:
		return 0.0, 0.0

	slope, intercept = np.polyfit(x, y, 1)
	y_pred = slope * x + intercept
	ss_res = np.sum((y - y_pred) ** 2)
	ss_tot = np.sum((y - np.mean(y)) ** 2)
	r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

	return slope, r2


def calc_momentum_score(close_prices):
	"""
	动量分数 = 年化收益率 * |R2|
	对对数价格做线性回归
	"""
	if len(close_prices) < 2:
		return None

	log_prices = np.log(close_prices)
	X = np.arange(len(log_prices), dtype=float)

	try:
		slope, r2 = linear_regression(X, log_prices)
	except Exception:
		return None

	if r2 <= 0:
		return 0.0

	annual_return = np.exp(slope * TRADING_DAYS_PER_YEAR) - 1
	return annual_return * abs(r2)


# ============================================================
# 步骤3：计算近5日动量分数序列 rank_stock_change()
# ============================================================

def rank_stock_change(stock, C, bar_date):
	"""
	回测版：计算目标股票近5日动量分数序列
	所有数据均排除当前 bar，避免未来函数
	"""
	result = {}

	try:
		data = C.get_market_data_ex(
			['close'], [stock],
			period='1d',
			end_time=bar_date,
			count=LOOKBACK_DAYS + 5 + 2,  # 多取1根排除当前bar
			dividend_type='none',
			fill_data=True,
			subscribe=False
		)
	except Exception as e:
		print(f'[rank_stock_change] 获取行情失败: {e}')
		return result

	if stock not in data or data[stock] is None:
		return result

	df = data[stock]
	if len(df) < LOOKBACK_DAYS + 2:
		return result

	close_prices = df['close'].values
	scores = []

	# 从远到近：d-4, d-3, d-2, d-1, d0
	for i in range(5, 0, -1):
		# 排除当前 bar，所以切片偏移 +1
		window = close_prices[-(LOOKBACK_DAYS + 1 + i):-(i + 1)]
		#print('window',df,window)
		if len(window) >= LOOKBACK_DAYS and not np.any(np.isnan(window)):
			score = calc_momentum_score(window)
			scores.append(score if score is not None else 0.0)
		else:
			scores.append(0.0)

	# 最新一天（d0，排除当前bar）
	latest = close_prices[-(LOOKBACK_DAYS + 1):-1]
	if len(latest) >= LOOKBACK_DAYS and not np.any(np.isnan(latest)):
		score = calc_momentum_score(latest)
		scores.append(score if score is not None else 0.0)
	else:
		scores.append(0.0)

	result[stock] = scores
	return result


# ============================================================
# 步骤4：过滤候选股
# ============================================================

def filter_target(stock, C, bar_date):
	"""
	回测版：剔除跌停、停牌
	使用 bar_date 当日数据判断
	"""
	if stock is None:
		return None

	try:
		data = C.get_market_data_ex(
			['open','close', 'preClose', 'suspendFlag'],
			[stock],
			period='1d',
			end_time=bar_date,
			count=1,
			dividend_type='none',
			fill_data=True,
			subscribe=False
		)
	except Exception:
		return None

	if stock not in data or data[stock] is None or len(data[stock]) == 0:
		return None

	df = data[stock]
	suspend = df['suspendFlag'].iloc[-1] if 'suspendFlag' in df.columns else 0
	if suspend == 1:
		print(f'[filter_target] {stock} 停牌中')
		return None

	last_close = df['close'].iloc[-1]
	last_open= df['open'].iloc[-1]
	pre_close = df['preClose'].iloc[-1] if 'preClose' in df.columns else last_close

	if last_close <= 0:
		return None

	limit_down = round(pre_close * 0.9, 2)
	if last_close <= limit_down:
		print(f'[filter_target] {stock} 跌停 收盘:{last_close} 跌停价:{limit_down}')
		return None

	return stock


# ============================================================
# 步骤5：计算综合择时信号 get_timing_signal()
# ============================================================

def get_timing_signal(stock, C, bar_date):
	"""
	回测版择时信号：
	  RSRS 仅记录，不介入决策
	  实际信号 = 动量分数连续下降天数是否 >= 2
	"""
	# RSRS（仅记录）
	rsrs = calc_rsrs(C, bar_date)
	if rsrs is not None:
		print(f'[择时] RSRS修正标准分: {rsrs:.4f}')
	else:
		print('[择时] RSRS 数据不足')

	# 动量分数连续下降天数
	scores = g.stock_df.get(stock, [])
	if len(scores) < 1:	 #连续下降天数2
		return 'KEEP'

	sig = 0
	for i in range(len(scores) - 1, 0, -1):
		if scores[i] < scores[i - 1]:
			sig += 1
		else:
			break

	print(f'[择时] 动量分数序列: {[round(s, 4) for s in scores]}')
	print(f'[择时] 连续下降天数: {sig}')

	return 'SELL' if sig >= 2 else 'BUY'


def calc_rsrs(C, bar_date):
	"""
	回测版 RSRS：N=14 拟合，M=600 算 zscore
	"""
	try:
		data = C.get_market_data_ex(
			['high', 'low'], ['000300.SH'],
			period='1d',
			end_time=bar_date,
			count=RSRS_M + RSRS_N + 2,
			dividend_type='none',
			fill_data=True,
			subscribe=False
		)
	except Exception:
		return None

	if '000300.SH' not in data or data['000300.SH'] is None:
		return None

	df = data['000300.SH']
	if len(df) < RSRS_M + RSRS_N + 1:
		return None

	highs = df['high'].values
	lows = df['low'].values

	# 排除当前 bar
	highs = highs[:-1]
	lows = lows[:-1]

	betas = []
	r2_list = []
	for i in range(RSRS_N - 1, len(highs)):
		h = highs[i - RSRS_N + 1:i + 1]
		l = lows[i - RSRS_N + 1:i + 1]
		if len(h) < RSRS_N or np.any(np.isnan(h)) or np.any(np.isnan(l)):
			continue

		try:
			slope, r2 = linear_regression(l, h)
			betas.append(slope)
			r2_list.append(r2)
		except Exception:
			continue

	if len(betas) < RSRS_M:
		return None

	recent_betas = betas[-RSRS_M:]
	mean_beta = np.mean(recent_betas)
	std_beta = np.std(recent_betas)
	if std_beta == 0:
		return 0.0

	zscore = (recent_betas[-1] - mean_beta) / std_beta
	recent_r2 = r2_list[-1] if r2_list else 0
	return zscore * recent_r2


# ============================================================
# 步骤6：执行调仓 adjust_position()
# ============================================================

def adjust_position(stock, signal, C, bar_date):
	"""
	回测版调仓：
	  SELL：清仓
	  BUY/KEEP：持仓不是目标股 → 换仓；是目标股 → 持有
	"""
	try:
		data = C.get_market_data_ex(
			['open'], [stock],
			period='1d',
			end_time=bar_date,
			count=1,
			dividend_type='none',
			subscribe=False
		)
		current_price = data[stock]['open'].iloc[-1] if stock in data else 0
		print('current_price',current_price)
	except Exception:
		print(f'[调仓] 无法获取 {stock} 价格')
		return
	holdings = get_trade_detail_data(g.account, g.acct_type, 'position')
	current_holdings = {}
	for pos in holdings:
		s = pos.m_strInstrumentID + '.' + pos.m_strExchangeID
		
		vol = pos.m_nCanUseVolume
		if vol > 0:
			current_holdings[s] = vol

	print(f'[调仓] 当前持仓: {current_holdings}')

	if signal == 'SELL':
		for s, vol in current_holdings.items():
			if vol > 0:
				data = C.get_market_data_ex(
			['open'], [s],
			period='1d',
			end_time=bar_date,
			count=1,
			dividend_type='none',
			subscribe=False
		)
				msg = f'SELL信号 清仓 {s}'
				print(f'[调仓] {msg}')
				passorder(24, 1101, g.account, s, 11, data[s]['open'].iloc[-1], vol,
						  STRATEGY_NAME, 1, msg, C)
		return

	# BUY / KEEP：已是目标股则持有
	if stock in current_holdings and current_holdings[stock] > 0:
		print(f'[调仓] KEEP: 继续持有 {stock}')
		return

	# 换仓：先卖旧
	for s, vol in current_holdings.items():
		if vol > 0:
			data = C.get_market_data_ex(
			['open'], [s],
			period='1d',
			end_time=bar_date,
			count=1,
			dividend_type='none',
			subscribe=False
		)
			msg = f'切换标的 卖出 {s}'
			print(f'[调仓] {msg}')
			passorder(24, 1101, g.account, s, 11 ,data[s]['open'].iloc[-1], vol,
					  STRATEGY_NAME, 1, msg, C)

	# 获取可用资金
	acc_info = get_trade_detail_data(g.account, g.acct_type, 'account')
	if not acc_info:
		print('[调仓] 无法获取账户信息')
		return
	available_cash = int(acc_info[0].m_dAvailable)

	# 获取目标股当日收盘价
	

	if current_price <= 0:
		print(f'[调仓] {stock} 价格异常: {current_price}')
		return

	
	
	current_price, limit_up, limit_down,low_price=get_price_and_limits(stock, C, bar_date)
	print('current_price',current_price, limit_up, limit_down,low_price)
	buy_vol = int(available_cash / current_price / 100) * 100
	if buy_vol < 100:
		print(f'[调仓] 资金不足买1手，可用:{available_cash} 股价:{current_price}')
		return
	
	if low_price>=limit_up:
		print('开盘涨停，无法买入')
		return

	msg = f'BUY信号 买入 {stock} {buy_vol}股'
	print(f'[调仓] {msg}')
	passorder(23, 1101, g.account, stock, 11,current_price , buy_vol,
			  STRATEGY_NAME, 1, msg, C)


# ============================================================
# stop 函数
# ============================================================

def stop(C):
	print(f'[动量择时策略-回测版] 回测结束，共处理 {g.bar_count} 根K线')