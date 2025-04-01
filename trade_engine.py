from abc import ABC, abstractmethod
import logging

class TradeEngine(ABC):
    """
    交易引擎基类
    
    定义了交易引擎的基本接口，所有具体的交易引擎（回测/实盘）都应该继承这个类。
    
    Attributes:
        commission_rate (float): 交易佣金率，默认万分之2.5
        min_commission (float): 最小佣金，默认5元
        stamp_duty_rate (float): 印花税率，默认千分之1
        strategy: 交易策略实例
        positions (dict): 持仓信息字典
        trades (list): 交易记录列表
        cash (float): 可用资金
        frozen_cash (float): 冻结资金
        market_value (float): 持仓市值
        total_asset (float): 总资产
    """
    
    def __init__(self):
        """初始化交易引擎"""
        # 设置费率
        self.commission_rate = 0.00025  # 佣金率：万分之2.5
        self.min_commission = 5.0       # 最小佣金：5元
        self.stamp_duty_rate = 0.001    # 印花税率：千分之1
        
        # 交易相关
        self.strategy = None
        self.positions = {}
        self.trades = []
        
        # 资金相关
        self.cash = 0.0
        self.frozen_cash = 0.0
        self.market_value = 0.0
        self.total_asset = 0.0
        
        # 日志设置
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # 添加运行模式标识
        self.is_backtest = False  # 默认非回测模式
        self.is_live = False      # 默认非实盘模式

    def on_trade(self, trade):
        """处理成交回报"""
        pass
        
    @abstractmethod
    def buy(self, stock_code, price, volume, datetime):
        """
        买入股票
        
        Args:
            stock_code (str): 股票代码
            price (float): 买入价格
            volume (int): 买入数量
            datetime: 交易时间
        Returns:
            tuple: (bool, str) 交易是否成功及消息
        """
        pass
        
    @abstractmethod
    def sell(self, stock_code, price, volume, datetime):
        """
        卖出股票
        
        Args:
            stock_code (str): 股票代码
            price (float): 卖出价格
            volume (int): 卖出数量
            datetime: 交易时间
        Returns:
            tuple: (bool, str) 交易是否成功及消息
        """
        pass
        
    @abstractmethod
    def get_volume(self, stock_code):
        """
        获取持仓数量
        
        Args:
            stock_code (str): 股票代码
        Returns:
            int: 持仓数量
        """
        pass
        
    @abstractmethod
    def get_can_use_volume(self, stock_code):
        """
        获取可用持仓数量
        
        Args:
            stock_code (str): 股票代码
        Returns:
            int: 可用持仓数量
        """
        pass
        
    @abstractmethod
    def get_open_price(self, stock_code):
        """
        获取持仓成本价
        
        Args:
            stock_code (str): 股票代码
        Returns:
            float: 持仓成本价
        """
        pass
        
    def set_strategy(self, strategy):
        """
        设置交易策略
        
        Args:
            strategy: 策略实例
        """
        self.strategy = strategy
        self.logger.info(f"设置策略: {strategy.__class__.__name__}")

    def setup_logger(self):
        """设置日志器"""
        logger = logging.getLogger('TradeEngine')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setLevel(logging.INFO)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            
        return logger

    # === 费用计算相关 ===
    def calculate_commission(self, price, volume):
        """
        计算交易手续费
        Args:
            price (float): 成交价格
            volume (int): 成交数量
        Returns:
            float: 手续费金额
        """
        return max(price * volume * self.commission_rate, self.min_commission)
        
    def calculate_tax(self, price, volume):
        """
        计算印花税（仅卖出时收取）
        Args:
            price (float): 成交价格
            volume (int): 成交数量
        Returns:
            float: 印花税金额
        """
        return price * volume * self.stamp_duty_rate

    # === 查询相关 ===
    def get_position(self, stock_code):
        """
        获取指定股票的持仓信息
        Args:
            stock_code (str): 股票代码
        Returns:
            dict: 持仓信息，若无持仓则返回None
        """
        return self.positions.get(stock_code, None)
        
    def get_all_positions(self):
        """
        获取所有持仓信息
        Returns:
            dict: 所有持仓信息
        """
        return self.positions
        
    def get_trades(self):
        """
        获取交易记录
        Returns:
            list: 交易记录列表
        """
        return self.trades
        
    def get_account_status(self):
        """
        获取账户状态
        Returns:
            dict: 账户状态信息
        """
        return {
            'cash': self.cash,
            'frozen_cash': self.frozen_cash,
            'market_value': self.market_value,
            'total_asset': self.total_asset
        }

    def process_bar(self, bar_data):
        """
        处理K线数据
        Args:
            bar_data: K线数据
        """
        if self.strategy:
            self.strategy.on_bar(bar_data)
            
    def process_tick(self, tick_data):
        """
        处理Tick数据
        Args:
            tick_data: Tick数据
        """
        if self.strategy:
            self.strategy.on_tick(tick_data)

    def smart_order_price(self, direction, best_bid, best_ask, slippage):
        """改进后的智能定价策略（ETF1厘钱，其他1分钱+动态调整）"""        
        # 基础滑点设置
        base_slippage = slippage
        
        # 动态调整逻辑（示例：当价格>20元时增加额外滑点）
        dynamic_slippage = 0 if best_ask <= 20 else slippage * 2
        total_slippage = base_slippage + dynamic_slippage

        if direction == 'buy':
            # 买方向：取卖一价加滑点
            price = max(
                best_ask + total_slippage,
                best_ask + slippage
            )
        elif direction == 'sell':
            # 卖方向：取买一价减滑点
            price = min(
                best_bid - total_slippage,
                best_bid - slippage
            )
        else:
            return None
        
        # 确保符合最小报价单位
        if base_slippage == 0.001:
            return round(round(price / 0.001) * 0.001, 3)
        else:
            return round(round(price / 0.01) * 0.01, 2)

    def calculate_order_price(self, mode,direction, stock_code, best_bid, best_ask, slippage):
        # 基础滑点设置
        base_slippage = slippage
        
        # 动态调整逻辑（示例：当价格>20元时增加额外滑点）
        dynamic_slippage = 0 if best_ask <= 20 else slippage
        if mode == 'live':
            total_slippage = base_slippage + dynamic_slippage
        else:
            total_slippage = 0

        if direction == 'buy':
            # 买方向：取卖一价加滑点
            price = best_ask + total_slippage

        elif direction == 'sell':
            # 卖方向：取买一价减滑点
            price = best_bid - total_slippage

        else:
            return None
        
        # 确保符合最小报价单位
        if base_slippage == 0.001:
            ret = round(round(price / 0.001) * 0.001, 3)
        else:
            ret = round(round(price / 0.01) * 0.01, 2)

        
        direction_str = "买入" if direction == 'buy' else "卖出"
        if stock_code.startswith(('1', '5')):
            self.logger.info(f"股票代码：{stock_code}，{direction_str}，最新买价：{best_bid:.3f}，最新卖价：{best_ask:.3f}，智能定价：{ret:.3f}")        
        else:
            self.logger.info(f"股票代码：{stock_code}，{direction_str}，最新买价：{best_bid:.2f}，最新卖价：{best_ask:.2f}，智能定价：{ret:.2f}")        
        
        return ret
