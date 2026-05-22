"""
xxydb 数据库工具函数
"""

import os
from pathlib import Path

from xxydb import xxydb


# 全局数据库连接缓存
_db_cache = {}


def get_db(path: str = None) -> xxydb:
    """
    获取或创建 xxydb 实例

    参数:
        path: 数据路径，默认从环境变量 XXYDB_PATH 获取，否则用 './data'

    返回:
        xxydb 实例
    """
    if path is None:
        path = os.environ.get("XXYDB_PATH", "./data")

    path = str(Path(path).resolve())

    if path not in _db_cache:
        _db_cache[path] = xxydb(path=path)

    return _db_cache[path]


def get_account_db(account_id: str, data_path: str = None) -> xxydb:
    """
    获取账户对应的数据库实例
    模拟交易结果存储在 {data_path}/simulation_results/ 下

    参数:
        account_id: 账户ID
        data_path: 账户数据路径

    返回:
        xxydb 实例
    """
    if data_path is None:
        data_path = os.environ.get("XXYDB_PATH", "./data")

    # 模拟交易结果存储在独立目录
    sim_path = Path(data_path) / "simulation_results"
    return get_db(str(sim_path))


def close_db(path: str = None):
    """关闭指定路径的数据库连接并从缓存中移除"""
    global _db_cache
    if path is None:
        path = os.environ.get("XXYDB_PATH", "./data")

    path = str(Path(path).resolve())

    if path in _db_cache:
        try:
            _db_cache[path].close()
        except Exception:
            pass
        try:
            del _db_cache[path]
        except KeyError:
            pass


def close_all():
    """关闭所有数据库连接"""
    global _db_cache
    for db in _db_cache.values():
        db.close()
    _db_cache.clear()
