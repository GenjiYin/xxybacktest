"""
live/trading.py 真实环境测试

前提：QMT 客户端已启动并登录。
运行：python tests/test_live_trading.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.live.trader import QMTTrader
from xxybacktest.live.context import create_live_context
from xxybacktest.live.trading import get_portfolio, get_account_positions, _refresh_portfolio
from xxybacktest.objects import Position

QMT_PATH   = r"D:\国金QMT交易端模拟\userdata_mini"
ACCOUNT_ID = "86962531"

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
    print(f"\n[setup] 连接 QMT ...")
    _trader = QMTTrader(QMT_PATH, ACCOUNT_ID)
    _ctx    = create_live_context(ACCOUNT_CONFIG, _trader)
    print("[setup] context 构建完成\n")


def teardown():
    if _trader is not None:
        _trader.disconnect()
        print("\n[teardown] 已断开连接")


# ---------------------------------------------------------------------------
# 测试：get_portfolio
# ---------------------------------------------------------------------------

def test_get_portfolio_returns_dict():
    """get_portfolio 应返回 dict，含四个资金字段。"""
    result = get_portfolio(_ctx)
    assert isinstance(result, dict), f"应返回 dict，实际: {type(result)}"
    for key in ('cash', 'frozen_cash', 'market_value', 'total_asset'):
        assert key in result, f"返回 dict 缺少字段: {key}"
    print(f"[PASS] get_portfolio 返回 dict，cash={result['cash']:,.2f}  "
          f"total_asset={result['total_asset']:,.2f}")


def test_get_portfolio_syncs_context():
    """get_portfolio 调用后，context.portfolio 应同步最新资金。"""
    # 先篡改 context.portfolio 的值
    _ctx.portfolio.cash = -1
    _ctx.portfolio.total_value = -1
    _ctx.portfolio.positions_value = -1

    p = _trader.get_portfolio()
    result = get_portfolio(_ctx)

    assert _ctx.portfolio.cash == p['cash'], \
        f"cash 未同步: ctx={_ctx.portfolio.cash}  trader={p['cash']}"
    assert _ctx.portfolio.total_value == p['total_asset'], \
        f"total_value 未同步: ctx={_ctx.portfolio.total_value}  trader={p['total_asset']}"
    assert _ctx.portfolio.positions_value == p['market_value'], \
        f"positions_value 未同步: ctx={_ctx.portfolio.positions_value}  trader={p['market_value']}"
    print("[PASS] get_portfolio 调用后 context.portfolio 已同步")


def test_get_portfolio_return_value_matches_trader():
    """get_portfolio 返回值应与 trader.get_portfolio() 完全一致。"""
    from_trader = _trader.get_portfolio()
    from_func   = get_portfolio(_ctx)
    assert from_func == from_trader, \
        f"返回值不一致:\n  func={from_func}\n  trader={from_trader}"
    print("[PASS] get_portfolio 返回值与 trader.get_portfolio() 一致")


# ---------------------------------------------------------------------------
# 测试：get_account_positions
# ---------------------------------------------------------------------------

def test_get_account_positions_returns_dict():
    """get_account_positions 应返回 dict。"""
    result = get_account_positions(_ctx)
    assert isinstance(result, dict), f"应返回 dict，实际: {type(result)}"
    print(f"[PASS] get_account_positions 返回 dict，共 {len(result)} 只持仓")


def test_get_account_positions_syncs_context():
    """get_account_positions 调用后，context.portfolio.positions 应同步。"""
    # 先清空持仓（模拟旧数据）
    _ctx.portfolio.positions = {}
    assert len(_ctx.portfolio.positions) == 0

    trader_pos = _trader.get_positions()
    get_account_positions(_ctx)

    assert len(_ctx.portfolio.positions) == len(trader_pos), \
        f"持仓未同步: ctx={len(_ctx.portfolio.positions)}  trader={len(trader_pos)}"
    print("[PASS] get_account_positions 调用后 context.portfolio.positions 已同步")


def test_get_account_positions_are_position_objects():
    """同步后的 context.portfolio.positions 中每个值应为 Position 对象。"""
    get_account_positions(_ctx)
    for code, pos in _ctx.portfolio.positions.items():
        assert isinstance(pos, Position), \
            f"{code}: 应为 Position 对象，实际为 {type(pos)}"
    print(f"[PASS] 所有持仓均为 Position 对象")


def test_get_account_positions_fields_match_trader():
    """Position 字段应与 trader.get_positions() 数据对应。"""
    trader_pos = _trader.get_positions()
    if not trader_pos:
        print("[SKIP] 当前无持仓，跳过字段检查")
        return

    get_account_positions(_ctx)
    for code, pos in _ctx.portfolio.positions.items():
        tp = trader_pos[code]
        assert pos.amount          == tp['volume'],          f"{code}: amount 不一致"
        assert pos.enable_amount   == tp['can_sell_volume'], f"{code}: enable_amount 不一致"
        assert pos.cost_basis      == tp['cost_price'],      f"{code}: cost_basis 不一致"
        assert pos.last_sale_price == tp['last_price'],      f"{code}: last_sale_price 不一致"
        assert pos.total_value     == tp['market_value'],    f"{code}: total_value 不一致"
    print("[PASS] 所有 Position 字段与 trader 数据一致")


def test_get_account_positions_return_matches_trader():
    """get_account_positions 返回值应与 trader.get_positions() 完全一致。"""
    from_trader = _trader.get_positions()
    from_func   = get_account_positions(_ctx)
    assert from_func == from_trader, \
        f"返回值不一致:\n  func={from_func}\n  trader={from_trader}"
    print("[PASS] get_account_positions 返回值与 trader.get_positions() 一致")


# ---------------------------------------------------------------------------
# 测试：_refresh_portfolio
# ---------------------------------------------------------------------------

def test_refresh_portfolio_restores_cash_and_positions():
    """_refresh_portfolio 调用后，资金和持仓都应恢复为 QMT 最新值。"""
    # 先篡改 context（模拟旧数据）
    _ctx.portfolio.cash = -999
    _ctx.portfolio.total_value = -999
    _ctx.portfolio.positions_value = -999
    _ctx.portfolio.positions = {}

    p = _trader.get_portfolio()
    trader_pos = _trader.get_positions()

    _refresh_portfolio(_ctx)

    assert _ctx.portfolio.cash == p['cash'], \
        f"cash 未刷新: ctx={_ctx.portfolio.cash}  trader={p['cash']}"
    assert _ctx.portfolio.total_value == p['total_asset'], \
        f"total_value 未刷新: ctx={_ctx.portfolio.total_value}  trader={p['total_asset']}"
    assert len(_ctx.portfolio.positions) == len(trader_pos), \
        f"持仓未刷新: ctx={len(_ctx.portfolio.positions)}  trader={len(trader_pos)}"
    print("[PASS] _refresh_portfolio 同时刷新了资金和持仓")


def test_refresh_portfolio_idempotent():
    """连续两次调用 _refresh_portfolio 结果应一致。"""
    _refresh_portfolio(_ctx)
    cash1 = _ctx.portfolio.cash
    pos_count1 = len(_ctx.portfolio.positions)

    _refresh_portfolio(_ctx)
    cash2 = _ctx.portfolio.cash
    pos_count2 = len(_ctx.portfolio.positions)

    assert cash1 == cash2, f"连续刷新后 cash 不一致: {cash1} != {cash2}"
    assert pos_count1 == pos_count2, f"连续刷新后持仓数量不一致: {pos_count1} != {pos_count2}"
    print("[PASS] _refresh_portfolio 幂等性验证通过")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    setup()
    try:
        print("--- get_portfolio ---")
        test_get_portfolio_returns_dict()
        test_get_portfolio_syncs_context()
        test_get_portfolio_return_value_matches_trader()

        print("\n--- get_account_positions ---")
        test_get_account_positions_returns_dict()
        test_get_account_positions_syncs_context()
        test_get_account_positions_are_position_objects()
        test_get_account_positions_fields_match_trader()
        test_get_account_positions_return_matches_trader()

        print("\n--- _refresh_portfolio ---")
        test_refresh_portfolio_restores_cash_and_positions()
        test_refresh_portfolio_idempotent()

        print("\n========== All live/trading tests passed ==========")
    finally:
        teardown()
