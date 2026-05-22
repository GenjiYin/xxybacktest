"""
live/trader.py 真实环境测试

前提：QMT 客户端已启动并登录，无需账号密码。
运行：python tests/test_live_trader.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.live.trader import QMTTrader, QMTConnectionError

QMT_PATH   = r"D:\国金QMT交易端模拟\userdata_mini"
ACCOUNT_ID = "86962531"


# ---------------------------------------------------------------------------
# 全局 trader 实例，所有测试共用，避免重复连接
# ---------------------------------------------------------------------------

_trader: QMTTrader = None


def setup():
    global _trader
    print(f"\n[setup] 连接 QMT，路径: {QMT_PATH}，账号: {ACCOUNT_ID}")
    _trader = QMTTrader(QMT_PATH, ACCOUNT_ID)
    print("[setup] 连接完成\n")


def teardown():
    if _trader is not None:
        _trader.disconnect()
        print("\n[teardown] 已断开连接")


# ---------------------------------------------------------------------------
# 测试：连接状态
# ---------------------------------------------------------------------------

def test_is_connected():
    """连接成功后 is_connected() 应返回 True。"""
    assert _trader.is_connected() is True
    print("[PASS] is_connected() = True")


# ---------------------------------------------------------------------------
# 测试：get_portfolio
# ---------------------------------------------------------------------------

def test_get_portfolio_returns_dict():
    """get_portfolio 应返回包含四个字段的 dict。"""
    result = _trader.get_portfolio()
    print(f"  portfolio = {result}")

    assert isinstance(result, dict)
    for key in ('cash', 'frozen_cash', 'market_value', 'total_asset'):
        assert key in result, f"缺少字段: {key}"
        assert isinstance(result[key], float), f"{key} 应为 float"
    print("[PASS] get_portfolio 返回结构正确")


def test_get_portfolio_total_asset_positive():
    """总资产应大于 0。"""
    result = _trader.get_portfolio()
    assert result['total_asset'] > 0, f"total_asset={result['total_asset']} 应 > 0"
    print(f"[PASS] total_asset = {result['total_asset']:,.2f}")


def test_get_portfolio_cash_plus_market_value():
    """可用资金 + 冻结资金 + 持仓市值 应约等于总资产（允许总资产 1% 误差）。

    注：total_asset 可能包含货币基金、理财等其他资产，不一定严格等于
    cash + frozen_cash + market_value。
    """
    p = _trader.get_portfolio()
    reconstructed = p['cash'] + p['frozen_cash'] + p['market_value']
    diff = abs(reconstructed - p['total_asset'])
    ratio = diff / p['total_asset'] if p['total_asset'] > 0 else 0
    print(f"  cash={p['cash']:.2f}  frozen={p['frozen_cash']:.2f}  "
          f"market_value={p['market_value']:.2f}  total={p['total_asset']:.2f}  diff={diff:.2f}  ratio={ratio:.4%}")
    assert ratio < 0.01, f"资金加总与总资产差异过大: {diff:.2f} ({ratio:.2%})"
    print("[PASS] cash + frozen_cash + market_value ≈ total_asset (差异 < 1%)")


# ---------------------------------------------------------------------------
# 测试：get_positions
# ---------------------------------------------------------------------------

def test_get_positions_returns_dict():
    """get_positions 应返回 dict，无持仓时为空 dict。"""
    result = _trader.get_positions()
    print(f"  持仓数量: {len(result)} 只")
    assert isinstance(result, dict)
    print("[PASS] get_positions 返回 dict")


def test_get_positions_field_structure():
    """每条持仓记录应包含五个字段，类型正确。"""
    result = _trader.get_positions()
    if not result:
        print("[SKIP] 当前无持仓，跳过字段结构检查")
        return

    for code, pos in result.items():
        assert 'volume' in pos and isinstance(pos['volume'], int), \
            f"{code}: volume 应为 int"
        assert 'can_sell_volume' in pos and isinstance(pos['can_sell_volume'], int), \
            f"{code}: can_sell_volume 应为 int"
        assert 'cost_price' in pos and isinstance(pos['cost_price'], float), \
            f"{code}: cost_price 应为 float"
        assert 'last_price' in pos and isinstance(pos['last_price'], float), \
            f"{code}: last_price 应为 float"
        assert 'market_value' in pos and isinstance(pos['market_value'], float), \
            f"{code}: market_value 应为 float"
        print(f"  {code}: volume={pos['volume']}  can_sell={pos['can_sell_volume']}  "
              f"cost={pos['cost_price']:.3f}  last={pos['last_price']:.3f}  "
              f"mktval={pos['market_value']:.2f}")

    print(f"[PASS] get_positions 所有 {len(result)} 条记录字段结构正确")


def test_get_positions_volume_positive():
    """所有返回的持仓 volume 应 > 0（零持仓应被过滤）。"""
    result = _trader.get_positions()
    for code, pos in result.items():
        assert pos['volume'] > 0, f"{code}: volume={pos['volume']} 应 > 0"
    print("[PASS] 所有持仓 volume > 0")


def test_get_positions_can_sell_le_volume():
    """can_sell_volume 应 <= volume（T+1 约束）。"""
    result = _trader.get_positions()
    for code, pos in result.items():
        assert pos['can_sell_volume'] <= pos['volume'], \
            f"{code}: can_sell_volume={pos['can_sell_volume']} > volume={pos['volume']}"
    print("[PASS] can_sell_volume <= volume（T+1 约束）")


def test_get_positions_market_value_consistent():
    """market_value 应等于 volume * last_price（我们自己计算的，精确相等）。"""
    result = _trader.get_positions()
    if not result:
        print("[SKIP] 当前无持仓")
        return

    for code, pos in result.items():
        expected = pos['volume'] * pos['last_price']
        assert pos['market_value'] == expected, \
            f"{code}: market_value={pos['market_value']} != volume*last_price={expected}"
    print("[PASS] market_value == volume * last_price")


# ---------------------------------------------------------------------------
# 测试：get_position
# ---------------------------------------------------------------------------

def test_get_position_held_stock():
    """对持仓中的股票查询，应返回 dict，字段结构与 get_positions 一致。"""
    positions = _trader.get_positions()
    if not positions:
        print("[SKIP] 当前无持仓，跳过 get_position 持仓股测试")
        return

    code = next(iter(positions))
    pos = _trader.get_position(code)

    assert pos is not None, f"{code} 应有持仓但 get_position 返回 None"
    for key in ('volume', 'can_sell_volume', 'cost_price', 'last_price', 'market_value'):
        assert key in pos, f"缺少字段: {key}"
    print(f"[PASS] get_position({code}) 返回结构正确，volume={pos['volume']}")


def test_get_position_not_held_returns_none():
    """无持仓的股票查询，应返回 None。"""
    pos = _trader.get_position("999999.SZ")
    assert pos is None, f"预期 None，实际: {pos}"
    print("[PASS] get_position(999999.SZ) = None")


def test_get_position_matches_get_positions():
    """get_position(code) 返回值应与 get_positions()[code] 完全一致。"""
    positions = _trader.get_positions()
    if not positions:
        print("[SKIP] 当前无持仓")
        return

    code = next(iter(positions))
    single = _trader.get_position(code)
    from_all = positions[code]

    assert single == from_all, \
        f"get_position({code}) 与 get_positions()[code] 不一致:\n  single={single}\n  from_all={from_all}"
    print(f"[PASS] get_position({code}) == get_positions()[code]")


# ---------------------------------------------------------------------------
# 测试：get_price
# ---------------------------------------------------------------------------

def test_get_price_with_held_stock():
    """对持仓中的股票查询最新价，应返回正数 float。"""
    positions = _trader.get_positions()
    if not positions:
        print("[SKIP] 当前无持仓，跳过 get_price 持仓股测试")
        return

    # 遍历持仓，找到第一个能查到价格的股票（可转债/停牌可能返回 None）
    for code in positions:
        price = _trader.get_price(code)
        if price is not None:
            break
    else:
        print("[SKIP] 所有持仓 tick 价格均为 None（可能全部停牌或为可转债）")
        return

    print(f"  {code} 最新价: {price}")
    assert isinstance(price, float)
    assert price > 0
    print(f"[PASS] get_price({code}) = {price}")


def test_get_price_invalid_code_returns_none():
    """无效代码应返回 None，不抛出异常。"""
    price = _trader.get_price("999999.SZ")
    assert price is None
    print("[PASS] 无效代码 get_price 返回 None")


def test_get_price_close_to_position_last_price():
    """get_price 返回值应与 get_positions 中的 last_price 接近（允许 2% 偏差）。"""
    positions = _trader.get_positions()
    if not positions:
        print("[SKIP] 当前无持仓")
        return

    # 遍历持仓，找到第一个能查到价格的股票
    for code in positions:
        tick_price = _trader.get_price(code)
        if tick_price is not None:
            break
    else:
        print("[SKIP] 所有持仓 tick 价格均为 None")
        return

    pos_price = positions[code]['last_price']

    ratio = abs(tick_price - pos_price) / pos_price if pos_price > 0 else 0
    print(f"  {code}: positions.last_price={pos_price:.3f}  get_price={tick_price:.3f}  偏差={ratio:.2%}")
    assert ratio < 0.02, f"价格偏差 {ratio:.2%} 超过 2%"
    print(f"[PASS] get_price 与持仓 last_price 偏差 < 2%")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    setup()
    try:
        test_is_connected()

        print("\n--- get_portfolio ---")
        test_get_portfolio_returns_dict()
        test_get_portfolio_total_asset_positive()
        test_get_portfolio_cash_plus_market_value()

        print("\n--- get_positions ---")
        test_get_positions_returns_dict()
        test_get_positions_field_structure()
        test_get_positions_volume_positive()
        test_get_positions_can_sell_le_volume()
        test_get_positions_market_value_consistent()

        print("\n--- get_position ---")
        test_get_position_held_stock()
        test_get_position_not_held_returns_none()
        test_get_position_matches_get_positions()

        print("\n--- get_price ---")
        test_get_price_with_held_stock()
        test_get_price_invalid_code_returns_none()
        test_get_price_close_to_position_last_price()

        print("\n========== All live/trader tests passed ==========")
    finally:
        teardown()
