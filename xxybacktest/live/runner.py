"""
live/runner.py — 实盘调仓入口

职责：
    - 加载账户配置、校验交易日、连接 QMT
    - 构建实盘 context、绑定交易函数
    - 执行策略（initialize + daily_callbacks）
    - handle_data 结束后统一刷新 portfolio（P4.4）
    - 保存结果 + 持久化策略状态
"""

import os
import re
import types
from datetime import datetime

from ..data import Data
from .context import create_live_context
from .recorder import _save_live_results
from .trader import QMTTrader, QMTConnectionError
from .trading import (
    get_account_positions,
    get_portfolio,
    get_price,
    inout_cash as _inout_cash,
    order as _order,
    order_buy as _order_buy,
    order_sell as _order_sell,
    order_target_percent as _order_target_percent,
    order_target_value as _order_target_value,
    order_value as _order_value,
    _refresh_portfolio,
)
from .utils import (
    _load_schedule,
    _load_strategy_state,
    _save_strategy_state,
    _update_schedule,
    is_trading_day,
)


def _load_func(code: str, func_name: str = "user_func"):
    """从源码字符串加载函数（复用 simulation/runner.py 的逻辑）。"""
    if not code or not code.strip():
        return None

    lines = code.split("\n")
    cleaned_lines = []
    for line in lines:
        match = re.match(r"\s*\d+\s*[│|]\s*(.*)", line)
        if match:
            cleaned_lines.append(match.group(1))
        else:
            cleaned_lines.append(line)

    code = "\n".join(cleaned_lines)
    module = types.ModuleType("dynamic_module")
    module.__dict__["__builtins__"] = __builtins__

    try:
        exec(code, module.__dict__)
    except Exception as e:
        raise ValueError(f"函数源码执行失败: {e}\n源码:\n{code[:200]}...")

    for name, obj in module.__dict__.items():
        if callable(obj) and not name.startswith("_"):
            return obj

    raise ValueError(f"在源码中未找到函数定义")


def run_live(account_id: str, data_path: str = "./data") -> dict:
    """
    执行单个实盘账户的调仓。

    参数:
        account_id: 账户ID
        data_path:  数据根目录

    返回:
        dict: {"account_id": ..., "status": "success"|"error"|"skipped", ...}
    """
    from ..simulation.submitter import get_account

    today = datetime.now().strftime("%Y-%m-%d")

    print(f"\n[实盘调仓] 账户: {account_id}  日期: {today}")

    # ------------------------------------------------------------------
    # 1. 加载账户配置
    # ------------------------------------------------------------------
    account = get_account(account_id, data_path)
    if not account:
        return {"account_id": account_id, "status": "error", "reason": "账户不存在"}

    if account.get("account_type") != "live":
        return {"account_id": account_id, "status": "error", "reason": "非实盘账户"}

    if account["status"] != "running":
        print(f"[跳过] 账户 {account_id} 状态为 {account['status']}")
        return {"account_id": account_id, "status": "skipped", "reason": "not_running"}

    account_data_path = account.get("data_path", data_path)

    # ------------------------------------------------------------------
    # 2. 交易日判断
    # ------------------------------------------------------------------
    if not is_trading_day(today, account_data_path):
        print(f"[跳过] {today} 非交易日")
        return {"account_id": account_id, "status": "skipped", "reason": "not_trading_day"}

    # ------------------------------------------------------------------
    # 3. 防并发
    # ------------------------------------------------------------------
    schedule = _load_schedule(account_id, account_data_path)
    if schedule.get("running"):
        print(f"[跳过] 账户 {account_id} 正在运行中")
        return {"account_id": account_id, "status": "skipped", "reason": "already_running"}

    _update_schedule(account_id, {"running": True, "last_run": today}, account_data_path)

    # ------------------------------------------------------------------
    # 4. 连接 QMT
    # ------------------------------------------------------------------
    qmt_path = account.get("qmt_path", "")
    live_account_id = account.get("live_account_id", "")
    if not qmt_path or not live_account_id:
        _update_schedule(account_id, {"running": False}, account_data_path)
        return {"account_id": account_id, "status": "error", "reason": "缺少 QMT 配置"}

    # 预检测 QMT 登录状态，避免未登录时卡在重试循环中
    from .trader import check_qmt_login
    if not check_qmt_login(qmt_path, live_account_id):
        print("[错误] 没有登录qmt")
        _update_schedule(account_id, {"running": False}, account_data_path)
        raise RuntimeError("没有登录qmt")

    trader = None
    try:
        trader = QMTTrader(qmt_path, live_account_id)
    except QMTConnectionError as e:
        _update_schedule(account_id, {"running": False}, account_data_path)
        return {"account_id": account_id, "status": "error", "reason": f"QMT 连接失败: {e}"}

    try:
        # --------------------------------------------------------------
        # 5. 加载策略状态
        # --------------------------------------------------------------
        strategy_state = _load_strategy_state(account_id, account_data_path)

        # --------------------------------------------------------------
        # 6. 构建实盘 context
        # --------------------------------------------------------------
        ctx = create_live_context(account, trader, strategy_state)
        ctx.current_dt = datetime.now()

        # --------------------------------------------------------------
        # 7. 预加载行情数据（供 history 使用）
        # --------------------------------------------------------------
        asset_type = account.get("asset_type", "stock")
        start_date = account.get("start_date", today)
        Data.init_db(account_data_path, asset_type=asset_type)
        if asset_type == "fund":
            Data.preload_fund_daily(start_date, today)
            Data.preload_fund_dividend(start_date, today)
        else:
            Data.preload_daily(start_date, today)
            Data.preload_dividend(start_date, today)

        # 交易日历（history 需要）
        calendar = Data.get_trade_calendar(start_date, today)
        ctx.data.calendar = calendar

        # 上一交易日：今天已过 is_trading_day 校验，故“今天之前最近交易日”即上一交易日。
        # 数据库边界（无更早交易日）时为 None。
        prev_day = Data.get_previous_trade_day(today)
        if prev_day is not None:
            ctx.previous_date = prev_day
            ctx.previous_dt = datetime.strptime(prev_day, "%Y-%m-%d")

        # --------------------------------------------------------------
        # 8. 绑定交易函数（API 签名与回测完全一致）
        # --------------------------------------------------------------
        ctx.order_buy = lambda code, amount: _order_buy(code, amount, ctx)
        ctx.order_sell = lambda code, amount: _order_sell(code, amount, ctx)
        ctx.order = lambda security, amount: _order(security, amount, ctx)
        ctx.order_value = lambda security, value: _order_value(security, value, ctx)
        ctx.order_target_value = lambda security, value: _order_target_value(security, value, ctx)
        ctx.order_target_percent = lambda security, percent: _order_target_percent(security, percent, ctx)
        ctx.inout_cash = lambda cash_amount: _inout_cash(cash_amount, ctx)

        # P4.4: 绑定刷新接口到 context
        ctx.get_portfolio = lambda: get_portfolio(ctx)
        ctx.get_account_positions = lambda: get_account_positions(ctx)
        ctx.get_price = lambda security: get_price(ctx, security)

        # --------------------------------------------------------------
        # 9. 绑定 run_daily（实盘：收集回调到列表）
        # --------------------------------------------------------------
        daily_callbacks = []

        def _run_daily(func, time_str="9:30"):
            daily_callbacks.append(func)

        ctx.run_daily = _run_daily

        # --------------------------------------------------------------
        # 10. 绑定 history
        # --------------------------------------------------------------
        def _history(instruments, fields=None, bar_count=1):
            return Data.history(ctx, instruments, fields, bar_count)

        ctx.history = _history

        # --------------------------------------------------------------
        # 11. 重建并执行策略函数
        # --------------------------------------------------------------
        initialize = _load_func(account["initialize_code"], "initialize")
        handle_data = _load_func(account["handle_data_code"], "handle_data") if account.get("handle_data_code") else None

        initialize(ctx)

        # 如果用户传了 handle_data 但没在 initialize 中注册，视为主策略
        if handle_data is not None and not daily_callbacks:
            daily_callbacks.append(handle_data)

        # 执行所有回调
        for callback in daily_callbacks:
            callback(ctx)

        # --------------------------------------------------------------
        # P4.4: handle_data 结束后统一刷新 portfolio
        # --------------------------------------------------------------
        _refresh_portfolio(ctx)

        # --------------------------------------------------------------
        # 12. 保存结果
        # --------------------------------------------------------------
        _save_live_results(account_id, ctx, account_data_path)

        # --------------------------------------------------------------
        # 13. 持久化策略状态
        # --------------------------------------------------------------
        _save_strategy_state(account_id, dict(ctx.g), account_data_path)

        # --------------------------------------------------------------
        # 14. 标记完成
        # --------------------------------------------------------------
        _update_schedule(account_id, {
            "running": False,
            "last_success": today,
        }, account_data_path)

        print(f"[实盘调仓完成] {account_id}")
        return {
            "account_id": account_id,
            "status": "success",
            "date": today,
        }

    except Exception as e:
        print(f"[错误] {account_id} 实盘调仓异常: {e}")
        import traceback
        traceback.print_exc()
        _update_schedule(account_id, {
            "running": False,
            "last_error": str(e),
            "last_error_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, account_data_path)
        raise

    finally:
        if trader is not None:
            trader.disconnect()
        try:
            Data.clear_cache()
            if Data._db is not None:
                Data._db.close()
                Data._db = None
        except Exception:
            pass
