"""C0 规则引擎框架 + C1 rule_stop 测试"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.context import DictObj, create_context
from xxybacktest.objects import Order
from xxybacktest.rules import Rules


def make_context(rule_list="rule_stop"):
    """构造带默认费率的简易 context。"""
    ctx = create_context()
    ctx.trade.rule_list = rule_list
    return ctx


def make_info(stop=0, **kwargs):
    """构造一个最小的行情 DictObj。"""
    defaults = {
        "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
        "volume": 1000000, "amount": 10000000.0,
        "upLimit": 11.0, "downLimit": 9.0,
        "stop": stop, "name": "测试股票", "st_status": 0,
    }
    defaults.update(kwargs)
    return DictObj(defaults)


# ------------------------------------------------------------------
# C0 框架：规则链 + 费用计算
# ------------------------------------------------------------------

def test_apply_normal_buy():
    """正常买入：规则通过，费用正确计算。"""
    ctx = make_context("rule_stop")
    info = make_info()
    order = Order("000001.SZ", 1000, is_buy=True, price=10.0, info=info)

    Rules(order, ctx).apply()

    assert order.status == 1
    assert order.value == 1000 * 10.0  # 10000
    # 买入税 = 0（A股）
    # 佣金 = max(10000 * 0.0003, 5) = max(3, 5) = 5
    assert order.cost == 5.0
    assert order.slip_value == 0.0  # 默认无滑点
    assert order.last_sale_price == 10.0


def test_apply_normal_sell():
    """正常卖出：印花税 + 佣金。"""
    ctx = make_context("rule_stop")
    info = make_info()
    order = Order("000001.SZ", 1000, is_buy=False, price=10.0, info=info)

    Rules(order, ctx).apply()

    assert order.status == 1
    # 卖出税 = 10000 * 0.001 = 10
    # 佣金 = max(10000 * 0.0003, 5) = 5
    assert order.cost == 10.0 + 5.0


def test_apply_large_order_commission():
    """大单佣金超过最低佣金。"""
    ctx = make_context("rule_stop")
    info = make_info()
    # 100000 股 × 10 元 = 1000000 元
    order = Order("000001.SZ", 100000, is_buy=True, price=10.0, info=info)

    Rules(order, ctx).apply()

    # 佣金 = 1000000 * 0.0003 = 300 > 5
    assert order.cost == 300.0


def test_apply_with_slippage():
    """有滑点时 slip_value 正确计算。"""
    ctx = make_context("rule_stop")
    ctx.trade.slip = 0.002  # 千二滑点
    info = make_info()
    order = Order("000001.SZ", 1000, is_buy=True, price=10.0, info=info)

    Rules(order, ctx).apply()

    assert order.slip_value == 10000 * 0.002  # 20.0


def test_apply_empty_rule_list():
    """空规则链：直接计算费用，不拦截。"""
    ctx = make_context("")
    info = make_info()
    order = Order("000001.SZ", 1000, is_buy=True, price=10.0, info=info)

    Rules(order, ctx).apply()

    assert order.status == 1
    assert order.value == 10000


def test_apply_already_cancelled():
    """已取消的订单（price=None）不处理。"""
    ctx = make_context("rule_stop")
    order = Order("000001.SZ", 1000, is_buy=True, price=None, info=None)

    assert order.status == -1
    Rules(order, ctx).apply()
    assert order.status == -1  # 保持取消
    assert order.value == 0    # 费用未计算


def test_apply_zero_amount():
    """数量为 0 直接取消。"""
    ctx = make_context("rule_stop")
    info = make_info()
    order = Order("000001.SZ", 0, is_buy=True, price=10.0, info=info)

    Rules(order, ctx).apply()

    assert order.status == -1


def test_unknown_rule_skipped():
    """未实现的规则名被跳过，不报错。"""
    ctx = make_context("rule_stop,rule_nonexistent")
    info = make_info()
    order = Order("000001.SZ", 1000, is_buy=True, price=10.0, info=info)

    Rules(order, ctx).apply()

    assert order.status == 1  # rule_stop 通过，未知规则跳过


# ------------------------------------------------------------------
# C1: rule_stop — 停牌检查
# ------------------------------------------------------------------

def test_rule_stop_suspended():
    """停牌股被拦截。"""
    ctx = make_context("rule_stop")
    info = make_info(stop=1)
    order = Order("000001.SZ", 1000, is_buy=True, price=10.0, info=info)

    Rules(order, ctx).apply()

    assert order.status == -1


def test_rule_stop_zero_price():
    """价格为 0 被拦截。"""
    ctx = make_context("rule_stop")
    info = make_info()
    order = Order("000001.SZ", 1000, is_buy=True, price=0, info=info)

    Rules(order, ctx).apply()

    assert order.status == -1


def test_rule_stop_nan_price():
    """价格为 NaN 被拦截。"""
    ctx = make_context("rule_stop")
    info = make_info()
    order = Order("000001.SZ", 1000, is_buy=True, price=float('nan'), info=info)

    Rules(order, ctx).apply()

    assert order.status == -1


def test_rule_stop_no_info():
    """无行情数据被拦截。"""
    ctx = make_context("rule_stop")
    order = Order("000001.SZ", 1000, is_buy=True, price=10.0, info=None)

    # info=None 时 Order 构造已设 status=-1，apply 直接跳过
    Rules(order, ctx).apply()
    assert order.status == -1


def test_rule_stop_normal_passes():
    """正常行情+正常价格通过。"""
    ctx = make_context("rule_stop")
    info = make_info(stop=0)
    order = Order("000001.SZ", 1000, is_buy=True, price=10.0, info=info)

    Rules(order, ctx).apply()

    assert order.status == 1


if __name__ == "__main__":
    test_apply_normal_buy()
    test_apply_normal_sell()
    test_apply_large_order_commission()
    test_apply_with_slippage()
    test_apply_empty_rule_list()
    test_apply_already_cancelled()
    test_apply_zero_amount()
    test_unknown_rule_skipped()
    test_rule_stop_suspended()
    test_rule_stop_zero_price()
    test_rule_stop_nan_price()
    test_rule_stop_no_info()
    test_rule_stop_normal_passes()
    print("All C0/C1 tests passed.")
