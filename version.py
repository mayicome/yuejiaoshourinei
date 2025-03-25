VERSION = "v1.0.5"

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
- 增加基金名称
- 修改回测的Bug
- 移动回撤计算程序的位置
""" 