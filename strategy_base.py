import logging
from abc import ABC, abstractmethod
import json
class StrategyBase(ABC):
    """
    交易策略基类
    
    定义了策略的基本接口，所有具体策略都应该继承这个类。
    
    Attributes:
        engine: 交易引擎实例（回测或实盘）
        logger: 日志记录器
    """
    
    def __init__(self, engine):
        """
        初始化策略
        
        Args:
            engine: 交易引擎实例，可以是回测引擎或实盘引擎
        """
        self.engine = engine
        self.logger = logging.getLogger(self.__class__.__name__)
        
    @abstractmethod
    def on_tick(self, tick_data):
        """
        处理Tick数据的回调方法
        
        Args:
            tick_data: Tick数据，包含最新价格等信息
        """
        pass
        
    @abstractmethod
    def on_bar(self, bar_data):
        """
        处理K线数据的回调方法
        
        Args:
            bar_data: K线数据，包含OHLCV等信息
        """
        pass
        
    def on_trade(self, trade_data):
        """
        处理成交回报的回调方法
        
        Args:
            trade_data (dict): 成交信息字典，包含成交时间、价格、数量等
        """
        pass
        
    def on_order(self, order_data):
        """
        处理委托回报的回调方法
        
        Args:
            order_data (dict): 委托信息字典，包含委托状态等
        """
        pass
        
    def buy(self, stock_code, price, volume, datetime):
        """买入接口"""
        return self.engine.buy(stock_code, price, volume, datetime)
        
    def sell(self, stock_code, price, volume, datetime):
        """卖出接口"""
        return self.engine.sell(stock_code, price, volume, datetime)
        
    def get_position(self, stock_code):
        """获取持仓信息"""
        return self.engine.get_position(stock_code)
        
    def get_all_positions(self):
        """获取所有持仓"""
        return self.engine.get_all_positions()
        
    def get_account_status(self):
        """获取账户状态"""
        return self.engine.get_account_status()
        
    def before_trading(self):
        """盘前处理（可选实现）"""
        pass
        
    def after_trading(self):
        """盘后处理（可选实现）"""
        pass

