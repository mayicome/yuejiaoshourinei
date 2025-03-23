from strategy_base import StrategyBase
import numpy as np
import logging
from datetime import datetime
import os
import math
import pandas as pd
from collections import deque

class OrderBookStrategy(StrategyBase):
    """
    盘口动量增强策略
    
    基于盘口动量进行自动交易。
    """
    
    def __init__(self, engine, bid_vol_threshold=500, ask_vol_threshold=200, logger=None):
        """
        初始化浮动限价策略
        
        Args:
            engine: 交易引擎实例
            bid_vol_threshold (int): 买一档成交量阈值，默认500
            ask_vol_threshold (int): 卖一档成交量阈值，默认200
            trend_confirmation (int): 趋势确认阈值，默认3
            logger: 日志记录器，如果为None则使用默认logger
        """
        super().__init__(engine)
        self.bid_vol_threshold = bid_vol_threshold
        self.ask_vol_threshold = ask_vol_threshold
        self.trend_confirmation = 3
        
        # 使用传入的logger或创建默认logger
        self.logger = logger or logging.getLogger('AdaptiveLimitStrategy')

        self.volume_processor = VolumeProcessor(window=100)  
        
        self.daily_stats = {
            'date': None,
            'initial_position': 0,
            'initial_cost': 0
        }
        self.buy_point = None
        self.sell_point = None
                
    def on_bar(self, bar_data):
        """
        处理K线数据，执行交易逻辑
        
        Args:
            bar_data (pd.Series): K线数据，包含时间、价格等信息
        """
        #try:
        if True:
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

            # 计算时间限制
            hour = dt.hour
            minute = dt.minute

            # 避开开盘和收盘前的波动时间
            if hour < 9 or (hour == 9 and minute < 31) or (hour == 14 and minute > 55) or hour > 14: # 14:55后禁止交易，如果交易则禁用市价单【DeepSeek：70%的算法交易在收盘前30分钟停止新开市价单】
                return
            
            #获取仓位信息
            current_volume = self.engine.get_volume(stock_code)
            if hasattr(self.engine, 'is_backtest') and self.engine.is_backtest:
                # 回测模式下的特殊处理
                current_can_use_volume = current_volume
            else:
                # 实盘模式处理
                current_can_use_volume = self.engine.get_can_use_volume(stock_code)
            target_position = self.engine.target_position
            
            #早盘超买限制
            if hour == 9 and minute <= 60:
                position_limit = target_position  + current_can_use_volume
                position_keep = 0
            elif hour == 10 and minute < 60:
                position_limit = target_position  + math.ceil(current_can_use_volume / 2 / 100) * 100
                position_keep = 0
            else:
                position_limit = target_position
                position_keep = 0

            #尾盘平仓策略（缩小阈值加快交易频率）和控制卖出（即使有可卖数量，也不执行卖出）
            if hour == 13 and minute >= 31:
                self.threshold = 0.003
                position_keep = math.ceil(target_position*0.8 / 100) * 100
            if hour == 14 and minute >= 1:
                self.threshold = 0.002  
                position_keep = target_position
            if hour == 14 and minute >= 31:
                self.threshold = 0.001
                position_keep = target_position
            if hour == 14 and minute >= 46:
                self.threshold = 0.0005
                position_keep = target_position
            
            # 新交易日处理
            if current_date != self.daily_stats['date']:
                
                #每笔交易不少于5000元（基于当前价格初略计算）
                min_trade_size1 = math.ceil(5000 / current_price / 100) * 100
                
                #总持仓在10笔交易内完成清仓（基于程序启动后的总持仓）
                min_trade_size2 = math.ceil(current_can_use_volume / 10 / 100) * 100
                
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
                
            # 执行交易逻辑
            self.execute_trades(stock_code, current_price, self.buy_point, self.sell_point, 
                              current_volume, current_can_use_volume, position_limit, position_keep, current_time, None)
                
        #except Exception as e:
        #    self.logger.error(f"股票代码: {stock_code}, 处理Bar数据出错: {str(e)}")

    def on_tick(self, tick_data):
        """处理Tick数据"""
        #try:
        if True:
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
            volume = tick_data['volume']
            ma5min_volume = self.volume_processor.update(volume) # 计算当前5分钟动态平均成交量（手），9：35之前是不到5分钟的数据

            # 避开开盘和收盘前的波动时间
            if hour < 9 or (hour == 9 and minute < 31) or (hour == 14 and minute > 55) or hour > 14: # 14:55后禁止交易，如果交易则禁用市价单【DeepSeek：70%的算法交易在收盘前30分钟停止新开市价单】
                return
            
            #获取仓位信息
            current_volume = self.engine.get_volume(stock_code)
            current_can_use_volume = self.engine.get_can_use_volume(stock_code)
            target_position = self.engine.target_position

            # 新交易日处理
            if current_date != self.daily_stats['date']:
                #回测模式，手动更新可用持仓量
                if hasattr(self.engine, 'is_backtest') and self.engine.is_backtest:
                    #新的一天，更新可用持仓量为当前持仓量
                    self.engine.update_account_info(stock_code=stock_code, volume=0, can_use_volume=current_volume - current_can_use_volume, open_price=current_price)
                
                current_can_use_volume = self.engine.get_can_use_volume(stock_code)
                print("get_current_can_use_volume", current_can_use_volume)


                #每笔交易不少于5000元（基于当前价格初略计算）
                min_trade_size1 = math.ceil(5000 / current_price / 100) * 100
                #总持仓在10笔交易内完成清仓（基于程序启动后的总持仓）
                min_trade_size2 = math.ceil(current_can_use_volume/10 / 100) * 100
                #总持仓在10笔交易内完成建仓（基于目标仓位，当可用持仓较少时有用）
                min_trade_size3 = math.ceil(target_position/10 / 100) * 100

                                
                #计算单笔交易的数量
                self.trade_size = int(max(min_trade_size1, min_trade_size2, min_trade_size3))

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
                    f"目标仓位: {target_position}, "
                    f"当前价格: {current_price}"
                )

            #早盘超买限制
            if hour == 9 and minute <= 60:
                position_limit = target_position  + current_can_use_volume
                position_keep = 0
            elif hour == 10 and minute < 60:
                position_limit = target_position  + math.ceil(current_can_use_volume / 2 / 100) * 100
                position_keep = 0
            else:
                position_limit = target_position
                position_keep = 0

            #尾盘平仓策略（缩小阈值加快交易频率）和控制卖出（即使有可卖数量，也不执行卖出）
            if hour == 13 and minute >= 31:
                self.threshold = 0.003
                position_keep = math.ceil(target_position*0.8 / 100) * 100
            if hour == 14 and minute >= 1:
                self.threshold = 0.002  
                position_keep = target_position
            if hour == 14 and minute >= 31:
                self.threshold = 0.001
                position_keep = target_position
            if hour == 14 and minute >= 46:
                self.threshold = 0.0005
                position_keep = target_position

            # 执行交易逻辑
            self.execute_trades(stock_code, current_price, 
                              current_volume, current_can_use_volume, position_limit, position_keep, current_time, tick_data, ma5min_volume)
        # except Exception as e:
        #    self.logger.error(f"股票代码: {stock_code}, 处理Tick数据出错: {str(e)}")

    def execute_trades(self, stock_code, current_price, 
                      current_volume, current_can_use_volume, position_limit, position_keep, current_time, tick_data, ma5min_volume):
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
        
        bidPrices = tick_data['bidPrice']
        askPrices = tick_data['askPrice']

        # 每个tick更新引擎的买一到买五和卖一到卖五价，用于下单和订单重试确定价格
        self.engine.bidPrices = bidPrices
        self.engine.askPrices = askPrices

        bidVolumes = tick_data['bidVol']
        askVolumes = tick_data['askVol']

        # 计算买卖盘口强度
        bid_strength = sum(bidVolumes[:3])  # 前3档买量
        ask_weakness = sum(askVolumes[:3])
        
        # 动态阈值调整（示例）
        self.bid_vol_threshold = max(500, int(0.2 * ma5min_volume))
        
        # 信号条件
        if (bid_strength > 3 * ask_weakness and 
            bidVolumes[0] > self.bid_vol_threshold):
            signal = 'buy'
            
        elif (ask_weakness > 2 * bid_strength and 
              askVolumes[0] > self.ask_vol_threshold):
            signal = 'sell'
        
        else:
            signal = 'hold'

        # 检查卖出条件
        if signal == 'sell':
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
                sell_volume = int(current_can_use_volume / 100 * 100)

            #仓位控制
            if current_volume <= position_keep:
                condition_key = 'position_keep_sell'
                if not hasattr(self, f'last_{condition_key}') or not getattr(self, f'last_{condition_key}'):
                    self.logger.info(
                        f"股票代码: {stock_code}, "
                        f"满足卖出条件但当前持仓量{current_volume} < 最小限制持仓量{position_keep}, 不执行卖出"
                    )
                    setattr(self, f'last_{condition_key}', True)
                return
            else:
                if hasattr(self, 'last_position_keep_sell'):
                    delattr(self, 'last_position_keep_sell')

            # 策略风险控制
            if tick_data is not None: #针对on_tick模式，进行风险控制
                # 买一价格异常监控
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
                
        # 检查买入条件
        elif signal == 'buy':
            if current_volume >= position_limit:
                condition_key = 'position_limit_buy'
                if not hasattr(self, f'last_{condition_key}') or not getattr(self, f'last_{condition_key}'):
                    self.logger.info(
                        f"股票代码: {stock_code}, "
                        f"满足买入条件但当前持仓量{current_volume} >= 最大限制持仓量{position_limit}, 不执行买入"
                    )
                    setattr(self, f'last_{condition_key}', True)
                return
            else:
                if hasattr(self, 'last_position_limit_buy'):
                    delattr(self, 'last_position_limit_buy')

            # 计算买入数量
            buy_volume = min(self.trade_size, int(position_limit - current_volume))
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
                askVolumes = tick_data['askVol']
                
                if askPrices[0] < current_price:
                    self.logger.warning(
                        f"股票代码: {stock_code}, "
                        f"买入委托风险控制: 买入数量={buy_volume}, 卖1价={askPrices[0]:.2f}<当前价={current_price:.2f}, 中止市价买入"
                    )
                    return
                # 流动性多维评估
                depth_liquidity = sum(askVolumes)*100
                if depth_liquidity < buy_volume * 2:
                    self.logger.warning(
                        f"股票代码: {stock_code}, "
                        f"买入委托风险控制: 当前价格={current_price:.2f}, 五档卖盘总量={depth_liquidity} < 买入数量={buy_volume} * 2, 中止市价买入"
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

class VolumeProcessor:
    def __init__(self, window=100):  # 5分钟窗口（每3秒1个tick）
        self.window = window
        self.volume_cache = deque(maxlen=window)
        self.last_volume = 0  # 用于计算增量

    def update(self, volume):
        """处理每个tick的成交量"""
        current_total = volume  # 当日累计成交量（单位：手）
        
        # 计算单tick增量（防止数据回滚）
        delta = max(0, current_total - self.last_volume)
        self.volume_cache.append(delta * 100)  # 转换为股数（1手=100股）
        self.last_volume = current_total
        
        return self.current_average()

    def current_average(self):
        """计算当前平均成交量（股）"""
        return sum(self.volume_cache) / len(self.volume_cache) if self.volume_cache else 0