VERSION = "v1.0.3"

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
版本号: {VERSION}
发布日期: 2025-03-24
主要功能:
- 支持实盘和回测
- 支持浮动限价交易策略
- 支持Tick周期实盘和回测
- 支持交易费用计算
""" 