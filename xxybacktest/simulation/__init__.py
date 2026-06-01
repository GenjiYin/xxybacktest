"""
模拟交易模块 - 每日重跑回测方案

导出接口:
    # 账户管理 (submitter.py)
    submit(name, initialize, handle_data, capital, ...) -> account_id
    update_account(account_id, initialize, handle_data, ...) -> dict
    pause(account_id, data_path) -> bool
    resume(account_id, data_path) -> bool
    delete(account_id, data_path) -> bool
    list_accounts(status, data_path) -> list
    get_account(account_id, data_path) -> dict

    # 重跑引擎 (runner.py)
    run_all(end_date, data_path) -> list
    run_single(account_id, end_date, data_path) -> dict
    get_account_nav(account_id, data_path) -> DataFrame
    get_account_positions(account_id, date, data_path) -> DataFrame
    get_account_orders(account_id, limit, data_path) -> DataFrame
"""

from .submitter import submit, update_account, pause, resume, delete, list_accounts, get_account
from .runner import run_all, run_single, get_account_nav, get_account_positions, get_account_orders
from .task_store import schedule_task
from .db_utils import close_all

__all__ = [
    # submitter
    "submit", "update_account", "pause", "resume", "delete", "list_accounts", "get_account",
    # runner
    "run_all", "run_single", "get_account_nav", "get_account_positions", "get_account_orders",
    # scheduler
    "schedule_task",
    # utils
    "close_all",
]
