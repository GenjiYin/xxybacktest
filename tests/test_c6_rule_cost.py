"""C6 现金充足性检查测试（含滑点）

验证合并后的 rule_cost 规则：
- 现金充足（含滑点）→ 通过
- 现金不足但可缩量 → 缩减 amount
- 连开销都不够 → 拒绝
- 卖出不受此规则影响
- 滑点为 0 时退化为纯手续费检查
- 滑点越大，缩量越多
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


def make_context(cash=1000000, rule_list="rule_stop,rule_cost",
                 dt_str="2026-03-20 09:30:00", slip=0.002):
    ctx = create_context()
    ctx.portfolio.cash = cash
    ctx.portfolio.total_value = cash
    ctx.portfolio.starting_cash = cash
    ctx.trade.rule_list = rule_list
    ctx.trade.slip = slip
    ctx.current_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    ctx.previous_date = "2026-03-19"
    return ctx


# ------------------------------------------------------------------
# 现金充足 → 通过
# ------------------------------------------------------------------

def test_enough_cash():
    """现金充足（含滑点），正常买入，amount 不变。"""
    ctx = make_context(cash=1000000)
    result = order_buy("600519.SH", 100, ctx)
    assert result.status == 1
    assert result.amount == 100


# ------------------------------------------------------------------
# 现金不足 → 缩量
# ------------------------------------------------------------------

def test_not_enough_cash_shrink():
    """现金不够买 100 股（含滑点），缩量。
    600519.SH 2026-03-20 open=1452.96, slip=0.002
    100 股: value=145296, cost≈43.59, slip_value=290.59
    total_needed ≈ 145630.18
    给 50000 现金，缩量。
    """
    ctx = make_context(cash=50000)
    result = order_buy("600519.SH", 100, ctx)
    assert result.status == 1
    assert result.amount < 100
    assert result.amount > 0


def test_shrink_result_affordable():
    """缩量后买入不应导致现金为负。"""
    ctx = make_context(cash=50000)
    result = order_buy("600519.SH", 100, ctx)
    assert result.status == 1
    assert ctx.portfolio.cash >= 0


# ------------------------------------------------------------------
# 连开销都不够 → 拒绝
# ------------------------------------------------------------------

def test_no_cash_rejected():
    """现金为 0，直接拒绝。"""
    ctx = make_context(cash=10)
    result = order_buy("600519.SH", 100, ctx)
    assert result.status == -1


def test_tiny_cash_rejected():
    """现金极小（< 最低佣金 5 元），拒绝。"""
    ctx = make_context(cash=3)
    result = order_buy("600519.SH", 100, ctx)
    assert result.status == -1


# ------------------------------------------------------------------
# 卖出不受影响
# ------------------------------------------------------------------

def test_sell_not_affected():
    """卖出时 rule_cost 不检查，直接通过。"""
    ctx = make_context(cash=0)
    ctx.portfolio.positions["600519.SH"] = Position(
        code="600519.SH", amount=100, enable_amount=100,
        last_sale_price=1450.0
    )
    result = order_sell("600519.SH", 100, ctx)
    assert result.status == 1


# ------------------------------------------------------------------
# 滑点相关
# ------------------------------------------------------------------

def test_zero_slip():
    """slip=0 时，只检查手续费，不涉及滑点。"""
    ctx = make_context(cash=50000, slip=0)
    result = order_buy("600519.SH", 100, ctx)
    assert result.status == 1
    amount_no_slip = result.amount

    ctx2 = make_context(cash=50000, slip=0.002)
    result2 = order_buy("600519.SH", 100, ctx2)
    assert result2.status == 1
    # 有滑点时缩量更多（或相等）
    assert result2.amount <= amount_no_slip


def test_larger_slip_smaller_amount():
    """滑点越大，缩量越多。"""
    ctx_small = make_context(cash=50000, slip=0.001)
    r1 = order_buy("600519.SH", 100, ctx_small)

    ctx_large = make_context(cash=50000, slip=0.01)
    r2 = order_buy("600519.SH", 100, ctx_large)

    assert r1.status == 1
    assert r2.status == 1
    assert r2.amount <= r1.amount


# ------------------------------------------------------------------
# 不配 rule_cost 时不生效
# ------------------------------------------------------------------

def test_no_rule_cost():
    """rule_list 不含 rule_cost 时，现金不足也能下单。"""
    ctx = make_context(cash=50000, rule_list="rule_stop")
    result = order_buy("600519.SH", 100, ctx)
    assert result.status == 1
    assert result.amount == 100


if __name__ == "__main__":
    setup_module()
    test_enough_cash()
    print("[PASS] test_enough_cash")
    test_not_enough_cash_shrink()
    print("[PASS] test_not_enough_cash_shrink")
    test_shrink_result_affordable()
    print("[PASS] test_shrink_result_affordable")
    test_no_cash_rejected()
    print("[PASS] test_no_cash_rejected")
    test_tiny_cash_rejected()
    print("[PASS] test_tiny_cash_rejected")
    test_sell_not_affected()
    print("[PASS] test_sell_not_affected")
    test_zero_slip()
    print("[PASS] test_zero_slip")
    test_larger_slip_smaller_amount()
    print("[PASS] test_larger_slip_smaller_amount")
    test_no_rule_cost()
    print("[PASS] test_no_rule_cost")
    print()
    print("All C6 tests passed.")
