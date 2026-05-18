"""
live/context.py 真实环境测试

前提：QMT 客户端已启动并登录。
运行：python tests/test_live_context.py
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.live.trader import QMTTrader
from xxybacktest.live.context import create_live_context
from xxybacktest.objects import Position

QMT_PATH   = r"D:\国金证券QMT交易端\userdata_mini"
ACCOUNT_ID = "8881686799"

# 模拟 submitter.get_account() 返回的账户配置
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
# 测试：context 基础结构
# ---------------------------------------------------------------------------

def test_context_has_required_fields():
    """context 应包含回测所需的全部顶层字段。"""
    for field in ('portfolio', 'trade', 'account', 'data', 'logs', 'performance', 'g'):
        assert hasattr(_ctx, field), f"缺少字段: {field}"
    print("[PASS] context 包含全部顶层字段")


def test_context_has_trader_attached():
    """context._trader 应指向传入的 QMTTrader 实例。"""
    assert _ctx._trader is _trader
    print("[PASS] context._trader 已挂载")


def test_context_current_dt_is_datetime():
    """current_dt 应为 datetime 对象且接近当前时间（1分钟内）。"""
    assert isinstance(_ctx.current_dt, datetime)
    delta = abs((datetime.now() - _ctx.current_dt).total_seconds())
    assert delta < 60, f"current_dt 与当前时间差 {delta:.1f}s，超过 60s"
    print(f"[PASS] current_dt = {_ctx.current_dt}")


# ---------------------------------------------------------------------------
# 测试：portfolio 资金
# ---------------------------------------------------------------------------

def test_portfolio_cash_matches_trader():
    """context.portfolio.cash 应与 trader.get_portfolio()['cash'] 一致。"""
    p = _trader.get_portfolio()
    assert _ctx.portfolio.cash == p['cash'], \
        f"cash 不一致: ctx={_ctx.portfolio.cash}  trader={p['cash']}"
    print(f"[PASS] portfolio.cash = {_ctx.portfolio.cash:,.2f}")


def test_portfolio_total_value_matches_trader():
    """context.portfolio.total_value 应与 trader.get_portfolio()['total_asset'] 一致。"""
    p = _trader.get_portfolio()
    assert _ctx.portfolio.total_value == p['total_asset'], \
        f"total_value 不一致: ctx={_ctx.portfolio.total_value}  trader={p['total_asset']}"
    print(f"[PASS] portfolio.total_value = {_ctx.portfolio.total_value:,.2f}")


def test_portfolio_starting_cash_from_config():
    """starting_cash 应等于账户配置里的 initial_cash（提交时锁定，永不变动）。"""
    assert _ctx.portfolio.starting_cash == ACCOUNT_CONFIG['initial_cash']
    print(f"[PASS] portfolio.starting_cash = {_ctx.portfolio.starting_cash:,.2f}")


def test_portfolio_total_value_positive():
    """总资产应大于 0。"""
    assert _ctx.portfolio.total_value > 0
    print(f"[PASS] total_value > 0")


# ---------------------------------------------------------------------------
# 测试：持仓 Position 对象
# ---------------------------------------------------------------------------

def test_positions_are_position_objects():
    """portfolio.positions 中的每个值应为 Position 实例。"""
    for code, pos in _ctx.portfolio.positions.items():
        assert isinstance(pos, Position), \
            f"{code}: 应为 Position 对象，实际为 {type(pos)}"
    print(f"[PASS] 所有持仓均为 Position 对象，共 {len(_ctx.portfolio.positions)} 只")


def test_positions_match_trader():
    """context 持仓数量应与 trader.get_positions() 一致。"""
    trader_pos = _trader.get_positions()
    assert len(_ctx.portfolio.positions) == len(trader_pos), \
        f"持仓数量不一致: ctx={len(_ctx.portfolio.positions)}  trader={len(trader_pos)}"
    print(f"[PASS] 持仓数量一致: {len(_ctx.portfolio.positions)} 只")


def test_position_fields_correct():
    """每个 Position 的字段应与 trader 数据对应。"""
    trader_pos = _trader.get_positions()
    if not trader_pos:
        print("[SKIP] 当前无持仓")
        return

    for code, pos in _ctx.portfolio.positions.items():
        tp = trader_pos[code]
        assert pos.amount         == tp['volume'],          f"{code}: amount 不一致"
        assert pos.enable_amount  == tp['can_sell_volume'], f"{code}: enable_amount 不一致"
        assert pos.cost_basis     == tp['cost_price'],      f"{code}: cost_basis 不一致"
        assert pos.last_sale_price == tp['last_price'],     f"{code}: last_sale_price 不一致"
        assert pos.total_value    == tp['market_value'],    f"{code}: total_value 不一致"
        print(f"  {code}: amount={pos.amount}  enable={pos.enable_amount}  "
              f"cost={pos.cost_basis:.3f}  last={pos.last_sale_price:.3f}")

    print(f"[PASS] 所有持仓字段与 trader 数据一致")


def test_position_total_cost_calculated():
    """Position.total_cost 应等于 volume * cost_price。"""
    if not _ctx.portfolio.positions:
        print("[SKIP] 当前无持仓")
        return

    for code, pos in _ctx.portfolio.positions.items():
        expected = pos.amount * pos.cost_basis
        assert abs(pos.total_cost - expected) < 0.01, \
            f"{code}: total_cost={pos.total_cost:.2f} != volume*cost={expected:.2f}"
    print("[PASS] Position.total_cost == volume * cost_price")


# ---------------------------------------------------------------------------
# 测试：trade 配置
# ---------------------------------------------------------------------------

def test_trade_config_from_account():
    """trade 字段应来自账户配置。"""
    assert _ctx.trade.asset_type == ACCOUNT_CONFIG['asset_type']
    assert _ctx.trade.benchmark  == ACCOUNT_CONFIG['benchmark']
    assert _ctx.trade.start_time == ACCOUNT_CONFIG['start_date']
    print(f"[PASS] trade 配置正确: asset_type={_ctx.trade.asset_type}  "
          f"benchmark={_ctx.trade.benchmark}")


def test_data_path_from_account():
    """data.data_path 应来自账户配置。"""
    assert _ctx.data.data_path == ACCOUNT_CONFIG['data_path']
    print(f"[PASS] data.data_path = {_ctx.data.data_path}")


# ---------------------------------------------------------------------------
# 测试：strategy_state 恢复
# ---------------------------------------------------------------------------

def test_strategy_state_restored():
    """传入 strategy_state 时，context.g 应包含对应键值。"""
    state = {'counter': 5, 'last_weights': {'000001.SZ': 0.2}}
    ctx2 = create_live_context(ACCOUNT_CONFIG, _trader, strategy_state=state)

    assert ctx2.g['counter'] == 5
    assert ctx2.g['last_weights']['000001.SZ'] == 0.2
    print("[PASS] strategy_state 正确恢复到 context.g")


def test_strategy_state_none_gives_empty_g():
    """不传 strategy_state 时，context.g 应为空。"""
    ctx2 = create_live_context(ACCOUNT_CONFIG, _trader, strategy_state=None)
    assert len(ctx2.g) == 0
    print("[PASS] strategy_state=None 时 context.g 为空")


def test_two_contexts_are_independent():
    """两次调用 create_live_context 应返回独立实例，修改一个不影响另一个。"""
    ctx_a = create_live_context(ACCOUNT_CONFIG, _trader)
    ctx_b = create_live_context(ACCOUNT_CONFIG, _trader)
    ctx_a.g['x'] = 999
    assert 'x' not in ctx_b.g
    print("[PASS] 两个 context 实例相互独立")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    setup()
    try:
        print("--- 基础结构 ---")
        test_context_has_required_fields()
        test_context_has_trader_attached()
        test_context_current_dt_is_datetime()

        print("\n--- portfolio 资金 ---")
        test_portfolio_cash_matches_trader()
        test_portfolio_total_value_matches_trader()
        test_portfolio_starting_cash_from_config()
        test_portfolio_total_value_positive()

        print("\n--- 持仓 Position ---")
        test_positions_are_position_objects()
        test_positions_match_trader()
        test_position_fields_correct()
        test_position_total_cost_calculated()

        print("\n--- trade 配置 ---")
        test_trade_config_from_account()
        test_data_path_from_account()

        print("\n--- strategy_state ---")
        test_strategy_state_restored()
        test_strategy_state_none_gives_empty_g()
        test_two_contexts_are_independent()

        print("\n========== All live/context tests passed ==========")
    finally:
        teardown()
