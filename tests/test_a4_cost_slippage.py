"""A4 测试用例：OrderCost / FixedSlippage / PriceRelatedSlippage"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.objects import OrderCost, FixedSlippage, PriceRelatedSlippage


def test_ordercost_defaults():
    """默认费率：A 股标准（印花税千一、佣金万三、最低 5 元）"""
    oc = OrderCost()
    assert oc.open_tax == 0
    assert oc.close_tax == 0.001
    assert oc.open_commission == 0.0003
    assert oc.close_commission == 0.0003
    assert oc.close_today_commission == 0
    assert oc.min_commission == 5
    print("[PASS] OrderCost 默认值")


def test_ordercost_custom():
    """自定义费率"""
    oc = OrderCost(
        open_tax=0,
        close_tax=0.0005,
        open_commission=0.0002,
        close_commission=0.0002,
        min_commission=0,
    )
    assert oc.close_tax == 0.0005
    assert oc.open_commission == 0.0002
    assert oc.min_commission == 0
    print("[PASS] OrderCost 自定义")


def test_ordercost_repr():
    """__repr__ 不报错且包含关键信息"""
    oc = OrderCost()
    r = repr(oc)
    assert "open_tax" in r
    assert "min_comm" in r
    print("[PASS] OrderCost __repr__")


def test_fixed_slippage():
    """固定金额滑点"""
    fs = FixedSlippage(0.02)
    assert fs.value == 0.02
    assert fs.type == "fixed"
    print("[PASS] FixedSlippage")


def test_price_related_slippage():
    """按比例滑点"""
    ps = PriceRelatedSlippage(0.002)
    assert ps.value == 0.002
    assert ps.type == "pricerelated"
    print("[PASS] PriceRelatedSlippage")


def test_slippage_repr():
    """Slippage __repr__ 不报错"""
    fs = FixedSlippage(0.01)
    ps = PriceRelatedSlippage(0.001)
    assert "0.01" in repr(fs)
    assert "0.001" in repr(ps)
    print("[PASS] Slippage __repr__")


if __name__ == "__main__":
    test_ordercost_defaults()
    test_ordercost_custom()
    test_ordercost_repr()
    test_fixed_slippage()
    test_price_related_slippage()
    test_slippage_repr()
    print("\nAll A4 tests passed.")
