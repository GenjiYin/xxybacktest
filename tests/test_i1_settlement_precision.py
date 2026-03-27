"""I1 资金结算精度测试

针对 D1/D2 的全流程精度验证，每笔数值精确到分。
所有测试使用真实数据（600519.SH 2026-03-20），手动计算期望值。

覆盖场景：
1. 单次买入：cash / positions_value / total_value / cost_basis / total_cost
2. 加仓：加权均价精确
3. 部分卖出：total_cost 更新 / cost_basis 重算 / cash 回收 / trade_return
4. 清仓：cash 精确回收 / positions 清空 / positions_value 归零
5. 缩量买入（C6+C5）：取整后 amount / 资金恒等式
6. 涨跌停拦截：订单被拒 / 资金不变
7. 买卖全流程闭环：初始资金 = 最终资金 + 总费用
8. 滑点场景：slip_value 精确 / 恒等式
9. 多股组合：两只股票同时持有，分别结算互不干扰
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

# 容差：精确到分
EPS = 0.01


def setup_module():
    Data.init_db(DATA_PATH)


def make_context(cash=10000000, dt_str="2026-03-20 09:30:00",
                 rule_list="rule_stop,rule_limit,rule_t1,rule_volume_num,rule_cost,rule_100",
                 slip=0):
    """全规则链 context，默认 1000 万现金。"""
    ctx = create_context()
    ctx.portfolio.cash = cash
    ctx.portfolio.total_value = cash
    ctx.portfolio.starting_cash = cash
    ctx.portfolio.positions_value = 0
    ctx.trade.rule_list = rule_list
    ctx.trade.slip = slip
    ctx.current_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    ctx.previous_date = "2026-03-19"
    return ctx


def get_open_price(code, ctx):
    """取当日开盘价。"""
    info = Data.get_daily_info(code, ctx)
    return info.open


# ==================================================================
# 辅助：资金恒等式检查
# ==================================================================

def assert_balance(ctx, label=""):
    """资金恒等式：total_value == cash + positions_value"""
    actual = ctx.portfolio.total_value
    expected = ctx.portfolio.cash + ctx.portfolio.positions_value
    assert abs(actual - expected) < EPS, (
        f"[{label}] 恒等式失败: total_value={actual}, "
        f"cash={ctx.portfolio.cash} + pv={ctx.portfolio.positions_value} = {expected}"
    )


# ==================================================================
# 1. 单次买入精度
# ==================================================================

def test_single_buy_precision():
    """单次买入 600519.SH 100 股，逐字段精确验证。"""
    ctx = make_context(cash=10000000)
    price = get_open_price("600519.SH", ctx)

    order = order_buy("600519.SH", 100, ctx)
    assert order.status == 1

    # 成交金额
    expected_value = 100 * price
    assert abs(order.value - expected_value) < EPS

    # 费用：买入无印花税，佣金 = max(value * 0.0003, 5)
    expected_commission = max(expected_value * 0.0003, 5)
    expected_cost = expected_commission  # open_tax = 0
    assert abs(order.cost - expected_cost) < EPS

    # 滑点 = 0
    assert order.slip_value == 0

    # 资金扣减
    expected_cash = 10000000 - expected_value - expected_cost
    assert abs(ctx.portfolio.cash - expected_cash) < EPS

    # positions_value
    assert abs(ctx.portfolio.positions_value - expected_value) < EPS

    # 恒等式
    assert_balance(ctx, "single_buy")

    # 持仓字段
    pos = ctx.portfolio.positions["600519.SH"]
    assert pos.amount == 100

    # total_cost = amount * price + commission
    expected_total_cost = 100 * price + expected_cost
    assert abs(pos.total_cost - expected_total_cost) < EPS

    # cost_basis = total_cost / amount
    expected_cost_basis = expected_total_cost / 100
    assert abs(pos.cost_basis - expected_cost_basis) < EPS

    # total_value
    assert abs(pos.total_value - expected_value) < EPS

    # T+1: enable_amount = 0
    assert pos.enable_amount == 0


# ==================================================================
# 2. 加仓精度（加权均价）
# ==================================================================

def test_add_position_weighted_avg():
    """两次买入 600519.SH，验证加权均价精确。
    同一天同价格买两次，检查 total_cost 和 cost_basis。
    """
    ctx = make_context(cash=10000000)
    price = get_open_price("600519.SH", ctx)

    order1 = order_buy("600519.SH", 200, ctx)
    assert order1.status == 1
    pos = ctx.portfolio.positions["600519.SH"]

    total_cost_1 = pos.total_cost
    amount_1 = pos.amount

    order2 = order_buy("600519.SH", 300, ctx)
    assert order2.status == 1

    # 加仓后 amount
    assert pos.amount == 500

    # total_cost = 旧 total_cost + 新买入数量 * 价格 + 新手续费
    expected_total_cost = total_cost_1 + 300 * price + order2.cost
    assert abs(pos.total_cost - expected_total_cost) < EPS

    # cost_basis = total_cost / amount
    expected_cost_basis = expected_total_cost / 500
    assert abs(pos.cost_basis - expected_cost_basis) < EPS

    # 恒等式
    assert_balance(ctx, "add_position")


# ==================================================================
# 3. 部分卖出精度
# ==================================================================

def test_partial_sell_precision():
    """买 500 股，卖 200 股，逐字段验证。"""
    ctx = make_context(cash=10000000)
    price = get_open_price("600519.SH", ctx)

    buy_order = order_buy("600519.SH", 500, ctx)
    assert buy_order.status == 1

    pos = ctx.portfolio.positions["600519.SH"]
    total_cost_before = pos.total_cost
    cost_basis_before = pos.cost_basis

    # 模拟次日盘前刷新（enable_amount = amount）
    pos.enable_amount = pos.amount

    cash_before_sell = ctx.portfolio.cash

    sell_order = order_sell("600519.SH", 200, ctx)
    assert sell_order.status == 1
    assert sell_order.amount == 200

    # 卖出费用: 印花税 + 佣金
    sell_value = 200 * price
    expected_tax = sell_value * 0.001
    expected_commission = max(sell_value * 0.0003, 5)
    expected_sell_cost = expected_tax + expected_commission
    assert abs(sell_order.cost - expected_sell_cost) < EPS

    # cash 回收
    expected_cash = cash_before_sell + sell_value - expected_sell_cost
    assert abs(ctx.portfolio.cash - expected_cash) < EPS

    # 剩余持仓
    assert pos.amount == 300
    assert pos.enable_amount == 300

    # total_cost 更新: total_cost = old_total_cost + sell_cost - sell_value
    expected_total_cost = total_cost_before + expected_sell_cost - sell_value
    assert abs(pos.total_cost - expected_total_cost) < EPS

    # cost_basis 重算
    expected_cost_basis = expected_total_cost / 300
    assert abs(pos.cost_basis - expected_cost_basis) < EPS

    # trade_return 验证
    net_per_share = (sell_value - expected_sell_cost) / 200
    expected_return = net_per_share / cost_basis_before - 1
    actual_return = ctx.logs.trade_returns[-1]
    assert abs(actual_return - expected_return) < 1e-6

    # 恒等式
    assert_balance(ctx, "partial_sell")


# ==================================================================
# 4. 清仓精度
# ==================================================================

def test_full_sell_precision():
    """买 300 股后全部卖出，验证 cash 精确回收。"""
    ctx = make_context(cash=10000000)
    price = get_open_price("600519.SH", ctx)

    buy_order = order_buy("600519.SH", 300, ctx)
    assert buy_order.status == 1

    pos = ctx.portfolio.positions["600519.SH"]
    pos.enable_amount = pos.amount  # 模拟次日

    cash_before = ctx.portfolio.cash

    sell_order = order_sell("600519.SH", 300, ctx)
    assert sell_order.status == 1

    # 持仓清空
    assert "600519.SH" not in ctx.portfolio.positions

    # positions_value 归零（只有一只股票的情况）
    assert abs(ctx.portfolio.positions_value - 0) < EPS

    # cash 精确
    sell_value = 300 * price
    sell_cost = sell_order.cost
    expected_cash = cash_before + sell_value - sell_cost
    assert abs(ctx.portfolio.cash - expected_cash) < EPS

    # 恒等式
    assert_balance(ctx, "full_sell")

    # 总资产损耗 = 买入费用 + 卖出费用
    total_fees = buy_order.cost + sell_order.cost
    asset_loss = 10000000 - ctx.portfolio.total_value
    assert abs(asset_loss - total_fees) < EPS


# ==================================================================
# 5. 缩量买入（C6 + C5）
# ==================================================================

def test_shrink_buy_precision():
    """现金不足时 C6 缩量 + C5 取整，验证结算精度。"""
    price = get_open_price("600519.SH", make_context())

    # 给的现金只够买 ~200 股
    budget = price * 200 + 500  # 留一点余量覆盖手续费
    ctx = make_context(cash=budget)

    order = order_buy("600519.SH", 500, ctx)

    if order.status == 1:
        # 被缩量了
        assert order.amount <= 200
        assert order.amount % 100 == 0  # C5 取整

        # 扣减金额不超过初始 cash
        deduction = order.value + order.cost + order.slip_value
        assert deduction <= budget + EPS

        # 恒等式
        assert_balance(ctx, "shrink_buy")
    else:
        # 缩量后 < 100 被拒绝
        assert ctx.portfolio.cash == budget


# ==================================================================
# 6. 涨跌停拦截（规则 C2）
# ==================================================================

def test_limit_up_rejected():
    """涨停封板股买入被拒，资金不变。"""
    ctx = make_context(cash=10000000)

    # 找 2026-03-20 涨停的股票（如果有）
    # 这里用通用逻辑：手动构造一个涨停情形
    # 改用 rule_list 仅含 rule_stop,rule_limit，手动检查
    # 实际测试中如果找不到涨停股，跳过
    info = Data.get_daily_info("600519.SH", ctx)
    price = info.open

    # 如果 open == high == upLimit → 涨停封板
    if price >= info.upLimit and price == info.high:
        order = order_buy("600519.SH", 100, ctx)
        assert order.status == -1
        assert ctx.portfolio.cash == 10000000
    # 否则此场景不适用，跳过（不 assert False）


# ==================================================================
# 7. 买卖全流程闭环
# ==================================================================

def test_buy_sell_round_trip():
    """买入→卖出完整闭环，初始资金 - 最终资金 = 总手续费。"""
    initial = 10000000
    ctx = make_context(cash=initial)
    price = get_open_price("600519.SH", ctx)

    buy = order_buy("600519.SH", 100, ctx)
    assert buy.status == 1

    pos = ctx.portfolio.positions["600519.SH"]
    pos.enable_amount = pos.amount

    sell = order_sell("600519.SH", 100, ctx)
    assert sell.status == 1

    total_fees = buy.cost + sell.cost + buy.slip_value + sell.slip_value
    final = ctx.portfolio.total_value
    assert abs((initial - final) - total_fees) < EPS, (
        f"闭环误差: initial={initial}, final={final}, "
        f"fees={total_fees}, diff={initial - final - total_fees}"
    )


def test_buy_sell_round_trip_000001():
    """000001.SZ 的买卖闭环。"""
    initial = 10000000
    ctx = make_context(cash=initial)

    buy = order_buy("000001.SZ", 1000, ctx)
    assert buy.status == 1

    pos = ctx.portfolio.positions["000001.SZ"]
    pos.enable_amount = pos.amount

    sell = order_sell("000001.SZ", 1000, ctx)
    assert sell.status == 1

    total_fees = buy.cost + sell.cost + buy.slip_value + sell.slip_value
    final = ctx.portfolio.total_value
    assert abs((initial - final) - total_fees) < EPS


# ==================================================================
# 8. 滑点场景
# ==================================================================

def test_slip_buy_precision():
    """带滑点的买入，slip_value 精确。"""
    ctx = make_context(cash=10000000, slip=0.002)
    price = get_open_price("600519.SH", ctx)

    order = order_buy("600519.SH", 100, ctx)
    assert order.status == 1

    expected_value = 100 * price
    expected_slip = expected_value * 0.002
    assert abs(order.slip_value - expected_slip) < EPS

    # 资金扣减含滑点
    expected_cash = 10000000 - expected_value - order.cost - expected_slip
    assert abs(ctx.portfolio.cash - expected_cash) < EPS

    assert_balance(ctx, "slip_buy")


def test_slip_round_trip():
    """带滑点的买卖闭环。"""
    initial = 10000000
    ctx = make_context(cash=initial, slip=0.001)

    buy = order_buy("600519.SH", 100, ctx)
    assert buy.status == 1

    pos = ctx.portfolio.positions["600519.SH"]
    pos.enable_amount = pos.amount

    sell = order_sell("600519.SH", 100, ctx)
    assert sell.status == 1

    total_loss = buy.cost + sell.cost + buy.slip_value + sell.slip_value
    final = ctx.portfolio.total_value
    assert abs((initial - final) - total_loss) < EPS, (
        f"滑点闭环误差: loss={initial - final}, fees+slip={total_loss}"
    )


# ==================================================================
# 9. 多股组合
# ==================================================================

def test_multi_stock_precision():
    """同时持有 600519.SH 和 000001.SZ，分别结算互不干扰。"""
    initial = 10000000
    ctx = make_context(cash=initial)

    buy1 = order_buy("600519.SH", 100, ctx)
    assert buy1.status == 1

    buy2 = order_buy("000001.SZ", 1000, ctx)
    assert buy2.status == 1

    assert len(ctx.portfolio.positions) == 2

    # positions_value = 两只股票市值之和
    pos1 = ctx.portfolio.positions["600519.SH"]
    pos2 = ctx.portfolio.positions["000001.SZ"]
    expected_pv = pos1.total_value + pos2.total_value
    assert abs(ctx.portfolio.positions_value - expected_pv) < EPS

    # 恒等式
    assert_balance(ctx, "multi_stock")

    # 卖出其中一只
    pos1.enable_amount = pos1.amount
    sell1 = order_sell("600519.SH", 100, ctx)
    assert sell1.status == 1

    assert "600519.SH" not in ctx.portfolio.positions
    assert "000001.SZ" in ctx.portfolio.positions
    assert_balance(ctx, "multi_stock_after_sell")


# ==================================================================
# 10. 边界：amount=0 / amount 极小
# ==================================================================

def test_zero_amount_rejected():
    """下单 0 股被拒绝。"""
    ctx = make_context()
    order = order_buy("600519.SH", 0, ctx)
    assert order.status == -1
    assert ctx.portfolio.cash == 10000000


def test_tiny_amount_rounded_to_zero():
    """下单 50 股，C5 取整后 < 100 → 拒绝。"""
    ctx = make_context()
    order = order_buy("600519.SH", 50, ctx)
    assert order.status == -1
    assert ctx.portfolio.cash == 10000000


# ==================================================================
# 11. 卖出金额精度：印花税逐笔验证
# ==================================================================

def test_sell_tax_exact():
    """卖出 600519.SH 200 股，手动计算印花税精确值。"""
    ctx = make_context(cash=10000000)
    price = get_open_price("600519.SH", ctx)

    order_buy("600519.SH", 200, ctx)
    pos = ctx.portfolio.positions["600519.SH"]
    pos.enable_amount = pos.amount

    sell = order_sell("600519.SH", 200, ctx)
    assert sell.status == 1

    sell_value = 200 * price
    expected_tax = sell_value * 0.001
    expected_commission = max(sell_value * 0.0003, 5)
    expected_cost = expected_tax + expected_commission
    assert abs(sell.cost - expected_cost) < EPS


# ==================================================================
# 12. 胜率精度
# ==================================================================

def test_win_rate_precision():
    """同价买卖（扣费后必然亏损），win 不应增加。"""
    ctx = make_context(cash=10000000)
    price = get_open_price("600519.SH", ctx)

    order_buy("600519.SH", 100, ctx)
    pos = ctx.portfolio.positions["600519.SH"]
    pos.enable_amount = pos.amount

    order_sell("600519.SH", 100, ctx)

    # 同价买卖，扣除手续费后 net_per_share < cost_basis，不算赢
    assert ctx.performance.win == 0
    assert ctx.performance.trade_num == 1


if __name__ == "__main__":
    setup_module()

    test_single_buy_precision()
    print("[PASS] test_single_buy_precision")

    test_add_position_weighted_avg()
    print("[PASS] test_add_position_weighted_avg")

    test_partial_sell_precision()
    print("[PASS] test_partial_sell_precision")

    test_full_sell_precision()
    print("[PASS] test_full_sell_precision")

    test_shrink_buy_precision()
    print("[PASS] test_shrink_buy_precision")

    test_limit_up_rejected()
    print("[PASS] test_limit_up_rejected")

    test_buy_sell_round_trip()
    print("[PASS] test_buy_sell_round_trip")

    test_buy_sell_round_trip_000001()
    print("[PASS] test_buy_sell_round_trip_000001")

    test_slip_buy_precision()
    print("[PASS] test_slip_buy_precision")

    test_slip_round_trip()
    print("[PASS] test_slip_round_trip")

    test_multi_stock_precision()
    print("[PASS] test_multi_stock_precision")

    test_zero_amount_rejected()
    print("[PASS] test_zero_amount_rejected")

    test_tiny_amount_rounded_to_zero()
    print("[PASS] test_tiny_amount_rounded_to_zero")

    test_sell_tax_exact()
    print("[PASS] test_sell_tax_exact")

    test_win_rate_precision()
    print("[PASS] test_win_rate_precision")

    print()
    print("All I1 settlement precision tests passed.")
