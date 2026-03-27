"""C9 退市股买入拦截测试

验证 rule_delist 规则：
- 买入退市股（名称含 '退'）→ 拒绝
- 卖出退市股 → 不拦截
- 买入正常股 → 通过
- 不配此规则时不生效
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.context import create_context, DictObj
from xxybacktest.rules import Rules
from xxybacktest.objects import Order, Position


def make_context(rule_list="rule_stop,rule_delist"):
    ctx = create_context()
    ctx.portfolio.cash = 1000000
    ctx.portfolio.total_value = 1000000
    ctx.portfolio.starting_cash = 1000000
    ctx.trade.rule_list = rule_list
    ctx.current_dt = datetime(2026, 3, 20, 9, 30, 0)
    ctx.previous_date = "2026-03-19"
    return ctx


def make_info(name="贵州茅台", stop=0):
    """构造模拟 info 对象。"""
    return DictObj({
        "ts_code": "600519.SH",
        "name": name,
        "open": 1450.0,
        "high": 1460.0,
        "low": 1440.0,
        "close": 1455.0,
        "pre_close": 1448.0,
        "volume": 5000000,
        "amount": 7250000000.0,
        "vwap": 1450.0,
        "upLimit": 1592.8,
        "downLimit": 1303.2,
        "stop": stop,
        "st_status": 0,
    })


# ------------------------------------------------------------------
# 买入退市股 → 拒绝
# ------------------------------------------------------------------

def test_buy_delist_rejected():
    """名称含 '退' 的股票买入被拒。"""
    ctx = make_context()
    info = make_info(name="退市博元")
    order = Order("600519.SH", 100, is_buy=True, price=1450.0, info=info)
    Rules(order, ctx).apply()
    assert order.status == -1


def test_buy_delist_with_tui_in_middle():
    """名称中间含 '退' 也拒绝。"""
    ctx = make_context()
    info = make_info(name="*ST退市股")
    order = Order("600519.SH", 100, is_buy=True, price=1450.0, info=info)
    Rules(order, ctx).apply()
    assert order.status == -1


# ------------------------------------------------------------------
# 卖出退市股 → 不拦截
# ------------------------------------------------------------------

def test_sell_delist_allowed():
    """卖出退市股不被拦截。"""
    ctx = make_context(rule_list="rule_delist")
    ctx.portfolio.positions["600519.SH"] = Position(
        code="600519.SH", amount=1000, enable_amount=1000,
        last_sale_price=1450.0
    )
    info = make_info(name="退市博元")
    order = Order("600519.SH", 1000, is_buy=False, price=1450.0, info=info)
    Rules(order, ctx).apply()
    assert order.status == 1


# ------------------------------------------------------------------
# 买入正常股 → 通过
# ------------------------------------------------------------------

def test_buy_normal_stock():
    """正常股票买入通过。"""
    ctx = make_context()
    info = make_info(name="贵州茅台")
    order = Order("600519.SH", 100, is_buy=True, price=1450.0, info=info)
    Rules(order, ctx).apply()
    assert order.status == 1


def test_buy_st_stock_allowed():
    """ST 股买入不被 rule_delist 拦截（只拦退市）。"""
    ctx = make_context()
    info = make_info(name="*ST某某")
    order = Order("600519.SH", 100, is_buy=True, price=1450.0, info=info)
    Rules(order, ctx).apply()
    assert order.status == 1


# ------------------------------------------------------------------
# 不配此规则时不生效
# ------------------------------------------------------------------

def test_no_rule_delist():
    """rule_list 不含 rule_delist 时退市股也能买。"""
    ctx = make_context(rule_list="rule_stop")
    info = make_info(name="退市博元")
    order = Order("600519.SH", 100, is_buy=True, price=1450.0, info=info)
    Rules(order, ctx).apply()
    assert order.status == 1


if __name__ == "__main__":
    test_buy_delist_rejected()
    print("[PASS] test_buy_delist_rejected")
    test_buy_delist_with_tui_in_middle()
    print("[PASS] test_buy_delist_with_tui_in_middle")
    test_sell_delist_allowed()
    print("[PASS] test_sell_delist_allowed")
    test_buy_normal_stock()
    print("[PASS] test_buy_normal_stock")
    test_buy_st_stock_allowed()
    print("[PASS] test_buy_st_stock_allowed")
    test_no_rule_delist()
    print("[PASS] test_no_rule_delist")
    print()
    print("All C9 tests passed.")
