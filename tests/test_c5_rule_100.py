"""C5 兜底取整测试

验证 rule_100 规则：
- 非整手 → 取整到 100 的倍数
- 已是整手 → 不变
- < 100 股 → 归零拒绝
- 配合 C6：缩量后的非整手被兜底取整
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.context import create_context
from xxybacktest.trading import order_buy, order_sell
from xxybacktest.data import Data
from xxybacktest.objects import Position

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data")


def setup_module():
    Data.init_db(DATA_PATH)


def make_context(cash=1000000, rule_list="rule_stop,rule_100",
                 dt_str="2026-03-20 09:30:00"):
    ctx = create_context()
    ctx.portfolio.cash = cash
    ctx.portfolio.total_value = cash
    ctx.portfolio.starting_cash = cash
    ctx.trade.rule_list = rule_list
    ctx.current_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    ctx.previous_date = "2026-03-19"
    return ctx


# ------------------------------------------------------------------
# 基本取整
# ------------------------------------------------------------------

def test_round_down():
    """150 股 → 取整为 100 股。"""
    ctx = make_context()
    result = order_buy("600519.SH", 150, ctx)
    assert result.status == 1
    assert result.amount == 100


def test_exact_multiple():
    """300 股 → 不变。"""
    ctx = make_context()
    result = order_buy("600519.SH", 300, ctx)
    assert result.status == 1
    assert result.amount == 300


def test_less_than_100_rejected():
    """50 股 → < 100，归零，拒绝。"""
    ctx = make_context()
    result = order_buy("600519.SH", 50, ctx)
    assert result.status == -1


# ------------------------------------------------------------------
# 配合 C6 缩量后兜底
# ------------------------------------------------------------------

def test_cost_then_100():
    """C6 缩量产生非整手，C5 兜底取整。
    rule_list = rule_stop,rule_cost,rule_100
    600519.SH open=1452.96, 给 50000 现金
    C6 缩量后可能是 34 股（非整手），C5 取整后应为 0 → 拒绝
    """
    ctx = make_context(cash=50000, rule_list="rule_stop,rule_cost,rule_100")
    result = order_buy("600519.SH", 100, ctx)
    # 50000 / 1452.96 ≈ 34 股，取整后 < 100 → 拒绝
    assert result.status == -1


def test_cost_then_100_enough():
    """C6 缩量后仍 >= 100，C5 取整保留。
    给 200000 现金，C6 缩量后约 137 股，C5 取整为 100。
    """
    ctx = make_context(cash=200000, rule_list="rule_stop,rule_cost,rule_100")
    result = order_buy("600519.SH", 200, ctx)
    assert result.status == 1
    assert result.amount % 100 == 0


# ------------------------------------------------------------------
# 卖出也取整
# ------------------------------------------------------------------

def test_sell_rounds():
    """卖出 150 股（持仓 1000）→ 取整为 100。"""
    ctx = make_context(rule_list="rule_stop,rule_100")
    ctx.portfolio.positions["600519.SH"] = Position(
        code="600519.SH", amount=1000, enable_amount=1000,
        last_sale_price=1450.0
    )
    result = order_sell("600519.SH", 150, ctx)
    assert result.status == 1
    assert result.amount == 100


if __name__ == "__main__":
    setup_module()
    test_round_down()
    print("[PASS] test_round_down")
    test_exact_multiple()
    print("[PASS] test_exact_multiple")
    test_less_than_100_rejected()
    print("[PASS] test_less_than_100_rejected")
    test_cost_then_100()
    print("[PASS] test_cost_then_100")
    test_cost_then_100_enough()
    print("[PASS] test_cost_then_100_enough")
    test_sell_rounds()
    print("[PASS] test_sell_rounds")
    print()
    print("All C5 tests passed.")
