VERSION = "1.0.0"

def get_version():
    return VERSION

def check_for_updates():
    """检查是否有新版本
    TODO: 未来可以添加在线检查更新的功能
    """
    return False, None

def show_version_info():
    """返回版本信息"""
    return f"""
当前版本: {VERSION}
发布日期: 2025-03-19
主要功能:
- 支持实盘和回测
- 支持网格交易策略
- 支持多种周期数据
- 支持交易费用计算
""" 