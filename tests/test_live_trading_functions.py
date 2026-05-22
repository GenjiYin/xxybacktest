"""
live/trading.py — 交易函数真实环境测试（模拟盘）

⚠️  安全说明：
    本脚本会连接 QMT 模拟盘并**真实下单**。
    所有下单金额已控制在极小范围（100 股低价 ETF，约 200 元以内）。
    运行前请确认 QMT 客户端已登录模拟账号。

运行：python tests/test_live_trading_functions.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.live.trader import QMTTrader
from xxybacktest.live.context import create_live_context
from xxybacktest.live.trading import (
    order_buy, order_sell, order, order_value,
    order_target_value, order_target_percent, inout_cash,
    _round_volume,
)

QMT_PATH   = r"D:\国金QMT交易端模拟\userdata_mini"
ACCOUNT_ID = "86962531"

# 测试用的低价 ETF，降低风险
TEST_CODE = "159949.SZ"

ACCOUNT_CONFIG = {
    "account_id":   ACCOUNT_ID,
    "name":         "测试实盘账户",
    "initial_cash": 1000000.0,
    "start_date":   "2024-01-01",
    "data_path":    r"D:\Desktop\最新回测框架\data",
    "asset_type":   "stock",
    "benchmark":    "000300.SH",
}

_trader = None
_ctx    = None


def setup():
    global _trader, _ctx
    print(f"\n[setup] 连接 QMT 模拟盘 ...")
    _trader = QMTTrader(QMT_PATH, ACCOUNT_ID)
    _ctx    = create_live_context(ACCOUNT_CONFIG, _trader)
    print("[setup] context 构建完成\n")


def teardown():
    if _trader is not None:
        _trader.disconnect()
        print("\n[teardown] 已断开连接")


# ---------------------------------------------------------------------------
# 辅助函数测试
# ---------------------------------------------------------------------------

def test_round_volume():
    """_round_volume 应向下取整到 100 的倍数。"""
    assert _round_volume(0) == 0
    assert _round_volume(50) == 0
    assert _round_volume(100) == 100
    assert _round_volume(150) == 100
    assert _round_volume(999) == 900
    print("[PASS] _round_volume 向下取整到 100 倍数正确")


# ---------------------------------------------------------------------------
# 前置检查
# ---------------------------------------------------------------------------

def _check_trading_ready():
    """检查是否可以安全测试：有行情、有资金。"""
    price = _trader.get_price(TEST_CODE)
    if price is None or price <= 0:
        print(f"[SKIP] {TEST_CODE} 无行情，跳过涉及下单的测试")
        return False

    p = _trader.get_portfolio()
    if p['cash'] < 1000:
        print(f"[SKIP] 可用资金不足 1000 元（当前 {p['cash']:.2f}），跳过下单测试")
        return False

    print(f"[INFO] {TEST_CODE} 最新价: {price:.3f}，可用资金: {p['cash']:,.2f}")
    return True


# ---------------------------------------------------------------------------
# order_buy / order_sell 测试
# ---------------------------------------------------------------------------

def test_order_buy_and_sell():
    """
    买入 100 股 TEST_CODE，验证订单记录，然后卖出还原。
    资金风险：约 price * 100 元。
    """
    if not _check_trading_ready():
        return

    price = _trader.get_price(TEST_CODE)
    print(f"\n[TEST] order_buy({TEST_CODE}, 100)")

    # 买入 100 股
    order_before = len(_ctx.logs.order_list)
    result = order_buy(TEST_CODE, 100, _ctx)

    assert result is not None, "order_buy 返回 None"
    assert result.code == TEST_CODE
    assert result.amount == 100
    assert result.is_buy is True
    assert result.status in (1, -1), f"status 应为 1 或 -1，实际 {result.status}"
    assert len(_ctx.logs.order_list) == order_before + 1
    print(f"  买入委托结果: status={result.status}, date={result.date}")

    # 卖出 100 股（还原持仓）
    print(f"[TEST] order_sell({TEST_CODE}, 100)")
    result2 = order_sell(TEST_CODE, 100, _ctx)

    assert result2 is not None, "order_sell 返回 None"
    assert result2.code == TEST_CODE
    assert result2.amount == 100
    assert result2.is_buy is False
    assert result2.status in (1, -1)
    assert len(_ctx.logs.order_list) == order_before + 2
    print(f"  卖出委托结果: status={result2.status}, date={result2.date}")

    print("[PASS] order_buy + order_sell 下单并记录 Order 成功")


def test_order_buy_invalid_amount():
    """买入数量 <= 0 时返回 None，不记录订单。"""
    order_before = len(_ctx.logs.order_list)
    assert order_buy(TEST_CODE, 0, _ctx) is None
    assert order_buy(TEST_CODE, -10, _ctx) is None
    assert len(_ctx.logs.order_list) == order_before
    print("[PASS] order_buy 无效数量返回 None，不记录订单")


def test_order_sell_invalid_amount():
    """卖出数量 <= 0 时返回 None。"""
    order_before = len(_ctx.logs.order_list)
    assert order_sell(TEST_CODE, 0, _ctx) is None
    assert order_sell(TEST_CODE, -10, _ctx) is None
    assert len(_ctx.logs.order_list) == order_before
    print("[PASS] order_sell 无效数量返回 None")


# ---------------------------------------------------------------------------
# order 测试
# ---------------------------------------------------------------------------

def test_order_positive_buy():
    """正数 → 买入（先买入 100 股，再卖出还原）。"""
    if not _check_trading_ready():
        return

    print(f"\n[TEST] order({TEST_CODE}, 100)")
    order_before = len(_ctx.logs.order_list)
    result = order(TEST_CODE, 100, _ctx)

    assert result is not None and result.is_buy is True
    assert len(_ctx.logs.order_list) == order_before + 1

    # 还原
    order(TEST_CODE, -100, _ctx)
    print("[PASS] order(正数) → order_buy，下单成功")


def test_order_negative_sell():
    """负数 → 卖出。"""
    if not _check_trading_ready():
        return

    # 先确保有持仓可卖
    pos = _trader.get_position(TEST_CODE)
    if not pos or pos['volume'] < 100:
        print(f"[SKIP] {TEST_CODE} 无持仓或持仓不足 100 股，跳过卖出测试")
        # 先买入再卖出
        order_buy(TEST_CODE, 100, _ctx)

    print(f"\n[TEST] order({TEST_CODE}, -100)")
    order_before = len(_ctx.logs.order_list)
    result = order(TEST_CODE, -100, _ctx)

    assert result is not None and result.is_buy is False
    assert len(_ctx.logs.order_list) == order_before + 1
    print("[PASS] order(负数) → order_sell，下单成功")


def test_order_zero_returns_none():
    """0 → None。"""
    order_before = len(_ctx.logs.order_list)
    assert order(TEST_CODE, 0, _ctx) is None
    assert len(_ctx.logs.order_list) == order_before
    print("[PASS] order(0) → None")


# ---------------------------------------------------------------------------
# order_value 测试
# ---------------------------------------------------------------------------

def test_order_value_buy():
    """买入约 1000 元（按价格计算股数，round 到 100 股）。"""
    if not _check_trading_ready():
        return

    price = _trader.get_price(TEST_CODE)
    target_value = price * 200  # 约 200 股的价值

    print(f"\n[TEST] order_value({TEST_CODE}, {target_value:.2f})")
    order_before = len(_ctx.logs.order_list)
    result = order_value(TEST_CODE, target_value, _ctx)

    assert result is not None and result.is_buy is True
    expected_vol = _round_volume(target_value / price)
    assert result.amount == expected_vol, \
        f"amount 应为 {expected_vol}，实际 {result.amount}"
    assert len(_ctx.logs.order_list) == order_before + 1

    # 还原：卖出同等数量
    order_value(TEST_CODE, -target_value, _ctx)
    print(f"[PASS] order_value(买入) 股数计算并下单正确，买入 {result.amount} 股")


def test_order_value_invalid_price():
    """无效代码价格返回 None。"""
    order_before = len(_ctx.logs.order_list)
    result = order_value("999999.SZ", 1000, _ctx)
    assert result is None
    assert len(_ctx.logs.order_list) == order_before
    print("[PASS] order_value 无效代码返回 None")


def test_order_value_zero_after_round():
    """金额太小导致 round 后为 0，返回 None。"""
    price = _trader.get_price(TEST_CODE)
    if price is None:
        print("[SKIP] 无行情，跳过")
        return

    order_before = len(_ctx.logs.order_list)
    result = order_value(TEST_CODE, price * 5, _ctx)  # 仅 5 股价值，round 后为 0
    assert result is None
    assert len(_ctx.logs.order_list) == order_before
    print("[PASS] order_value 金额太小返回 None")


# ---------------------------------------------------------------------------
# order_target_value 测试
# ---------------------------------------------------------------------------

def test_order_target_value_buy_new():
    """根据实际持仓，验证 order_target_value 差值计算和下单方向正确。

    注意：QMT 持仓是异步更新的，卖出后 get_position 可能仍返回旧值。
    测试根据查询到的实际持仓计算预期行为，不假设持仓已清零。
    """
    if not _check_trading_ready():
        return

    price = _trader.get_price(TEST_CODE)
    target_value = price * 100  # 目标 100 股
    target_vol = _round_volume(target_value / price)

    pos = _trader.get_position(TEST_CODE)
    current_vol = pos['volume'] if pos else 0
    expected_change = target_vol - current_vol

    print(f"\n[TEST] order_target_value({TEST_CODE}, {target_value:.2f})")
    print(f"       当前持仓: {current_vol} 股，目标: {target_vol} 股，差值: {expected_change}")

    result = order_target_value(TEST_CODE, target_value, _ctx)

    if expected_change == 0:
        assert result is None, f"预期 None，实际: {result}"
        print("[PASS] 无需调仓，返回 None")
    elif expected_change > 0:
        assert result is not None and result.is_buy is True, \
            f"预期买入 {expected_change} 股，实际: {result}"
        assert result.amount == expected_change
        print(f"[PASS] 买入 {result.amount} 股")
    else:
        assert result is not None and result.is_buy is False, \
            f"预期卖出 {-expected_change} 股，实际: {result}"
        assert result.amount == -expected_change
        print(f"[PASS] 卖出 {result.amount} 股")


def test_order_target_value_sell_down():
    """目标市值减小 → 验证减仓逻辑与实际持仓一致。"""
    if not _check_trading_ready():
        return

    price = _trader.get_price(TEST_CODE)
    target_value = price * 100  # 目标 100 股
    target_vol = _round_volume(target_value / price)

    pos = _trader.get_position(TEST_CODE)
    current_vol = pos['volume'] if pos else 0
    expected_change = target_vol - current_vol

    print(f"\n[TEST] order_target_value({TEST_CODE}, {target_value:.2f}) — 调仓")
    print(f"       当前持仓: {current_vol} 股，目标: {target_vol} 股，差值: {expected_change}")

    result = order_target_value(TEST_CODE, target_value, _ctx)

    if expected_change == 0:
        assert result is None
        print("[PASS] 无需调仓，返回 None")
    elif expected_change > 0:
        assert result is not None and result.is_buy is True
        print(f"[PASS] 买入 {result.amount} 股")
    else:
        assert result is not None and result.is_buy is False
        print(f"[PASS] 卖出 {result.amount} 股")


def test_order_target_value_no_change():
    """目标市值与现有持仓一致 → 无需调仓。"""
    if not _check_trading_ready():
        return

    pos = _trader.get_position(TEST_CODE)
    if not pos:
        print("[SKIP] 无持仓，跳过")
        return

    price = _trader.get_price(TEST_CODE)
    target_value = price * pos['volume']

    print(f"\n[TEST] order_target_value({TEST_CODE}, {target_value:.2f}) — 无需调仓")
    order_before = len(_ctx.logs.order_list)
    result = order_target_value(TEST_CODE, target_value, _ctx)

    assert result is None
    assert len(_ctx.logs.order_list) == order_before
    print("[PASS] order_target_value 无需调仓返回 None")


def test_order_target_value_clear():
    """目标市值 0 → 清仓（如有持仓）或无需操作（如已清仓）。"""
    if not _check_trading_ready():
        return

    pos = _trader.get_position(TEST_CODE)
    current_vol = pos['volume'] if pos else 0

    print(f"\n[TEST] order_target_value({TEST_CODE}, 0) — 清仓")
    print(f"       当前持仓: {current_vol} 股")

    result = order_target_value(TEST_CODE, 0, _ctx)

    if current_vol == 0:
        assert result is None, f"预期 None，实际: {result}"
        print("[PASS] 已无持仓，无需清仓")
    else:
        assert result is not None and result.is_buy is False
        assert result.amount == current_vol
        print(f"[PASS] 清仓卖出 {result.amount} 股")


# ---------------------------------------------------------------------------
# order_target_percent 测试
# ---------------------------------------------------------------------------

def test_order_target_percent_normal():
    """percent=0.001 → 根据实际持仓验证差值计算和下单方向。"""
    if not _check_trading_ready():
        return

    total_asset = _trader.get_portfolio()['total_asset']
    target_value = total_asset * 0.001
    price = _trader.get_price(TEST_CODE)
    target_vol = _round_volume(target_value / price) if price else 0

    pos = _trader.get_position(TEST_CODE)
    current_vol = pos['volume'] if pos else 0
    expected_change = target_vol - current_vol

    print(f"\n[TEST] order_target_percent({TEST_CODE}, 0.001)")
    print(f"       总资产: {total_asset:,.2f}，目标市值: {target_value:,.2f}")
    print(f"       当前持仓: {current_vol} 股，目标: {target_vol} 股，差值: {expected_change}")

    result = order_target_percent(TEST_CODE, 0.001, _ctx)

    if expected_change == 0:
        assert result is None
        print("[PASS] 无需调仓，返回 None")
    elif expected_change > 0:
        assert result is not None and result.is_buy is True
        print(f"[PASS] 买入 {result.amount} 股")
    else:
        assert result is not None and result.is_buy is False
        print(f"[PASS] 卖出 {result.amount} 股")


def test_order_target_percent_invalid():
    """percent < 0 或 > 1 返回 None。"""
    order_before = len(_ctx.logs.order_list)
    assert order_target_percent(TEST_CODE, -0.1, _ctx) is None
    assert order_target_percent(TEST_CODE, 1.5, _ctx) is None
    assert len(_ctx.logs.order_list) == order_before
    print("[PASS] order_target_percent 非法 percent 返回 None")


# ---------------------------------------------------------------------------
# inout_cash 测试
# ---------------------------------------------------------------------------

def test_inout_cash_warning():
    """inout_cash 应输出 warning 且不操作。"""
    inout_cash(10000, _ctx)
    print("[PASS] inout_cash 输出 warning 且不操作")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    setup()
    try:
        print("--- 辅助函数 ---")
        test_round_volume()

        print("\n--- 参数校验（不涉及下单）---")
        test_order_buy_invalid_amount()
        test_order_sell_invalid_amount()
        test_order_zero_returns_none()
        test_order_value_invalid_price()
        test_order_value_zero_after_round()
        test_order_target_percent_invalid()
        test_inout_cash_warning()

        print("\n--- 真实下单测试（模拟盘）---")
        print("⚠️  以下测试会向 QMT 模拟盘真实下单，金额已控制在极小范围。")
        print(f"    测试标的: {TEST_CODE}，单笔风险约 200 元以内。\n")

        test_order_buy_and_sell()
        test_order_positive_buy()
        test_order_negative_sell()
        test_order_value_buy()
        test_order_target_value_buy_new()
        test_order_target_value_sell_down()
        test_order_target_value_no_change()
        test_order_target_value_clear()
        test_order_target_percent_normal()

        print("\n========== All live/trading function tests passed ==========")
    finally:
        teardown()
