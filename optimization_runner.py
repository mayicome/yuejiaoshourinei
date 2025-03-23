# optimization_runner.py
import pandas as pd
from param_optimizer import GridSearchOptimizer
from backtest_engine import BacktestEngine
from adaptive_limit_strategy import AdaptiveLimitStrategy  # 替换为你的策略类
import logging
import os
import sys
from datetime import datetime
import numpy as np

# 配置数据源
data_config = {
    'symbol': '002836.SZ',
    'start': '2025-02-04',
    'end': '2025-03-03',
    'period': 'tick',
    'base_position': 10000,
    'avg_cost': 8.00,
    'capital': 100000
}

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
    log_file = os.path.join(log_dir, f"optimization_{datetime.now().strftime('%Y%m%d')}.log")
    
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

def run_optimization(data_config, param_grid,progress_callback=None):
    """执行单个优化任务"""
    # 加载数据
    data = {
        'symbol': data_config['symbol'],
        'start': data_config['start'],
        'end': data_config['end'],
        'period': 'tick',
        'base_position': data_config['base_position'],
        'can_use_position': data_config['can_use_position'],
        'target_position': data_config['target_position'],
        'avg_cost': data_config['avg_cost'],
        'capital': data_config['capital']
    }
    
    # 初始化优化器和策略
    optimizer = GridSearchOptimizer(param_grid)
    # 显示开始处理
    if progress_callback:
        progress_callback(0, len(param_grid['threshold']))
    results_df = optimizer.optimize(data, AdaptiveLimitStrategy, progress_callback=progress_callback)
    
    return results_df

def save_results(results, symbol):
    """保存优化结果"""
    os.makedirs('results', exist_ok=True)
    path = f'results/optimization_{symbol}.csv'
    results.to_csv(path, index=False)
    print(f"已保存 {symbol} 优化结果至 {path}")

if __name__ == "__main__":
    # 初始化日志
    logger = setup_logger()
    # 初始化优化器
    optimizer = GridSearchOptimizer(param_grid=param_grid)
    
    # 执行优化（接收两个返回值）
    results_df = optimizer.optimize(
        data_source=data_config,
        strategy_class=AdaptiveLimitStrategy,  
        metric='sharpe_ratio'
    )
    
    # 保存结果（使用DataFrame）
    results_df.to_csv('optimization_results.csv', index=False)
    
    # 显示最佳参数（调整访问方式）
    print("\n=== 最佳参数组合 ===")
    print(f"夏普比率: {results_df['sharpe_ratio'].max():.2f}") 
    print("参数配置:")
    for k, v in results_df.iloc[results_df['sharpe_ratio'].idxmax()].items(): 
        if k != 'sharpe_ratio':
            print(f"  {k}: {v}")

