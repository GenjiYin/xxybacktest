"""
xxybacktest — A股量化回测框架

使用方式:
    from xxybacktest import run_backtest, OrderCost, FixedSlippage
    from xxybacktest import order, order_value, order_target_value, order_target_percent
"""

from .backtest import run_backtest
from .objects import (
    Position,
    Order,
    OrderCost,
    FixedSlippage,
    PriceRelatedSlippage,
)
from .trading import (
    order,
    order_buy,
    order_sell,
    order_value,
    order_target_value,
    order_target_percent,
    inout_cash,
)
from .context import DictObj, create_context
from .events import Event, load_events, insert_event, register_daily
from .performance import Performance
from .rules import Rules
from .types import Context
from .data import Data

# 模拟交易模块
from . import simulation

__version__ = "0.1.0"
