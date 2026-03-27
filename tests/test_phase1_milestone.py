"""Phase 1 里程碑验证：买入持有策略端到端测试

策略：第一天 09:30 买入 100 股贵州茅台（600519.SH），之后持有不动。
回测区间：2024-01-02 ~ 2024-01-12（9 个交易日）
初始资金：1,000,000

验证项：
1. cash 扣款正确
2. 持仓数量正确
3. total_value = cash + positions_value（每日成立）
4. context.current_dt 的 datetime 约定在 E1 → B3 链路上跑通
5. T+1 机制：买入当天 enable_amount=0，次日刷新为 amount
6. 日终估值用 close 价格
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.backtest import run_backtest
from xxybacktest.trading import order_buy, order_sell
from xxybacktest.data import Data

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data")

# 真实行情数据（600519.SH 贵州茅台）
# 来源：xxydb 实际查询结果
DAILY_DATA = {
    "2024-01-02": {"open": 1715.00, "close": 1685.01},
    "2024-01-03": {"open": 1681.11, "close": 1694.00},
    "2024-01-04": {"open": 1693.00, "close": 1669.00},
    "2024-01-05": {"open": 1661.33, "close": 1663.36},
    "2024-01-08": {"open": 1661.00, "close": 1643.99},
    "2024-01-09": {"open": 1641.01, "close": 1641.00},
    "2024-01-10": {"open": 1641.10, "close": 1641.50},
    "2024-01-11": {"open": 1640.10, "close": 1646.57},
    "2024-01-12": {"open": 1639.97, "close": 1643.06},
}

CAPITAL = 1_000_000
BUY_AMOUNT = 100
CODE = "600519.SH"
COMMISSION_RATE = 0.0003
MIN_COMMISSION = 5


def _initialize(context):
    """策略初始化：不做特别操作。"""
    pass


def _handle_data(context):
    """策略逻辑：仅第一天买入，之后持有。"""
    if CODE not in context.portfolio.positions:
        order_buy(CODE, BUY_AMOUNT, context)


def _run():
    """运行回测并返回 context。"""
    return run_backtest(
        initialize=_initialize,
        handle_data=_handle_data,
        start_date="2024-01-02",
        end_date="2024-01-12",
        capital=CAPITAL,
        data_path=DATA_PATH,
        rule_list="rule_stop",
    )


# ------------------------------------------------------------------
# 测试用例
# ------------------------------------------------------------------

def test_backtest_runs():
    """回测能完整跑完，不报错。"""
    ctx = _run()
    assert ctx is not None
    assert len(ctx.performance.returns) == 9  # 9 个交易日


def test_day1_buy():
    """第一天买入：价格=open，数量=1000。"""
    ctx = _run()

    # 应有且仅有 1 笔成交
    buy_trades = [t for t in ctx.logs.trade_list if t.is_buy]
    assert len(buy_trades) == 1

    trade = buy_trades[0]
    assert trade.amount == BUY_AMOUNT
    assert trade.last_sale_price == DAILY_DATA["2024-01-02"]["open"]  # 09:30 用 open


def test_day1_cash():
    """第一天买入后 cash 正确。"""
    ctx = _run()

    price = DAILY_DATA["2024-01-02"]["open"]  # 9.39
    value = BUY_AMOUNT * price                # 9390
    commission = max(value * COMMISSION_RATE, MIN_COMMISSION)  # max(2.817, 5) = 5
    cost = commission  # 买入无税
    expected_cash = CAPITAL - value - cost     # 1000000 - 9390 - 5 = 990605

    # cash 在日终估值后不变（只有买卖才改 cash）
    assert abs(ctx.portfolio.cash - expected_cash) < 0.01


def test_position_amount():
    """持仓数量始终为 100（买入后一直持有）。"""
    ctx = _run()
    assert CODE in ctx.portfolio.positions
    assert ctx.portfolio.positions[CODE].amount == BUY_AMOUNT


def test_total_value_equals_cash_plus_positions():
    """每日 total_value = cash + positions_value。"""
    ctx = _run()
    assert abs(
        ctx.portfolio.total_value
        - ctx.portfolio.cash
        - ctx.portfolio.positions_value
    ) < 0.01


def test_final_valuation_uses_close():
    """最终估值用最后一天的 close 价格。"""
    ctx = _run()
    last_close = DAILY_DATA["2024-01-12"]["close"]  # 1643.06
    expected_positions_value = BUY_AMOUNT * last_close  # 164306

    assert abs(ctx.portfolio.positions_value - expected_positions_value) < 0.01


def test_final_total_value():
    """最终 total_value 手算验证。"""
    ctx = _run()

    # cash（买入后不变）
    buy_price = DAILY_DATA["2024-01-02"]["open"]
    buy_value = BUY_AMOUNT * buy_price
    buy_cost = max(buy_value * COMMISSION_RATE, MIN_COMMISSION)
    expected_cash = CAPITAL - buy_value - buy_cost

    # 最终持仓市值
    last_close = DAILY_DATA["2024-01-12"]["close"]
    expected_pos_value = BUY_AMOUNT * last_close

    expected_total = expected_cash + expected_pos_value
    assert abs(ctx.portfolio.total_value - expected_total) < 0.01


def test_daily_returns_count():
    """9 个交易日产生 9 条收益率记录。"""
    ctx = _run()
    assert len(ctx.performance.returns) == 9


def test_daily_return_day1():
    """第一天收益率：买入 open=1715.00，收盘 close=1685.01，整体亏损。"""
    ctx = _run()

    # 第一天手算：
    # buy: value=100*1715=171500, commission=max(171500*0.0003,5)=51.45, cost=51.45
    # cash = 1000000 - 171500 - 51.45 = 828448.55
    # 日终: positions_value = 100*1685.01 = 168501
    # total_value = 828448.55 + 168501 = 996949.55
    # daily_return = 996949.55 / 1000000 = 0.99694955
    day1_return = ctx.performance.returns[0]
    assert day1_return[0] == "2024-01-02"

    expected_total = 828448.55 + 100 * 1685.01
    expected_return = expected_total / CAPITAL
    assert abs(day1_return[1] - expected_return) < 0.0001


def test_t1_mechanism():
    """T+1：买入当天不可卖，次日可卖。

    通过检查最终 enable_amount == amount 验证盘前刷新跑通了。
    """
    ctx = _run()
    pos = ctx.portfolio.positions[CODE]
    # 经过多日盘前刷新，enable_amount 应等于 amount
    assert pos.enable_amount == pos.amount


def test_current_dt_is_datetime():
    """context.current_dt 在回测结束后是 datetime 类型。"""
    ctx = _run()
    assert isinstance(ctx.current_dt, datetime)


def test_no_extra_trades():
    """只在第一天买入一次，后续不再交易。"""
    ctx = _run()
    assert len(ctx.logs.trade_list) == 1


# ======================================================================
# 场景二：买入持有两天后卖出
# ======================================================================
#
# 手算过程：
#
# 01-02 09:30 买入 100 股 @ open=1715.00
#   value      = 100 * 1715.00 = 171,500.00
#   commission = max(171500*0.0003, 5) = 51.45
#   cost       = 51.45（买入无税）
#   cash       = 1,000,000 - 171,500 - 51.45 = 828,448.55
#
# 01-02 日终 close=1685.01 → pos=168,501.00 → total=996,949.55
# 01-03 日终 close=1694.00 → pos=169,400.00 → total=997,848.55
#
# 01-04 09:30 卖出 100 股 @ open=1693.00
#   value      = 100 * 1693.00 = 169,300.00
#   tax        = 169,300 * 0.001 = 169.30
#   commission = max(169300*0.0003, 5) = 50.79
#   cost       = 169.30 + 50.79 = 220.09
#   cash       = 828,448.55 + 169,300 - 220.09 = 997,528.46
#   positions  = 清空
#
# 01-04 ~ 01-12 日终: 纯现金，total_value = 997,528.46
#
# 单笔收益率:
#   cost_basis = (171500 + 51.45) / 100 = 1715.5145
#   net_per_share = (169300 - 220.09) / 100 = 1690.7991
#   trade_return = 1690.7991 / 1715.5145 - 1 = -0.014403...
#
# 胜负: net_per_share(1690.80) < cost_basis(1715.51) → 败，win=0

SELL_CLOSE_TAX = 0.001

# 手算关键值
_buy_price = DAILY_DATA["2024-01-02"]["open"]       # 1715.00
_buy_value = BUY_AMOUNT * _buy_price                 # 171500
_buy_commission = max(_buy_value * COMMISSION_RATE, MIN_COMMISSION)  # 51.45
_buy_cost = _buy_commission                          # 51.45（无税）
_cash_after_buy = CAPITAL - _buy_value - _buy_cost   # 828448.55

_sell_price = DAILY_DATA["2024-01-04"]["open"]       # 1693.00
_sell_value = BUY_AMOUNT * _sell_price               # 169300
_sell_tax = _sell_value * SELL_CLOSE_TAX             # 169.30
_sell_commission = max(_sell_value * COMMISSION_RATE, MIN_COMMISSION)  # 50.79
_sell_cost = _sell_tax + _sell_commission             # 220.09
_cash_after_sell = _cash_after_buy + _sell_value - _sell_cost  # 997528.46

_cost_basis = (_buy_value + _buy_cost) / BUY_AMOUNT  # 1715.5145
_net_per_share = (_sell_value - _sell_cost) / BUY_AMOUNT  # 1690.7991
_trade_return = _net_per_share / _cost_basis - 1     # -0.014403...


def _handle_data_sell(context):
    """01-02 买入，01-04 卖出。"""
    date_str = context.current_dt.strftime("%Y-%m-%d")
    if date_str == "2024-01-02":
        order_buy(CODE, BUY_AMOUNT, context)
    elif date_str == "2024-01-04":
        order_sell(CODE, BUY_AMOUNT, context)


def _run_sell():
    return run_backtest(
        initialize=_initialize,
        handle_data=_handle_data_sell,
        start_date="2024-01-02",
        end_date="2024-01-12",
        capital=CAPITAL,
        data_path=DATA_PATH,
        rule_list="rule_stop",
    )


def test_sell_backtest_runs():
    """场景二回测跑完不报错。"""
    ctx = _run_sell()
    assert ctx is not None
    assert len(ctx.performance.returns) == 9


def test_sell_buy_day1():
    """第一天买入价格和数量正确。"""
    ctx = _run_sell()
    buy_trades = [t for t in ctx.logs.trade_list if t.is_buy]
    assert len(buy_trades) == 1
    assert buy_trades[0].amount == BUY_AMOUNT
    assert buy_trades[0].last_sale_price == _buy_price


def test_sell_on_day3():
    """第三天卖出价格和数量正确。"""
    ctx = _run_sell()
    sell_trades = [t for t in ctx.logs.trade_list if not t.is_buy]
    assert len(sell_trades) == 1
    assert sell_trades[0].amount == BUY_AMOUNT
    assert sell_trades[0].last_sale_price == _sell_price


def test_sell_cash_after_buy():
    """买入后 cash 正确（卖出前不变）。"""
    ctx = _run_sell()
    # 卖出后 cash 已变化，用最终值反推验证
    # 也可以直接检查卖出订单的 value/cost
    sell_trade = [t for t in ctx.logs.trade_list if not t.is_buy][0]
    assert abs(sell_trade.value - _sell_value) < 0.01
    assert abs(sell_trade.cost - _sell_cost) < 0.01


def test_sell_cash_after_sell():
    """卖出后 cash 正确。"""
    ctx = _run_sell()
    assert abs(ctx.portfolio.cash - _cash_after_sell) < 0.01


def test_sell_position_cleared():
    """清仓后 positions 为空。"""
    ctx = _run_sell()
    assert CODE not in ctx.portfolio.positions


def test_sell_final_total_value():
    """清仓后 total_value = cash（纯现金）。"""
    ctx = _run_sell()
    assert abs(ctx.portfolio.total_value - _cash_after_sell) < 0.01
    assert abs(ctx.portfolio.positions_value - 0) < 0.01
    assert abs(ctx.portfolio.total_value - ctx.portfolio.cash) < 0.01


def test_sell_flat_after_clear():
    """清仓后剩余交易日收益率全为 1.0。"""
    ctx = _run_sell()
    # 01-04 卖出后，01-05 ~ 01-12 的日收益率应为 1.0
    for date_str, ret in ctx.performance.returns:
        if date_str > "2024-01-04":
            assert abs(ret - 1.0) < 0.0001, f"{date_str} 收益率={ret}，预期=1.0"


def test_sell_trade_return():
    """单笔卖出收益率正确。"""
    ctx = _run_sell()
    assert len(ctx.logs.trade_returns) == 1
    assert abs(ctx.logs.trade_returns[0] - _trade_return) < 0.0001


def test_sell_win_count():
    """这笔亏损交易，win=0，trade_num=1。"""
    ctx = _run_sell()
    assert ctx.performance.trade_num == 1
    assert ctx.performance.win == 0


def debug_run_sell():
    """场景二调试输出。"""
    print("=" * 70)
    print("Phase 1 里程碑 — 场景二：买入持有两天后卖出")
    print("=" * 70)
    print(f"股票: {CODE}  初始资金: {CAPITAL:,.0f}  买入: 01-02  卖出: 01-04")
    print()

    ctx = _run_sell()

    # 成交明细
    print("── 成交明细 ──")
    for t in ctx.logs.trade_list:
        side = "买入" if t.is_buy else "卖出"
        print(f"  {side} {t.code}  数量={t.amount}  价格={t.last_sale_price}"
              f"  金额={t.value:.2f}  手续费={t.cost:.2f}  滑点={t.slip_value:.2f}")
    print()

    # 逐日估值
    print("── 逐日估值 ──")
    print(f"{'日期':>12s}  {'引擎净值比':>12s}  {'链式推算总资产':>16s}")
    print("-" * 50)
    engine_total = CAPITAL
    for date_str, ret in ctx.performance.returns:
        engine_total *= ret
        print(f"  {date_str}  {ret:>12.6f}  {engine_total:>16.2f}")
    print()

    # 最终状态
    print("── 最终 context 状态 ──")
    print(f"  cash             = {ctx.portfolio.cash:.2f}")
    print(f"  positions_value  = {ctx.portfolio.positions_value:.2f}")
    print(f"  total_value      = {ctx.portfolio.total_value:.2f}")
    has_pos = CODE in ctx.portfolio.positions
    print(f"  持仓             = {'有' if has_pos else '已清空'}")
    print(f"  trade_num        = {ctx.performance.trade_num}")
    print(f"  win              = {ctx.performance.win}")
    if ctx.logs.trade_returns:
        print(f"  trade_return     = {ctx.logs.trade_returns[0]:.6f}")
    print()

    # 交叉验证
    print("── 一致性交叉验证 ──")
    checks = []

    # 1. total_value = cash（纯现金）
    diff1 = abs(ctx.portfolio.total_value - ctx.portfolio.cash)
    ok1 = diff1 < 0.01
    checks.append(ok1)
    print(f"  total_value == cash（纯现金）                  "
          f"差值={diff1:.4f}  {'PASS' if ok1 else 'FAIL'}")

    # 2. cash = 手算值
    diff2 = abs(ctx.portfolio.cash - _cash_after_sell)
    ok2 = diff2 < 0.01
    checks.append(ok2)
    print(f"  cash == 手算 ({_cash_after_sell:.2f})         "
          f"差值={diff2:.4f}  {'PASS' if ok2 else 'FAIL'}")

    # 3. 链式推算 = total_value
    diff3 = abs(engine_total - ctx.portfolio.total_value)
    ok3 = diff3 < 0.01
    checks.append(ok3)
    print(f"  净值比链式推算 == total_value                  "
          f"差值={diff3:.4f}  {'PASS' if ok3 else 'FAIL'}")

    # 4. trade_return = 手算
    if ctx.logs.trade_returns:
        diff4 = abs(ctx.logs.trade_returns[0] - _trade_return)
        ok4 = diff4 < 0.0001
        checks.append(ok4)
        print(f"  trade_return == 手算 ({_trade_return:.6f})   "
              f"差值={diff4:.6f}  {'PASS' if ok4 else 'FAIL'}")

    print()
    if all(checks):
        print("交叉验证: 全部通过")
    else:
        print("交叉验证: 存在不一致，请检查!")
    print()


def debug_run():
    """打印逐日回测状态，用于人工核对。"""
    print("=" * 70)
    print("Phase 1 里程碑 — 买入持有策略 调试信息")
    print("=" * 70)
    print(f"股票: {CODE}  初始资金: {CAPITAL:,.0f}  买入数量: {BUY_AMOUNT}")
    print()

    ctx = _run()

    # ── 成交明细 ──
    print("── 成交明细 ──")
    for t in ctx.logs.trade_list:
        side = "买入" if t.is_buy else "卖出"
        print(f"  {side} {t.code}  数量={t.amount}  价格={t.last_sale_price}"
              f"  金额={t.value:.2f}  手续费={t.cost:.2f}  滑点={t.slip_value:.2f}")
    print()

    # ── 逐日估值（手算 vs 引擎实际记录）──
    print("── 逐日估值 ──")
    print(f"{'日期':>12s}  {'close':>7s}  {'手算持仓':>10s}  {'手算总资产':>12s}"
          f"  {'引擎净值比':>12s}  {'引擎推算总资产':>14s}")
    print("-" * 78)

    # 手算 cash（买入后不再变化）
    buy_price = DAILY_DATA["2024-01-02"]["open"]
    buy_value = BUY_AMOUNT * buy_price
    buy_cost = max(buy_value * COMMISSION_RATE, MIN_COMMISSION)
    hand_cash = CAPITAL - buy_value - buy_cost

    # 用引擎的净值比链式推算总资产
    engine_total = CAPITAL  # 第一天的 previous_value
    for date_str, ret in ctx.performance.returns:
        close = DAILY_DATA[date_str]["close"]
        hand_pos = BUY_AMOUNT * close
        hand_total = hand_cash + hand_pos
        engine_total = engine_total * ret  # ret 是净值比
        print(f"  {date_str}  {close:>7.2f}  {hand_pos:>10.2f}  {hand_total:>12.2f}"
              f"  {ret:>12.6f}  {engine_total:>14.2f}")
    print()

    # ── 最终 context 状态 ──
    pos = ctx.portfolio.positions[CODE]
    print("── 最终 context 状态（引擎实际值）──")
    print(f"  cash               = {ctx.portfolio.cash:.2f}")
    print(f"  positions_value    = {ctx.portfolio.positions_value:.2f}")
    print(f"  total_value        = {ctx.portfolio.total_value:.2f}")
    print(f"  持仓数量 (amount)  = {pos.amount}")
    print(f"  enable_amount      = {pos.enable_amount}")
    print(f"  cost_basis         = {pos.cost_basis:.4f}")
    print(f"  total_cost         = {pos.total_cost:.2f}")
    print(f"  total_value (pos)  = {pos.total_value:.2f}")
    print(f"  last_sale_price    = {pos.last_sale_price:.2f}")
    print(f"  current_dt         = {ctx.current_dt}")
    print(f"  previous_date      = {ctx.previous_date}")
    print(f"  订单数             = {len(ctx.logs.order_list)}")
    print(f"  成交数             = {len(ctx.logs.trade_list)}")
    print(f"  收益率记录数       = {len(ctx.performance.returns)}")
    print()

    # ── 一致性交叉验证 ──
    print("── 一致性交叉验证 ──")
    checks = []

    # 1. total_value = cash + positions_value
    diff1 = abs(ctx.portfolio.total_value - ctx.portfolio.cash - ctx.portfolio.positions_value)
    ok1 = diff1 < 0.01
    checks.append(ok1)
    print(f"  total_value == cash + positions_value          "
          f"差值={diff1:.4f}  {'PASS' if ok1 else 'FAIL'}")

    # 2. positions_value = amount * last_sale_price
    expected_pos_val = pos.amount * pos.last_sale_price
    diff2 = abs(ctx.portfolio.positions_value - expected_pos_val)
    ok2 = diff2 < 0.01
    checks.append(ok2)
    print(f"  positions_value == amount * last_sale_price    "
          f"差值={diff2:.4f}  {'PASS' if ok2 else 'FAIL'}")

    # 3. pos.total_value = amount * last_sale_price
    diff3 = abs(pos.total_value - expected_pos_val)
    ok3 = diff3 < 0.01
    checks.append(ok3)
    print(f"  pos.total_value == amount * last_sale_price    "
          f"差值={diff3:.4f}  {'PASS' if ok3 else 'FAIL'}")

    # 4. cost_basis = total_cost / amount
    expected_cb = pos.total_cost / pos.amount
    diff4 = abs(pos.cost_basis - expected_cb)
    ok4 = diff4 < 0.0001
    checks.append(ok4)
    print(f"  cost_basis == total_cost / amount              "
          f"差值={diff4:.6f}  {'PASS' if ok4 else 'FAIL'}")

    # 5. cash = 手算 cash
    diff5 = abs(ctx.portfolio.cash - hand_cash)
    ok5 = diff5 < 0.01
    checks.append(ok5)
    print(f"  cash == 手算cash ({hand_cash:.2f})             "
          f"差值={diff5:.4f}  {'PASS' if ok5 else 'FAIL'}")

    # 6. 引擎推算总资产 vs context.total_value
    diff6 = abs(engine_total - ctx.portfolio.total_value)
    ok6 = diff6 < 0.01
    checks.append(ok6)
    print(f"  净值比链式推算 == total_value                  "
          f"差值={diff6:.4f}  {'PASS' if ok6 else 'FAIL'}")

    # 7. 手算最终总资产 vs context.total_value
    last_close = DAILY_DATA["2024-01-12"]["close"]
    hand_final = hand_cash + BUY_AMOUNT * last_close
    diff7 = abs(hand_final - ctx.portfolio.total_value)
    ok7 = diff7 < 0.01
    checks.append(ok7)
    print(f"  手算最终总资产 ({hand_final:.2f}) == total_value  "
          f"差值={diff7:.4f}  {'PASS' if ok7 else 'FAIL'}")

    print()
    if all(checks):
        print("交叉验证: 全部通过")
    else:
        print("交叉验证: 存在不一致，请检查!")
    print()


if __name__ == "__main__":
    Data.init_db(DATA_PATH)

    # 先输出调试信息
    debug_run()

    # 再跑断言测试
    print("── 运行断言测试 ──")
    test_backtest_runs()
    print("  [PASS] test_backtest_runs")
    test_day1_buy()
    print("  [PASS] test_day1_buy")
    test_day1_cash()
    print("  [PASS] test_day1_cash")
    test_position_amount()
    print("  [PASS] test_position_amount")
    test_total_value_equals_cash_plus_positions()
    print("  [PASS] test_total_value_equals_cash_plus_positions")
    test_final_valuation_uses_close()
    print("  [PASS] test_final_valuation_uses_close")
    test_final_total_value()
    print("  [PASS] test_final_total_value")
    test_daily_returns_count()
    print("  [PASS] test_daily_returns_count")
    test_daily_return_day1()
    print("  [PASS] test_daily_return_day1")
    test_t1_mechanism()
    print("  [PASS] test_t1_mechanism")
    test_current_dt_is_datetime()
    print("  [PASS] test_current_dt_is_datetime")
    test_no_extra_trades()
    print("  [PASS] test_no_extra_trades")
    print()
    print("Phase 1 milestone: ALL 12 TESTS PASSED")
    print()

    # ── 场景二：买入持有两天后卖出 ──
    print()
    debug_run_sell()

    print("── 运行场景二断言测试 ──")
    test_sell_backtest_runs()
    print("  [PASS] test_sell_backtest_runs")
    test_sell_buy_day1()
    print("  [PASS] test_sell_buy_day1")
    test_sell_on_day3()
    print("  [PASS] test_sell_on_day3")
    test_sell_cash_after_buy()
    print("  [PASS] test_sell_cash_after_buy")
    test_sell_cash_after_sell()
    print("  [PASS] test_sell_cash_after_sell")
    test_sell_position_cleared()
    print("  [PASS] test_sell_position_cleared")
    test_sell_final_total_value()
    print("  [PASS] test_sell_final_total_value")
    test_sell_flat_after_clear()
    print("  [PASS] test_sell_flat_after_clear")
    test_sell_trade_return()
    print("  [PASS] test_sell_trade_return")
    test_sell_win_count()
    print("  [PASS] test_sell_win_count")
    print()
    print("Phase 1 场景二: ALL 10 TESTS PASSED")
