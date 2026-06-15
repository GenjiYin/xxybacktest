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
import json
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

# 账户配置表完整列名（含实盘扩展字段）
_ACCOUNT_COLUMNS = [
    "account_id", "name", "initialize_code", "handle_data_code",
    "initial_cash", "start_date", "data_path", "status",
    "asset_type", "benchmark", "created_at", "updated_at",
    "account_type", "live_account_id", "qmt_path",
    "trigger_cron", "execution_mode", "rebalance_interval",
]


def _get_accounts_df(db) -> pd.DataFrame:
    """从数据库加载账户配置"""
    try:
        df = db.query(f"SELECT * FROM {ACCOUNTS_TABLE}").df()
        # 兼容旧表：补充缺失列
        for col in _ACCOUNT_COLUMNS:
            if col not in df.columns:
                df[col] = None
        return df
    except Exception:
        # 表不存在，返回空 DataFrame
        return pd.DataFrame(columns=_ACCOUNT_COLUMNS)


def _save_accounts_df(db, df: pd.DataFrame):
    """保存账户配置到数据库"""
    if not df.empty:
        df["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    else:
        # 空 DataFrame 也要保留列结构
        df = pd.DataFrame(columns=_ACCOUNT_COLUMNS)
    db.write_data(
        df, id=ACCOUNTS_TABLE, date_col="created_at",
        partitioning=None, unique_together=["account_id"], rewrite=True
    )


def _generate_account_id(account_type: str = "sim") -> str:
    """生成账户ID: sim_YYYYMMDD_HHMMSS_XXX 或 live_YYYYMMDD_HHMMSS_XXX"""
    now = datetime.now()
    short_uuid = uuid.uuid4().hex[:6]
    prefix = "live" if account_type == "live" else "sim"
    return f"{prefix}_{now.strftime('%Y%m%d_%H%M%S')}_{short_uuid}"


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
    account_type: str = "sim",
    live_account_id: Optional[str] = None,
    qmt_path: Optional[str] = None,
    trigger_cron: str = "30 9 * * *",
    execution_mode: str = "daily",
    rebalance_interval: int = 1,
) -> str:
    """
    提交策略为模拟交易账户或实盘账户。

    参数:
        name: 账户名称（展示用）
        initialize: 初始化函数，会被存储用于后续每日重跑
        handle_data: 策略主函数（可选，如果为None则需在initialize中自行注册run_daily）
        capital: 初始资金（默认10万）。实盘时此值会被 QMT 的 total_asset 覆盖
        start_date: 策略开始日期，格式'YYYY-MM-DD'，默认为今天
        data_path: 数据源路径，指向xxydb数据目录（默认'./data'）
        asset_type: 资产类型，'stock'或'fund'（默认'stock'）
        benchmark: 基准指数代码（默认'000001.SH'）
        run_now: 是否立即运行回测（默认False，需等待定时任务）
        account_type: 账户类型，'sim'（模拟）或 'live'（实盘）
        live_account_id: 实盘账户的 QMT 资金账号（account_type='live' 时必填）
        qmt_path: QMT 客户端安装目录（account_type='live' 时必填）
        trigger_cron: 定时触发 cron 表达式（默认 '30 9 * * *'，即每天 9:30）
        execution_mode: 执行模式，'daily'（每日）或 'periodic'（按周期）
        rebalance_interval: 调仓周期天数（execution_mode='periodic' 时生效）

    返回:
        account_id: 账户唯一ID

    示例:
        >>> # 模拟账户
        >>> account_id = submit("测试策略", initialize, capital=100000)
        >>> # 实盘账户
        >>> account_id = submit("实盘策略", initialize,
        ...     account_type="live",
        ...     live_account_id="8881686799",
        ...     qmt_path=r"D:\\国金证券QMT交易端\\userdata_mini")
    """
    db = get_db(data_path)
    try:
        if start_date is None:
            start_date = datetime.now().strftime("%Y-%m-%d")

        # ------------------------------------------------------------------
        # 实盘：连接 QMT 读取总资产作为 initial_cash
        # ------------------------------------------------------------------
        if account_type == "live":
            if not qmt_path or not live_account_id:
                raise ValueError(
                    "account_type='live' 时必须提供 qmt_path 和 live_account_id"
                )
            from ..live.trader import QMTTrader
            trader = QMTTrader(qmt_path, live_account_id)
            try:
                portfolio = trader.get_portfolio()
                capital = portfolio["total_asset"]
                print(f"[实盘] 连接 QMT 成功，读取总资产: {capital:,.2f}")
            finally:
                trader.disconnect()

        initialize_code = _extract_source(initialize)
        handle_data_code = _extract_source(handle_data) if handle_data else None

        account_id = _generate_account_id(account_type)

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
            "account_type": account_type,
            "live_account_id": live_account_id,
            "qmt_path": qmt_path,
            "trigger_cron": trigger_cron,
            "execution_mode": execution_mode,
            "rebalance_interval": rebalance_interval,
        }

        df = pd.concat([df, pd.DataFrame([new_account])], ignore_index=True)
        _save_accounts_df(db, df)

        type_label = "实盘" if account_type == "live" else "模拟交易"
        print(f"[{type_label}] 账户已创建: {account_id} ({name})")
        print(f"  数据源: {data_path}")

        # 立即运行回测（仅模拟账户）
        if run_now:
            if account_type == "live":
                print(f"[实盘] 跳过立即运行，等待定时调度触发")
            else:
                print(f"[模拟交易] 立即运行回测...")
                from .runner import run_single

                def _rollback():
                    """回滚本次新增的账户记录，不留垃圾账户。
                    run_single 在 run_backtest 成功后才写结果文件，失败时无结果数据，
                    故仅需从账户表删除本次新增的这一行。"""
                    db_rb = get_db(data_path)
                    df_rb = _get_accounts_df(db_rb)
                    df_rb = df_rb[df_rb["account_id"] != account_id]
                    _save_accounts_df(db_rb, df_rb)
                    print(f"[模拟交易] 已回滚失败账户: {account_id}")

                try:
                    result = run_single(account_id, data_path=data_path)
                except Exception as e:
                    # run_single 未兜住的异常（如结果存储阶段报错）
                    print(f"[模拟交易] 回测异常: {e}")
                    _rollback()
                    return None

                if result['status'] == 'success':
                    print(f"[模拟交易] 回测完成，最终净值: {result['final_nav']:.4f}")
                else:
                    print(f"[模拟交易] 回测失败: {result.get('reason', '未知错误')}")
                    _rollback()
                    return None

        # ── 实盘账户：热注册到 APScheduler（无需重启 xxy-sim）──
        if account_type == "live":
            try:
                from functools import partial
                from .scheduler import add_func_job, get_scheduler
                from ..live.runner import run_live

                scheduler = get_scheduler()
                if scheduler.running:
                    task_id = f"live_{account_id}"
                    wrapped = partial(run_live, account_id, data_path)
                    add_func_job(task_id, f"实盘-{name}", wrapped, trigger_cron, data_path)
                    print(f"[实盘] 定时任务已热注册: {task_id} (cron: {trigger_cron})")
                else:
                    print(f"[实盘] APScheduler 未启动，任务将在 xxy-sim 启动后自动注册")
            except Exception as e:
                print(f"[实盘] 热注册定时任务失败: {e}")

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
        # 兼容处理：account_type 可能是 nan/None，用 account_id 前缀兜底
        account_type = "sim"
        if "account_type" in df.columns:
            val = df.loc[mask, "account_type"].values[0]
            if pd.notna(val) and val is not None:
                account_type = str(val).strip()
        # 双重保险：live_ 前缀的账户一律按实盘清理
        is_live = (account_type == "live") or account_id.startswith("live_")

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

        # ── 实盘账户额外清理 ──
        print(f"[DEBUG] account_type={account_type!r}, is_live={is_live}, account_id={account_id}")
        if is_live:
            # 1. 从 APScheduler 移除定时 job
            try:
                from .scheduler import remove_job
                remove_job(f"live_{account_id}")
                print(f"[DEBUG] APScheduler job live_{account_id} 已移除")
            except Exception as e:
                print(f"[DEBUG] APScheduler 移除失败: {e}")

            # 2. 清理 live_schedule.json
            try:
                live_schedule_path = Path(account_data_path) / "live" / "live_schedule.json"
                print(f"[DEBUG] live_schedule_path = {live_schedule_path}")
                if live_schedule_path.exists():
                    with open(live_schedule_path, "r", encoding="utf-8") as f:
                        schedule_data = json.load(f)
                    print(f"[DEBUG] live_schedule.json keys: {list(schedule_data.keys())}")
                    if account_id in schedule_data:
                        del schedule_data[account_id]
                        with open(live_schedule_path, "w", encoding="utf-8") as f:
                            json.dump(schedule_data, f, ensure_ascii=False, indent=2)
                        print(f"[DEBUG] live_schedule.json 已删除 {account_id}")
                    else:
                        print(f"[DEBUG] account_id {account_id} 不在 live_schedule.json 中")
                else:
                    print(f"[DEBUG] live_schedule.json 不存在")
            except Exception as e:
                print(f"[DEBUG] live_schedule.json 清理失败: {e}")
                import traceback
                traceback.print_exc()

            # 3. 清理实盘结果目录
            try:
                live_account_dir = Path(account_data_path) / "live" / "accounts" / account_id
                if live_account_dir.exists():
                    shutil.rmtree(live_account_dir)
                    print(f"[DEBUG] 实盘结果目录已删除: {live_account_dir}")
                else:
                    print(f"[DEBUG] 实盘结果目录不存在: {live_account_dir}")
            except Exception as e:
                print(f"[DEBUG] 实盘结果目录清理失败: {e}")

        # 4. 清理任务日志（模拟+实盘通用）
        try:
            log_dir = Path(account_data_path) / "simulation_results" / "task_logs"
            for prefix in ["", "live_"]:
                task_id = f"{prefix}{account_id}"
                for ext in [".log", ".status"]:
                    log_file = log_dir / f"{task_id}{ext}"
                    if log_file.exists():
                        log_file.unlink()
                # 历史日志目录
                history_dir = log_dir / "history" / task_id
                if history_dir.exists():
                    shutil.rmtree(history_dir)
        except Exception:
            pass

        type_label = "实盘" if account_type == "live" else "模拟交易"
        print(f"[{type_label}] 账户已删除: {account_id}")
        return True
    finally:
        # 关键修复：每个 close_db 独立 try-except，一个失败不影响另一个
        try:
            close_db(data_path)
        except Exception:
            pass
        if sim_path is not None:
            try:
                close_db(sim_path)
            except Exception:
                pass


def update_account(
    account_id: str,
    data_path: str = "./data",
    name: str = None,
    initialize: Callable = None,
    handle_data: Callable = None,
    initialize_code: str = None,
    handle_data_code: str = None,
    trigger_cron: str = None,
    qmt_path: str = None,
    live_account_id: str = None,
    execution_mode: str = None,
    rebalance_interval: int = None,
) -> dict:
    """
    更新已有账户的配置和策略代码。

    策略代码修改后，下次定时任务触发时自动生效（run_live 会从数据库读取最新源码）。
    trigger_cron 修改后，如果 APScheduler 正在运行，则自动热更新（无需重启 xxy-sim）。

    参数:
        account_id:          账户ID
        data_path:           数据源路径（默认'./data'）
        name:                新账户名称（可选）
        initialize:          新 initialize 函数对象（可选，与 initialize_code 二选一）
        handle_data:         新 handle_data 函数对象（可选，与 handle_data_code 二选一）
        initialize_code:     新 initialize 源码字符串（可选，Web API 调用时用）
        handle_data_code:    新 handle_data 源码字符串（可选，Web API 调用时用）
        trigger_cron:        新 cron 表达式（可选）
        qmt_path:            新 QMT 路径（可选）
        live_account_id:     新 QMT 资金账号（可选）
        execution_mode:      新执行模式（可选）
        rebalance_interval:  新调仓周期（可选）

    返回:
        dict: {
            'success': bool,
            'account_id': str,
            'updated_fields': list,   # 实际被修改的字段名
            'cron_changed': bool,     # cron 是否被修改
            'scheduler_refreshed': bool | None,  # scheduler 是否热更新成功
        }

    用法示例（Python 脚本）:
        >>> def new_initialize(ctx):
        ...     ctx.g["target_pct"] = 0.10
        ...
        >>> update_account("live_xxx", initialize=new_initialize)

    用法示例（Web API）:
        PUT /accounts/live_xxx
        Body: {"initialize_code": "def initialize(ctx):\\n    ctx.g['x'] = 1", "trigger_cron": "30 10 * * *"}
    """
    db = get_db(data_path)
    try:
        df = _get_accounts_df(db)
        mask = df["account_id"] == account_id
        if not mask.any():
            return {"success": False, "account_id": account_id, "reason": "账户不存在"}

        old_row = df.loc[mask].iloc[0].to_dict()
        updates = {}

        if name is not None:
            updates["name"] = name
        if initialize is not None:
            updates["initialize_code"] = _extract_source(initialize)
        if handle_data is not None:
            updates["handle_data_code"] = _extract_source(handle_data) if handle_data else None
        if initialize_code is not None:
            updates["initialize_code"] = initialize_code
        if handle_data_code is not None:
            updates["handle_data_code"] = handle_data_code
        if trigger_cron is not None:
            updates["trigger_cron"] = trigger_cron
        if qmt_path is not None:
            updates["qmt_path"] = qmt_path
        if live_account_id is not None:
            updates["live_account_id"] = live_account_id
        if execution_mode is not None:
            updates["execution_mode"] = execution_mode
        if rebalance_interval is not None:
            updates["rebalance_interval"] = rebalance_interval

        if not updates:
            return {"success": True, "account_id": account_id, "updated_fields": [], "reason": "无更新内容"}

        for k, v in updates.items():
            df.loc[mask, k] = v
        _save_accounts_df(db, df)

        result = {
            "success": True,
            "account_id": account_id,
            "updated_fields": list(updates.keys()),
            "cron_changed": False,
            "scheduler_refreshed": None,
        }

        # 如果 cron 变了且 scheduler 已启动，热更新 job
        old_cron = old_row.get("trigger_cron", "")
        new_cron = updates.get("trigger_cron")
        if new_cron is not None and new_cron != old_cron:
            result["cron_changed"] = True
            try:
                from .scheduler import get_scheduler, add_func_job, remove_job
                from ..live.runner import run_live
                from functools import partial

                scheduler = get_scheduler()
                task_id = f"live_{account_id}"
                job_name = updates.get("name", old_row.get("name", account_id))

                # 只有 job 已注册时才热更新（xxy-sim 未运行则无 job）
                if scheduler.get_job(task_id):
                    remove_job(task_id)
                    wrapped = partial(run_live, account_id, data_path)
                    add_func_job(task_id, f"实盘-{job_name}", wrapped, new_cron, data_path)
                    result["scheduler_refreshed"] = True
                    print(f"[update_account] job {task_id} 已热更新，新 cron: {new_cron}")
                else:
                    result["scheduler_refreshed"] = False
                    print(f"[update_account] job {task_id} 未在 scheduler 中，跳过热更新（需重启 xxy-sim）")
            except Exception as e:
                result["scheduler_refreshed"] = False
                result["scheduler_error"] = str(e)
                print(f"[update_account] scheduler 热更新失败: {e}")

        type_label = "实盘" if old_row.get("account_type") == "live" else "模拟交易"
        print(f"[{type_label}] 账户已更新: {account_id}, 字段: {list(updates.keys())}")
        return result
    finally:
        close_db(data_path)


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
                        "data_path", "status", "asset_type", "benchmark", "created_at",
                        "account_type", "live_account_id", "qmt_path",
                        "trigger_cron", "execution_mode", "rebalance_interval"]
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
