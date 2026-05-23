"""
live/recorder.py — 实盘结果持久化

将实盘交易结果写入独立 Parquet 文件：
  data/live/accounts/{account_id}/
    daily_values.parquet   — 追加（每天一行：date / nav / daily_return）
    positions.parquet      — 覆盖（当前持仓快照）
    orders.parquet         — 追加（有订单时）
"""

import os

import pandas as pd

from ..data import Data


def _get_instrument_name(code: str) -> str:
    """尝试从 Data 缓存中获取股票名称。"""
    try:
        return Data._instrument_names.get(code, "")
    except Exception:
        return ""


def _save_live_results(account_id: str, context, data_path: str):
    """
    保存实盘交易结果到独立 Parquet 文件。

    参数:
        account_id: 账户ID
        context:    实盘上下文（含 portfolio、logs.order_list 等）
        data_path:  数据根目录
    """
    account_dir = os.path.join(data_path, "live", "accounts", account_id)
    os.makedirs(account_dir, exist_ok=True)

    today = (
        context.current_dt.strftime("%Y-%m-%d")
        if hasattr(context.current_dt, "strftime")
        else str(context.current_dt)
    )

    # ------------------------------------------------------------------
    # 1. daily_values — 按日期去重，同一天的重复运行只保留最新结果
    # ------------------------------------------------------------------
    nav_path = os.path.join(account_dir, "daily_values.parquet")

    if os.path.exists(nav_path):
        df_nav = pd.read_parquet(nav_path)
    else:
        df_nav = pd.DataFrame(columns=["date", "nav", "daily_return"])

    starting_cash = float(context.portfolio.starting_cash)
    total_value = float(context.portfolio.total_value)
    nav = total_value / starting_cash if starting_cash != 0 else 1.0

    if not df_nav.empty:
        prev_nav = float(df_nav["nav"].iloc[-1])
        daily_return = (nav - prev_nav) / prev_nav if prev_nav != 0 else 0.0
    else:
        daily_return = 0.0

    new_row = pd.DataFrame([{"date": today, "nav": nav, "daily_return": daily_return}])

    # 去重：删除已有同日期记录，追加最新结果
    df_nav = df_nav[df_nav["date"] != today]
    df_nav = pd.concat([df_nav, new_row], ignore_index=True)
    df_nav.to_parquet(nav_path, index=False)

    # ------------------------------------------------------------------
    # 2. positions — 覆盖写入当前持仓
    # ------------------------------------------------------------------
    pos_path = os.path.join(account_dir, "positions.parquet")

    pos_records = []
    total_val = float(context.portfolio.total_value)
    for code, pos in context.portfolio.positions.items():
        ratio = pos.total_value / total_val if total_val != 0 else 0.0
        cum_return = pos.last_sale_price / pos.cost_basis - 1 if pos.cost_basis != 0 else 0.0
        cum_profit = pos.amount * (pos.last_sale_price - pos.cost_basis)
        pos_records.append({
            "date": today,
            "instrument": code,
            "name": _get_instrument_name(code),
            "volume": pos.amount,
            "ratio": ratio,
            "cum_profit": cum_profit,
            "cum_return": cum_return,
            "close_price": pos.last_sale_price,
            "avg_cost": pos.cost_basis,
        })

    if pos_records:
        df_pos = pd.DataFrame(pos_records)
    else:
        df_pos = pd.DataFrame(columns=[
            "date", "instrument", "name", "volume", "ratio",
            "cum_profit", "cum_return", "close_price", "avg_cost",
        ])
    df_pos.to_parquet(pos_path, index=False)

    # ------------------------------------------------------------------
    # 3. orders — 有订单时追加（按日期去重，同一天的重复运行只保留最新）
    # ------------------------------------------------------------------
    order_path = os.path.join(account_dir, "orders.parquet")

    order_records = []
    for o in context.logs.order_list:
        if hasattr(o.date, "strftime"):
            order_date = o.date.strftime("%Y-%m-%d")
        else:
            order_date = str(o.date) if o.date else today

        status_str = "filled" if o.status == 1 else "rejected"
        side_str = "buy" if o.is_buy else "sell"

        order_records.append({
            "date": order_date,
            "instrument": o.code,
            "name": _get_instrument_name(o.code),
            "volume": o.amount,
            "side": side_str,
            "status": status_str,
            "price": o.price if o.price is not None else 0.0,
            "cost": getattr(o, "cost", 0.0),
        })

    if order_records:
        df_new = pd.DataFrame(order_records)
        if os.path.exists(order_path):
            df_existing = pd.read_parquet(order_path)
            # 去重：删除已有同日期记录，追加最新结果
            df_existing = df_existing[df_existing["date"] != today]
            df_orders = pd.concat([df_existing, df_new], ignore_index=True)
        else:
            df_orders = df_new
        df_orders.to_parquet(order_path, index=False)

    print(
        f"  [实盘存储] daily: {len(df_nav)} 条, "
        f"positions: {len(pos_records)}, orders: {len(order_records)}"
    )
