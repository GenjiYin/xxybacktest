"""D1 买入结算测试

验证: 新建持仓、加仓、费用计算、资金扣减、规则拦截。
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.context import create_context, DictObj
from xxybacktest.trading import order_buy
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
# 新建持仓
# ------------------------------------------------------------------

def test_new_position():
    """首次买入：创建持仓，扣减资金。"""
    ctx = make_context(cash=1000000)
    order = order_buy("000001.SZ", 1000, ctx)

    assert order.status == 1

    # 持仓已建立
    assert "000001.SZ" in ctx.portfolio.positions
    pos = ctx.portfolio.positions["000001.SZ"]
    assert pos.amount == 1000
    assert pos.code == "000001.SZ"

    # 价格应为当日 open（09:30 时刻）
    info = Data.get_daily_info("000001.SZ", ctx)
    assert pos.last_sale_price == info.open


def test_new_position_cash_deducted():
    """买入后现金减少 = 成交金额 + 手续费 + 滑点。"""
    ctx = make_context(cash=1000000)
    initial_cash = ctx.portfolio.cash

    order = order_buy("000001.SZ", 1000, ctx)

    expected_deduction = order.value + order.cost + order.slip_value
    assert ctx.portfolio.cash == initial_cash - expected_deduction


def test_new_position_total_value():
    """买入后 total_value = cash + positions_value。"""
    ctx = make_context(cash=1000000)
    order = order_buy("000001.SZ", 1000, ctx)

    assert ctx.portfolio.total_value == (
        ctx.portfolio.cash + ctx.portfolio.positions_value
    )


def test_new_position_cost_basis():
    """新建持仓的 cost_basis = (amount * price + 手续费) / amount。"""
    ctx = make_context(cash=1000000)
    order = order_buy("000001.SZ", 1000, ctx)

    pos = ctx.portfolio.positions["000001.SZ"]
    expected_cost_basis = (order.amount * order.last_sale_price + order.cost) / order.amount
    assert abs(pos.cost_basis - expected_cost_basis) < 0.0001


# ------------------------------------------------------------------
# 加仓
# ------------------------------------------------------------------

def test_add_position():
    """加仓：amount 累加，cost_basis 加权平均。"""
    ctx = make_context(cash=1000000)

    order1 = order_buy("000001.SZ", 500, ctx)
    pos = ctx.portfolio.positions["000001.SZ"]
    amount_after_first = pos.amount
    cost_after_first = pos.total_cost

    order2 = order_buy("000001.SZ", 300, ctx)
    assert pos.amount == amount_after_first + 300
    assert pos.total_cost == cost_after_first + order2.cost + 300 * order2.last_sale_price
    assert abs(pos.cost_basis - pos.total_cost / pos.amount) < 0.0001


def test_add_position_enable_amount_without_t1():
    """不配 rule_t1 时（T+0），加仓后 enable_amount 增加。"""
    ctx = make_context(cash=1000000)  # rule_list="rule_stop"，无 rule_t1

    order1 = order_buy("000001.SZ", 500, ctx)
    pos = ctx.portfolio.positions["000001.SZ"]
    # 无 rule_t1，enable_amount = amount = 500
    assert pos.enable_amount == 500

    order2 = order_buy("000001.SZ", 300, ctx)
    # T+0：新买的也可卖，enable_amount 增加
    assert pos.enable_amount == 800


def test_add_position_enable_amount_with_t1():
    """配 rule_t1 时（A股 T+1），加仓后 enable_amount 不增加。"""
    ctx = make_context(cash=1000000)
    ctx.trade.rule_list = "rule_stop,rule_t1"

    order1 = order_buy("000001.SZ", 500, ctx)
    pos = ctx.portfolio.positions["000001.SZ"]
    # rule_t1 将 enable_amount 设为 0
    assert pos.enable_amount == 0

    order2 = order_buy("000001.SZ", 300, ctx)
    # T+1：新买的不可卖，enable_amount 仍为 0
    assert pos.enable_amount == 0


# ------------------------------------------------------------------
# 费用
# ------------------------------------------------------------------

def test_min_commission():
    """小单佣金不低于 min_commission（5 元）。"""
    ctx = make_context(cash=1000000)
    order = order_buy("000001.SZ", 100, ctx)  # 小单

    assert order.status == 1
    # 100 股 × ~10 元 = ~1000 元，佣金 = 1000*0.0003=0.3 < 5
    assert order.cost >= 5.0


def test_buy_no_tax():
    """A 股买入无印花税（open_tax=0）。"""
    ctx = make_context(cash=1000000)
    order = order_buy("000001.SZ", 1000, ctx)

    # 买入费用 = 仅佣金（无税）
    value = order.value
    commission = max(value * 0.0003, 5)
    assert abs(order.cost - commission) < 0.0001


# ------------------------------------------------------------------
# 规则拦截
# ------------------------------------------------------------------

def test_nonexistent_stock_rejected():
    """不存在的股票被拒绝。"""
    ctx = make_context(cash=1000000)
    order = order_buy("999999.SZ", 1000, ctx)

    assert order.status == -1
    assert "999999.SZ" not in ctx.portfolio.positions
    assert ctx.portfolio.cash == 1000000  # 资金不变


# ------------------------------------------------------------------
# 日志记录
# ------------------------------------------------------------------

def test_order_logged():
    """所有订单都记入 order_list。"""
    ctx = make_context(cash=1000000)
    order_buy("000001.SZ", 1000, ctx)

    assert len(ctx.logs.order_list) == 1


def test_trade_logged():
    """成交的订单记入 trade_list。"""
    ctx = make_context(cash=1000000)
    order_buy("000001.SZ", 1000, ctx)

    assert len(ctx.logs.trade_list) == 1


def test_rejected_not_in_trade_list():
    """被拒的订单不记入 trade_list。"""
    ctx = make_context(cash=1000000)
    order_buy("999999.SZ", 1000, ctx)

    assert len(ctx.logs.order_list) == 1
    assert len(ctx.logs.trade_list) == 0


if __name__ == "__main__":
    setup_module()
    test_new_position()
    test_new_position_cash_deducted()
    test_new_position_total_value()
    test_new_position_cost_basis()
    test_add_position()
    test_add_position_enable_amount_without_t1()
    test_add_position_enable_amount_with_t1()
    test_min_commission()
    test_buy_no_tax()
    test_nonexistent_stock_rejected()
    test_order_logged()
    test_trade_logged()
    test_rejected_not_in_trade_list()
    print("All D1 tests passed.")
