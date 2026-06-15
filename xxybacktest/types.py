"""
类型提示（仅供 IDE 自动补全和类型检查用，不影响运行时）

使用方式:
    from xxybacktest.types import Context

    def handle_data(context: Context):
        context.portfolio.cash  # ← IDE 能补全
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Protocol

from .objects import Position, Order


class TradeConfig(Protocol):
    market: str
    model_id: str
    start_time: str
    end_time: str
    benchmark: str
    log_type: str
    record_type: str
    strategy: str
    order_volume_ratio: float
    slip: float
    sliptype: str
    rule_list: str


class AccountConfig(Protocol):
    username: str
    password: str
    account_id: str
    open_tax: float
    close_tax: float
    open_commission: float
    close_commission: float
    close_today_commission: float
    min_commission: float


class Portfolio(Protocol):
    inout_cash: float
    cash: float
    transferable_cash: float
    locked_cash: float
    margin: float
    total_value: float
    previous_value: float
    returns: float
    starting_cash: float
    positions_value: float
    portfolio_value: float
    positions: Dict[str, Position]


class DataStore(Protocol):
    calendar: List[str]
    event_list: list
    data_source: str
    daily_info: Any
    dividend: dict
    quote: Any
    client: Any


class Logs(Protocol):
    trade_list: list
    order_list: List[Order]
    position_list: list
    return_list: list
    trade_returns: List[float]
    history: dict


class Performance(Protocol):
    returns: List[list]
    bench_returns: list
    turnover: list
    win: int
    win_ratio: float
    trade_num: int
    indicators: dict


class Context(Protocol):
    id: str
    universe: list
    previous_date: Optional[str]
    previous_dt: Optional[datetime]
    current_dt: Optional[datetime]
    params: Any

    trade: TradeConfig
    account: AccountConfig
    portfolio: Portfolio
    data: DataStore
    logs: Logs
    performance: Performance
    data_path: str

    g: dict

    # H3 动态挂载
    run_daily: Callable[[Callable, str], None]
