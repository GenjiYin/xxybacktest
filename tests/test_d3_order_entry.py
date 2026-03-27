"""D3 下单入口测试

验证: order（按数量）、order_value（按金额）、order_target_value（调仓至目标市值）、
      order_target_percent（按总资产百分比调仓，二创扩展）。
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.context import create_context
from xxybacktest.trading import order, order_value, order_target_value, order_target_percent, order_buy
from xxybacktest.data import Data

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data")

def setup_module():
    Data.init_db(DATA_PATH)


def make_context(cash=1000000, rule_list="rule_stop", dt_str="2024-01-02 09:30:00"):
    """构造可交易的 context。"""
    ctx = create_context()
    ctx.portfolio.cash = cash
    ctx.portfolio.total_value = cash
    ctx.portfolio.starting_cash = cash
    ctx.trade.rule_list = rule_list
    ctx.current_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    ctx.previous_date = None
    return ctx


# ------------------------------------------------------------------
# order: 按数量下单
# ------------------------------------------------------------------

def test_order_positive_buys():
    """order(amount>0) 走买入路径。"""
    ctx = make_context()
    result = order("000001.SZ", 1000, ctx)

    assert result is not None
    assert result.status == 1
    assert result.is_buy is True
    assert "000001.SZ" in ctx.portfolio.positions
    assert ctx.portfolio.positions["000001.SZ"].amount == 1000


def test_order_negative_sells():
    """order(amount<0) 走卖出路径。"""
    ctx = make_context()
    # 先买入建仓
    order_buy("000001.SZ", 1000, ctx)
    # 模拟 T+1：手动解锁 enable_amount
    ctx.portfolio.positions["000001.SZ"].enable_amount = 1000

    result = order("000001.SZ", -500, ctx)

    assert result is not None
    assert result.status == 1
    assert result.is_buy is False
    assert ctx.portfolio.positions["000001.SZ"].amount == 500


def test_order_zero_returns_none():
    """order(amount=0) 不下单，返回 None。"""
    ctx = make_context()
    result = order("000001.SZ", 0, ctx)
    assert result is None


def test_order_sell_clears_position():
    """order 负数清仓。"""
    ctx = make_context()
    order_buy("000001.SZ", 1000, ctx)
    ctx.portfolio.positions["000001.SZ"].enable_amount = 1000

    result = order("000001.SZ", -1000, ctx)

    assert result.status == 1
    assert "000001.SZ" not in ctx.portfolio.positions


# ------------------------------------------------------------------
# order_value: 按金额下单
# ------------------------------------------------------------------

def test_order_value_positive_buys():
    """order_value(value>0) 买入对应金额的股票。"""
    ctx = make_context()
    price = Data.get_price("000001.SZ", ctx)
    target_value = 10000.0

    result = order_value("000001.SZ", target_value, ctx)

    assert result is not None
    assert result.status == 1
    assert result.is_buy is True

    expected_amount = int(target_value / price)
    assert result.amount == expected_amount


def test_order_value_negative_sells():
    """order_value(value<0) 卖出对应金额的股票。"""
    ctx = make_context()
    order_buy("000001.SZ", 2000, ctx)
    ctx.portfolio.positions["000001.SZ"].enable_amount = 2000

    price = Data.get_price("000001.SZ", ctx)
    sell_value = -5000.0

    result = order_value("000001.SZ", sell_value, ctx)

    assert result is not None
    assert result.status == 1
    assert result.is_buy is False

    expected_amount = int(5000.0 / price)
    assert result.amount == expected_amount


def test_order_value_zero_returns_none():
    """order_value(value=0) 不下单。"""
    ctx = make_context()
    result = order_value("000001.SZ", 0, ctx)
    assert result is None


def test_order_value_tiny_returns_none():
    """金额太小（不足 1 股）时不下单。"""
    ctx = make_context()
    result = order_value("000001.SZ", 0.01, ctx)
    assert result is None


def test_order_value_invalid_stock():
    """不存在的股票，get_price 返回 None，直接返回 None。"""
    ctx = make_context()
    result = order_value("999999.SZ", 10000, ctx)
    assert result is None


# ------------------------------------------------------------------
# order_target_value: 调仓至目标市值
# ------------------------------------------------------------------

def test_target_value_from_zero():
    """无持仓时调仓 = 纯买入。"""
    ctx = make_context()
    price = Data.get_price("000001.SZ", ctx)
    target = 50000.0

    result = order_target_value("000001.SZ", target, ctx)

    assert result is not None
    assert result.status == 1
    assert result.is_buy is True

    expected_amount = int(target / price)
    assert result.amount == expected_amount


def test_target_value_increase():
    """持仓不足时加仓。"""
    ctx = make_context()
    order_buy("000001.SZ", 500, ctx)

    price = Data.get_price("000001.SZ", ctx)
    target = 20000.0
    target_amount = int(target / price)
    change = target_amount - 500

    result = order_target_value("000001.SZ", target, ctx)

    assert result is not None
    if change > 0:
        assert result.is_buy is True
        assert result.amount == change


def test_target_value_decrease():
    """持仓过多时减仓。"""
    ctx = make_context()
    order_buy("000001.SZ", 3000, ctx)
    ctx.portfolio.positions["000001.SZ"].enable_amount = 3000

    price = Data.get_price("000001.SZ", ctx)
    target = 10000.0
    target_amount = int(target / price)
    change = target_amount - 3000

    result = order_target_value("000001.SZ", target, ctx)

    assert result is not None
    if change < 0:
        assert result.is_buy is False
        assert result.amount == -change


def test_target_value_zero_clears():
    """target=0 清仓。"""
    ctx = make_context()
    order_buy("000001.SZ", 1000, ctx)
    ctx.portfolio.positions["000001.SZ"].enable_amount = 1000

    result = order_target_value("000001.SZ", 0, ctx)

    assert result is not None
    assert result.is_buy is False
    assert "000001.SZ" not in ctx.portfolio.positions


def test_target_value_zero_no_position():
    """无持仓时 target=0，不报错，返回 None（修复原项目 Bug）。"""
    ctx = make_context()
    result = order_target_value("000001.SZ", 0, ctx)
    # change = 0 - 0 = 0 → order(sec, 0, ctx) → None
    assert result is None


def test_target_value_no_change():
    """持仓已匹配目标时不下单。"""
    ctx = make_context()
    price = Data.get_price("000001.SZ", ctx)
    # 买入刚好 int(target/price) 股
    exact_amount = int(50000 / price)
    order_buy("000001.SZ", exact_amount, ctx)

    result = order_target_value("000001.SZ", 50000.0, ctx)
    # change = int(50000/price) - exact_amount = 0
    assert result is None


def test_target_value_invalid_stock():
    """不存在的股票返回 None。"""
    ctx = make_context()
    result = order_target_value("999999.SZ", 10000, ctx)
    assert result is None


# ------------------------------------------------------------------
# order_target_percent: 按总资产百分比调仓（二创扩展）
# ------------------------------------------------------------------

def test_target_percent_buy_10pct():
    """无持仓时 10% 配置 = 买入 total_value*0.1 的市值。"""
    ctx = make_context(cash=1000000)
    price = Data.get_price("000001.SZ", ctx)
    target_value = 1000000 * 0.1

    result = order_target_percent("000001.SZ", 0.1, ctx)

    assert result is not None
    assert result.status == 1
    assert result.is_buy is True
    assert result.amount == int(target_value / price)


def test_target_percent_zero_clears():
    """percent=0 清仓。"""
    ctx = make_context()
    order_buy("000001.SZ", 1000, ctx)
    ctx.portfolio.positions["000001.SZ"].enable_amount = 1000

    result = order_target_percent("000001.SZ", 0.0, ctx)

    assert result is not None
    assert result.is_buy is False
    assert "000001.SZ" not in ctx.portfolio.positions


def test_target_percent_zero_no_position():
    """无持仓 + percent=0 不报错，返回 None。"""
    ctx = make_context()
    result = order_target_percent("000001.SZ", 0.0, ctx)
    assert result is None


def test_target_percent_negative_rejected():
    """percent<0 拒绝。"""
    ctx = make_context()
    result = order_target_percent("000001.SZ", -0.1, ctx)
    assert result is None


def test_target_percent_over_one_rejected():
    """percent>1 拒绝（不支持杠杆）。"""
    ctx = make_context()
    result = order_target_percent("000001.SZ", 1.5, ctx)
    assert result is None


def test_target_percent_full_allocation():
    """percent=1.0 全仓买入。"""
    ctx = make_context(cash=1000000)
    price = Data.get_price("000001.SZ", ctx)
    target_value = 1000000 * 1.0

    result = order_target_percent("000001.SZ", 1.0, ctx)

    assert result is not None
    assert result.status == 1
    assert result.is_buy is True
    assert result.amount == int(target_value / price)


def test_target_percent_reduce():
    """已持仓 50% 调到 20%，减仓。"""
    ctx = make_context(cash=1000000)
    price = Data.get_price("000001.SZ", ctx)

    # 先买入约 50% 仓位
    buy_amount = int(1000000 * 0.5 / price)
    order_buy("000001.SZ", buy_amount, ctx)
    ctx.portfolio.positions["000001.SZ"].enable_amount = buy_amount

    # 调到 20%
    total_value = ctx.portfolio.total_value
    target_value = total_value * 0.2
    target_amount = int(target_value / price)
    change = target_amount - ctx.portfolio.positions["000001.SZ"].amount

    result = order_target_percent("000001.SZ", 0.2, ctx)

    assert result is not None
    if change < 0:
        assert result.is_buy is False


def test_target_percent_invalid_stock():
    """不存在的股票返回 None。"""
    ctx = make_context()
    result = order_target_percent("999999.SZ", 0.1, ctx)
    assert result is None


if __name__ == "__main__":
    setup_module()
    test_order_positive_buys()
    test_order_negative_sells()
    test_order_zero_returns_none()
    test_order_sell_clears_position()
    test_order_value_positive_buys()
    test_order_value_negative_sells()
    test_order_value_zero_returns_none()
    test_order_value_tiny_returns_none()
    test_order_value_invalid_stock()
    test_target_value_from_zero()
    test_target_value_increase()
    test_target_value_decrease()
    test_target_value_zero_clears()
    test_target_value_zero_no_position()
    test_target_value_no_change()
    test_target_value_invalid_stock()
    test_target_percent_buy_10pct()
    test_target_percent_zero_clears()
    test_target_percent_zero_no_position()
    test_target_percent_negative_rejected()
    test_target_percent_over_one_rejected()
    test_target_percent_full_allocation()
    test_target_percent_reduce()
    test_target_percent_invalid_stock()
    print("All D3 tests passed.")
