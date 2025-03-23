import itertools
import pandas as pd
from tqdm import tqdm  # 进度条工具
from backtest_engine import BacktestEngine
from datetime import datetime
import numpy as np

class GridSearchOptimizer:
    """
    参数优化器
    
    使用示例：
    >>> param_grid = {'threshold': [0.001, 0.002]}
    >>> optimizer = GridSearchOptimizer(param_grid)
    >>> optimizer.optimize(data_source, strategy_class)
    """
    def __init__(self, param_grid):
        """
        param_grid示例：
        {
            'threshold': [0.001, 0.002, 0.003],
            'trade_size': [100, 200],
            'slippage': [0.0001, 0.0002]
        }
        """
        self.param_grid = param_grid
        self.results = []
    
    def generate_combinations(self):
        """生成所有参数组合"""
        keys = self.param_grid.keys()
        values = self.param_grid.values()
        return [dict(zip(keys, combo)) for combo in itertools.product(*values)]
    
    def optimize(self, data_source, strategy_class, metric='sharpe_ratio', progress_callback=None):
        """
        data_source: 统一数据接口
        strategy_class: 策略类（需符合引擎接口）
        param_grid: 参数网格字典
        """
        # 预处理并缓存公共数据
        processed_data = self._preprocess_dates(data_source)
        public_params = {
            'stock_code': processed_data['symbol'],
            'base_position': processed_data['base_position'],
            'can_use_position': processed_data['can_use_position'],
            'target_position': processed_data['target_position'],
            'avg_cost': processed_data['avg_cost'],
            'initial_capital': processed_data['capital'],
            'period': processed_data['period']
        }
        
        # 创建主引擎（只加载数据）
        master_engine = BacktestEngine(**public_params)
        if not master_engine.load_data(
            stock_code=processed_data['symbol'],
            start_date=processed_data['start'],
            end_date=processed_data['end'],
            period=processed_data['period']
        ):
            raise ValueError("数据加载失败")
        
        # 深拷贝基础数据
        base_data = master_engine.data.copy(deep=True)
        count = 0
        for params in self.generate_combinations():
            # 创建新引擎时复制数据
            new_engine = BacktestEngine(**public_params)
            new_engine.data = base_data.copy(deep=True)  # 创建独立副本
            
            # 确保策略初始化不会修改数据
            strategy = strategy_class(new_engine, **params)
            new_engine.set_strategy(strategy)
            
            # 执行回测
            new_engine.run_backtest()
            
            # 收集结果
            result = new_engine.get_results()
            result.update({'params': params})
            
            # 获取结果时使用指定指标
            current_metric = result.get(metric)
            
            if current_metric is None:
                raise ValueError(f"指标{metric}不存在于回测结果中，可用指标：{list(result.keys())}")
                
            # 记录时包含所有指标但使用指定指标排序
            record = {
                'params': params,
                metric: current_metric,
                **{k:v for k,v in result.items() if k != metric}
            }
            self.results.append(record)
            
            # 重置引擎
            new_engine.reset()

            '''returns_list = new_engine._get_daily_returns()
            # 添加调试
            print(f"\n参数: {params}")
            print(f"夏普: {result['sharpe_ratio']:.2f}")
            print("收益率统计:")
            print("数量:", len(returns_list))
            print("均值:", np.mean(returns_list))'''
            
            #sharpe = new_engine._calculate_sharpe()  # 必须调用

            count += 1
            if progress_callback:
                progress_callback(count, len(self.generate_combinations()))
        
        # 按指定指标排序
        results_df = pd.DataFrame(self.results).sort_values(metric, ascending=False)

        # 重置索引确保顺序正确
        results_df = results_df.reset_index(drop=True)

        # 修改这里：只将第一个最高值标记为最佳
        # 首先将所有行设置为False
        results_df['是否最佳'] = False
        
        # 只将第一个最高值标记为最佳
        if not results_df.empty:
            # 确保metric列是数值类型
            results_df[metric] = pd.to_numeric(results_df[metric], errors='coerce')
            
            # 检查是否有非NA值
            if not results_df[metric].isna().all():
                # 只将第一个最高值标记为最佳
                best_idx = results_df[metric].idxmax()
                results_df.loc[best_idx, '是否最佳'] = True

        return results_df

    def _preprocess_dates(self, data_source):
        """日期格式预处理"""
        processed = data_source.copy()
        
        # 转换开始日期
        if isinstance(processed['start'], str):
            processed['start'] = datetime.strptime(processed['start'], "%Y-%m-%d")
            
        # 转换结束日期
        if isinstance(processed['end'], str):
            processed['end'] = datetime.strptime(processed['end'], "%Y-%m-%d")
            
        # 确保包含period参数
        if 'period' not in processed:
            processed['period'] = 'tick'  # 默认值
        
        return processed 

    def _calculate_metrics(self, engine):
        """直接使用engine.trades进行计算"""
        trades = engine.trades  # 直接访问原有属性
        
        if not trades:
            return {
                'total_return': 0.0,
                'sharpe_ratio': 0.0,
                'max_drawdown': 0.0,
                'win_rate': 0.0
            }
        
        # 后续计算逻辑保持不变...
        # 使用trades代替trade_log
        returns = pd.Series([t['pnl']/engine.initial_capital for t in trades])
        # ...其他计算... 