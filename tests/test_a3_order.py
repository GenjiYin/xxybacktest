"""A3 测试用例：Order 订单对象"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.objects import Order
from xxybacktest.context import DictObj


def make_info():
    """构造一条模拟当日行情，供多个测试复用。"""
    return DictObj({
        "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2,
        "volume": 1000000, "amount": 10200000,
        "upLimit": 11.0, "downLimit": 9.0, "stop": 0,
    })


def test_buy_order():
    """正常买入订单，status 应为 1"""
    info = make_info()
    o = Order(code="000001.SZ", amount=500, is_buy=True, price=10.0, info=info)
    assert o.status == 1
    assert o.is_buy is True
    assert o.code == "000001.SZ"
    assert o.amount == 500
    assert o.price == 10.0
    assert o.info.open == 10.0
    print("[PASS] 正常买入订单")


def test_sell_order():
    """正常卖出订单，status 应为 1"""
    info = make_info()
    o = Order(code="000001.SZ", amount=200, is_buy=False, price=10.2, info=info)
    assert o.status == 1
    assert o.is_buy is False
    print("[PASS] 正常卖出订单")


def test_price_none_cancel():
    """price 为 None 时，订单自动取消 (status=-1)"""
    o = Order(code="000002.SZ", amount=100, is_buy=True, price=None, info=None)
    assert o.status == -1
    print("[PASS] price=None 自动取消")


def test_info_none_cancel():
    """info 为 None 时，即使 price 有值也应取消"""
    o = Order(code="000002.SZ", amount=100, is_buy=True, price=10.0, info=None)
    assert o.status == -1
    print("[PASS] info=None 自动取消")


def test_enable_amount_init():
    """enable_amount 初始等于 amount（T+1 规则会在后续改为 0）"""
    info = make_info()
    o = Order(code="000001.SZ", amount=300, is_buy=True, price=10.0, info=info)
    assert o.enable_amount == 300
    print("[PASS] enable_amount 初始等于 amount")


def test_default_cost_fields():
    """cost / slip_value / last_sale_price / value 初始为 0 或 None"""
    info = make_info()
    o = Order(code="000001.SZ", amount=100, is_buy=True, price=10.0, info=info)
    assert o.cost == 0
    assert o.slip_value == 0
    assert o.last_sale_price is None
    assert o.value == 0
    print("[PASS] 费用字段初始值")


def test_order_id_unique():
    """不同订单的 order_id 不同"""
    info = make_info()
    o1 = Order(code="000001.SZ", amount=100, is_buy=True, price=10.0, info=info)
    o2 = Order(code="000001.SZ", amount=100, is_buy=True, price=10.0, info=info)
    assert len(o1.order_id) == 64  # SHA256 hex
    assert o1.order_id != o2.order_id
    print("[PASS] 订单 ID 唯一")


def test_order_repr():
    """__repr__ 包含关键信息且不报错"""
    info = make_info()
    o = Order(code="600519.SH", amount=100, is_buy=True, price=1800.0, info=info)
    r = repr(o)
    assert "BUY" in r
    assert "600519.SH" in r
    assert "OK" in r

    o2 = Order(code="600519.SH", amount=100, is_buy=False, price=None, info=None)
    r2 = repr(o2)
    assert "SELL" in r2
    assert "CANCEL" in r2
    print("[PASS] __repr__")


if __name__ == "__main__":
    test_buy_order()
    test_sell_order()
    test_price_none_cancel()
    test_info_none_cancel()
    test_enable_amount_init()
    test_default_cost_fields()
    test_order_id_unique()
    test_order_repr()
    print("\nAll A3 tests passed.")
