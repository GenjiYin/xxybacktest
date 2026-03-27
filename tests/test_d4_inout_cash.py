"""D4 出入金测试

验证 inout_cash：
- 入金：cash / total_value / starting_cash 同步增加
- 出金：三者同步减少
- 出金后 cash 可为负（不做校验，由策略负责）
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.context import create_context
from xxybacktest.trading import inout_cash


def make_context(cash=1000000):
    ctx = create_context()
    ctx.portfolio.cash = cash
    ctx.portfolio.total_value = cash
    ctx.portfolio.starting_cash = cash
    return ctx


def test_deposit():
    """入金 50 万，三个字段各加 50 万。"""
    ctx = make_context(cash=1000000)
    inout_cash(500000, ctx)
    assert ctx.portfolio.cash == 1500000
    assert ctx.portfolio.total_value == 1500000
    assert ctx.portfolio.starting_cash == 1500000


def test_withdraw():
    """出金 30 万，三个字段各减 30 万。"""
    ctx = make_context(cash=1000000)
    inout_cash(-300000, ctx)
    assert ctx.portfolio.cash == 700000
    assert ctx.portfolio.total_value == 700000
    assert ctx.portfolio.starting_cash == 700000


def test_zero():
    """出入金 0，无变化。"""
    ctx = make_context(cash=1000000)
    inout_cash(0, ctx)
    assert ctx.portfolio.cash == 1000000
    assert ctx.portfolio.total_value == 1000000
    assert ctx.portfolio.starting_cash == 1000000


def test_multiple_operations():
    """多次出入金累加。"""
    ctx = make_context(cash=1000000)
    inout_cash(200000, ctx)
    inout_cash(-50000, ctx)
    inout_cash(100000, ctx)
    assert ctx.portfolio.cash == 1250000
    assert ctx.portfolio.total_value == 1250000
    assert ctx.portfolio.starting_cash == 1250000


if __name__ == "__main__":
    test_deposit()
    print("[PASS] test_deposit")
    test_withdraw()
    print("[PASS] test_withdraw")
    test_zero()
    print("[PASS] test_zero")
    test_multiple_operations()
    print("[PASS] test_multiple_operations")
    print()
    print("All D4 tests passed.")
