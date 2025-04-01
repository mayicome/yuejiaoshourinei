from trade_engine import TradeEngine
from xtquant.xttype import StockAccount
from xtquant import xtconstant
from datetime import datetime
import logging
from xtquant.xttrader import XtQuantTraderCallback
from threading import Thread
import sys
from PyQt5.QtCore import QObject, pyqtSignal, QMetaObject, Q_ARG, Qt
from logging.handlers import RotatingFileHandler
import os
import time

class MyXtQuantTraderCallback(XtQuantTraderCallback):
    # 实测只有on_stock_order, on_stock_trade有回调，持仓和资金定期通过update_asset_positions()更新
    # on_account_status，on_disconnected有回调
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        
    def on_stock_order(self, order):
        """委托回报推送"""
        # 创建线程处理订单状态
        #self.engine.logger.info(f"XT-委托回报推送: {order.order_id}, 股票代码={order.stock_code}, 方向={order.order_type}, 价格={order.price}, 数量={order.order_volume}")
        Thread(target=self.engine.on_order_callback, args=(order,), daemon=True).start()
        
    def on_stock_trade(self, trade):
        """成交回报推送"""
        Thread(target=self.engine.on_trade_callback, args=(trade,), daemon=True).start()
        
    def on_stock_position(self, position):
        """持仓变动推送"""
        self.engine.logger.info(f"XT-持仓变动: {position.stock_code}, 数量={position.volume}")
        
    def on_asset_change(self, asset):
        """资金变动推送"""
        self.engine.logger.info(f"XT-资金变动: 可用资金={asset.cash}, 总资产={asset.total_asset}")

    def on_order_stock_async_response(self, response):
        """
        异步下单回报推送
        :param response: XtOrderResponse 对象
        :return:
        """
        self.engine.logger.info(f"XT-异步下单回报推送: {response.account_id}, 订单号={response.order_id}, 序号={response.seq}, 策略名称={response.strategy_name}")

    def on_order_status(self, order):
        """委托回报推送"""
        if self.stock_code is None or order.stock_code != self.stock_code:
            return
        try:
            # 将XTOrder对象转换为字典
            order_dict = {
                'order_id': order.order_id,
                'stock_code': order.stock_code,
                'order_type': order.order_type,
                'price': order.price,
                'order_volume': order.order_volume,
                'order_status': order.order_status,
                'traded_volume': order.traded_volume
            }
            
            # 使用字典进行后续处理
            self.logger.info(f"委托状态更新: {order_dict}")
            
            # 使用Q_ARG传递字典
            if hasattr(self, 'main_window'):
                QMetaObject.invokeMethod(
                    self.main_window,
                    "update_order_table",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(type(order), order)
                )
            else:
                self.logger.error("main_window属性不存在，无法更新订单表格")
            
        except Exception as e:
            self.logger.error(f"处理委托回报时出错: {str(e)}")

    def on_disconnected(self):
        """连接断开"""
        self.engine.logger.info("XT-连接断开")
        self.engine.signals.status.emit("账户连接状态：断开【请检查网络连接，启动miniQMT，并重启本程序】")
        
    def on_stock_asset(self, asset):
        """资金信息推送"""
        self.engine.logger.info(f"XT-资金信息推送: {asset.account_id}, 现金={asset.cash}, 冻结资金={asset.frozen_cash}, 市值={asset.market_value}, 总资产={asset.total_asset}")

    def on_order_error(self, order_error):
        """委托失败推送"""
        self.engine.logger.info(f"XT-委托报错回调 {order_error.order_remark} {order_error.error_msg}")
        
    def on_cancel_error(self, cancel_error):
        """撤单失败推送"""
        self.engine.logger.info(f"XT-撤单失败推送{datetime.now()} {sys._getframe().f_code.co_name}，{cancel_error.order_id}，{cancel_error.error_msg}")

    def on_cancel_order_stock_async_response(self, response):
        """异步撤单回报推送"""
        self.engine.logger.info(f"XT-异步撤单回报{datetime.now()} {sys._getframe().f_code.co_name}")

    def on_account_status(self, status):
        """账户状态推送"""
        status_messages = {
            0: "账户连接状态：正常",
            1: "账户连接状态：连接中【如果长时间处于连接中状态，请检查网络连接。非交易时段，可忽略】",
            2: "账户连接状态：登录中",
            3: "账户连接状态：失败【请检查网络连接，并确保miniQMT已经正常登录运行。如果仍然失败，请重启miniQMT】",
            4: "账户连接状态：初始化中",
            5: "账户连接状态：登录成功",
            6: "账户连接状态：收盘后"
        }
        message = status_messages.get(
            status.status, 
            f"账户连接状态：未知，状态号{status.status}"
        )
        self.engine.signals.status.emit(message)

    def on_order_change(self, order):
        """委托变动推送"""
        self.engine.logger.info(f'XT-委托变动回调')

    def on_position_change(self, position):
        """持仓变动推送"""
        self.engine.logger.info(f'XT-持仓变动回调')

class StatusSignals(QObject):
    """单独的信号类"""
    status = pyqtSignal(str)

class LiveEngine(TradeEngine):
    """实盘交易引擎类"""
    def __init__(self, xt_trader, account_id):
        """
        初始化实盘引擎
        Args:
            xt_trader: XtQuantTrader实例
            account_id: 资金账号
        """
        super().__init__()
        self.is_live = True  # 标记为实盘模式
        
        # 创建信号对象
        self.signals = StatusSignals()
        
        # 交易接口相关
        self.xt_trader = xt_trader
        self.account = StockAccount(account_id, 'STOCK')
        
        # 日志设置
        self.logger = logging.getLogger('LiveTrade')
        
        # 基础属性
        self.strategy = None
        self.positions = {}
        self.trades = []
        
        # 新增必要属性
        self.stock_code = None  # 交易的股票代码
        self.target_position = 0  # 目标持仓量
        
        # 资金相关
        self.cash = 0
        self.frozen_cash = 0
        self.market_value = 0
        self.total_asset = 0
        
        self.order_retry_limit = 3  # 订单重试次数
        self.active_orders = {}  # 跟踪活跃订单
        
    def connect(self):
        """
        建立交易连接并初始化回调
        Returns:
            int: 连接结果代码，0表示成功
        """
        try:
            # 建立交易连接
            connect_result = self.xt_trader.connect()
            if connect_result != 0:
                self.logger.error(f"建立交易连接失败，错误码: {connect_result}")
                return connect_result
                
            # 订阅交易回调
            subscribe_result = self.xt_trader.subscribe(self.account)
            if subscribe_result != 0:
                self.logger.error(f"订阅交易回调失败，错误码: {subscribe_result}")
                return subscribe_result
                
            # 创建并注册回调对象
            callback = MyXtQuantTraderCallback(self)
            self.xt_trader.register_callback(callback)
            
            self.logger.info("交易连接建立成功")
            return 0
            
        except Exception as e:
            self.logger.error(f"连接交易服务器时出错: {str(e)}")
            return -1

    def update_asset_positions(self):
        """
        更新账户资金和持仓信息
        Returns:
            bool: 更新是否成功
        """
        try:
            # 更新资金信息
            asset = self.xt_trader.query_stock_asset(self.account)
            if asset:
                self.cash = asset.cash
                self.frozen_cash = asset.frozen_cash
                self.market_value = asset.market_value
                self.total_asset = asset.total_asset
                
            # 更新持仓信息
            positions = self.xt_trader.query_stock_positions(self.account)
            if positions:
                self.positions.clear()
                for pos in positions:
                    self.positions[pos.stock_code] = {
                        'volume': pos.volume,
                        'can_use_volume': pos.can_use_volume,
                        'open_price': round(pos.open_price, 3),
                        'market_value': pos.market_value
                    }

            return True
            
        except Exception as e:
            self.logger.error(f"更新账户信息失败: {str(e)}")
            return False

    def set_strategy(self, strategy):
        """
        设置交易策略
        Args:
            strategy: 策略实例
        """
        self.strategy = strategy
        #self.logger.info(f"设置策略: {strategy.__class__.__name__}")

    '''def smart_order_price(self, direction, best_bid, best_ask, tick_size):
        """改进后的智能定价策略（固定1分钱+动态调整）"""        
        # 基础滑点设置
        base_slippage = tick_size  # 固定1分钱
        
        # 动态调整逻辑（示例：当价格>20元时增加额外滑点）
        dynamic_slippage = 0 if best_ask <= 20 else tick_size * 2
        total_slippage = base_slippage + dynamic_slippage

        if direction == 'buy':
            # 买方向：取卖一价加滑点（确保至少加1分钱）
            price = max(
                best_ask + total_slippage,
                best_ask + tick_size  # 保底加1分钱
            )
        elif direction == 'sell':
            # 卖方向：取买一价减滑点（确保至少减1分钱）
            price = min(
                best_bid - total_slippage,
                best_bid - tick_size  # 保底减1分钱
            )
        else:
            return None
        
        # 确保符合最小报价单位
        if base_slippage == 0.001:
            return round(round(price / 0.001) * 0.001, 3)
        else:
            return round(round(price / 0.01) * 0.01, 2)'''

    '''def calculate_order_price(self, stock_code, direction):
        """获取实时定价"""
        # 获取最新五档行情
        if stock_code.startswith('1') or stock_code.startswith('5'):
            tick_size = 0.001
        else:
            tick_size = 0.01
        best_bid = self.bidPrices[0]  # 买一价
        best_ask = self.askPrices[0]  # 卖一价
        ret = self.smart_order_price(direction, best_bid, best_ask, tick_size)
        direction_str = "买入" if direction == 'buy' else "卖出"
        if stock_code.startswith('1') or stock_code.startswith('5'):
            ret_text = f"{ret:.3f}"
        else:
            ret_text = f"{ret:.2f}"
        self.logger.info(f"股票代码：{stock_code}，{direction_str}，最新买价：{best_bid}，最新卖价：{best_ask}，智能定价：{ret_text}")        
        return ret'''

    def buy(self, stock_code, price, volume, datetime):
        """
        发送买入委托
        Args:
            stock_code (str): 股票代码
            price (float): 此参数在使用最新价时会被忽略
            volume (int): 买入数量
            datetime: 交易时间
        Returns:
            tuple: (bool, str) 交易是否成功及消息
        """
        try:
            # 根据股票代码设置滑点
            if stock_code.startswith('1') or stock_code.startswith('5'):
                self.slippage = 0.001
            else:
                self.slippage = 0.01

            # 获取智能定价
            dynamic_price = self.calculate_order_price('live', 'buy', stock_code, self.bidPrices[0], self.askPrices[0], self.slippage)
            if not dynamic_price:
                self.logger.warning(f"股票代码：{stock_code}，无法获取实时价格，未能买入")
                return False, f"股票代码：{stock_code}，无法获取实时价格，未能买入"#super().buy(stock_code, price, volume, datetime)
                
            self.logger.info(f"股票代码：{stock_code}，智能买入定价: {dynamic_price} (基准价: {price})，买入数量: {volume}")
            
            # 发送限价单
            order_id = self.xt_trader.order_stock(
                account=self.account,
                stock_code=stock_code,
                order_type=xtconstant.STOCK_BUY,
                order_volume=int(volume),
                price_type=xtconstant.FIX_PRICE,  # 改为限价单
                price=dynamic_price,
                strategy_name="岳教授日内交易",
                order_remark=stock_code
            )
            
            # 记录活跃订单
            self.active_orders[order_id] = {
                'retry_count': 0,
                'direction': 'buy',
                'stock_code': stock_code,
                'volume': volume,
                'base_price': price
            }
            
            # 记录交易
            trade = {
                'time': datetime,
                'stock_code': stock_code,
                'direction': 'buy',
                'price': price,
                'volume': volume,
                'status': '已提交',
                'order_id': order_id
            }
            
            if order_id > 0:
                self.logger.info(f"股票代码: {stock_code}, 买入委托成功，委托号: {order_id}")
                return True, "买入成功"
            else:
                self.logger.error(f"股票代码: {stock_code}, 买入委托失败，错误码: {order_id}")
                return False, "买入失败"    
                
        except Exception as e:
            self.logger.error(f"股票代码：{stock_code}，买入委托异常: {str(e)}")
            return False, f"股票代码：{stock_code}，买入异常: {str(e)}"

    def sell(self, stock_code, price, volume, datetime):
        """
        发送卖出委托
        Args:
            stock_code (str): 股票代码
            price (float): 此参数在使用最新价时会被忽略
            volume (int): 卖出数量
            datetime: 交易时间
        Returns:
            tuple: (bool, str) 交易是否成功及消息
        """
        try:
            # 根据股票代码设置滑点
            if stock_code.startswith('1') or stock_code.startswith('5'):
                self.slippage = 0.001
            else:
                self.slippage = 0.01

            # 获取智能定价
            dynamic_price = self.calculate_order_price('live', 'sell', stock_code, self.bidPrices[0], self.askPrices[0], self.slippage)
            if not dynamic_price:
                self.logger.warning(f"股票代码：{stock_code}，无法获取实时价格，未能卖出")
                return False, f"股票代码：{stock_code}，无法获取实时价格，未能卖出"#super().sell(stock_code, price, volume, datetime)
            
            self.logger.info(f"股票代码：{stock_code}，智能卖出定价: {dynamic_price} (基准价: {price})，卖出数量: {volume}")
                
            # 发送限价单
            order_id = self.xt_trader.order_stock(
                account=self.account,
                stock_code=stock_code,
                order_type=xtconstant.STOCK_SELL,
                order_volume=int(volume),
                price_type=xtconstant.FIX_PRICE,  # 改为限价单
                price=dynamic_price,
                strategy_name="岳教授日内交易",
                order_remark=stock_code
            )
            
            # 记录活跃订单
            self.active_orders[order_id] = {
                'retry_count': 0,
                'direction': 'sell',
                'stock_code': stock_code,
                'volume': volume,
                'base_price': price
            }
            
            # 记录交易
            trade = {
                'time': datetime,
                'stock_code': stock_code,
                'direction': 'sell',
                'price': price,
                'volume': volume,
                'status': '已提交',
                'order_id': order_id
            }
                
            if order_id > 0:
                self.logger.info(f"股票代码: {stock_code}, 卖出委托成功，委托号: {order_id}，智能定价: {dynamic_price}（当前价: {price}）")
                return True, "卖出成功"
            else:
                self.logger.error(f"股票代码: {stock_code}, 卖出委托失败，错误码: {order_id}")
                return False, "卖出失败"
                
        except Exception as e:
            self.logger.error(f"股票代码：{stock_code}，卖出委托异常: {str(e)}")
            return False, f"股票代码：{stock_code}，卖出异常: {str(e)}"

    def get_open_price(self, symbol):
        """
        获取指定股票的持仓成本价
        Args:
            symbol (str): 股票代码
        Returns:
            float: 持仓成本价，如果没有持仓返回0
        """
        if symbol in self.positions:
            return self.positions[symbol]['open_price']
        return 0

    def get_volume(self, symbol):
        """获取当前持仓数量"""
        if symbol in self.positions:
            return self.positions[symbol]['volume']
        return 0

    def get_can_use_volume(self, symbol):
        """获取当前可用持仓数量"""
        if symbol in self.positions:
            return self.positions[symbol]['can_use_volume']
        return 0

    def on_tick(self, tick_data):
        """
        处理实时行情数据
        Args:
            tick_data (dict): 行情数据字典
        """
        if self.strategy is None:
            return
            
        for stock_code in tick_data:
            if stock_code == self.stock_code:
                tick_data = tick_data[stock_code][0]
                current_price = float(tick_data['lastPrice'])
                self.strategy.on_tick(tick_data)
                break
        message = f"最新价：{current_price:.3f}" if self.stock_code.startswith(('1', '5')) else f"最新价：{current_price:.2f}"
        self.signals.status.emit(message)

    def on_order(self, order_data):
        """
        处理委托信息
        Args:
            order_data (dict): 委托信息字典
        """
        self.logger.info(
            f"委托信息 - 订单号: {order_data.get('order_id')}, "
            f"状态: {order_data.get('status')}"
        )
        
        if self.strategy:
            self.strategy.on_order(order_data)

    def set_stock_code(self, stock_code):
        """
        设置当前交易的股票代码
        Args:
            stock_code (str): 股票代码
        """
        self.stock_code = stock_code

    def set_main_window(self, main_window):
        """
        设置主窗口引用
        Args:
            main_window: 主窗口实例
        """
        self.main_window = main_window

    def on_order_callback(self, order):
        """
        处理订单状态变化回调
        """
        if self.stock_code is None or order.stock_code != self.stock_code:
            return
        try:
            # 状态
            status_map = {
                48: "未报",
                49: "待报",
                50: "已报",
                51: "已报待撤",
                52: "部成待撤",
                53: "部撤",
                54: "已撤",
                55: "部成",
                56: "已成",
                57: "废单",
            }
            status = status_map.get(order.order_status, "未知")

            self.logger.info(
                f"股票代码: {order.stock_code}, 订单状态变化, "
                f"订单号: {order.order_id}, "
                f"状态: {status}, "
                f"成交量: {order.traded_volume}"
            )
            
            # 使用 QMetaObject.invokeMethod 在主线程中更新UI
            if hasattr(self, 'main_window'):
                QMetaObject.invokeMethod(self.main_window, 
                                       "update_order_table",
                                       Qt.QueuedConnection,
                                       Q_ARG(type(order), order))
            else:
                self.logger.error(f"委托回报推送没有更新交易记录: {order.order_id}, 股票代码={order.stock_code}, 方向={order.order_type}, 价格={order.price}, 数量={order.order_volume}")
            
            # 修改时间差计算部分
            if order.order_time:
                # 将时间戳转换为datetime对象（假设order_time是秒级时间戳）
                try:
                    order_time = datetime.fromtimestamp(order.order_time)
                    time_diff = (datetime.now() - order_time).seconds
                except TypeError:
                    # 处理可能的毫秒级时间戳
                    order_time = datetime.fromtimestamp(order.order_time / 1000)
                    time_diff = (datetime.now() - order_time).seconds
                
                self.logger.debug(f"订单时间: {order_time}，当前时间: {datetime.now()}，时间差: {time_diff}秒")
                
                # 处理未成交订单
                if order.order_status in [50, 51, 52] and time_diff > 30:
                    self.logger.info(f"股票代码：{order.stock_code}，订单{order.order_id}超时未完全成交，尝试撤单重下")
                    self.retry_order(order.stock_code, order.order_id)
            
            elif order.order_status == 54:  # 已撤单
                if order.order_id in self.active_orders:
                    self.logger.info(f"股票代码：{order.stock_code}，订单{order.order_id}已撤单，尝试重下")
                    self.retry_order(order.stock_code, order.order_id)
        except Exception as e:
            self.logger.error(f"股票代码: {order.stock_code}, 处理订单状态变化出错: {str(e)}")

            
    def on_trade_callback(self, trade_info):
        """
        处理成交回报回调
        Args:
            trade_info: 成交信息对象
        """
        try:
            # 构造成交信息
            trade_data = {
                'stock_code': trade_info.stock_code,
                'direction': 'buy' if trade_info.order_type == 23 else 'sell',
                'price': float(trade_info.traded_price),
                'volume': trade_info.traded_volume,
                'trade_time': trade_info.traded_time,
                'order_id': trade_info.order_id
            }

            if trade_data['stock_code'] != self.stock_code:
                #self.logger.info(f"收到{order.stock_code}的委托回报，但当前程序交易的是{self.stock_code}，跳过处理")
                return

            # 记录成交
            self.trades.append(trade_data)
            
            # 更新账户信息
            self.update_asset_positions()
            
            trade_time = datetime.fromtimestamp(trade_data['trade_time']).strftime('%H:%M:%S')

            # 记录详细日志
            direction_str = "买入" if trade_data['direction'] == 'buy' else "卖出"
            self.logger.info(
                f"股票代码：{trade_data['stock_code']}，{direction_str}成交回报，成交价格: {trade_data['price']}, 成交数量: {trade_data['volume']}, 成交时间: {trade_time}"
            )
            
        except Exception as e:
            self.logger.error(f"处理成交回报出错: {str(e)}")

    def retry_order(self, order_id):
        """修改后的重试逻辑（每次增加1分钱）"""
        if order_id not in self.active_orders:
            return
            
        order_info = self.active_orders[order_id]
        
        # 每次重试增加1分钱滑点
        order_info['retry_count'] += 1
        if order_info['stock_code'].startswith('1') or order_info['stock_code'].startswith('5'):
            additional_slippage = (order_info['retry_count']+1) * 0.001
        else:
            additional_slippage = (order_info['retry_count']+1) * 0.01
        
        # 获取最新行情
        current_bid = self.bidPrices[0]
        current_ask = self.askPrices[0]
        
        # 计算新价格
        if order_info['direction'] == 'buy':
            new_price = current_ask + additional_slippage
        else:
            new_price = current_bid - additional_slippage
        
        # 价格四舍五入到分
        if order_info['stock_code'].startswith('1') or order_info['stock_code'].startswith('5'):
            new_price = round(new_price, 3)
        else:
            new_price = round(new_price, 2)
        
        # 重新下单
        if order_info['direction'] == 'buy':
            self.buy(order_info['stock_code'], new_price, order_info['volume'], datetime.now())
        else:
            self.sell(order_info['stock_code'], new_price, order_info['volume'], datetime.now())
