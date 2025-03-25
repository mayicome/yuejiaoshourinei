import pandas as pd
import numpy as np
import datetime

class DrawdownCalculator:
    """回撤计算工具类"""
    
    @staticmethod
    def calculate_drawdown(equity_curve):
        """
        计算最大回撤及其发生时间
        
        Args:
            equity_curve: 权益曲线，可以是列表或pandas Series
            
        Returns:
            dict: 包含最大回撤值、波峰时间和波谷时间的字典
        """
        # 检查equity_curve是否为None或空
        if equity_curve is None:
            print("警告: equity_curve 为 None")
            return {'max_drawdown': 0, 'peak_time': '', 'valley_time': ''}
            
        # 如果是列表，检查是否为空
        if isinstance(equity_curve, list) and len(equity_curve) == 0:
            print("警告: equity_curve 是空列表")
            return {'max_drawdown': 0, 'peak_time': '', 'valley_time': ''}
            
        # 如果是Series或DataFrame，检查是否为空
        if isinstance(equity_curve, (pd.Series, pd.DataFrame)) and equity_curve.empty:
            print("警告: equity_curve 是空的 Series 或 DataFrame")
            return {'max_drawdown': 0, 'peak_time': 'none', 'valley_time': 'none'}
            
        # 如果只有一个值，没有回撤
        if isinstance(equity_curve, list) and len(equity_curve) == 1:
            print("警告: equity_curve 只有一个值")
            return {'max_drawdown': 0, 'peak_time': '', 'valley_time': ''}
        if isinstance(equity_curve, pd.Series) and len(equity_curve) == 1:
            print("警告: equity_curve Series 只有一个值")
            return {'max_drawdown': 0, 'peak_time': '', 'valley_time': ''}
            
        try:
            # 转换为Series以便使用pandas功能
            if isinstance(equity_curve, list):
                equity_curve = pd.Series(equity_curve)
                
            # 再次检查转换后是否为空
            if equity_curve.empty:
                print("警告: 转换后的 equity_curve 为空")
                return {'max_drawdown': 0, 'peak_time': '', 'valley_time': ''}
                
            # 检查是否有非NaN值
            if equity_curve.isna().all():
                print("警告: equity_curve 全是 NaN 值")
                return {'max_drawdown': 0, 'peak_time': '', 'valley_time': ''}
                
            # 移除NaN值
            equity_curve = equity_curve.dropna()
            
            # 再次检查是否为空
            if equity_curve.empty:
                print("警告: 移除 NaN 后 equity_curve 为空")
                return {'max_drawdown': 0, 'peak_time': '', 'valley_time': ''}
                
            # 检查是否全是0
            if (equity_curve == 0).all():
                print("警告: equity_curve 全是 0")
                return {'max_drawdown': 0, 'peak_time': '', 'valley_time': ''}
                
            # 计算累计最大值
            running_max = equity_curve.cummax()
            
            # 计算回撤
            drawdown = (equity_curve / running_max - 1) * 100
            
            # 检查drawdown是否为空
            if drawdown.empty:
                print("警告: drawdown 为空")
                return {'max_drawdown': 0, 'peak_time': '', 'valley_time': ''}
                
            # 检查是否有回撤
            if drawdown.min() >= 0:
                print("信息: 没有回撤")
                return {'max_drawdown': 0, 'peak_time': '', 'valley_time': ''}
                
            # 找到最大回撤
            max_drawdown = drawdown.min()
            
            # 找到最大回撤的结束位置（波谷）
            valley_idx = drawdown.idxmin()
            
            # 找到最大回撤的开始位置（波峰）
            # 在波谷之前的最后一个峰值
            peak_slice = running_max.loc[:valley_idx]
            if peak_slice.empty:
                print("警告: peak_slice 为空")
                return {'max_drawdown': max_drawdown, 'peak_time': '', 'valley_time': str(valley_idx)}
                
            peak_idx = peak_slice.idxmax()
            
            # 打印调试信息
            print(f"max_drawdown: {max_drawdown}")
            print(f"peak_idx: {peak_idx}")
            print(f"valley_idx: {valley_idx}")
            
            # 获取波峰和波谷的时间
            peak_time = str(peak_idx)
            valley_time = str(valley_idx)
            print("max_drawdown:")
            print(max_drawdown)
            print("peak_time:")
            print(peak_time)
            print("valley_time:")
            print(valley_time)
            return {
                'max_drawdown': max_drawdown,
                'peak_time': peak_time,
                'valley_time': valley_time
            }
        except Exception as e:
            print(f"计算最大回撤时发生错误: {str(e)}")
            # 打印更多调试信息
            print(f"equity_curve 类型: {type(equity_curve)}")
            if hasattr(equity_curve, '__len__'):
                print(f"equity_curve 长度: {len(equity_curve)}")
            if isinstance(equity_curve, (pd.Series, pd.DataFrame)):
                print(f"equity_curve 前5个值: {equity_curve.head()}")
            print("max_drawdown:")
            print(max_drawdown)
            print("peak_time:")
            print(peak_time)
            print("valley_time:")
            print(valley_time)
            
            return {'max_drawdown': 0, 'peak_time': 'none', 'valley_time': 'none'}
