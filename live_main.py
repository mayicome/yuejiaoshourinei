import sys
import time
import logging
from datetime import datetime, timedelta
import time
from PyQt5.QtWidgets import (
    QMainWindow, 
    QMessageBox, 
    QTableWidgetItem, 
    QApplication,
    QTableWidget,
    QAction,
    QWidget,
    QHeaderView,
    QLabel,
    QInputDialog,
    QDialog,
    QVBoxLayout,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QHBoxLayout,
    QSplitter,
    QProgressBar,
    QProgressDialog,
    QComboBox,
    QDateEdit
)
from PyQt5.QtGui import QIntValidator, QRegExpValidator, QDoubleValidator, QColor, QTextCursor
from PyQt5.QtCore import (
    QTimer, QThread, QMetaObject, Q_ARG, pyqtSlot, pyqtSignal,
    Qt, QRegExp, QMetaType
)
import xtquant.xttrader as xttrader
from live_ui import Ui_MainWindow
from adaptive_limit_strategy import AdaptiveLimitStrategy
from order_book_strategy import OrderBookStrategy
from live_engine import LiveEngine
import math
import xtquant.xtdata as xtdata
import warnings
import os
import pandas as pd
import akshare as ak
from PyQt5.QtGui import QColor
from PyQt5.QtCore import QEvent, QObject, pyqtSignal, QMetaType
import io
import configparser
import chardet
from logging.handlers import TimedRotatingFileHandler
from chncal import *
import psutil
import batch_optimizer
import requests
import zipfile
import shutil
import subprocess
import threading
import queue
from pathlib import Path
import ast

warnings.filterwarnings("ignore", category=DeprecationWarning)
xtdata.enable_hello = False

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
    
def list_top_level(dir_path):
    """
    仅遍历指定目录的顶层内容
    :param dir_path: 要遍历的目录路径
    :return: 生成器，逐个返回 (条目路径, 是否是目录) 的元组
    """
    try:
        for entry in os.scandir(dir_path):
            yield (entry.path, entry.is_dir())
    except Exception as e:
        print(f"目录遍历失败: {str(e)}")

def safe_path_handle(path):
    """安全处理包含特殊字符的路径"""
    try:
        # 处理中文路径编码问题
        if isinstance(path, bytes):
            path = path.decode('utf-8')
        # 转换Windows长路径格式
        if os.name == 'nt' and not path.startswith('\\\\?\\'):
            path = '\\\\?\\' + os.path.abspath(path)
        return os.path.normpath(path)
    except Exception as e:
        print(f"路径处理失败: {path} - {str(e)}")
        return path

def copy_files(source_dir, target_dir):
        """文件复制处理"""
        # 复制文件
        # 遍历source_dir目录下的所有文件和子目录
        src_dir = source_dir #safe_path_handle(source_dir)
        # 把src_dir中的\\换成\
        #src_dir = src_dir.replace('\\\\', '\\')
        dst_dir = target_dir #safe_path_handle(target_dir)
        # 把dst_dir中的\\换成\  
        #dst_dir = dst_dir.replace('\\\\', '\\')

        files = [p for p, is_dir in list_top_level(src_dir) if not is_dir]
        print(files)
        for file in files:
            #src_file = os.path.join(src_dir, file)
            dst_file = os.path.join(dst_dir, file)    
            
        shutil.copy2(file, dst_file)  # 保留元数据
        print(f"已复制: {file} → {dst_file}")

class TradingThread(QThread):
    """交易线程"""
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.logger = logging.getLogger('LiveTrade')
        self.is_running = False
        
    def on_data(self, data):
        """处理数据"""        
        try:
            self.engine.on_tick(data)
        except Exception as e:
            self.logger.error(f"处理数据出错: {str(e)}")
            
    def run(self):
        """运行交易逻辑"""
        try:
            self.is_running = True
            period = 'tick'
            if self.engine.stock_code in self.engine.positions:
                pos = self.engine.positions[self.engine.stock_code]
            else:
                # 创建空持仓记录
                pos = {
                    'volume': 0,
                    'can_use_volume': 0,
                    'open_price': 0.0,
                    'market_value': 0.0
                }
                self.engine.positions[self.engine.stock_code] = pos
            self.logger.info(f"股票代码：{self.engine.stock_code}开始交易, 初始持仓：[持仓数量{pos['volume']},可用数量{pos['can_use_volume']},成本价{pos['open_price']},市值{round(pos['market_value'],1)}],目标仓位: {self.engine.target_position}，周期：{period}")
            
            # 如果已有seq属性，先取消订阅
            if hasattr(self, 'seq'):
                xtdata.unsubscribe_quote(self.seq)

            # 初始化seq属性
            self.seq = xtdata.subscribe_quote(
                self.engine.stock_code, 
                period=period, 
                start_time='', 
                end_time='', 
                count=0,
                callback=self.on_data
            )
            
            if self.seq <= 0:
                self.logger.error(f"股票代码：{self.engine.stock_code}订阅行情失败")
                return
                
            self.logger.info(f"股票代码：{self.engine.stock_code}订阅行情成功")
            
        except Exception as e:
            self.logger.error(f"股票代码：{self.engine.stock_code}交易线程出错: {str(e)}")
            self.is_running = False
            
            
    def resubscribe(self):
        """重新订阅行情"""
        try:
            if hasattr(self, 'seq'):
                xtdata.unsubscribe_quote(self.seq)
            
            self.seq = xtdata.subscribe_quote(
                self.engine.stock_code, 
                period='tick',
                start_time='', 
                end_time='', 
                count=0,
                callback=self.on_data
            )
            
            if self.seq <= 0:
                self.logger.error("重新订阅行情失败")
            else:
                self.logger.info("重新订阅行情成功")
                
        except Exception as e:
            self.logger.error(f"重新订阅行情时出错: {str(e)}")
            
    def stop(self):
        """停止交易"""
        self.is_running = False
        if hasattr(self, 'seq'):
            xtdata.unsubscribe_quote(self.seq)

        if self.engine.stock_code in self.engine.positions:
            pos = self.engine.positions[self.engine.stock_code]
        else:
            pos = {
                'volume': 0,
                'can_use_volume': 0,
                'open_price': 0.0,
                'market_value': 0.0
            }
            self.engine.positions[self.engine.stock_code] = pos
        self.logger.info(f"股票代码：{self.engine.stock_code}停止交易，当前持仓: [持仓数量{pos['volume']},可用数量{pos['can_use_volume']},成本价{pos['open_price']},市值{round(pos['market_value'],1)}],目标仓位: {self.engine.target_position}")

# 创建一个新的线程类
class InitTradingThread(QThread):
    # 定义信号
    status_signal = pyqtSignal(str)
    
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
    
    def run(self):
        """线程运行函数"""
        connect_result = -1
        while connect_result != 0:
            connect_result = self.engine.connect()
            if connect_result != 0:
                self.status_signal.emit("账户连接状态：失败【请检查网络连接，并确保miniQMT已经正常登录运行。如果仍然失败，请重启miniQMT】")
                time.sleep(1)
            else:
                self.status_signal.emit("账户连接状态：正常")
                break

class OptimizationThread(QThread):
    """优化线程"""
    def __init__(self, file_path, param_file, output_dir, progress_callback=None):
        super().__init__()
        self.file_path = file_path
        self.param_file = param_file
        self.output_dir = output_dir
        self.progress_callback = progress_callback
    
    def run(self):
        """线程运行函数"""
        # 使用新的单进程优化方法
        batch_optimizer.batch_optimize_single_process(
            input_file=self.file_path, 
            param_file=self.param_file, 
            output_dir=self.output_dir, 
            progress_callback=self.progress_callback
        )

def get_zip_root_dir(zip_path):
    """获取zip文件的根目录名称"""
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        # 获取所有文件列表
        all_files = zip_ref.namelist()
        
        # 如果为空，返回None
        if not all_files:
            return None
            
        # 查找根目录名
        root_dirs = set()
        for file_path in all_files:
            # 分割路径，取第一段
            parts = file_path.split('/')
            if parts and parts[0]:  # 确保非空
                root_dirs.add(parts[0])
        
        # 如果只有一个根目录，返回它
        if len(root_dirs) == 1:
            return root_dirs.pop()
        else:
            # 多个根目录（可能没有公共根目录）
            return list(root_dirs)

class UpgradeThread(QThread):
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, latest_version, parent=None):
        super().__init__(parent)
        self.latest_version = latest_version
        self.logger = logging.getLogger('LiveTrade')

    def run(self):
        try:
            # 下载
            self.logger.info("开始下载")
            url = f"https://github.com/mayicome/yuejiaoshourinei/archive/refs/tags/{self.latest_version}.zip"
            response = requests.get(url)
            with open(f"{self.latest_version}.zip", "wb") as f:
                f.write(response.content)
            self.logger.info(f"下载完成")
            self.logger.info(f"开始解压")
            update_dir = "updates"
            if not os.path.exists(update_dir):
                os.makedirs(update_dir)
            # 解压文件到指定目录
            with zipfile.ZipFile(f"{self.latest_version}.zip", "r") as zip_ref:
                zip_ref.extractall(update_dir)
            self.logger.info(f"解压完成")
            root_dir = get_zip_root_dir(f"{self.latest_version}.zip")
            if root_dir is None:
                self.logger.error("解压后的根目录名获取失败")
                return
            if isinstance(root_dir, list):
                self.logger.error("解压后的根目录名获取失败")
                return
            unzip_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), update_dir, root_dir)
            path_obj = Path(unzip_dir)
            if not path_obj.exists():
                self.logger.error(f"错误: 目录不存在: {unzip_dir}")
                return []
                
            files = [item.name for item in path_obj.iterdir()]
            
            # 遍历files，只保留不包含.ini的文件
            files = [f for f in files if not f.endswith('.ini')]
            # 遍历files，只保留不包含.zip的文件
            files = [f for f in files if not f.endswith('.zip')]
            self.logger.info("开始复制")
            # 获取当前目录
            current_dir = os.path.dirname(os.path.abspath(__file__))
            for file in files:
                # 获取file的绝对路径
                unzip_file = os.path.join(unzip_dir, file)
                file_obj = Path(unzip_file)
                # 复制file到当前目录
                shutil.copy2(file_obj, current_dir)
            
            # 删除压缩文件
            os.remove(f"{self.latest_version}.zip")
            # 删除解压后的文件夹
            shutil.rmtree(path_obj)
            self.logger.info("复制完成")

            success = True
            message = "升级完成，即将重启。"
            self.logger.info(message)

        except Exception as e:
            success = False
            message = f"升级失败: {str(e)}"

        # 发送信号
        self.finished_signal.emit(success, message)

class LiveTradeWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger('LiveTrade')
        self.logger.info("初始化主界面")

        self.is_switching = False  # 添加标志位防止切换标签时递归
        
        # 初始化UI
        self.setupUi(self)
        
        # 初始化变量
        self.trading_thread = None
        self.last_trading_heartbeat = time.time()  # 初始化心跳时间
        
        # 初始化持仓更新定时器
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_positions_table)
        
        # 添加独立的心跳检测定时器，不受交易异常影响
        self.heartbeat_timer = QTimer()
        self.heartbeat_timer.timeout.connect(self.check_trading_status)
        self.heartbeat_timer.start(5000)  # 每5秒检查一次交易状态
        
        # 先初始化交易接口
        self.init_trading_interface()  # 新增初始化方法
        
        # 再创建engine
        self.engine = LiveEngine(
            xt_trader=self.xt_trader, 
            account_id=self.account  # 使用从config读取的account
        )
        
        # 设置主窗口引用到engine
        self.engine.set_main_window(self)  

        # 创建交易初始化线程
        self.init_thread = InitTradingThread(self.engine)

        
        # 创建自定义日志处理器类
        class QTextEditHandler(logging.Handler):
            """自定义日志处理器，将日志输出到QTextEdit"""
            def __init__(self, text_edit, max_lines=1000):
                super().__init__()
                self.text_edit = text_edit
                self.max_lines = max_lines

            def emit(self, record):
                msg = self.format(record)
                # 使用信号在主线程中更新UI
                QMetaObject.invokeMethod(self.text_edit, 
                                       "append",
                                       Qt.QueuedConnection,
                                       Q_ARG(str, msg))
                # 检查行数并删除旧的行
                if self.text_edit.document().lineCount() > self.max_lines:
                    cursor = self.text_edit.textCursor()
                    cursor.movePosition(cursor.Start)
                    cursor.movePosition(cursor.Down, cursor.KeepAnchor, 
                                      self.text_edit.document().lineCount() - self.max_lines)
                    cursor.removeSelectedText()
        
        # 设置日志
        logger = logging.getLogger('LiveTrade')
        
        # 如果logger已经配置过，直接返回
        if not logger.handlers:
            logger.setLevel(logging.INFO)
            
            # 创建logs目录（如果不存在）
            log_dir = "logs"
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            
            # 生成日志文件名（使用当前日期）
            log_file = os.path.join(log_dir, f"live_trade_{datetime.now().strftime('%Y%m%d')}.log")
            
            # 添加文件处理器
            file_handler = TimedRotatingFileHandler(
                filename=os.path.join(log_dir, 'live_trade.log'),  # 基础文件名
                when='midnight',     # 每天午夜滚动
                interval=1,          # 每天一次
                backupCount=30,       # 保留30天日志
                encoding='utf-8',
                utc=False            # 使用本地时间
            )
            file_handler.suffix = "%Y%m%d.log"  # 定义滚动后的文件名格式
            file_handler.setLevel(logging.INFO)
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
            
            # 添加QTextEdit处理器，设置最大显示1000行
            text_handler = QTextEditHandler(self.textEdit, max_lines=1000)
            text_handler.setLevel(logging.INFO)
            text_formatter = logging.Formatter('%(asctime)s - %(message)s')  # 简化的格式
            text_handler.setFormatter(text_formatter)
            logger.addHandler(text_handler)
            
            # 添加控制台处理器
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
            )
            console_handler.setFormatter(console_formatter)
            logger.addHandler(console_handler)
        
        self.logger = logger
        self.logger.info("程序启动")  # 使用logger
        
        # 创建一个QLabel用于状态栏
        self.status_label = QLabel()
        self.status_label.setTextFormat(Qt.RichText)  # 启用富文本支持
        self.statusbar.addWidget(self.status_label)
        self.statusbar.setStyleSheet("QStatusBar { color: black; }")
        self.statusbar.setSizeGripEnabled(False)

        self.all_a_stocks = None
        self.load_all_stocks_info()
        
        # 初始化UI
        self.init_ui()
        
        # 连接信号
        self.init_thread.status_signal.connect(self.statusbar.showMessage)
        self.engine.signals.status.connect(self.receive_message)
        
        # 启动线程
        self.init_thread.start()
        
        # 启动定时更新
        self.update_timer.start(1000)  # 每秒更新一次
        
        # 创建一个透明的遮罩层
        self.mask_widget = QWidget(self)
        self.mask_widget.setStyleSheet("background-color: rgba(0, 0, 0, 0);")
        self.mask_widget.hide()
        
        # 添加交易状态标志和事件过滤器
        self.tableWidget_2.viewport().installEventFilter(self)

        # 添加异常捕获钩子
        sys.excepthook = self.handle_uncaught_exception

        self.progress_dialog = None
        self.upgrade_thread = None
        self.progress_label = None

    def optimization_progress_callback(self, current, total):
        """优化回调函数"""
        self.progress_count = int((current / total) * 100)
        # 使用信号安全地更新UI
        QMetaObject.invokeMethod(
            self.progress_bar, 
            "setValue", 
            Qt.QueuedConnection,
            Q_ARG(int, self.progress_count)
        )

    def init_trading_interface(self):
        """初始化交易接口"""
        config = configparser.ConfigParser()
        with open('config.ini', 'rb') as f:
            result = chardet.detect(f.read())
        
        with open('config.ini', 'r', encoding=result['encoding']) as f:
            config.read_file(f)
        
        path = config.get('Account', 'path_qmt')
        self.account = config.get('Account', 'account_id')
        print(f"path: {path}, account: {self.account}")
        session = int(time.time())
        
        # 创建xt_trader实例
        self.xt_trader = xttrader.XtQuantTrader(path, session)
        time.sleep(1)
        self.xt_trader.start()

        # 读取setting部分，如果没有则设置默认值
        # 检查setting部分是否存在
        if 'setting' not in config:
            self.min_trade_amount = 10000
            self.param_grid = None
        else:
            self.min_trade_amount = int(config.get('setting', 'min_trade_amount'))
            param_grid = config.get('setting', 'param_grid')
            self.param_grid = eval(param_grid)

    def receive_message(self, message):
        """接收消息"""
        # 更新最后心跳时间
        if "最新价" in message:
            self.last_trading_heartbeat = time.time()
            self.statusbar.showMessage(message, 2500)
        elif message == "账户连接状态：正常":
            self.statusbar.showMessage(message)
            if not self.update_timer.isActive():
                self.update_timer.start(1000)
                self.statusbar.showMessage("交易线程恢复正常，恢复更新持仓信息")
                self.logger.info("交易线程恢复正常，恢复更新持仓信息")
        else:
            #self.logger.info(message)
            self.statusbar.showMessage(message)
            self.update_timer.stop()
            result = "交易线程异常，停止更新持仓信息以免拥塞。收到的信息内容：" + message
            self.statusbar.showMessage(result)
            self.logger.info(result)

    def init_ui(self):
        """初始化UI"""
        #self.logger.info("开始初始化UI")
        
        # 设置交易记录表格
        self.tableWidget.setColumnCount(8)
        self.tableWidget.setHorizontalHeaderLabels([
            '订单编号','报单时间', '股票代码', '交易类型', '委托价格', '数量', '委托状态', '策略名称'
        ])

        # 设置表格列宽自动调整
        self.tableWidget.horizontalHeader().setStretchLastSection(True)  # 最后一列自动填充
        self.tableWidget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)  # 所有列自动调整
        
        # 设置持仓表格
        self.tableWidget_2.setColumnCount(6)
        self.tableWidget_2.setHorizontalHeaderLabels([
            '股票代码', '股票名称','持仓数量', '可用数量', '成本价', '市值'
        ])
        
        # 设置表格为不可编辑
        self.tableWidget_2.setEditTriggers(QTableWidget.NoEditTriggers)
        # 设置整行选择
        self.tableWidget_2.setSelectionBehavior(QTableWidget.SelectRows)
        # 设置单行选择
        self.tableWidget_2.setSelectionMode(QTableWidget.SingleSelection)

        self.tableWidget_2.horizontalHeader().setStretchLastSection(True)  # 最后一列自动填充
        self.tableWidget_2.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)  # 所有列自动调整

        # 连接选择变化信号
        self.tableWidget_2.itemSelectionChanged.connect(self.on_position_selected)

        # 设置持仓表格
        self.tableWidget_3.setColumnCount(6)
        self.tableWidget_3.setHorizontalHeaderLabels([
            '股票代码', '股票名称','持仓数量', '可用数量', '成本价', '市值'
        ])
        
        # 设置表格为不可编辑
        self.tableWidget_3.setEditTriggers(QTableWidget.NoEditTriggers)
        # 设置整行选择
        self.tableWidget_3.setSelectionBehavior(QTableWidget.SelectRows)
        # 设置单行选择
        self.tableWidget_3.setSelectionMode(QTableWidget.SingleSelection)

        self.tableWidget_3.horizontalHeader().setStretchLastSection(True)  # 最后一列自动填充
        self.tableWidget_3.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)  # 所有列自动调整

        self.current_table = self.tableWidget_2

        self.pushButton.clicked.connect(self.on_button_clicked)
        self.pushButton_2.clicked.connect(self.on_button_2_clicked)
        self.pushButton_3.clicked.connect(self.on_button_3_clicked)
        # 点击tab_2时，触发on_stock_selected
        self.tabWidget.currentChanged.connect(self.on_tab_changed)

        # 设置策略选择单选按钮
        self.radioButton.clicked.connect(self.on_strategy_selected)
        self.radioButton_2.clicked.connect(self.on_strategy_selected)
        self.radioButton_3.clicked.connect(self.on_strategy_selected)
        # 触发点击self.radioButton
        self.radioButton.click()

        self.threshold = -1

        # "浮动限价策略", "adaptive_limit"
        # 这种策略在学术文献中常被称为"Adaptive Limit Order Book Strategy"，特别适合A股这种存在涨跌停限制且T+1交易的市场环境。
        # 流动性好的股票：0.05%~0.1%
        # 低价小盘股：0.5%~1%
        # 极端行情：动态扩大至2%~3%
        
        #"盘口动量增强策略", "order_book"
        # Order Book Momentum Enhancement
        # 捕捉主力资金盘口异动
        # 3秒级快速响应
        # 动态调整阈值适应不同流动性

        #"事件驱动套利策略", "event_driven"
        # Event-Driven Arbitrage Strategy
        # 利用A股典型的事件驱动特征
        # 2分钟内完成事件反应
        # 涨停板检查避免无效委托

        # 策略组合优势：
        # 盘口策略捕捉微观结构变化
        # 事件策略把握宏观驱动因素
        # 两者形成互补：当市场平静时依靠盘口策略，当事件驱动时切换至新闻策略

        # 添加操作菜单栏
        menubar = self.menuBar()

        # 添加设置菜单
        setting_menu = menubar.addMenu('管理')
        
        # 添加版本信息动作
        setting_action = QAction('设置参数', self)
        setting_action.triggered.connect(self.show_setting)
        setting_menu.addAction(setting_action)
        
        # 添加帮助菜单
        help_menu = menubar.addMenu('帮助')
        
        # 添加版本信息动作
        version_action = QAction('版本信息', self)
        version_action.triggered.connect(self.show_version)
        help_menu.addAction(version_action)

        try:
            # 更新账户信息
            if not self.engine.update_asset_positions():
                self.logger.error("更新账户信息失败")
                return
            
        except Exception as e:
            self.logger.error(f"初始化交易失败: {str(e)}")
            import traceback
            self.logger.error(f"错误详情: {traceback.format_exc()}")

    def init_trading(self):
        """初始化交易连接"""
        # 建立交易连接
        connect_result = -1
        while connect_result != 0:
            connect_result = self.engine.connect()
            if connect_result != 0:
                self.statusbar.showMessage("账户连接状态：失败【请检查网络连接，并确保miniQMT已经正常登录运行。如果仍然失败，请重启miniQMT】")
                time.sleep(1)
            
        self.statusbar.showMessage("账户连接状态：正常")

    def on_button_clicked(self):
        """处理按钮点击事件"""
        if self.pushButton.text() == "开始交易":
            self.start_trading()
        else:
            self.stop_trading()

    def on_button_2_clicked(self):
        """处理按钮点击事件"""
        result_file = getattr(self, 'result_file', None)
        
        if result_file and os.path.exists(result_file):
            # 读取excel文件并在新窗口显示
            df = pd.read_excel(result_file)
            # 判断是否读取成功
            if df.empty:
                QMessageBox.warning(self, "警告", "还没有智能评测结果，请在回测后查看")
                return
            # 创建一个新窗口
            new_window = QDialog(self)
            new_window.setWindowTitle("优化结果")
            new_window.setFixedSize(800, 600)
                # 创建一个表格
            table = QTableWidget(new_window)
            table.setGeometry(10, 10, 780, 580)
            
            # 设置表格的行数和列数
            table.setRowCount(len(df))
            table.setColumnCount(len(df.columns))
            table.setHorizontalHeaderLabels(df.columns)
            
            # 填充表格数据
            for i, row in enumerate(df.itertuples(index=False)):
                for j, value in enumerate(row):
                    #if j == 0:
                    table.setItem(i, j, QTableWidgetItem(str(value)))
            
            # 显示新窗口
            new_window.show()
        else:
            QMessageBox.warning(self, "警告", "还没有智能评测结果，请在回测后查看") 

    def on_button_3_clicked(self):
        """处理按钮点击事件"""
        if self.engine.stock_code:
            # 创建DataFrame时直接指定列名
            columns = ['代码', '名称', '起始日期', '结束日期', '基础仓位', '可用仓位', '目标仓位', '平均成本', '初始可用资金']
            stocks = pd.DataFrame(columns=columns)
            
            # 正确处理QDate对象
            start_date = self.start_date.toString("yyyy-MM-dd") if hasattr(self, 'start_date') else (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            end_date = self.end_date.toString("yyyy-MM-dd") if hasattr(self, 'end_date') else datetime.now().strftime('%Y-%m-%d')
            
            stocks.loc[0] = [
                self.engine.stock_code, 
                self.get_stock_name(self.engine.stock_code), 
                start_date, 
                end_date, 
                self.current_table.item(self.current_table.currentRow(), 2).text(), 
                self.current_table.item(self.current_table.currentRow(), 3).text(), 
                self.lineEdit_2.text(), 
                self.current_table.item(self.current_table.currentRow(), 4).text(), 
                self.engine.cash
            ]
        else:
            QMessageBox.warning(self, "警告", "请先选择要交易的股票！")
            return
        #保存股票信息到.\data\init_position.xlsx
        file_path = os.path.join(os.path.dirname(__file__), 'data', 'init_position.xlsx')
        stocks.to_excel(file_path, index=False, engine='openpyxl')
        param_file = os.path.join(os.path.dirname(__file__), 'config.ini')
        output_dir = os.path.join(os.path.dirname(__file__), 'data')
        
        # 把选择的最少交易数量写入config中
        # 先从config中读取param_grid
        # 打开并读取现有配置文件
        config = configparser.ConfigParser()        # 检测文件编码
        with open(param_file, 'rb') as f:
            content = f.read()
            encoding = chardet.detect(content)['encoding']
        
        # 读取现有配置
        with open(param_file, 'r', encoding=encoding) as f:
            config.read_file(f)

        if not config.has_section('setting'):
            config.add_section('setting')
            param_grid = {}  # 初始化为空字典
        else:
            # 安全读取param_grid
            try:
                param_grid_str = config.get('setting', 'param_grid', fallback='{}')
                param_grid = ast.literal_eval(param_grid_str)  # 使用更安全的解析方式
            except (SyntaxError, ValueError) as e:
                self.logger.error(f"解析param_grid失败: {str(e)}")
                param_grid = {}
        
        # 处理交易数量输入
        trade_size = self.lineEdit_3.text()
        if not trade_size.isdigit():
            trade_size = 100
        trade_size = int(trade_size)
        
        # 更新参数网格
        param_grid['trade_size'] = [trade_size]  # 保持为列表形式

        # 写入配置时转换为字符串
        config['setting']['param_grid'] = str(param_grid)

        # 保存配置
        with open(param_file, 'w', encoding=encoding) as f:
            config.write(f)
        
        try:
            # 创建进度对话框
            self.progress_window = QDialog(self)
            self.progress_window.setWindowTitle("智能评估参数")
            self.progress_window.setFixedSize(400, 150)  # 增加高度
            
            # 设置窗口标志（保留关闭按钮，移除帮助按钮）
            self.progress_window.setWindowFlags(
                Qt.Dialog | 
                Qt.WindowTitleHint |
                Qt.WindowSystemMenuHint |
                Qt.WindowCloseButtonHint  # 只保留关闭按钮
            )

            # 设置布局
            layout = QVBoxLayout(self.progress_window)
            
            # 添加标签和进度条
            label = QLabel("正在进行不同参数组合的策略回测，请稍候...", self.progress_window)
            self.progress_bar = QProgressBar(self.progress_window)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            
            # 添加状态标签
            self.status_label = QLabel("正在准备评估任务...", self.progress_window)
            self.status_label.setWordWrap(True)
            
            # 添加取消按钮
            cancel_button = QPushButton("取消", self.progress_window)
            cancel_button.clicked.connect(self.cancel_optimization)
            
            layout.addWidget(label)
            layout.addWidget(self.progress_bar)
            layout.addWidget(self.status_label)
            layout.addWidget(cancel_button)
            
            # 设置进度条更新定时器
            self.progress_timer = QTimer()
            self.progress_timer.timeout.connect(self.update_optimization_status)
            self.progress_timer.start(1000)  # 每500毫秒更新一次
            
            # 设置进度条为0
            self.progress_count = 0
            
            # 显示提示信息
            self.status_label.setText("正在启动回测任务，请耐心等待...")
            
            # 显示进度窗口
            self.progress_window.show()
            QApplication.processEvents()  # 强制处理等待的事件

            # 启动优化线程
            self.optimization_thread = OptimizationThread(file_path, param_file, output_dir, self.optimization_progress_callback)
            self.optimization_thread.finished.connect(self.on_optimization_finished)
            self.optimization_thread.start()
            
        except Exception as e:
            self.logger.error(f"保存或执行优化时出错: {str(e)}")
            QMessageBox.warning(self, "错误", f"保存或执行优化时出错: {str(e)}")

    def update_optimization_status(self):
        """更新优化状态"""
        if hasattr(self, 'progress_count'):
            self.progress_bar.setValue(self.progress_count)
            
            # 根据进度更新状态提示
            if self.progress_count < 20:
                self.status_label.setText("正在准备评估数据...")
            elif self.progress_count < 40:
                self.status_label.setText("正在执行参数组合分析...")
            elif self.progress_count < 60:
                self.status_label.setText("正在进行历史数据回测...")
            elif self.progress_count < 80:
                self.status_label.setText("正在计算收益指标...")
            else:
                self.status_label.setText("正在生成评估报告...")

    def cancel_optimization(self):
        """取消优化任务"""
        if hasattr(self, 'optimization_thread') and self.optimization_thread.isRunning():
            reply = QMessageBox.question(
                self.progress_window, 
                "确认取消", 
                "确定要取消评估任务吗？已完成的评估将丢失。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # 先安全地停止定时器
                if hasattr(self, 'progress_timer') and self.progress_timer.isActive():
                    self.progress_timer.stop()

                # 终止线程
                self.optimization_thread.terminate()
                self.optimization_thread.wait(1000)
                
                # 关闭进度窗口
                self.progress_window.close()
                
                QMessageBox.information(self, "已取消", "评估任务已取消")

    def on_optimization_finished(self):
        """优化完成后的操作"""
        # 先安全地停止定时器
        if hasattr(self, 'progress_timer') and self.progress_timer.isActive():
            self.progress_timer.stop()

        # 设置进度为100%
        self.progress_bar.setValue(100)
        
        # 延迟关闭进度窗口
        QTimer.singleShot(1000, self.progress_window.accept)
        symbol = self.engine.stock_code.split('.')[0]
        # 获取优化结果文件
        self.result_file = os.path.join(os.path.dirname(__file__), 'data', f"optimizer_result_{symbol}.xlsx")
        # 以只读的方式打开优化结果excel文件
        df = pd.read_excel(self.result_file)
        # 读取第一行波动阈值列的值
        params = df.iloc[0]['波动阈值']
        print(f"优化结果: {params}")        
        self.lineEdit.setText(str(params))
        # 显示完成消息
        QMessageBox.information(self, "完成", f"回测已完成，回测的结果显示：在指定时间段，给出的波动阈值中，最优的值为{params}。\n该结果并不构成投资建议，请根据实际情况调整后再开始进行实盘交易。\n查看详细的回测结果请点击右侧按钮")
        self.logger.info(f"优化已完成，波动阈值的推荐值为{params}")

    def add_stock(self):
        """添加单支股票"""
        # 创建自定义对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("添加股票")
        dialog.setFixedSize(300, 150)
        
        layout = QVBoxLayout()
        
        # 添加标签
        label = QLabel("请输入6位股票代码：")
        layout.addWidget(label)
        
        # 添加单行输入框
        stock_input = QLineEdit()
        stock_input.setPlaceholderText("例如：600000")
        stock_input.setMaxLength(6)  # 限制最大输入长度
        stock_input.setValidator(QRegExpValidator(QRegExp(r'^\d{6}$')))  # 添加起止符更严格
        layout.addWidget(stock_input)
        
        # 添加按钮
        button_box = QHBoxLayout()
        ok_button = QPushButton("确定")
        cancel_button = QPushButton("取消")
        button_box.addWidget(ok_button)
        button_box.addWidget(cancel_button)
        layout.addLayout(button_box)
        
        dialog.setLayout(layout)
        
        # 连接按钮信号
        def on_ok_clicked():
            symbol = stock_input.text().strip()
            if len(symbol) != 6 or not symbol.isdigit():
                QMessageBox.warning(dialog, "输入错误", "请输入有效的6位数字股票代码")
                return
            
            dialog.accept()
            
        def on_cancel_clicked():
            self.tabWidget.setCurrentIndex(0)
            dialog.reject()
        
        ok_button.clicked.connect(on_ok_clicked)
        cancel_button.clicked.connect(on_cancel_clicked)
        
        # 显示对话框并获取结果
        if dialog.exec_() == QDialog.Accepted:
            symbol = stock_input.text().strip()
            self.logger.info(f"添加股票: {symbol}")
            
            # 更新交易引擎
            stock_code = symbol2stock(symbol)
            self.engine.set_stock_code(stock_code)
            
            # 更新UI显示
            self.update_positions_table()

    def on_tab_changed(self):
        """处理标签点击事件"""
        index = self.tabWidget.currentIndex()
        if self.trading_thread:
            if self.is_switching:
                return
        
            message = QMessageBox.information(self, "提示", "请先中止交易再切换标签页")
            self.is_switching = True
            if index == 1:
                self.tabWidget.setCurrentIndex(0)
            elif index == 0:
                self.tabWidget.setCurrentIndex(1)
            self.is_switching = False
            return
        if index == 0:
            self.current_table = self.tableWidget_2
            if self.tableWidget_2.rowCount() == 0:                
                self.engine.stock_code = None
            else:
                self.engine.stock_code = self.tableWidget_2.item(0, 0).text()
        elif index == 1:  
            self.current_table = self.tableWidget_3
            self.engine.stock_code = None
            self.add_stock()
        # 根据当前标签页更新表格数据（如果需要）
        self.update_positions_table()


    def on_strategy_selected(self):
        """处理策略选择事件"""
        self.logger.info(f"策略选择: {self.sender().text()}") 
        if self.sender().text() == "浮动限价策略":
            self.label.setText("波动阈值 %：")
            self.lineEdit.setText("0.005")
            # 设置验证器
            validator = QDoubleValidator(0.001, 0.3, 3)
            validator.setNotation(QDoubleValidator.StandardNotation)
            self.lineEdit.setValidator(validator)
        elif self.sender().text() == "盘口动量增强策略":
            QMessageBox.information(self, "提示", "该功能为VIP功能，请先升级为VIP")
            #self.label.setText("策略参数：")
            self.radioButton.setChecked(True)
        elif self.sender().text() == "事件驱动套利策略":
            QMessageBox.information(self, "提示", "该功能为VVIP功能，请先升级为VVIP")
            #self.label.setText("策略参数：")
            self.radioButton.setChecked(True)

    def start_trading(self):
        """开始交易"""
        try:
            # 获取当前选中的行
            current_row = self.current_table.currentRow()
            if current_row < 0:
                QMessageBox.warning(self, "警告", "没有可交易的股票！")
                return

            # 获取股票代码
            stock_code = self.current_table.item(current_row, 0).text()
            print(f"start stock_code: {stock_code}")
            if not stock_code:
                QMessageBox.warning(self, "警告", "请先选择要交易的股票！")
                return
            
            # 检查可用数量
            can_use_volume = self.current_table.item(current_row, 3).text()
            if not can_use_volume:
                QMessageBox.warning(self, "警告", "无法获取可用数量！")
                return
            elif int(can_use_volume) == 0:
                QMessageBox.warning(self, "提醒", "当前股票可用数量为0，今天只能建仓。")
                self.logger.info(f"所选股票{stock_code}当前可用数量为0，今天只能建仓。")
            
            # 检查目标仓位
            try:
                target_position = int(self.lineEdit_2.text())
                if target_position < 0:
                    QMessageBox.warning(self, "警告", "目标仓位不能为负数！")
                    return
                elif target_position == 0:
                    QMessageBox.warning(self, "提醒", "目标仓位为0，将以清仓作为目标。")
                    self.logger.info(f"所选股票{stock_code}目标仓位为0，将以清仓作为目标。")
            except ValueError:
                QMessageBox.warning(self, "警告", "无法获取目标仓位！")
                return
            
            if self.lineEdit_3.text() == "":
                self.trade_size = 100
            else:
                self.trade_size = int(self.lineEdit_3.text())
            
            if self.radioButton.isChecked():
                self.threshold = float(self.lineEdit.text())
                strategy_type = "adaptive_limit"
                if self.threshold == -1:
                    QMessageBox.warning(self, "警告", "采用浮动限价策略请先设置波动阈值！")
                    return
            elif self.radioButton_2.isChecked():
                strategy_type = "order_book"
            elif self.radioButton_3.isChecked():
                strategy_type = "event_driven"
            else:
                QMessageBox.warning(self, "警告", "请先选择策略！")
                return
            
            # 创建并设置策略（传入engine参数）
            if strategy_type == "adaptive_limit":
                strategy = AdaptiveLimitStrategy(
                    self.engine, 
                    threshold=self.threshold, 
                    trade_size=self.trade_size, 
                    min_trade_amount=self.min_trade_amount, 
                    logger=logging.getLogger('LiveTrade')  # 使用主程序的logger
                )
            elif strategy_type == "order_book":
                strategy = OrderBookStrategy(
                    self.engine, 
                    bid_vol_threshold=500, 
                    ask_vol_threshold=300, 
                    min_trade_amount=self.min_trade_amount, 
                    logger=logging.getLogger('LiveTrade')  # 使用主程序的logger
                )
                self.logger.info(f"使用盘口动量增强策略，买一档成交量阈值为{500},卖一档成交量阈值为{300},最小交易金额为{self.min_trade_amount},最小交易数量为{self.trade_size}")
            '''elif strategy_type == "event_driven":
                strategy = EventDrivenStrategy(
                    self.engine, 
                    logger=logging.getLogger('LiveTrade')  # 使用主程序的logger
                )  # 传入engine'''
            self.engine.set_strategy(strategy)

            # 禁用表格选择但保持可见
            self.current_table.setSelectionMode(QTableWidget.NoSelection)
            
            # 保持当前行的选中状态
            if current_row >= 0:
                self.current_table.selectRow(current_row)
            
            # 禁用收盘目标仓位编辑
            self.lineEdit_2.setEnabled(False)
            
            # 改变按钮文本为"中止交易"
            self.pushButton.setText("中止交易")
            
            # 设置股票代码
            self.engine.set_stock_code(stock_code)
            self.engine.target_position = target_position
                        
            # 创建并启动交易线程
            self.trading_thread = TradingThread(self.engine)
            self.trading_thread.start()

        except Exception as e:
            self.logger.error(f"开始交易时出错: {str(e)}")

    def stop_trading(self):
        """中止交易"""
        #try:
        if True:
            # 恢复表格选择功能
            self.current_table.setSelectionMode(QTableWidget.SingleSelection)
            
            # 恢复收盘目标仓位编辑
            self.lineEdit_2.setEnabled(True)
            
            # 改变按钮文本为"开始交易"
            self.pushButton.setText("开始交易")
            
            # 中止交易线程
            if hasattr(self, 'trading_thread') and self.trading_thread is not None:
                self.trading_thread.stop()
                self.trading_thread = None
            
        #except Exception as e:
        #    self.logger.error(f"中止交易时出错: {str(e)}")
        #    QMessageBox.critical(self, "错误", f"中止交易时出错: {str(e)}")

    def on_thread_log(self, msg):
        """处理线程日志"""
        self.textEdit.append(msg)
        self.logger.info(msg)

    def on_thread_error(self, msg):
        """处理线程错误"""
        self.textEdit.append(f"错误: {msg}")
        self.logger.error(msg)
        QMessageBox.critical(self, "错误", msg)

    def closeEvent(self, event):
        """窗口关闭事件"""
        try:
            # 确保关闭时停止交易线程
            if self.trading_thread:
                QMessageBox.warning(self, "警告", "请先中止交易再退出")
                event.ignore()
                return
            # 终止所有子线程
            if self.trading_thread and self.trading_thread.isRunning():
                self.trading_thread.terminate()
                self.trading_thread.wait(2000)  # 最多等待2秒
                
            # 确保定时器停止
            self.update_timer.stop()
            
            event.accept()
        except Exception as e:
            self.logger.error(f"关闭窗口时出错: {str(e)}")

    def on_position_selected(self):
        """处理持仓表格的选择变化"""
        try:
            # 获取当前选中的行
            selected_rows = self.tableWidget_2.selectedItems()
            if not selected_rows:
                return
            
            # 获取选中行的行号
            current_row = selected_rows[0].row()
            can_use_volume = self.tableWidget_2.item(current_row, 3).text()
            
            # 设置收盘目标仓位为可用数量            
            self.lineEdit_2.setText(can_use_volume)

            self.engine.stock_code = self.tableWidget_2.item(current_row, 0).text()
            
        except Exception as e:
            self.logger.error(f"处理选择变化时出错: {str(e)}")

    def update_positions_table(self):
        #try:
        if True:
            # 更新账户信息
            if not self.engine.update_asset_positions():
                return
            
            # 更新持仓表格
            positions = self.engine.positions
            current_row = self.current_table.currentRow()  # 保存当前选中的行
            if current_row < 0 and self.current_table.rowCount() >= 1:
                current_row = 0
            
            pos = None
            # 如果启动了交易线程
            if self.trading_thread:
                # 只显示当前交易股票或占位记录
                self.current_table.setRowCount(1)
                # 如果当前交易股票在positions中，则显示，否则显示占位记录
                if self.engine.stock_code in positions:
                    pos = positions[self.engine.stock_code]
                else:
                    pos = {
                        'volume': 0,
                        'can_use_volume': 0,
                        'open_price': 0.0,
                        'market_value': 0.0
                    }
                stock_code = self.engine.stock_code
                row = 0
            else:
                if self.current_table == self.tableWidget_2:
                    # 显示全部持仓
                    self.current_table.setRowCount(len(positions))
                    stock_items = positions.items()
                    row = 0  # 初始化row变量
                elif self.current_table == self.tableWidget_3:
                    if self.engine.stock_code:
                        pos = {
                        'volume': 0,
                        'can_use_volume': 0,
                        'open_price': 0.0,
                        'market_value': 0.0
                        }
                        #把这条记录添加到positions中
                        positions[self.engine.stock_code] = pos
                        self.current_table.setRowCount(1)
                    else:# 不显示持仓
                        self.current_table.setRowCount(0)
                        stock_items = []
                        row = 0  # 初始化row变量

            # 统一处理数据显示
            for row, (stock_code, pos) in enumerate(stock_items if pos is None else [(self.engine.stock_code, pos)]):
                # 处理各字段的默认值
                volume = pos.get('volume', 0)
                can_use_volume = pos.get('can_use_volume', volume)
                open_price = pos.get('open_price', 0.0)
                market_value = pos.get('market_value', 0.0)

                # 处理nan值
                if isinstance(open_price, float) and math.isnan(open_price):
                    open_price = 0.0
                if isinstance(market_value, float) and math.isnan(market_value):
                    market_value = 0.0
                
                # 获取股票名称
                stock_name = self.get_stock_name(stock_code)

                # 设置表格内容
                self.current_table.setItem(row, 0, QTableWidgetItem(stock_code))
                self.current_table.setItem(row, 1, QTableWidgetItem(stock_name))
                self.current_table.setItem(row, 2, QTableWidgetItem(str(volume)))
                self.current_table.setItem(row, 3, QTableWidgetItem(str(can_use_volume)))
                self.current_table.setItem(row, 4, QTableWidgetItem(f"{open_price:.3f}"))
                self.current_table.setItem(row, 5, QTableWidgetItem(f"{market_value:.2f}"))

            self.current_table.selectRow(current_row)

        #except Exception as e:
        #    self.logger.error(f"更新显示失败: {str(e)}")

    @pyqtSlot(object)  # 使用装饰器标记为槽
    def update_order_table(self, order):
        """
        更新订单表格
        Args:
            order: 订单信息
        """
        try:
            # 订单编号
            order_id = str(order.order_id)
            # 如果在tablewidget中第一列找到order_id，则更新，否则插入新行
            for row in range(self.tableWidget.rowCount()):
                if self.tableWidget.item(row, 0).text() == order_id:
                    current_row = row
                    break
            else:
                current_row = self.tableWidget.rowCount()
                self.tableWidget.insertRow(current_row)
            
            # 状态映射
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
            
            # 设置各列的值
            self.tableWidget.setItem(current_row, 0, QTableWidgetItem(str(order.order_id)))
            self.tableWidget.setItem(current_row, 1, QTableWidgetItem(datetime.now().strftime('%H:%M:%S')))
            self.tableWidget.setItem(current_row, 2, QTableWidgetItem(order.stock_code))
            self.tableWidget.setItem(current_row, 3, QTableWidgetItem("买入" if order.order_type == 23 else "卖出"))
            self.tableWidget.setItem(current_row, 4, QTableWidgetItem(str(round(order.price, 2))))
            self.tableWidget.setItem(current_row, 5, QTableWidgetItem(str(order.order_volume)))
            self.tableWidget.setItem(current_row, 6, QTableWidgetItem(status_map.get(order.order_status, "未知")))
            self.tableWidget.setItem(current_row, 7, QTableWidgetItem("岳教授日内交易"))
            
            # 滚动到最新行
            self.tableWidget.scrollToBottom()
            
        except Exception as e:
            self.logger.error(f"更新订单表格出错: {str(e)}")

    def get_stock_name(self, stock_code):
        # 查找匹配的股票代码
        result = self.all_a_stocks[self.all_a_stocks['证券代码'] == stock_code[:6]]
        if not result.empty:
            return result['证券简称'].values[0]
        return "未知名称"

    def load_all_stocks_info(self):
        """加载股票基本信息"""
        # 确保data目录存在
        data_dir = os.path.join(os.path.dirname(__file__), 'data')
        os.makedirs(data_dir, exist_ok=True)
        
        # 检查是否存在all_a_stocks.csv文件且是今天创建的
        csv_file = os.path.join(data_dir, 'all_a_stocks.csv')
        if os.path.exists(csv_file):
            # 获取文件的最后修改时间
            file_mtime = datetime.fromtimestamp(os.path.getmtime(csv_file))
            today = datetime.now().date()
            
            # 如果文件是今天修改的,则直接读取CSV文件
            if file_mtime.date() == today:
                try:
                    self.all_a_stocks = pd.read_csv(csv_file, dtype={'证券代码': str})
                    self.logger.info(f"已从{csv_file}文件读取全A股股票和基金名称信息")
                    return
                except Exception as e:
                    self.logger.error(f"读取{csv_file}文件时出错: {e}")

        if self.all_a_stocks is None:
            # 获取沪深京 A 股的基本信息
            stock_info_sh_name_code_df = ak.stock_info_sh_name_code()
            # 先创建副本，然后选择需要的列
            stock_info_sh = stock_info_sh_name_code_df[['证券代码', '证券简称', '上市日期']].copy()
            # 使用 loc 设置数据类型
            stock_info_sh.loc[:, '证券代码'] = stock_info_sh['证券代码'].astype(str)
            
            stock_info_sz_name_code_df = ak.stock_info_sz_name_code()
            # 先创建副本，然后选择需要的列
            stock_info_sz = stock_info_sz_name_code_df[['A股代码', 'A股简称', 'A股上市日期']].copy()
            # 使用 loc 设置数据类型
            stock_info_sz.loc[:, 'A股代码'] = stock_info_sz['A股代码'].astype(str)
            # 重命名列
            stock_info_sz = stock_info_sz.rename(columns={
                'A股代码': '证券代码',
                'A股简称': '证券简称', 
                'A股上市日期': '上市日期'
            })
            
            stock_info_bj_name_code_df = ak.stock_info_bj_name_code()
            # 先创建副本，然后选择需要的列
            stock_info_bj = stock_info_bj_name_code_df[['证券代码', '证券简称', '上市日期']].copy()
            # 使用 loc 设置数据类型
            stock_info_bj.loc[:, '证券代码'] = stock_info_bj['证券代码'].astype(str)

            stock_info_jj_name_code_df = ak.fund_etf_spot_em()
            stock_info_jj = stock_info_jj_name_code_df[['代码', '名称']].copy()
            # 使用 loc 设置数据类型
            stock_info_jj.loc[:, '代码'] = stock_info_jj['代码'].astype(str)
            # 把代码列改为证券代码，把名称改为证券简称
            stock_info_jj.rename(columns={'代码': '证券代码', '名称': '证券简称'}, inplace=True)
            # 增加上市日期列，内容为空
            stock_info_jj['上市日期'] = ''
            
            # 合并所有数据
            self.all_a_stocks = pd.concat([stock_info_sh, stock_info_sz, stock_info_bj, stock_info_jj])
            
            # 将所有股票信息写入CSV文件
            try:
                self.all_a_stocks.to_csv(csv_file, index=False, encoding='utf-8')
                self.logger.info(f"已将股票信息写入文件: {csv_file}")
            except Exception as e:
                self.logger.error(f"写入{csv_file}文件时出错: {e}")

    def get_latest_version(self):
        """通过GitHub API获取最新版本号"""
        api_url = "https://api.github.com/repos/mayicome/yuejiaoshourinei/releases/latest"
        
        try:
            # 添加User-Agent头避免被拒绝
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            
            response = requests.get(api_url, headers=headers)
            if response.status_code == 200:
                # 解析JSON数据获取tag_name
                data = response.json()
                return data['tag_name']
            else:
                print(f"API请求失败，状态码：{response.status_code}")
                return "未获取到"
            
        except Exception as e:
            print(f"获取版本号时出错：{str(e)}，请确保你能访问gitHub.com再试。")
            return "未获取到"

    def show_version(self):
        """显示版本信息"""
        from version import show_version_info, get_version
        # 获取当前版本号
        current_version = get_version()
        version_info = show_version_info()
        # 获取最新版本号
        self.latest_version = self.get_latest_version()
        # 显示版本信息
        if current_version == self.latest_version:
            QMessageBox.information(self, "版本信息", f"当前版本: {version_info}\n最新版本: {self.latest_version}\n已是最新版本")
        elif self.latest_version == "未获取到":
            QMessageBox.information(self, "版本信息", f"当前版本: {version_info}\n最新版本: {self.latest_version}\n请确保你能访问gitHub.com再试。")
        else:
            # 弹出对话框，提示用户更新，可以选择更新或者不更新
            dialog = QDialog(self)
            dialog.setWindowTitle("版本管理")
            dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
            layout = QVBoxLayout()
            label = QLabel(f"当前版本: {current_version}\n最新版本: {self.latest_version}\n\n请及时更新")
            layout.addWidget(label)
            button = QPushButton("升级")
            button.clicked.connect(self.upgrade_program)
            layout.addWidget(button)
            dialog.setLayout(layout)
            dialog.exec_()

    def upgrade_program(self):
        """启动升级流程"""
        if not hasattr(self, 'latest_version') or not self.latest_version:
            QMessageBox.warning(self, "警告", "没有可用的更新版本")
            return
        
        self.logger.info(f"开始升级，新版本号为：{self.latest_version}")

        # 创建并启动升级线程
        self.upgrade_thread = UpgradeThread(self.latest_version)
        self.upgrade_thread.finished_signal.connect(self.handle_upgrade_finished)
        self.upgrade_thread.start()
        # 关闭对话框
        self.sender().parent().close()

    def handle_upgrade_finished(self, success, message):
        """统一处理完成信号"""
        # 确保只处理一次
        if not hasattr(self, '_processing_finish'):
            self._processing_finish = True
            
            # 显示最终结果
            if success:
                QMessageBox.information(self, "成功", message)
                self.restart_application()
            else:
                message = message + "\n请确保你能访问gitHub.com再试。"
                QMessageBox.critical(self, "失败", message)
            
            del self._processing_finish

    def cancel_upgrade(self):
        """安全取消升级"""
        if self.upgrade_thread and self.upgrade_thread.isRunning():
            # 禁用取消按钮防止重复点击
            self.progress_dialog.setCancelButtonText("正在取消...")
            self.progress_dialog.setCancelButton(None)
            
            # 发送中断请求
            self.upgrade_thread.requestInterruption()
            
            # 设置超时检测
            self.check_timer = QTimer(self)
            self.check_timer.timeout.connect(self.check_upgrade_status)
            self.check_timer.start(1000)  # 每秒检查一次

    def check_upgrade_status(self):
        """检查升级线程状态"""
        if not self.upgrade_thread.isRunning():
            self.check_timer.stop()
            QMessageBox.warning(self, "取消", "升级操作已中止")

    def show_setting(self):
        """显示设置参数"""
        # 打开一个窗口，显示两行内容，一行是：每笔交易最少金额，一行是：每天最多交易次数，分别可以输入正整数
        # 在主窗口中间打开对话框，
        dialog = QDialog(self)
        dialog.setWindowTitle("设置参数")
        dialog.setFixedSize(1000, 400)
        screen_center = self.geometry().center()
        dialog.move(screen_center - dialog.rect().center())
        layout = QVBoxLayout()
        
        # 每笔交易最少金额
        min_trade_amount_label = QLabel("每笔交易最少金额（单位：元）:（特殊情况如卖出时可用持仓不足该金额，会根据可用持仓计算交易数量）")
        self.min_trade_amount_input = QLineEdit()
        #设置输入框的大小为10个字符
        self.min_trade_amount_input.setFixedWidth(100)
        self.min_trade_amount_input.setValidator(QIntValidator())
        self.min_trade_amount_input.setText(str(self.min_trade_amount))
        layout.addWidget(min_trade_amount_label)
        layout.addWidget(self.min_trade_amount_input)
        
        # 回测时使用的波动阈值
        thresholds_label = QLabel("回测时使用的波动阈值:")
        self.thresholds_input = QLineEdit()
        #设置输入框的大小为10个字符
        self.thresholds_input.setFixedWidth(980)
        # 从字典param_grid中获取thresholds
        # 先把字符串转换为字典
        thresholds = self.param_grid['threshold']
        self.thresholds_input.setText(str(thresholds))
        layout.addWidget(thresholds_label)
        layout.addWidget(self.thresholds_input)

        #回测开始日期
        start_date_label = QLabel("回测开始日期（从下拉框中选择，只能选最近一个月以内的）:")
        self.start_date_input = QDateEdit()
        #设置输入框的大小为10个字符
        self.start_date_input.setFixedWidth(120)
        #限制只能从日历中选择日期，不能输入日期
        self.start_date_input.setCalendarPopup(True)

        start_date = self.start_date.toString("yyyy-MM-dd") if hasattr(self, 'start_date') else (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        self.start_date_input.setDate(datetime.strptime(start_date, '%Y-%m-%d').date())
        #限制不能选择今天以前一个月以前的日期
        self.start_date_input.setMinimumDate(datetime.now().date() - timedelta(days=30))
        #限制不能选择今天以后的日期
        self.start_date_input.setMaximumDate(datetime.now().date() - timedelta(days=0))
        layout.addWidget(start_date_label)
        layout.addWidget(self.start_date_input)

        #回测结束日期
        end_date_label = QLabel("回测结束日期（从下拉框中选择，只能选最近一个月以内的）:")
        self.end_date_input = QDateEdit()
        #设置输入框的大小为10个字符
        self.end_date_input.setFixedWidth(120)
        #限制只能从日历中选择日期，不能输入日期
        self.end_date_input.setCalendarPopup(True)
        end_date = self.end_date.toString("yyyy-MM-dd") if hasattr(self, 'end_date') else datetime.now().strftime('%Y-%m-%d')
        self.end_date_input.setDate(datetime.strptime(end_date, '%Y-%m-%d').date())
        #限制不能选择今天以前一个月以前的日期
        self.end_date_input.setMinimumDate(datetime.now().date() - timedelta(days=30))
        #限制不能选择今天以后的日期
        self.end_date_input.setMaximumDate(datetime.now().date() - timedelta(days=0))
        layout.addWidget(end_date_label)
        layout.addWidget(self.end_date_input)

        # 添加确定按钮
        ok_button = QPushButton("确定")
        ok_button.clicked.connect(self.save_setting)
        layout.addWidget(ok_button) 

        dialog.setLayout(layout)
        dialog.exec_()

    def save_setting(self):
        """保存设置"""
        try:
            start_date = self.start_date_input.date()
            end_date = self.end_date_input.date()
            if start_date > end_date:
                QMessageBox.warning(self, "警告", "回测开始日期不能大于回测结束日期")
                return
            self.start_date = start_date
            self.end_date = end_date
            print(f"回测开始日期: {self.start_date}, 回测结束日期: {self.end_date}")
            min_trade_amount = int(self.min_trade_amount_input.text())
            self.min_trade_amount = min_trade_amount
            thresholds = self.thresholds_input.text()
            self.param_grid = {}
            self.param_grid['threshold'] = thresholds
            self.param_grid['trade_size'] = '[100]' #此处的trade_size不需要改变，只是为了程序能支持多个参数的组合才保留下来
            self.logger.info(f"每笔交易最少金额: {self.min_trade_amount},波动阈值: {thresholds}")
            # 打开并读取现有配置文件
            config = configparser.ConfigParser()
            config_path = 'config.ini'
            
            # 检测文件编码
            with open(config_path, 'rb') as f:
                content = f.read()
                encoding = chardet.detect(content)['encoding']
            
            # 读取现有配置
            with open(config_path, 'r', encoding=encoding) as f:
                config.read_file(f)
            
            # 更新或添加设置部分
            if not config.has_section('setting'):
                config.add_section('setting')
            
            config.set('setting', 'min_trade_amount', str(self.min_trade_amount))
            print(self.param_grid)
            config.set('setting', 'param_grid', str(self.param_grid))

            # 保存配置（所有部分）
            with open(config_path, 'w', encoding=encoding) as f:
                config.write(f)
            
            QMessageBox.information(self, "成功", "设置已保存，将在下一次开始实盘或回测时生效。\n注意：\n1、如果当前已启动交易，需要先中止交易再重启交易方能生效。\n2、回撤起止日期只在本次程序中生效，重启程序将恢复初始的一个月的起止日期。")
            
            # 关闭对话框（正确的方式）
            self.sender().parent().close()
            
        except Exception as e:
            self.logger.error(f"保存设置失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"保存设置失败: {str(e)}")

    def on_stock_selected(self, stock_code):
        """当选择股票时"""
        try:
            # 获取可用数量
            available_position = self.engine.get_position(stock_code)
            # 设置为目标仓位的初始值
            self.engine.set_target_position(available_position)
            # 更新UI显示
            self.lineEdit_2.setValue(available_position)
            
        except Exception as e:
            self.logger.error(f"设置目标仓位出错: {str(e)}")

    def on_target_position_changed(self, value):
        """当目标仓位改变时"""
        try:
            self.engine.set_target_position(value)
        except Exception as e:
            self.logger.error(f"更新目标仓位出错: {str(e)}")

    def handle_uncaught_exception(self, exc_type, exc_value, exc_traceback):
        """全局异常捕获"""
        self.logger.error("未捕获异常", 
                        exc_info=(exc_type, exc_value, exc_traceback))
        QMessageBox.critical(self, "致命错误", 
                            f"未处理异常: {str(exc_value)}\n详细日志已记录")
        os._exit(1)  # 立即退出

    def check_trading_status(self):
        """检查交易状态"""
        if self.trading_thread:  # 只在交易启动时检查
            # 获取当前时间
            now = datetime.now()
            current_time = now.time()
            
            # 检查是否为交易日（周一到周五）
            is_trading_day = is_tradeday()
            
            # 检查是否在交易时段
            morning_start = datetime.strptime('09:30:00', '%H:%M:%S').time()
            morning_end = datetime.strptime('11:30:00', '%H:%M:%S').time()
            afternoon_start = datetime.strptime('13:00:00', '%H:%M:%S').time()
            afternoon_end = datetime.strptime('15:00:00', '%H:%M:%S').time()
            
            is_trading_hour = (
                (current_time >= morning_start and current_time <= morning_end) or  # 上午交易时段
                (current_time >= afternoon_start and current_time <= afternoon_end)  # 下午交易时段
            )
            
            # 只在交易日的交易时段内检查心跳
            if is_trading_day and is_trading_hour:
                # 检查是否收到心跳
                time_since_last_heartbeat = time.time() - self.last_trading_heartbeat
                
                # 如果超过60秒没有收到"交易中。。。"的心跳消息
                if time_since_last_heartbeat > 30:
                    self.logger.warning(f"检测到交易线程可能已停止 ({time_since_last_heartbeat:.1f}秒无心跳)，尝试重启...")
                    self.restart_trading()
                    self.last_trading_heartbeat = time.time()  # 更新心跳时间，否则可能一直重启
            else:
                self.last_trading_heartbeat = time.time() #否则交易时段一开始的时候就会重启


    def restart_trading(self):
        """重启交易"""
        try:
            # 先停止当前的交易线程
            if self.trading_thread:
                self.trading_thread.stop()
                self.trading_thread.wait()  # 等待线程结束
            
            # 重新创建并启动交易线程
            self.trading_thread = TradingThread(self.engine)
            self.trading_thread.start()
            
            self.logger.info("交易线程已重启")
            
        except Exception as e:
            self.logger.error(f"重启交易线程时出错: {str(e)}")

    def restart_application(self):
        """安全重启应用（处理特殊路径）"""
        QApplication.quit()
        
        # 获取当前执行文件的绝对路径（带双引号）
        main_file = f'"{os.path.abspath(sys.argv[0])}"'
        
        # 获取Python解释器路径（带双引号）
        python_exe = f'"{sys.executable}"'
        
        # 使用subprocess确保路径解析正确
        subprocess.Popen(f"{python_exe} {main_file}", shell=True)
        
        # 完全退出当前进程
        os._exit(0)

if __name__ == "__main__":
    # 设置Python环境的默认编码
    if sys.platform.startswith('win'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    app = QApplication([])
    window = LiveTradeWindow()
    # 查看有多少个同名程序已经开启
    current_pid = os.getpid()
    count = 0
    # 遍历所有进程
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            # 
            
            proc_info = proc.info
            
            # 如果是Python进程且运行的是当前脚本
            if (proc_info['pid'] != current_pid and  # 不是当前进程
                proc_info['name'] == 'python.exe' and # 是Python进程
                proc_info['cmdline'] and # 命令行参数存在
                'live_main.py' in proc_info['cmdline'][-1]): # 运行的是当前脚本
                
                count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    print(f"当前有{count}个同名程序已经开启")
    if count > 1:
        print(f"当前有{count}个同名程序已经开启")
        # 在屏幕中间向右下方（100，100）偏移
        screen_center = QApplication.primaryScreen().availableGeometry().center()
        window.move(screen_center.x() + 10*count, screen_center.y() + 10*count)
        window.show()
        app.exec_() 

    # 在屏幕中间显示
    screen_center = QApplication.primaryScreen().availableGeometry().center()
    window.move(screen_center - window.rect().center())
    window.show()
    app.exec_() 