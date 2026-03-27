"""A2 测试用例：Position 持仓对象"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.objects import Position
from xxybacktest.context import create_context


def test_position_basic_fields():
    """基本字段赋值"""
    p = Position(code="000001", amount=1000, enable_amount=0, last_sale_price=10.5)
    assert p.code == "000001"
    assert p.amount == 1000
    assert p.enable_amount == 0
    assert p.last_sale_price == 10.5
    print("[PASS] 基本字段")


def test_position_derived_fields():
    """派生字段自动计算"""
    p = Position(code="000001", amount=1000, enable_amount=0, last_sale_price=10.5)
    assert p.cost_basis == 10.5
    assert p.total_cost == 10500.0
    assert p.total_value == 10500.0
    print("[PASS] 派生字段")


def test_position_in_context():
    """Position 存入 context.portfolio.positions 后可正常读写"""
    ctx = create_context()
    p = Position(code="600519", amount=200, enable_amount=200, last_sale_price=1800.0)
    ctx.portfolio.positions["600519"] = p

    pos = ctx.portfolio.positions["600519"]
    assert pos.code == "600519"
    assert pos.amount == 200
    assert pos.total_value == 360000.0
    print("[PASS] 存入 context 并读取")


def test_position_mutable():
    """结算模块会直接修改 Position 字段，验证可变性"""
    p = Position(code="000001", amount=1000, enable_amount=0, last_sale_price=10.0)

    # 模拟 T+1：次日 enable_amount 刷新
    p.enable_amount = p.amount
    assert p.enable_amount == 1000

    # 模拟收盘估值：价格变动后刷新 total_value
    p.last_sale_price = 11.0
    p.total_value = p.amount * p.last_sale_price
    assert p.total_value == 11000.0

    # 模拟加仓后更新 cost_basis
    p.cost_basis = (10.0 * 1000 + 11.0 * 500) / 1500
    assert abs(p.cost_basis - 10.3333) < 0.001
    print("[PASS] 字段可变性")


def test_position_repr():
    """__repr__ 输出可读"""
    p = Position(code="000001", amount=100, enable_amount=100, last_sale_price=5.0)
    r = repr(p)
    assert "000001" in r
    assert "100" in r
    print("[PASS] __repr__")


if __name__ == "__main__":
    test_position_basic_fields()
    test_position_derived_fields()
    test_position_in_context()
    test_position_mutable()
    test_position_repr()
    print("\nAll A2 tests passed.")
