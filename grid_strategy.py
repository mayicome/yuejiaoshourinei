from strategy_base import StrategyBase
import numpy as np
import logging
from datetime import datetime
import os
import math
import pandas as pd

class GridStrategy(StrategyBase):
    """
    网格交易策略
    
    基于价格波动在预设的网格价位进行自动交易。
    当价格上涨到某个网格价位时卖出，下跌到某个网格价位时买入。
    
    Attributes:
        threshold (float): 网格间距（百分比）
        trade_size (int): 每次交易数量
        base_price (float): 当前网格基准价格
    """
    
    def __init__(self, engine, grid_step=0.004, grid_size=100, logger=None):
        """
        初始化网格策略
        
        Args:
            engine: 交易引擎实例
            grid_step (float): 网格间距（百分比），默认0.5%
            grid_size (int): 每次交易数量，默认100股
            logger: 日志记录器，如果为None则使用默认logger
        """
        super().__init__(engine)
        self.threshold = grid_step
        self.trade_size = grid_size
        self.base_price = 0
        
        # 使用传入的logger或创建默认logger
        self.logger = logger or logging.getLogger('GridStrategy')
        
        self.daily_stats = {
            'date': None,
            'initial_position': 0
        }
        self.buy_point = None
        self.sell_point = None
                
    def on_bar(self, bar_data):
        """
        处理K线数据，执行交易逻辑
        
        Args:
            bar_data (pd.Series): K线数据，包含时间、价格等信息
        """
        try:
            stock_code = self.engine.stock_code
            current_price = bar_data.lastPrice
            if current_price <= 0:
                return
            
            # 转换时间格式
            time_str = f"{bar_data.time:.0f}"  # 先转成整数字符串，去掉小数点
            dt = datetime.strptime(time_str, '%Y%m%d%H%M%S')
            current_time = dt.strftime('%Y-%m-%d %H:%M:%S')
            current_date = dt.strftime('%Y%m%d')
            
            self.logger.info(f"处理 Bar 数据: {current_time}")
            
            # 获取持仓信息
            current_volume = self.engine.get_volume(stock_code)
            current_can_use_volume = self.engine.get_can_use_volume(stock_code)
            
            # 新交易日处理
            if current_date != self.daily_stats['date']:
                
                #每笔交易不少于5000元（基于当前价格初略计算）
                min_trade_size1 = math.ceil(5000 / current_price) / 100 * 100
                
                #总持仓在10笔交易内完成清仓（基于程序启动后的总持仓）
                min_trade_size2 = math.ceil(current_can_use_volume/10) / 100 * 100
                
                #计算单笔交易的数量
                self.trade_size = max(min_trade_size1, min_trade_size2, self.trade_size)
                self.logger.info(
                    f"股票代码: {stock_code}, "
                    f"调整交易数量至 {self.trade_size} 股以满足单次交易资金不小于5000元及总交易次数不大于10次的要求"
                )

                self.daily_stats = {
                    'date': current_date,
                    'initial_position': current_can_use_volume,
                    'initial_cost': self.engine.get_open_price(stock_code)
                }
                self.logger.info(                    
                    f"股票代码: {stock_code}, "
                    f"新交易日: {current_date}, "
                    f"初始仓位: {self.daily_stats['initial_position']}, "
                    f"初始成本: {self.daily_stats['initial_cost']}, "
                    f"目标仓位: {self.engine.target_position}, "
                    f"当前价格: {current_price}"
                )
                self.buy_point, self.sell_point = self.calculate_trade_points(stock_code, current_price)

            # 计算时间限制
            hour = dt.hour
            minute = dt.minute
            
            # 避开开盘和收盘前的波动时间
            if (hour == 9 and minute < 1) or (hour == 14 and minute > 55):
                return
            
            # 执行交易逻辑
            self.execute_trades(stock_code, current_price, self.buy_point, self.sell_point, 
                              current_volume, current_can_use_volume, current_time, None)
                
        except Exception as e:
            self.logger.error(f"股票代码: {stock_code}, 处理Bar数据出错: {str(e)}")

    def on_tick(self, tick_data):
        """处理Tick数据"""
        try:
            stock_code = self.engine.stock_code
            current_price = tick_data['lastPrice']
            # 检查价格是否有效
            if current_price <= 0:
                return
            
            
            # 当前时间处理
            dt = datetime.fromtimestamp(tick_data['time'] / 1000)  # 除以1000转换为秒
            current_time = dt.strftime('%Y-%m-%d %H:%M:%S')
            current_date = dt.strftime('%Y%m%d')
            
            # 计算时间限制
            hour = dt.hour
            minute = dt.minute

            # 避开开盘和收盘前的波动时间
            if (hour == 9 and minute < 31) or (hour == 14 and minute > 55): # 14:55后禁止交易，如果交易则禁用市价单【DeepSeek：70%的算法交易在收盘前30分钟停止新开市价单】
                return
            
            current_volume = self.engine.get_volume(stock_code)
            current_can_use_volume = self.engine.get_can_use_volume(stock_code)

            # 新交易日处理
            if current_date != self.daily_stats['date']:
                
                #每笔交易不少于5000元（基于当前价格初略计算）
                min_trade_size1 = math.ceil(5000 / current_price) / 100 * 100
                
                #总持仓在10笔交易内完成清仓（基于程序启动后的总持仓）
                min_trade_size2 = math.ceil(current_can_use_volume/10) / 100 * 100
                
                #计算单笔交易的数量
                self.trade_size = max(min_trade_size1, min_trade_size2, self.trade_size)
                self.logger.info(
                    f"股票代码: {stock_code}, "
                    f"调整交易数量至 {self.trade_size} 股以满足单次交易资金不小于5000元及总交易次数不大于10次的要求"
                )

                self.daily_stats = {
                    'date': current_date,
                    'initial_position': current_can_use_volume,
                    'initial_cost': self.engine.get_open_price(stock_code)
                }
                self.logger.info(
                    f"股票代码: {stock_code}, "
                    f"新交易日: {current_date}, "
                    f"初始仓位: {self.daily_stats['initial_position']}, "
                    f"初始成本: {self.daily_stats['initial_cost']}, "
                    f"目标仓位: {self.engine.target_position}, "
                    f"当前价格: {current_price}"
                )
                self.base_price = current_price
                self.buy_point, self.sell_point = self.calculate_trade_points(stock_code, self.base_price, self.threshold)  # 更新基准价

            #尾盘平仓策略            
            if hour == 13 and minute >= 31:
                self.threshold = 0.003
            if hour == 14 and minute >= 1:
                self.threshold = 0.002  
            if hour == 14 and minute >= 31:
                self.threshold = 0.001
            if hour == 14 and minute >= 46:
                self.threshold = 0.0005
            buy_point, sell_point = self.calculate_trade_points(stock_code, self.base_price, self.threshold)  # 更新基准价

            # 执行交易逻辑
            self.execute_trades(stock_code, current_price, buy_point, sell_point, 
                              current_volume, current_can_use_volume, current_time, tick_data)
        except Exception as e:
            self.logger.error(f"股票代码: {stock_code}, 处理Tick数据出错: {str(e)}")

    def execute_trades(self, stock_code, current_price, buy_point, sell_point, 
                      current_volume, current_can_use_volume, current_time, tick_data):
        """
        执行交易决策
        
        Args:
            stock_code (str): 股票代码
            current_price (float): 当前价格
            buy_point (float): 买入价位
            sell_point (float): 卖出价位
            current_volume (int): 当前持仓
            current_can_use_volume (int): 当前可用持仓
            bar_data: 行情数据
        """
        position_limit = self.engine.target_position
        
        # 检查卖出条件
        if current_price >= sell_point:
            if current_can_use_volume < 100:
                # 使用独立的状态变量跟踪不同条件
                condition_key = 'low_position_sell'
                if not hasattr(self, f'last_{condition_key}') or not getattr(self, f'last_{condition_key}'):
                    self.logger.info(
                        f"股票代码: {stock_code}, "
                        f"满足卖出条件但当前可用持仓量{current_can_use_volume} < 100, 不执行卖出"
                    )
                    setattr(self, f'last_{condition_key}', True)
                return
            else:
                # 当条件不再满足时重置状态
                if hasattr(self, 'last_low_position_sell'):
                    delattr(self, 'last_low_position_sell')

            # 计算卖出数量
            sell_volume = min(self.trade_size, current_can_use_volume)
            if current_can_use_volume < self.trade_size * 1.5:
                sell_volume = current_can_use_volume

            # 尾盘平仓策略
            if self.threshold <= 0.002: #2点以后
                if current_volume < position_limit:
                    condition_key = 'position_limit_sell'
                    if not hasattr(self, f'last_{condition_key}') or not getattr(self, f'last_{condition_key}'):
                        self.logger.info(
                            f"股票代码: {stock_code}, "
                            f"满足卖出条件但当前处于尾盘平仓阶段且持仓量{current_volume} < 目标持仓量{position_limit}, 不执行卖出"
                        )
                        setattr(self, f'last_{condition_key}', True)
                    return
                else:
                    if hasattr(self, 'last_position_limit_sell'):
                        delattr(self, 'last_position_limit_sell')

            # 策略风险控制
            if tick_data is not None: #针对on_tick模式，进行风险控制
                # 买一价格异常监控
                bidPrices = tick_data['bidPrice']
                if bidPrices[0] < current_price*0.90:
                    self.logger.warning(
                        f"股票代码: {stock_code}, "
                        f"卖出委托风险控制: 当前价格={current_price:.2f}, 数量={sell_volume}, 买1价={bidPrices[0]:.2f}<=最新价{current_price}*0.90, 中止市价卖出"
                    )
                    return

            success, msg = self.engine.sell(stock_code, current_price, sell_volume, current_time)
            if success:                        
                self.logger.info(
                    f"股票代码: {stock_code}, "
                    f"卖出委托成功: 价格={current_price:.2f}, 数量={sell_volume}"
                )
                self.base_price = current_price
                self.buy_point, self.sell_point = self.calculate_trade_points(stock_code, self.base_price, self.threshold)

        # 检查买入条件
        elif current_price <= buy_point:
            if current_volume >= position_limit:
                condition_key = 'position_limit_buy'
                if not hasattr(self, f'last_{condition_key}') or not getattr(self, f'last_{condition_key}'):
                    self.logger.info(
                        f"股票代码: {stock_code}, "
                        f"满足买入条件但当前持仓量{current_volume} >= 目标持仓量{position_limit}, 不执行买入"
                    )
                    setattr(self, f'last_{condition_key}', True)
                return
            else:
                if hasattr(self, 'last_position_limit_buy'):
                    delattr(self, 'last_position_limit_buy')

            # 计算买入数量
            buy_volume = min(self.trade_size, position_limit - current_volume)
            #if position_limit - current_volume < self.trade_size * 1.5:
            #    buy_volume = position_limit - current_volume

            account_status = self.get_account_status()
            required_capital = current_price * buy_volume

            if account_status['cash'] < required_capital:
                condition_key = 'insufficient_funds'
                if not hasattr(self, f'last_{condition_key}') or not getattr(self, f'last_{condition_key}'):
                    self.logger.info(
                        f"股票代码: {stock_code}, "
                        f"满足买入条件但计划买入数量={buy_volume}, 需要资金={required_capital:.2f}, 当前可用资金={account_status['cash']}, 资金不足，无法买入"
                    )
                    setattr(self, f'last_{condition_key}', True)
                return
            else:
                if hasattr(self, 'last_insufficient_funds'):
                    delattr(self, 'last_insufficient_funds')

            # 策略风险控制
            if tick_data is not None: #针对on_tick模式，进行风险控制
                # 卖一价格异常监控
                askPrices = tick_data['askPrice']
                askVolumes = tick_data['askVol']
                
                if askPrices[0] <= current_price:
                    self.logger.warning(
                        f"股票代码: {stock_code}, "
                        f"买入委托风险控制: 当前价格={current_price:.2f}, 数量={buy_volume}, 卖1价={askPrices[0]:.2f}<=当前价, 中止市价买入"
                    )
                    return
                # 流动性多维评估
                depth_liquidity = sum(askVolumes)                        
                if depth_liquidity < buy_volume * 2:
                    self.logger.warning(
                        f"股票代码: {stock_code}, "
                        f"买入委托风险控制: 当前价格={current_price:.2f}, 数量={buy_volume}, 五档卖盘总量={depth_liquidity} < 数量{self.trade_size} * 2, 中止市价买入"
                    )
                    return
                '''# 波动率自适应检查
                volatility = calculate_5min_volatility(stock_code)
                if volatility > self.volatility_threshold:
                    self.logger.warning(
                        f"股票代码: {stock_code}, "
                        f"买入委托风险控制: 当前价格={current_price:.2f}, 数量={buy_volume}, 波动率{volatility}超过阈值, 中止市价买入"
                    )
                    return
                # 涨跌幅动态限制
                # 计算有效涨跌幅限制
                effective_upper = tick_data['upperLimit'] * 0.99  # 留1%缓冲  
                if tick_data['askPrice'][0] >= effective_upper:
                    self.logger.warning(
                        f"股票代码: {stock_code}, "
                        f"买入委托风险控制: 当前价格={current_price:.2f}, 数量={buy_volume}, 卖一价接近涨停板, 中止市价买入"
                    )
                    return'''
            success, msg = self.engine.buy(stock_code, current_price, buy_volume, current_time)
            if success:
                self.logger.info(
                    f"股票代码: {stock_code}, "
                    f"买入委托成功: 价格={current_price:.2f}, 数量={buy_volume}"
                )
                self.base_price = current_price
                self.buy_point, self.sell_point = self.calculate_trade_points(stock_code, self.base_price, self.threshold)
            
    def get_account_status(self):
        """
        获取账户状态信息
        
        Returns:
            dict: 包含现金和持仓信息的字典
        """
        stock_code = self.engine.stock_code
        return {
            'cash': self.engine.cash,
            'position': self.engine.get_volume(stock_code),
            'can_use_position': self.engine.get_can_use_volume(stock_code)
        }

    def calculate_trade_points(self, stock_code, base_price, threshold):
        """
        计算交易点价格
        
        Args:
            base_price (float): 基准价格
        Returns:
            tuple: (买入价格, 卖出价格)
        """
        if base_price <= 0:
            self.logger.error(f"股票代码: {stock_code}, 基准价异常={base_price}！")
            return 10000, 0
        
        buy_point = round(base_price * (1 - threshold), 2)
        sell_point = round(base_price * (1 + threshold), 2)
        if buy_point == base_price:
            buy_point -= 0.01
        if sell_point == base_price:
            sell_point += 0.01

        # 避免重复写logger（如果base_price和threshold都与上一次相同，则不写logger）
        if hasattr(self, 'last_threshold'):
            if hasattr(self, 'last_base_price'):
                if self.last_base_price != base_price or self.last_threshold != threshold:
                    self.logger.info(f"股票代码: {stock_code}, 计算买卖点价格，基准价={base_price}，买入点={buy_point}，卖出点={sell_point}")
                
        self.last_base_price = base_price
        self.last_threshold = threshold
        return buy_point, sell_point