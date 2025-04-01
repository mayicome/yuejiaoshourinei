from trade_engine import TradeEngine
import pandas as pd
from datetime import datetime
from xtquant import xtdata
import time
import logging
import os
import numpy as np
from drawdown_calculator import DrawdownCalculator

def symbol2stock(symbol):
    """
    将股票代码转换为QMT识别的格式
    Args:
        symbol (str): 原始股票代码（例如：000001、600001等）
    Returns:
        str: QMT格式的股票代码（例如：000001.SZ、600001.SH等）
    """
    symbol = symbol.strip()
    
    if '.SZ' in symbol or '.SH' in symbol or '.BJ' in symbol:
        return symbol
        
    symbol = symbol.zfill(6)
    
    if symbol.startswith(('0', '1', '3')):
        return f"{symbol}.SZ"  # 深交所
    elif symbol.startswith(('5', '6')):
        return f"{symbol}.SH"  # 上交所
    elif symbol.startswith(('4', '8')):
        return f"{symbol}.BJ"  # 北交所
    else:
        raise ValueError(f"无效的股票代码: {symbol}")
    
class BacktestEngine(TradeEngine):
    """
    回测引擎类
    用于执行策略回测，模拟交易环境，记录交易过程和结果
    """
    
    def __init__(self, stock_code, base_position, can_use_position, target_position, avg_cost, initial_capital=1000000, period='tick'):
        """
        初始化回测引擎
        Args:
            stock_code (str): 股票代码
            base_position (int): 初始持仓数量
            can_use_position (int): 可用持仓数量
            target_position (int): 目标持仓数量
            avg_cost (float): 初始持仓成本
            initial_capital (float): 初始资金，默认100万
            period (str): 数据周期，默认'tick'
        """
        super().__init__()
        self.logger = logging.getLogger('Backtest')
        self.strategy = None
        self.stock_code = stock_code
        self.positions = {}
        self.trades = []
        self.data = None
        self.target_position = target_position
        self.seq = 0
        self.total_trading_days = 0
        self.total_trades = 0
        self.avg_daily_trades = 0

        xtdata.enable_hello = False
        
        # 设置初始账户信息
        self.setup_account_info(stock_code, base_position, can_use_position, target_position, avg_cost, initial_capital)

        #if self.stock_code.startswith('1') or self.stock_code.startswith('5'):
        #    self.slippage = 0.001
        #else:
        #    self.slippage = 0.01

        self.slippage = 0 # 回测时不考虑滑点

        
        # 交易费用设置
        self.commission_rate = 0.0001  # 佣金费率，双向收取，万分之1
        self.min_commission = 5.0       # 最低佣金，5元
        self.stamp_duty_rate = 0.001    # 印花税，仅卖出收取，千分之1
        self.transfer_fee_rate = 0.0000441  # 过户费（含经手费），双向收取，万分之0.441

        # 回测进度相关
        self.current_idx = 0
        self.current_datetime = None
        self.current_stock = None

        self.is_backtest = True  # 标记为回测模式

        self._data_cache = {}  # 新增数据缓存字典

        self.period = period  # 新增属性

        self.start_date = None  # 新增
        self.end_date = None    # 新增

        data_dir = os.path.join(os.path.dirname(__file__), 'data')
        # 检查是否存在all_a_stocks.csv文件
        csv_file = os.path.join(data_dir, 'all_a_stocks.csv')
        if os.path.exists(csv_file):
            try:
                self.all_a_stocks = pd.read_csv(csv_file, dtype={'证券代码': str})
                self.logger.info(f"已从{csv_file}文件读取全A股股票和基金名称信息")
            except Exception as e:
                self.logger.error(f"读取{csv_file}文件时出错: {e}")

    def get_stock_name(self, stock_code):
        # 查找匹配的股票代码
        result = self.all_a_stocks[self.all_a_stocks['证券代码'] == stock_code[:6]]
        if not result.empty:
            return result['证券简称'].values[0]
        return "未知名称"

    def load_data(self, stock_code, start_date, end_date, period="tick"):
        """带缓存的数据加载方法"""
        self.start_date = pd.to_datetime(start_date)
        self.end_date = pd.to_datetime(end_date)
        cache_key = f"{stock_code}|{start_date}|{end_date}|{period}"
        
        # 检查缓存
        if cache_key in self._data_cache:
            self.data = self._data_cache[cache_key]
            return True
        
        # 无缓存时加载数据
        stock = symbol2stock(stock_code)
        self.current_stock = stock_code
        self.period = period
        
        if period != "1d":
            startdate = start_date.strftime("%Y%m%d") + "093000"
            enddate = end_date.strftime("%Y%m%d") + "150000"
        else:
            startdate = start_date.strftime("%Y%m%d")
            enddate = end_date.strftime("%Y%m%d")
        
        self.logger.info(f"加载股票数据: {stock}, 时间范围: {startdate} - {enddate}, 周期: {period}")
        print("startdate:", startdate, "enddate:", enddate)
        
        # 获取历史行情数据
        code_list = [stock]  # 定义要下载和订阅的股票代码列表
        count = -1  # 设置count参数，使gmd_ex返回全部数据

        # 下载历史数据
        xtdata.download_history_data(stock, period, startdate, enddate)
        
        # 订阅实时行情
        if self.seq > 0:
            xtdata.unsubscribe_quote(self.seq)
            time.sleep(1)
        self.seq = xtdata.subscribe_quote(stock, period=period)  # 订阅股票的实时行情
        time.sleep(1)  # 等待一段时间，确保订阅完成

        # 获取历史行情数据
        df = xtdata.get_market_data_ex([], code_list, period=period, 
                                  start_time=startdate, 
                                  end_time=enddate, 
                                  count=count)            
        
        if stock in df and len(df[stock]) > 0:
            self.data = pd.DataFrame(df[stock])
            # 将索引重置为一个新的列，命名为'time'
            if period!="tick":
                self.data.reset_index(names=['time'], inplace=True)

            self.data = self.data.sort_values('time')
            if 'close' in self.data.columns and 'lastPrice' not in self.data.columns:
                self.data = self.data.rename(columns={'close': 'lastPrice'})
            self.current_idx = 0
            self.current_datetime = None

            self.logger.info(f"成功加载股票{stock}的历史数据，共{len(self.data)}条记录")
            
            self.data.index = pd.to_datetime(self.data.index)
            self.logger.info(f"数据时间范围: {self.data.index[0].strftime('%Y-%m-%d %H:%M:%S')} 到 {self.data.index[-1].strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 处理并缓存数据
            processed_data = self._process_data(self.data)
            self._data_cache[cache_key] = processed_data
            self.data = processed_data
            self.data = self.data[self.data['lastPrice'] > 0]
            # 保存数据到excel
            self.data.to_excel(f'{stock}.xlsx', index=False)

            return True
        
        # 如果无法从API获取数据，尝试从本地CSV文件加载
        self.logger.error(f"未获取到股票{stock}的数据或数据为空")
        return False

    def run_backtest(self):
        """
        运行回测
        Returns:
            bool: 回测是否成功完成
        """
        if not hasattr(self, 'strategy') or self.strategy is None:
            self.logger.error("策略未设置")
            return False
            
        if self.data is None or len(self.data) == 0:
            self.logger.error("没有可用的回测数据")
            return False
        
        self.logger.info(f"开始回测 - 股票代码：{self.stock_code}, 初始资金: {self.initial_cash}, 初始持仓市值: {self.initial_market_value}")
        
        self.portfolio_values = []  # 重置净值记录
        for idx, row in self.data.iterrows():
            self.current_idx = idx
            self.current_datetime = row.get('time', 0)
            
            # 根据数据周期调用相应的策略方法
            if self.period == "tick":
                self.strategy.on_tick(row)
            else:
                self.strategy.on_bar(row)
            
            current_value = self.get_portfolio_value()
            
            self.portfolio_values.append(current_value)

        return True

    def set_strategy(self, strategy):
        """
        设置回测策略
        Args:
            strategy: 策略实例
        """
        self.strategy = strategy
        #self.logger.info(f"设置策略: {strategy.__class__.__name__}")
        
    def process_bar(self, bar_data):
        """处理K线数据"""
        if hasattr(self, 'strategy'):
            self.strategy.on_bar(bar_data)
        
    def setup_account_info(self, stock_code, base_position, can_use_position, target_position, avg_cost, initial_capital):
        """
        设置账户初始信息
        Args:
            stock_code (str): 股票代码
            base_position (int): 初始持仓数量
            can_use_position (int): 可用持仓数量
            target_position (int): 目标持仓数量
            avg_cost (float): 初始持仓成本
            initial_capital (float): 初始资金
        Returns:
            bool: 是否设置成功
        """
        try:
            # 设置资金相关
            self.initial_cash = initial_capital
            self.initial_market_value = base_position * avg_cost
            self.cash = initial_capital
            self.frozen_cash = 0
            self.market_value = base_position * avg_cost
            self.total_asset = initial_capital + self.market_value
            
            # 设置持仓信息
            self.positions[stock_code] = {
                'volume': int(base_position),
                'can_use_volume': int(can_use_position),
                'open_price': avg_cost,
                'market_value': base_position * avg_cost,
            }
            return True
            
        except Exception as e:
            self.logger.error(f"设置账户信息时出错: {str(e)}")
            return False
    
    def update_account_info(self, stock_code=None, cash=None, frozen_cash=None, volume=None, can_use_volume=None, open_price=None):
        """
        更新账户信息
        Args:
            stock_code (str, optional): 股票代码
            cash (float, optional): 现金变化量
            frozen_cash (float, optional): 冻结资金变化量
            volume (int, optional): 持仓数量变化量
            can_use_volume (int, optional): 可用数量变化量
            open_price (float, optional): 持仓成本
        Returns:
            bool: 是否更新成功
        """
        try:
            # 更新持仓信息
            if all(v is not None for v in [stock_code, volume, can_use_volume, open_price]):
                self.positions[stock_code]['volume'] += int(volume)
                self.positions[stock_code]['can_use_volume'] += int(can_use_volume)
                self.positions[stock_code]['open_price'] = open_price
                self.positions[stock_code]['market_value'] = volume * open_price

            # 更新资金相关
            if cash is not None:
                self.cash += cash
            if frozen_cash is not None:
                self.frozen_cash += frozen_cash
            
            # 更新市值
            # 对于positions里的每个position,取它的总量乘以open_price得到持仓市值
            # 然后把这些持仓市值加起来得到总市值
            self.market_value = sum(position['volume'] * position['open_price'] for position in self.positions.values())
            self.total_asset = self.cash + self.market_value

            return True
            
        except Exception as e:
            self.logger.error(f"更新账户信息时出错: {str(e)}")
            return False

    def buy(self, stock_code, price, volume, datetime):
        """
        执行买入操作
        Args:
            stock_code (str): 股票代码
            price (float): 买入价格
            volume (int): 买入数量
            datetime: 交易时间
        Returns:
            tuple: (bool, str) 交易是否成功及错误信息
        """
        # 获取智能定价
        dynamic_price = self.calculate_order_price('buy', stock_code, self.bidPrices[0], self.askPrices[0], self.slippage)
        if not dynamic_price:
            self.logger.warning(f"股票代码：{stock_code}，无法获取实时价格，未能买入")
            return False, f"股票代码：{stock_code}，无法获取实时价格，未能买入"#super().buy(stock_code, price, volume, datetime)
            
        self.logger.info(f"股票代码：{stock_code}，智能买入定价: {dynamic_price} (基准价: {price})")

        # 打印买入前的持仓信息
        self.logger.info(f"股票代码：{stock_code}，买入交易前的持仓信息: {self.positions[stock_code]}")
        try:
            # 计算交易费用
            amount = dynamic_price * volume
            commission,stamp_duty,total_cost  = self.calculate_total_cost('buy',stock_code, amount)

            # 判断是否为T+0 ETF
            is_t0_etf = False
            if stock_code.startswith(('159', '511', '518', '513')):  # ETF代码前缀
                # 检查是否为T+0 ETF
                t0_keywords = ['港股', '恒生', '债券', '货币', '黄金', '原油', 'QDII', '现金', '短债', '超短债', '国债', '信用债', '可转债']
                stock_name = self.get_stock_name(stock_code)
                if any(keyword in stock_name for keyword in t0_keywords):
                    is_t0_etf = True
            # 记录交易
            trade = {
                'time': datetime,
                'stock_code': stock_code,
                'direction': 'buy',
                'price': dynamic_price,
                'volume': volume,
                'amount': amount,
                'commission': commission,
                'total_cost': total_cost,
                'volume_after_trade': self.get_volume(stock_code) + volume,
                'can_use_volume_after_trade': self.get_can_use_volume(stock_code) + (volume if is_t0_etf else 0)
            }
            self.trades.append(trade)

            if stock_code in self.positions:
                # 计算新的平均成本
                old_volume = self.positions[stock_code]['volume']
                old_cost = self.positions[stock_code]['open_price'] * old_volume
                new_cost = old_cost + dynamic_price * volume
                new_avg_price = new_cost / (old_volume + volume)
            else:
                new_avg_price = dynamic_price

            # 更新账户信息
            self.update_account_info(
                stock_code=stock_code,
                cash=-total_cost,
                volume=volume,
                can_use_volume=volume if is_t0_etf else 0,  # 如果是T+0 ETF，买入时增加可用持仓量
                open_price=new_avg_price
            )

            #调用on_trade()，触发更新交易表格
            self.on_trade(trade)

            # 打印买入后的持仓信息
            self.logger.info(f"股票代码：{stock_code}，买入交易后的持仓信息: {self.positions[stock_code]}")
    
            return True, "买入成功"

        except Exception as e:
            self.logger.error(f"买入出错: {str(e)}")
            return False, f"买入出错: {str(e)}"

    def sell(self, stock_code, price, volume, datetime):
        """
        修改后的卖出方法，添加盈亏计算
        """
        # 获取智能定价
        dynamic_price = self.calculate_order_price('sell', stock_code, self.bidPrices[0], self.askPrices[0], self.slippage)
        if not dynamic_price:
            self.logger.warning(f"股票代码：{stock_code}，无法获取实时价格，未能卖出")
            return False, f"股票代码：{stock_code}，无法获取实时价格，未能卖出"
            
        self.logger.info(f"股票代码：{stock_code}，智能卖出定价: {dynamic_price} (基准价: {price})")

        # 打印交易前的持仓信息
        self.logger.info(f"股票代码：{stock_code}，卖出交易前的持仓信息: {self.positions[stock_code]}")
        #try:            
        if True:
            # 计算盈亏
            position = self.positions.get(stock_code)
            if position:
                # 计算持仓成本
                original_volume = position['volume']
                original_cost = position['open_price'] * original_volume
                cost = position['open_price'] * volume
                # 计算实际成交金额（扣除费用）
                amount = dynamic_price * volume
                commission,stamp_duty,total_fee  = self.calculate_total_cost('sell',stock_code, amount)
                net_proceeds = amount - total_fee
                
                # 计算盈亏
                pnl = net_proceeds - cost
                
                # 保持剩余持仓成本不变（先进先出法）
                if volume < original_volume:# 部分卖出
                    new_avg_price = position['open_price']  # 部分卖出均价不变，全部卖出持仓为0，均价变不变无所谓
                else: #全部平仓
                    new_avg_price = 0

                # 修改交易记录字典
                trade = {
                    'time': datetime,
                    'stock_code': stock_code,
                    'direction': 'sell',
                    'price': dynamic_price,
                    'volume': volume,
                    'pnl': pnl,  # 新增盈亏字段
                    'amount': amount,
                    'commission': commission,
                    'stamp_duty': stamp_duty,
                    'total_fee': total_fee,
                    'net_amount': net_proceeds,
                    'volume_after_trade': self.get_volume(stock_code) - volume,
                    'can_use_volume_after_trade': self.get_can_use_volume(stock_code) - volume
                }
                self.trades.append(trade)

                # 更新账户信息
                self.update_account_info(
                    stock_code=stock_code,
                    cash=net_proceeds,
                    volume=-volume,
                    can_use_volume=-volume,
                    open_price=new_avg_price
                )

                #调用on_trade()，触发更新交易表格
                self.on_trade(trade)

                # 打印交易后的持仓信息
                self.logger.info(f"股票代码：{stock_code}，卖出交易后的持仓信息: {self.positions[stock_code]}")
                
                self.logger.info(f"卖出盈亏计算: 成本价={position['open_price']:.2f} 成交价={dynamic_price:.2f} 数量={volume} 盈亏={pnl:.2f}")
                
                return True, "卖出成功"
            
        #except Exception as e:
        #    self.logger.error(f"卖出出错: {str(e)}")
        #    return False, f"卖出出错: {str(e)}"

    def calculate_total_cost(self, direction, stock_code, amount):
        """
        计算交易成本
        Args:
            amount (float): 交易金额
        Returns:
            float: 佣金金额
        """
        commission = amount * self.commission_rate

        if not stock_code.startswith(('1', '5')):
            commission = max(commission, self.min_commission)
        transfer_fee = amount * self.transfer_fee_rate

        if direction == 'sell' and not stock_code.startswith(('1', '5')):
            stamp_duty = amount * self.stamp_duty_rate
        else:
            stamp_duty = 0
        
        total_fee = commission + transfer_fee + stamp_duty 
        
        return commission,stamp_duty,total_fee

    def calculate_win_rate(self):
        """
        计算交易胜率
        Returns:
            float: 胜率（0-1之间的小数）
        """
        if not self.trades:
            return 0
        #print("self.trades:",self.trades)
        sell_trades = [t for t in self.trades if t['direction'] == 'sell']
        if not sell_trades:
            return 0
            
        winning_trades = sum(
            1 for t in sell_trades
            if t['net_amount'] > t['volume'] * t['price'] * (1 + self.commission_rate)
        )
        return winning_trades / len(sell_trades)
    
    def logger_info(self):
        """
        打印回测数据时间范围信息
        """
        if hasattr(self, 'data') and self.data is not None:
            self.logger.info(
                f"数据时间范围: {self.data.index[0]} 到 {self.data.index[-1]}"
            )

    def get_volume(self, stock_code):
        """
        获取指定股票的持仓数量
        Args:
            stock_code (str): 股票代码
        Returns:
            int: 持仓数量
        """
        return self.positions.get(stock_code, {}).get('volume', 0)

    def get_can_use_volume(self, stock_code):
        """
        获取指定股票的可用数量
        Args:
            stock_code (str): 股票代码
        Returns:
            int: 可用数量
        """
        return self.positions.get(stock_code, {}).get('can_use_volume', 0)

    def get_open_price(self, stock_code):
        """
        获取指定股票的持仓成本
        Args:
            stock_code (str): 股票代码
        Returns:
            float: 持仓成本，无持仓时返回0
        """
        return self.positions.get(stock_code, {}).get('open_price', 0)

    def get_results(self):
        """标准化结果输出"""
        mdd,peak_time,max_dd_time = self._calculate_mdd()
        print("mdd:",mdd)
        print("peak_time:",peak_time)
        print("max_dd_time:",max_dd_time)
        self.get_trade_times_per_day()
        dict = {
            'total_return': self._calculate_total_return(),
            'sharpe_ratio': self._calculate_sharpe(),
            'max_drawdown': mdd,
            'peak_time': peak_time,
            'max_dd_time': max_dd_time,
            'win_rate': self._calculate_win_rate(),
            'total_trading_days': self.total_trading_days,
            'min_trades_days': self.min_trades_days,
            'max_trades_days': self.max_trades_days,
            'total_trades': self.total_trades,
            'avg_daily_trades': self.avg_daily_trades
        }
        print("dict:",dict)
        print(len(dict))
        return dict

    def reset(self):
        """重置引擎状态"""
        self.trades.clear()  # 修改为正确的属性名
        self.current_bar = None
        # 重置其他必要状态变量
        self.cash = self.initial_cash  # 重置现金
        self.market_value = self.initial_market_value  # 重置持仓市值

    def _calculate_total_return(self):
        """计算总收益率"""
        try:
            initial_total = self.initial_cash + self.initial_market_value
            final_total = self.cash + self.market_value
            return (final_total - initial_total) / initial_total
        except ZeroDivisionError:
            return 0.0

    def _calculate_sharpe(self):
        returns = self._get_daily_returns()
        # 添加样本量检查
        if len(returns) < 4:
            self.logger.warning("有效交易日不足5天，夏普比率设为0")
            return 0
        
        annual_factor = np.sqrt(252)
        rf_daily = 0.025 / 252
        
        # 转换为numpy数组便于计算
        returns = np.array(returns)
        excess_returns = returns - rf_daily
        
        # 添加中间结果打印
        print("\n[夏普计算参数]")
        print(f"年化因子: {annual_factor:.4f}")
        print(f"日无风险利率: {rf_daily:.6f}")
        print(f"超额收益均值: {excess_returns.mean():.6f}")
        print(f"超额收益标准差: {excess_returns.std():.6f}")
        
        sharpe = excess_returns.mean() / excess_returns.std() * annual_factor
        print(f"计算得出的夏普比率: {sharpe:.2f}")
        
        std_return = np.std(returns)
        if std_return < 1e-6:
            self.logger.warning("收益率标准差过小，夏普比率设为0")
            return 0
        
        return sharpe

    def _calculate_mdd(self):
        # 只使用交易数据创建净值序列
        time_index = []
        equity_values = []
        current_equity = self.initial_cash + self.initial_market_value
        
        # 添加交易数据
        for trade in self.trades:
            try:
                trade_time = pd.to_datetime(trade['time'])
                time_index.append(trade_time)
                # 买入时要减去交易成本
                if trade['direction'] == 'buy':
                    current_equity -= trade.get('commission', 0)
                # 卖出时加上盈亏，减去交易成本
                else:
                    current_equity += trade.get('pnl', 0) - trade.get('commission', 0) - trade.get('stamp_duty', 0)
                equity_values.append(current_equity)
                self.logger.info(f"交易时间: {trade_time}, 方向: {trade['direction']}, 盈亏: {trade.get('pnl', 0)}, 手续费: {trade.get('commission', 0)}, 印花税: {trade.get('stamp_duty', 0)}, 累计净值: {current_equity}")
            except Exception as e:
                self.logger.warning(f"处理交易时间出错: {trade.get('time')}, 错误: {str(e)}")
                continue
        
        # 创建完整序列
        full_series = pd.Series(equity_values, index=time_index)
        print("full_series:")
        print(full_series)
        # 使用通用工具类计算回撤
        drawdown_info = DrawdownCalculator.calculate_drawdown(full_series)
        #self.max_drawdown = drawdown_info['max_drawdown']
        #self.peak_time = drawdown_info['peak_time']
        #self.valley_time = drawdown_info['valley_time']
        
        return drawdown_info['max_drawdown'], drawdown_info['peak_time'], drawdown_info['valley_time']

    def _calculate_win_rate(self):
        """计算胜率"""
        sell_trades = [t for t in self.trades if t['direction'] == 'sell']
        if not sell_trades:
            return 0.0
        
        win_count = sum(1 for t in sell_trades if t.get('pnl', 0) > 0)
        return win_count / len(sell_trades)

    def _process_data(self, raw_data):
        """处理数据并返回处理后的数据"""
        # 在这里添加数据处理逻辑
        return raw_data

    def _get_daily_returns(self):
        """基于策略净值计算日收益率"""
        if len(self.portfolio_values) < 2:
            return []
            
        # 创建净值序列（与数据索引对齐）
        nav_series = pd.Series(
            self.portfolio_values,
            index=self.data.iloc[:len(self.portfolio_values)].index
        )
        
        # 按日resample
        daily_nav = nav_series.resample('D').last().ffill()        
        returns = daily_nav.pct_change().dropna()

        self.avg_daily_trades = len(self.trades)/(len(returns)+1)
        
        self.total_trading_days = len(daily_nav)
        self.total_trades = len(self.trades)
        
        return returns.tolist()
    
    def get_trade_times_per_day(self):
        """计算每日交易次数"""
        #把self.trades按日期分组
        trades_by_date = {}
        for trade in self.trades:
            trade_date = datetime.strptime(trade['time'], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d')
            if trade_date not in trades_by_date:
                trades_by_date[trade_date] = []
            trades_by_date[trade_date].append(trade)
        #计算每日交易次数
        trade_times_per_day = {}
        for trade_date, trades in trades_by_date.items():
            trade_times_per_day[trade_date] = len(trades)
        #计算每日交易次数的最小值和最大值
        if len(trade_times_per_day)     > 0:
            self.min_trades_days = min(trade_times_per_day.values())
            self.max_trades_days = max(trade_times_per_day.values())
        else:
            self.min_trades_days = 0
            self.max_trades_days = 0

        print("self.min_trades_days:",self.min_trades_days)
        print("self.max_trades_days:",self.max_trades_days)

        return

    def get_portfolio_value(self):
        """获取当前总资产"""
        return self.cash + self.market_value

    def find_valley_time(self, prices):
        """找到价格的波谷时间"""
        try:
            # 将时间格式从 "YYYY-MM-DD HH:MM" 改为 "YYYY-MM-DD"
            valley_time = prices.idxmin().strftime('%Y-%m-%d')
            return valley_time
        except Exception as e:
            self.logger.error(f"查找波谷时间出错: {str(e)}")
            return None

if __name__ == '__main__':
    engine = BacktestEngine('000001', 100, 10, 1000000)
    engine.load_data('000001', datetime(2025,2,4), datetime(2025,3,3), 'tick')