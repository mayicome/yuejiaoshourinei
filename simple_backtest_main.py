import warnings
import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QMessageBox, 
                            QTableWidgetItem, QComboBox, QTableWidget)
from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import QDate, QThread, pyqtSignal
from backtest_ui import Ui_MainWindow
import pandas as pd
from datetime import datetime, timedelta
from xtquant import xtdata  # 导入xtquant库中的xtdata模块，用于获取市场数据
import time
from backtest_engine import BacktestEngine
from adaptive_limit_strategy import AdaptiveLimitStrategy
from order_book_strategy import OrderBookStrategy
# 导入其他策略类（后续添加）
from PyQt5.QtGui import QColor
import numpy as np
import logging
import os
from PyQt5.QtWidgets import QAction

# 在程序开始时忽略特定警告
warnings.filterwarnings("ignore", category=DeprecationWarning)

# 禁用Hello消息
xtdata.enable_hello = False

#将股票代码转换为QMT识别的格式
def symbol2stock(symbol):
    if symbol.startswith("0") or symbol.startswith("3"):
        stock = symbol+".SZ"
    elif symbol.startswith("6"):
        stock = symbol+".SH"
    else:
        stock = symbol+".BJ"
    return stock

def setup_logger():
    """设置主程序日志"""
    logger = logging.getLogger('Backtest')
    
    # 如果logger已经配置过，直接返回
    if logger.handlers:
        return logger
        
    logger.setLevel(logging.INFO)
    
    # 创建logs目录（如果不存在）
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 生成日志文件名（使用当前日期）
    log_file = os.path.join(log_dir, f"backtest_{datetime.now().strftime('%Y%m%d')}.log")
    
    # 添加文件处理器
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # 添加控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    return logger

class BacktestWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.backtest_thread = None
        
        # 初始化日志
        self.logger = setup_logger()
        
        # 初始化界面
        self.init_ui()
        
        # 连接信号和槽
        self.connect_signals()
        
    def init_ui(self):
        """初始化用户界面"""
        try:
            # 设置日期范围
            # 设置起始日期为昨天
            thedaybeforeyesterday = QDate.currentDate().addDays(-30)
            self.ui.dateEdit.setDate(thedaybeforeyesterday)
            yesterday = QDate.currentDate().addDays(-1)
            self.ui.dateEdit_2.setDate(yesterday)
            
            # 设置策略选择下拉框
            self.ui.comboBox.addItem("浮动限价策略", "adaptive_limit")
            self.ui.comboBox.addItem("盘口动量增强策略", "order_book")
            self.ui.comboBox.addItem("事件驱动套利策略", "event_driven")
        
            # 设置周期选择下拉框
            self.ui.comboBox_2.clear()  # 先清空已有项
            periods = [
                ("逐笔", "tick"),
                ("1分钟", "1m"),
                ("5分钟", "5m"),
                ("15分钟", "15m"),
                ("30分钟", "30m"),
                ("60分钟", "60m")
            ]
            for display_text, value in periods:
                self.ui.comboBox_2.addItem(display_text, value)
            
            # 添加导出按钮
            self.ui.exportButton = QtWidgets.QPushButton(self.ui.centralwidget)
            self.ui.exportButton.setText("导出结果")
            self.ui.exportButton.setEnabled(False)  # 初始时禁用
            # 将按钮添加到现有布局中
            self.ui.verticalLayout.addWidget(self.ui.exportButton)
            
            # 设置表格
            self.setup_trade_table()
            
            # 添加帮助菜单
            menubar = self.menuBar()
            help_menu = menubar.addMenu('帮助')
            
            # 添加版本信息动作
            version_action = QAction('版本信息', self)
            version_action.triggered.connect(self.show_version)
            help_menu.addAction(version_action)
            
        except Exception as e:
            self.logger.error(f"界面初始化失败: {str(e)}")

    def setup_trade_table(self):
        """设置交易记录表格"""
        # 设置列标题和宽度
        headers = ['时间', '股票代码', '交易类型', '价格', '交易数量', '手续费', '交易后持仓', '交易后可用持仓']
        self.ui.tableWidget.setColumnCount(len(headers))
        self.ui.tableWidget.setHorizontalHeaderLabels(headers)
        
        # 设置列宽
        self.ui.tableWidget.setColumnWidth(0, 150)  # 时间列
        self.ui.tableWidget.setColumnWidth(1, 80)   # 股票代码列
        self.ui.tableWidget.setColumnWidth(2, 80)   # 交易类型列
        self.ui.tableWidget.setColumnWidth(3, 80)   # 价格列
        self.ui.tableWidget.setColumnWidth(4, 80)   # 数量列
        self.ui.tableWidget.setColumnWidth(5, 80)   # 手续费列
        self.ui.tableWidget.setColumnWidth(6, 80)   # 持仓列
        self.ui.tableWidget.setColumnWidth(7, 80)   # 可用持仓列
        

        # 设置表格样式
        self.ui.tableWidget.setAlternatingRowColors(True)  # 交替行颜色
        self.ui.tableWidget.setSortingEnabled(True)        # 允许排序
        self.ui.tableWidget.setEditTriggers(QTableWidget.NoEditTriggers)  # 禁止编辑

    def connect_signals(self):
        """连接信号和槽"""
        try:
            self.ui.pushButton.clicked.connect(self.start_backtest)
            
            # 连接导出按钮
            self.ui.exportButton.clicked.connect(self.export_results)
            
        except Exception as e:
            self.logger.error(f"信号连接失败: {str(e)}")

    def start_backtest(self):
        """开始回测"""
        #try:
        if True:
            # 清空结果显示
            self.ui.tableWidget.setRowCount(0)
            self.ui.textEdit.clear()
            
            # 禁用按钮
            self.ui.pushButton.setEnabled(False)
            self.ui.exportButton.setEnabled(False)
            
            # 获取输入参数
            stock_code = self.ui.lineEdit.text().strip()
            start_date = self.ui.dateEdit.date().toPyDate()
            end_date = self.ui.dateEdit_2.date().toPyDate()
            base_position = int(self.ui.lineEdit_2.text() or "0")
            initial_capital = int(self.ui.lineEdit_3.text() or "1000000")
            avg_cost = float(self.ui.lineEdit_4.text() or "0")
            self.initial_threshold_everyday = float(self.ui.lineEdit_5.text() or "0.004")
            strategy_type = self.ui.comboBox.currentData()
            current_index = self.ui.comboBox_2.currentIndex()
            period = self.ui.comboBox_2.itemData(current_index)
            
            # 参数验证
            if not stock_code:
                QMessageBox.warning(self, "警告", "请输入股票代码")
                return
                
            if start_date > end_date:
                QMessageBox.warning(self, "警告", "开始日期必须早于结束日期")
                return
                
            if initial_capital <= 0:
                QMessageBox.warning(self, "警告", "可用资金必须大于0")
                return
                
            if base_position > 0 and avg_cost <= 0:
                QMessageBox.warning(self, "警告", "有底仓时平均成本必须大于0")
                return
            
            # 创建回测引擎
            self.engine = BacktestEngine(stock_code, base_position, avg_cost, initial_capital=initial_capital)
            self.engine.on_trade = self.on_trade  # 设置成交回调
            self.logger.info("开始回测")
            
            strategy_type = self.ui.comboBox.currentData()
            
            # 创建策略
            if strategy_type == "adaptive_limit":
                self.strategy = AdaptiveLimitStrategy(self.engine, threshold=self.initial_threshold_everyday, trade_size=100, logger=self.logger)
            elif strategy_type == "order_book":
                self.strategy = OrderBookStrategy(self.engine, bid_vol_threshold=500, ask_vol_threshold=300, logger=self.logger)
            
            # 设置策略
            self.engine.set_strategy(self.strategy)
            
            # 加载数据
            if not self.engine.load_data(stock_code, start_date, end_date, period=period):
                QMessageBox.critical(self, "错误", "加载历史数据失败")
                # 启用按钮
                self.ui.pushButton.setEnabled(True)
                self.ui.exportButton.setEnabled(True)
                return
            # 运行回测
            self.engine.run_backtest()
            
            # 发送最终结果
            results = self.engine.get_results()
            if results:
                self.show_final_results(results)
                # 启用按钮
                self.ui.pushButton.setEnabled(True)
                self.ui.exportButton.setEnabled(True)
            
        #except Exception as e:
        #    self.logger.error(f"回测过程中出错：{str(e)}")
        #    # 出错时也要启用按钮
        #    self.ui.pushButton.setEnabled(True)
        #    self.ui.exportButton.setEnabled(True)
        #    QMessageBox.critical(self, "错误", str(e))
            
    def on_trade_update(self, trades):
        """处理交易更新"""
        self.backtest_thread.update_trade.emit(trades)

    def show_final_results(self, results):
        """显示最终回测结果"""
        print(f"results: {results}")
        '''try:
            # 计算额外的统计指标
            total_trades = results['total_trades']
            winning_trades = results.get('winning_trades', 0)
            losing_trades = total_trades - winning_trades
            
            diff_volume = results['final_volume'] - results['initial_volume']
            diff_price = results['final_price'] - results['initial_price']
            diff_market_value = diff_volume * diff_price            # 格式化结果显示
            static_asset = results['initial_volume'] * results['final_price'] + results['initial_capital']
            result_text = (
                "====== 回测结果汇总 ======\n\n"
                f"策略类型: {self.ui.comboBox.currentText()}\n"
                f"回测周期: {self.ui.comboBox_2.currentText()}\n"
                f"回测区间: {self.ui.dateEdit.date().toString('yyyy-MM-dd')} 至 "
                f"{self.ui.dateEdit_2.date().toString('yyyy-MM-dd')}\n"
                f"波动阈值: {self.initial_threshold_everyday:.2%}\n\n"
                
                "====== 资金统计 ======\n"
                f"初始资金: {results['initial_capital']:,.2f}\n"                
                f"初始持仓数量: {results['initial_volume']}\n"
                f"初始持仓价格: {results['initial_price']:.3f}\n"
                f"初始持仓市值: {results['initial_market_value']:,.2f}\n"
                f"初始总资产: {results['initial_asset']:,.2f}\n"
                f"最终资金: {results['final_capital']:,.2f}\n"
                f"最终持仓数量: {results['final_volume']}\n"
                f"最终持仓价格: {results['final_price']:.3f}\n"
                f"最终持仓市值: {results['final_market_value']:,.2f}\n"
                f"最终总资产: {results['final_asset']:,.2f}\n\n"
                
                "====== 收益统计 ======\n"
                f"总交易次数: {total_trades}\n"
                #f"总收益率: {results['total_returns']:.2%}\n"
                f"持仓不动的总资产: {round(static_asset, 2)}\n"
                f"日内交易在此基础上增加的收益: {round(results['final_asset']-static_asset, 2)}\n"
                f"日内交易增加的收益率为: {(results['final_asset']-static_asset)/static_asset:.2%}\n"                
            )
            
            if 'max_drawdown' in results:
                result_text += f"最大回撤: {results['max_drawdown']:.2%}\n"
            
            if 'sharpe_ratio' in results:
                result_text += f"夏普比率: {results['sharpe_ratio']:.2f}\n"
            
            self.ui.textEdit.setText(result_text)
            self.logger.info("回测结果显示完成")
            
        except Exception as e:
            self.logger.error(f"显示回测结果失败: {str(e)}")
            QMessageBox.warning(self, "警告", f"显示回测结果时出错: {str(e)}")'''
        
    def show_error(self, error_msg):
        """显示错误信息"""
        QMessageBox.critical(self, "错误", error_msg)
        
    def on_backtest_finished(self):
        """回测完成后的处理"""
        self.ui.pushButton.setEnabled(True)
        self.ui.exportButton.setEnabled(True)  # 启用导出按钮
        self.logger.info("回测完成")

    def update_trade_table(self, trade):
        """更新交易记录表格"""
        try:
            current_row = self.ui.tableWidget.rowCount()
            self.ui.tableWidget.insertRow(current_row)
            
            # 处理时间
            '''if isinstance(trade['time'], pd.Series):
                # 从科学计数法格式的时间戳转换为正常时间
                time_value = float(trade['time']['time'])  # 获取时间值
                time_str = f"{time_value:.0f}"  # 转换为整数字符串
                # 提取年月日时分秒
                year = int(time_str[:4])
                month = int(time_str[4:6])
                day = int(time_str[6:8])
                hour = int(time_str[8:10])
                minute = int(time_str[10:12])
                second = int(time_str[12:14])
                time_str = f"{year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"
            else:
                time_str = self.format_trade_time(trade['time'])'''
            print(f"trade['time']: {trade['time']}")
            # 添加交易记录
            self.ui.tableWidget.setItem(current_row, 0, QTableWidgetItem(str(trade['time'])))
            self.ui.tableWidget.setItem(current_row, 1, QTableWidgetItem(str(trade['stock_code'])))
            direct = '买入' if trade['direction'] == 'buy' else '卖出'
            self.ui.tableWidget.setItem(current_row, 2, QTableWidgetItem(direct))
            self.ui.tableWidget.setItem(current_row, 3, QTableWidgetItem(f"{float(trade['price']):.3f}"))
            self.ui.tableWidget.setItem(current_row, 4, QTableWidgetItem(str(trade['volume'])))
            
            # 计算并显示总费用
            if trade['direction'] == 'buy':
                total_fee = trade['commission']
            else:  # sell
                total_fee = trade['commission'] + trade['stamp_duty']
            self.ui.tableWidget.setItem(current_row, 5, QTableWidgetItem(f"{total_fee:.2f}"))

            self.ui.tableWidget.setItem(current_row, 6, QTableWidgetItem(str(trade['volume_after_trade'])))
            self.ui.tableWidget.setItem(current_row, 7, QTableWidgetItem(str(trade['can_use_volume_after_trade'])))
            
            # 设置颜色
            color = QtGui.QColor(255, 182, 193) if trade['direction'] == 'buy' else QtGui.QColor(144, 238, 144)
            for col in range(8):
                self.ui.tableWidget.item(current_row, col).setBackground(color)
            
            # 滚动到最新记录
            self.ui.tableWidget.scrollToBottom()
            
        except Exception as e:
            self.logger.error(f"更新交易记录表格失败: {str(e)}, 详细信息: {trade}")

    def format_trade_time(self, trade_time):
        """格式化交易时间"""
        try:
            if isinstance(trade_time, pd.Timestamp):
                return trade_time.strftime('%Y-%m-%d %H:%M:%S.%f')
            elif isinstance(trade_time, str):
                try:
                    # 处理带微秒的时间格式（最多支持6位小数）
                    if '.' in trade_time:
                        dt_str, micro = trade_time.split('.')
                        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                        return f"{dt.strftime('%Y-%m-%d %H:%M:%S')}.{micro[:6]}"
                    else:
                        return datetime.strptime(trade_time, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
                except ValueError:
                    return trade_time
            elif isinstance(trade_time, (int, float)):
                # 处理时间戳格式（假设是纳秒级时间戳）
                dt = datetime.fromtimestamp(trade_time / 1e9)
                return dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]  # 保留微秒
            return str(trade_time)
        except Exception as e:
            self.logger.error(f"时间格式化失败: {str(e)}")
            return str(trade_time)

    def on_trade(self, trade):
        """处理成交回报"""
        self.logger.info(f"收到成交记录：{trade}")
        self.update_trade_table(trade)

    def show_version(self):
        """显示版本信息"""
        from version import show_version_info
        QMessageBox.information(self, "版本信息", show_version_info())

    def export_results(self):
        """导出回测结果"""
        try:
            # 获取保存路径
            default_filename = f"回测结果_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            filename, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "导出回测结果",
                default_filename,
                "Excel文件 (*.xlsx);;CSV文件 (*.csv)"
            )
            
            if not filename:
                return
                
            # 准备交易记录数据
            trades_data = []
            for row in range(self.ui.tableWidget.rowCount()):
                trade = {
                    '时间': self.ui.tableWidget.item(row, 0).text(),
                    '股票代码': self.ui.tableWidget.item(row, 1).text(),
                    '交易类型': self.ui.tableWidget.item(row, 2).text(),
                    '价格': float(self.ui.tableWidget.item(row, 3).text()),
                    '数量': int(self.ui.tableWidget.item(row, 4).text()),
                    '手续费': float(self.ui.tableWidget.item(row, 5).text())
                }
                trades_data.append(trade)
            
            # 创建交易记录DataFrame
            trades_df = pd.DataFrame(trades_data)
            
            # 获取回测结果文本
            results_text = self.ui.textEdit.toPlainText()
            
            # 根据文件类型导出
            if filename.endswith('.xlsx'):
                with pd.ExcelWriter(filename) as writer:
                    trades_df.to_excel(writer, sheet_name='交易记录', index=False)
                    # 将回测结果文本转换为DataFrame
                    results_lines = results_text.split('\n')
                    results_data = []
                    for line in results_lines:
                        if ':' in line:
                            key, value = line.split(':', 1)
                            results_data.append({'指标': key.strip(), '值': value.strip()})
                    results_df = pd.DataFrame(results_data)
                    results_df.to_excel(writer, sheet_name='回测统计', index=False)
            else:  # CSV
                trades_df.to_csv(filename, index=False, encoding='utf-8-sig')
                # 导出回测结果为单独的文本文件
                results_filename = filename.rsplit('.', 1)[0] + '_统计.txt'
                with open(results_filename, 'w', encoding='utf-8') as f:
                    f.write(results_text)
            
            QMessageBox.information(self, "成功", "回测结果导出成功！")
            
        except Exception as e:
            self.logger.error(f"导出结果失败: {str(e)}")
            QMessageBox.warning(self, "错误", f"导出结果失败: {str(e)}")

class BacktestThread(QThread):
    # 定义信号
    update_trade = pyqtSignal(list)  # 更新交易记录
    update_result = pyqtSignal(dict)  # 更新回测结果
    finished = pyqtSignal()  # 回测完成
    error = pyqtSignal(str)  # 错误信息
    
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.strategy = engine.strategy
        self.engine.set_strategy(self.strategy)
        
    def run(self):
        #try:
        if True:
            if self.engine.run_backtest():
                # 发送最终结果
                results = self.engine.get_results()
                if results:
                    self.update_result.emit(results)
            else:
                self.error.emit("回测执行失败")
        #except Exception as e:
        #    self.error.emit(str(e))
        #finally:
        #    self.finished.emit()

def main():
    app = QApplication(sys.argv)
    window = BacktestWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main() 