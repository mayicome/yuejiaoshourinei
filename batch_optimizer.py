import concurrent.futures
from optimization_runner import run_optimization
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import re
import time
import openpyxl
import argparse  # 新增：导入argparse模块
import configparser
import chardet

def safe_filename(symbol):
    """生成安全文件名"""
    # 移除非法字符
    clean = re.sub(r'[\\/*?:"<>|]', '', symbol)
    # 截断长度
    return clean[:50]

def process_stock(row, param_grid, progress_callback=None):
    symbol = row['symbol']
    def internal_callback(current, total):
        if progress_callback:
            progress_callback(current, total)
    try:        
        # 合并数据加载和优化       
        results = run_optimization({
            'symbol': row['symbol'],
            'start': row['start'],
            'end': row['end'],
            'period': 'tick',
            'base_position': int(row['base_position']),  # 确保类型正确
            'can_use_position': int(row['can_use_position']),
            'target_position': int(row['target_position']),
            'avg_cost': float(row['avg_cost']),
            'capital': float(row['capital'])
        }, param_grid, internal_callback)

        # 处理可能的空结果或全NA结果
        if isinstance(results, pd.DataFrame) and results.empty:
            print(f"{row['symbol']} 优化结果为空")
            return pd.DataFrame()
            
        # 如果结果中有NA值，确保idxmax不会引发警告
        if isinstance(results, pd.Series) and results.isna().all():
            print(f"{row['symbol']} 优化结果全为NA")
            return pd.DataFrame()
        
        return results
    except Exception as e:
        import traceback
        print(f"处理 {symbol} 时发生错误: {str(e)}")
        print(f"错误详情: {traceback.format_exc()}")
        return pd.DataFrame()

def save_result(result, symbol, output_dir="results"):
    """保存优化结果并返回最佳记录"""
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    path = os.path.join(output_dir, f"{safe_filename(symbol)}_result.xlsx")

    #把result_df的列名转换为中文
    result.columns = ['参数', '夏普比率', '总收益', '最大回撤', '回撤波峰时间', '回撤波谷时间', '胜率', '总交易天数', '最小交易次数', '最大交易次数', '总交易次数', '平均每日交易次数', '是否最佳']
        

    # 保存单个结果文件
    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        result.to_excel(writer, index=False)
        
    print(f"成功保存 {symbol} 到 {path}")
    
    # 返回最佳参数记录
    best_record = result[result['是否最佳'] == True]
    if not best_record.empty:
        best_record.insert(0, '股票代码', symbol)  # 添加股票代码列
        return best_record
    return pd.DataFrame()
    
    #except Exception as e:
    #    print(f"保存 {symbol} 失败: {str(e)}")
    #    return pd.DataFrame()

#将股票代码转换为QMT识别的格式
def symbol2stock(symbol):
    #如果symbol是整形，转换成字符型
    if isinstance(symbol, int):
        symbol = str(symbol)
    #如果symbol的长度不足6位，前面补零
    if len(symbol) < 6:
        symbol = symbol.zfill(6)
    #如果symbol的长度大于6位直接返回
    if len(symbol) > 6:
        return symbol
    #如果symbol以0或3开头，转换为深市股票
    if symbol.startswith("0") or symbol.startswith("3"):
        stock = symbol+".SZ"
    #如果symbol以6开头，转换为沪市股票
    elif symbol.startswith("6"):
        stock = symbol+".SH"
    #如果symbol以9开头，转换为北交所股票
    elif symbol.startswith("9"):
        stock = symbol+".BJ"
    return stock

def read_config(config_path):
    """读取配置文件，自动检测编码"""
    config = configparser.ConfigParser()
    
    # 检测文件编码
    with open(config_path, 'rb') as f:
        result = chardet.detect(f.read())
    
    # 使用检测到的编码打开文件
    with open(config_path, 'r', encoding=result['encoding']) as f:
        config.read_file(f)
    
    return config

def read_stocks(input_file):
    # 读取Excel文件
    try:
        stocks = pd.DataFrame()
        stocks_read = pd.read_excel(input_file, engine='openpyxl')
    except Exception as e:
        print(f"读取文件失败: {str(e)}")
        return
        
    #如果stocks没有代码列，则报错
    if '代码' not in stocks_read.columns:
        raise ValueError("文件中必须有代码列")
    stocks['symbol'] = stocks_read['代码'].apply(symbol2stock)

    if '起始日期' in stocks_read.columns:
        stocks['start'] = stocks_read['起始日期']
    else:
        stocks['start'] = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    if '结束日期' in stocks_read.columns:
        stocks['end'] = stocks_read['结束日期']
    else:
        stocks['end'] = (datetime.now() - timedelta(days=0)).strftime('%Y-%m-%d')
    if '基础仓位' in stocks_read.columns:
        stocks['base_position'] = stocks_read['基础仓位']
    else:
        stocks['base_position'] = 10000
    if '可用仓位' in stocks_read.columns:
        stocks['can_use_position'] = stocks_read['可用仓位']
    else:
        stocks['can_use_position'] = 10000
    if '目标仓位' in stocks_read.columns:
        stocks['target_position'] = stocks_read['目标仓位']
    else:
        stocks['target_position'] = 10000
    if '平均成本' in stocks_read.columns:
        stocks['avg_cost'] = stocks_read['平均成本']
    elif '收盘价' in stocks_read.columns:
        stocks['avg_cost'] = stocks_read['收盘价']
    else:
        stocks['avg_cost'] = 10.00
    if '初始可用资金' in stocks_read.columns:
        stocks['capital'] = stocks_read['初始可用资金']
    else:
        stocks['capital'] = 100000
    return stocks

def read_param_grid(param_file):
    """读取参数文件"""
    # 读取参数文件
    if param_file:
        try:
            config = read_config(param_file)
            param_grid = config.get('setting', 'param_grid')
            #如果param_grid是字符串，则转换为字典
            if isinstance(param_grid, str):
                param_grid = eval(param_grid)
            param_grid['trade_size'] = [100]
            #将param_grid['threshold']转换为列表
            if isinstance(param_grid['threshold'], str):
                param_grid['threshold'] = eval(param_grid['threshold'])
            #将param_grid['threshold']列表内的每个元素转换成浮点数
            param_grid['threshold'] = [float(x) for x in param_grid['threshold']]

            print(f"参数网格: {param_grid}")
        except Exception as e:
            print(f"读取参数文件失败: {str(e)}")
    else:
        param_grid = {
            'threshold': [0, 0.001, 0.002, 0.003, 0.004, 0.005, 0.006, 0.007, 0.008, 0.009, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 1],
            'trade_size': [100]
        }
    return param_grid

def batch_optimize(input_file=None, param_file=None, output_dir=None, progress_callback=None):
    """批量优化处理函数，支持自定义输入和输出路径"""
    # 设置默认值
    if input_file is None:
        input_file = 'config/stocks.xlsx'
    if output_dir is None:
        output_dir = 'results'
    
    print(f"输入文件: {input_file}")
    print(f"参数文件: {param_file}")
    print(f"输出目录: {output_dir}")
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    #读取股票列表
    stocks = read_stocks(input_file)
    #读取参数文件
    param_grid = read_param_grid(param_file)
    
    start_time = time.time()
    success_count = 0
    failed_count = 0
    summary_data = []  # 用于收集汇总数据

    with concurrent.futures.ProcessPoolExecutor() as executor:
        futures = {}
        for _, row in stocks.iterrows():
            future = executor.submit(
                process_stock, 
                row.to_dict(),
                param_grid,
                progress_callback
            )
            futures[future] = row['symbol']
            print(f"已提交 {row['symbol']}")
        
        for future in concurrent.futures.as_completed(futures):
            symbol = futures[future]
            try:
                result = future.result()
                # 保存结果并获取最佳记录
                best_record = save_result(result, symbol, output_dir)
                if not best_record.empty:
                    summary_data.append(best_record)
                success_count += 1
            except Exception as e:
                print(f"{symbol} 失败: {str(e)}")
                failed_count += 1
            finally:
                print(f"进度: {success_count+failed_count}/{len(stocks)}")
            
    # 保存汇总文件
    if summary_data:
        try:
            summary_df = pd.concat(summary_data, ignore_index=True)
            summary_path = os.path.join(output_dir, f"最优夏普比率汇总_{datetime.now().strftime('%Y%m%d')}.xlsx")
            with pd.ExcelWriter(summary_path, engine='openpyxl') as writer:
                summary_df.to_excel(writer, index=False)
            print(f"成功生成汇总文件：{summary_path}")
        except Exception as e:
            print(f"生成汇总文件失败: {str(e)}")
    else:
        print("没有生成汇总文件")

    print(f"总耗时: {time.time()-start_time:.1f}秒")
    print(f"成功: {success_count}, 失败: {failed_count}")

def batch_optimize_single_process(input_file, param_file, output_dir=None, progress_callback=None):
    """
    批量优化函数 - 单进程版本
    对于UI应用程序使用，避免多进程序列化问题
    
    Args:
        input_file: 输入Excel文件路径
        param_file: 参数配置文件路径
        output_dir: 输出目录，默认为输入文件所在目录
        progress_callback: 进度回调函数，接受current和total两个参数
    """
    # 设置默认值
    if input_file is None:
        input_file = 'config/stocks.xlsx'
    if output_dir is None:
        output_dir = 'results'
    
    print(f"输入文件: {input_file}")
    print(f"参数文件: {param_file}")
    print(f"输出目录: {output_dir}")
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    #读取股票列表
    stocks = read_stocks(input_file)

    row = stocks.iloc[0]
    
    #读取参数文件
    param_grid = read_param_grid(param_file)

    # 单线程处理每只股票
    if True:
        symbol = row['symbol']
        #print("row:",row)
        config = {
                'symbol': str(symbol),  # 确保是字符串标量
                'start': str(row['start']),
                'end': str(row['end']),
                'base_position': int(row['base_position']),
                'can_use_position': int(row['can_use_position']),
                'target_position': int(row['target_position']),
                'avg_cost': float(row['avg_cost']),
                'capital': float(row['capital']),
                'period': 'tick'
            }
        try:
            from optimization_runner import run_optimization
            results = run_optimization(config, param_grid,progress_callback)
            
            # 处理结果
            output_file = os.path.join(output_dir, f"optimizer_result_{symbol.split('.')[0]}.xlsx")
            results.to_excel(output_file, index=False)
            print(f"结果已保存到 {output_file}")
            
        except Exception as e:
            print(f"{symbol} 失败: {str(e)}")
        
        # 更新进度
        if progress_callback:
            progress_callback(1, 1)
        
        print(f"进度: 1/1")

if __name__ == '__main__':
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description='批量优化股票交易策略')
    parser.add_argument('--input', '-i', type=str, help='输入Excel文件的绝对路径')
    parser.add_argument('--param_file', '-p', type=str, help='参数文件的绝对路径')
    parser.add_argument('--output', '-o', type=str, help='输出目录的绝对路径')
    
    # 解析命令行参数
    args = parser.parse_args()
    
    # 调用批量优化函数，传入命令行参数
    batch_optimize(input_file=args.input, param_file=args.param_file, output_dir=args.output) 