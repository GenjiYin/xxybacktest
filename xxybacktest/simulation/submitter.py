"""
模拟交易账户管理 - 阶段二

功能：
    - submit(): 注册策略为模拟交易账户
    - pause()/resume(): 暂停/恢复账户
    - delete(): 删除账户
    - list_accounts(): 列出所有账户
    - get_account(): 获取单个账户详情
"""

import inspect
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from .db_utils import close_db, get_db


# 账户配置表名
ACCOUNTS_TABLE = "simulation_accounts"


def _get_accounts_df(db) -> pd.DataFrame:
    """从数据库加载账户配置"""
    try:
        return db.query(f"SELECT * FROM {ACCOUNTS_TABLE}").df()
    except Exception:
        # 表不存在，返回空 DataFrame
        return pd.DataFrame(columns=[
            "account_id", "name", "initialize_code", "handle_data_code",
            "initial_cash", "start_date", "data_path", "status",
            "asset_type", "benchmark", "created_at", "updated_at"
        ])


def _save_accounts_df(db, df: pd.DataFrame):
    """保存账户配置到数据库"""
    if not df.empty:
        df["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    else:
        # 空 DataFrame 也要保留列结构
        df = pd.DataFrame(columns=[
            "account_id", "name", "initialize_code", "handle_data_code",
            "initial_cash", "start_date", "data_path", "status",
            "asset_type", "benchmark", "created_at", "updated_at"
        ])
    db.write_data(
        df, id=ACCOUNTS_TABLE, date_col="created_at",
        partitioning=None, unique_together=["account_id"], rewrite=True
    )


def _generate_account_id() -> str:
    """生成账户ID: sim_YYYYMMDD_HHMMSS_XXX"""
    now = datetime.now()
    short_uuid = uuid.uuid4().hex[:6]
    return f"sim_{now.strftime('%Y%m%d_%H%M%S')}_{short_uuid}"


def _extract_source(func: Optional[Callable]) -> Optional[str]:
    """提取函数源码，如果为None则返回None"""
    if func is None:
        return None
    try:
        return inspect.getsource(func)
    except (OSError, TypeError) as e:
        raise ValueError(f"无法提取函数源码: {e}")


def submit(
    name: str,
    initialize: Callable,
    handle_data: Optional[Callable] = None,
    capital: float = 100000,
    start_date: Optional[str] = None,
    data_path: str = "./data",
    asset_type: str = "stock",
    benchmark: str = "000001.SH",
    run_now: bool = False,
) -> str:
    """
    提交策略为模拟交易账户。

    参数:
        name: 账户名称（展示用）
        initialize: 初始化函数，会被存储用于后续每日重跑
        handle_data: 策略主函数（可选，如果为None则需在initialize中自行注册run_daily）
        capital: 初始资金（默认10万）
        start_date: 策略开始日期，格式'YYYY-MM-DD'，默认为今天
        data_path: 数据源路径，指向xxydb数据目录（默认'./data'）
        asset_type: 资产类型，'stock'或'fund'（默认'stock'）
        benchmark: 基准指数代码（默认'000001.SH'）
        run_now: 是否立即运行回测（默认False，需等待定时任务）

    返回:
        account_id: 账户唯一ID

    示例:
        >>> def initialize(context):
        ...     context.run_daily(strategy, "9:30")
        >>> def strategy(context):
        ...     print(context.current_dt)
        >>> account_id = submit("测试策略", initialize, capital=100000, data_path="./my_data")
        >>> # 立即运行，无需等待定时任务
        >>> account_id = submit("测试策略", initialize, run_now=True)
    """
    db = get_db(data_path)
    try:
        if start_date is None:
            start_date = datetime.now().strftime("%Y-%m-%d")

        initialize_code = _extract_source(initialize)
        handle_data_code = _extract_source(handle_data) if handle_data else None

        account_id = _generate_account_id()

        # 加载现有账户
        df = _get_accounts_df(db)

        # 添加新账户
        new_account = {
            "account_id": account_id,
            "name": name,
            "initialize_code": initialize_code,
            "handle_data_code": handle_data_code,
            "initial_cash": capital,
            "start_date": start_date,
            "data_path": data_path,
            "status": "running",
            "asset_type": asset_type,
            "benchmark": benchmark,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        df = pd.concat([df, pd.DataFrame([new_account])], ignore_index=True)
        _save_accounts_df(db, df)

        print(f"[模拟交易] 账户已创建: {account_id} ({name})")
        print(f"  数据源: {data_path}")

        # 立即运行回测
        if run_now:
            print(f"[模拟交易] 立即运行回测...")
            from .runner import run_single
            result = run_single(account_id, data_path=data_path)
            if result['status'] == 'success':
                print(f"[模拟交易] 回测完成，最终净值: {result['final_nav']:.4f}")
            else:
                print(f"[模拟交易] 回测失败: {result.get('reason', '未知错误')}")

        return account_id
    finally:
        close_db(data_path)


def pause(account_id: str, data_path: str = "./data") -> bool:
    """
    暂停指定账户（暂停后不会参与每日重跑）

    参数:
        account_id: 账户ID
        data_path: 数据源路径（默认'./data'）

    返回:
        bool: 是否成功
    """
    db = get_db(data_path)
    try:
        df = _get_accounts_df(db)

        mask = df["account_id"] == account_id
        if not mask.any():
            return False

        df.loc[mask, "status"] = "paused"
        df.loc[mask, "updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _save_accounts_df(db, df)

        print(f"[模拟交易] 账户已暂停: {account_id}")
        return True
    finally:
        close_db(data_path)


def resume(account_id: str, data_path: str = "./data") -> bool:
    """
    恢复指定账户（恢复后会参与每日重跑）

    参数:
        account_id: 账户ID
        data_path: 数据源路径（默认'./data'）

    返回:
        bool: 是否成功
    """
    db = get_db(data_path)
    try:
        df = _get_accounts_df(db)

        mask = df["account_id"] == account_id
        if not mask.any():
            return False

        df.loc[mask, "status"] = "running"
        df.loc[mask, "updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _save_accounts_df(db, df)

        print(f"[模拟交易] 账户已恢复: {account_id}")
        return True
    finally:
        close_db(data_path)


def delete(account_id: str, data_path: str = "./data") -> bool:
    """
    删除指定账户及其所有历史数据

    参数:
        account_id: 账户ID
        data_path: 数据源路径（默认'./data'）

    返回:
        bool: 是否成功
    """
    db = get_db(data_path)
    sim_path = None
    try:
        df = _get_accounts_df(db)

        mask = df["account_id"] == account_id
        if not mask.any():
            return False

        # 获取账户自己的 data_path（可能和传入的不同）
        account_data_path = df.loc[mask, "data_path"].values[0]

        # 删除账户配置
        df = df[~mask]
        _save_accounts_df(db, df)

        # 删除该账户的结果数据（使用账户自己的 data_path）
        sim_path = str(Path(account_data_path) / "simulation_results")
        sim_db = get_db(sim_path)
        for table in ["simulation_daily_values", "simulation_positions", "simulation_orders"]:
            try:
                result_df = sim_db.query(f"SELECT * FROM {table}").df()
                original_len = len(result_df)
                result_df = result_df[result_df["account_id"] != account_id]
                # 只要有数据变化就重写（包括清空）
                if len(result_df) != original_len:
                    if table == "simulation_positions":
                        unique_keys = ["account_id", "date", "instrument"]
                    elif table == "simulation_orders":
                        unique_keys = None
                    else:
                        unique_keys = ["account_id", "date"]
                    sim_db.write_data(
                        result_df, id=table, date_col="date",
                        partitioning=None, unique_together=unique_keys, rewrite=True
                    )
            except Exception:
                pass  # 表可能不存在

        # 删除新格式的独立账户目录
        account_dir = Path(account_data_path) / "simulation_results" / "accounts" / account_id
        if account_dir.exists():
            shutil.rmtree(account_dir)

        print(f"[模拟交易] 账户已删除: {account_id}")
        return True
    finally:
        close_db(data_path)
        if sim_path is not None:
            close_db(sim_path)


def list_accounts(status: Optional[str] = None, data_path: str = "./data") -> list:
    """
    列出所有模拟交易账户

    参数:
        status: 过滤状态 'running'/'paused'/'stopped'，None表示全部
        data_path: 数据源路径（默认'./data'）

    返回:
        list: 账户信息列表
    """
    db = get_db(data_path)
    try:
        df = _get_accounts_df(db)

        if status:
            df = df[df["status"] == status]

        # 按创建时间倒序
        df = df.sort_values("created_at", ascending=False)

        # 不返回源码字段（太大）
        display_cols = ["account_id", "name", "initial_cash", "start_date",
                        "data_path", "status", "asset_type", "benchmark", "created_at"]
        df = df[[c for c in display_cols if c in df.columns]]

        return df.to_dict("records")
    finally:
        close_db(data_path)


def get_account(account_id: str, data_path: str = "./data") -> Optional[dict]:
    """
    获取单个账户详情

    参数:
        account_id: 账户ID
        data_path: 数据源路径（默认'./data'）

    返回:
        dict: 账户信息，不存在则返回None
    """
    db = get_db(data_path)
    try:
        df = _get_accounts_df(db)

        mask = df["account_id"] == account_id
        if not mask.any():
            return None

        return df[mask].iloc[0].to_dict()
    finally:
        close_db(data_path)
