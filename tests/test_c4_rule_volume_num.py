"""C4 数量校验测试

验证 rule_volume_num 规则：
- 卖出截断到 enable_amount
- 清仓时跳过取整（允许零碎卖出）
- 非科创板取整到 100 股
- 科创板(688) 最低 200 股，上限 50000 股
- 买入也要取整
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


def setup_module():
    Data.init_db(DATA_PATH)


def make_context(cash=1000000, rule_list="rule_stop,rule_volume_num",
                 dt_str="2026-03-20 09:30:00"):
    ctx = create_context()
    ctx.portfolio.cash = cash
    ctx.portfolio.total_value = cash
    ctx.portfolio.starting_cash = cash
    ctx.trade.rule_list = rule_list
    ctx.current_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    ctx.previous_date = "2026-03-19"
    return ctx


# ------------------------------------------------------------------
# 买入取整（非科创板）
# ------------------------------------------------------------------

def test_buy_round_down_to_100():
    """买入 150 股 → 取整为 100 股。"""
    ctx = make_context()
    result = order_buy("600519.SH", 150, ctx)
    assert result.status == 1
    assert result.amount == 100


def test_buy_exact_100():
    """买入 100 股 → 不变。"""
    ctx = make_context()
    result = order_buy("600519.SH", 100, ctx)
    assert result.status == 1
    assert result.amount == 100


def test_buy_less_than_100_rejected():
    """买入 50 股 → < 100，归零，拒绝。"""
    ctx = make_context()
    result = order_buy("600519.SH", 50, ctx)
    assert result.status == -1


def test_buy_350_rounds_to_300():
    """买入 350 股 → 取整为 300 股。"""
    ctx = make_context()
    result = order_buy("600519.SH", 350, ctx)
    assert result.status == 1
    assert result.amount == 300


# ------------------------------------------------------------------
# 卖出截断到 enable_amount
# ------------------------------------------------------------------

def test_sell_truncate_to_enable_amount():
    """卖出 1000 股但 enable_amount=500 → 截断为 500。"""
    ctx = make_context()
    ctx.portfolio.positions["600519.SH"] = Position(
        code="600519.SH", amount=1000, enable_amount=500,
        last_sale_price=1450.0
    )
    result = order_sell("600519.SH", 1000, ctx)
    assert result.status == 1
    assert result.amount == 500


def test_sell_enable_amount_zero_rejected():
    """enable_amount=0（今天刚买的）→ 卖出被拒。"""
    ctx = make_context()
    ctx.portfolio.positions["600519.SH"] = Position(
        code="600519.SH", amount=1000, enable_amount=0,
        last_sale_price=1450.0
    )
    result = order_sell("600519.SH", 1000, ctx)
    assert result.status == -1


def test_sell_no_position_rejected():
    """没有持仓 → 卖出被拒。"""
    ctx = make_context()
    result = order_sell("600519.SH", 100, ctx)
    assert result.status == -1


# ------------------------------------------------------------------
# 清仓跳过取整
# ------------------------------------------------------------------

def test_sell_clear_skip_rounding():
    """清仓 150 股（amount==pos.amount）→ 跳过取整，允许零碎卖出。"""
    ctx = make_context()
    ctx.portfolio.positions["600519.SH"] = Position(
        code="600519.SH", amount=150, enable_amount=150,
        last_sale_price=1450.0
    )
    result = order_sell("600519.SH", 150, ctx)
    assert result.status == 1
    assert result.amount == 150


def test_sell_partial_still_rounds():
    """部分卖出 150 股（持仓 1000）→ 取整为 100。"""
    ctx = make_context()
    ctx.portfolio.positions["600519.SH"] = Position(
        code="600519.SH", amount=1000, enable_amount=1000,
        last_sale_price=1450.0
    )
    result = order_sell("600519.SH", 150, ctx)
    assert result.status == 1
    assert result.amount == 100


# ------------------------------------------------------------------
# 科创板(688)
# ------------------------------------------------------------------

def test_buy_star_200():
    """科创板买入 200 股 → 通过（最低 200）。"""
    ctx = make_context(dt_str="2024-01-03 09:30:00")
    ctx.previous_date = "2024-01-02"
    result = order_buy("688001.SH", 200, ctx)
    assert result.status == 1
    assert result.amount == 200


def test_buy_star_less_than_200_rejected():
    """科创板买入 100 股 → < 200，归零，拒绝。"""
    ctx = make_context(dt_str="2024-01-03 09:30:00")
    ctx.previous_date = "2024-01-02"
    result = order_buy("688001.SH", 100, ctx)
    assert result.status == -1


def test_buy_star_over_50000_truncated():
    """科创板买入 60000 股 → 截断为 50000。"""
    ctx = make_context(cash=100_000_000, dt_str="2024-01-03 09:30:00")
    ctx.previous_date = "2024-01-02"
    result = order_buy("688001.SH", 60000, ctx)
    assert result.status == 1
    assert result.amount == 50000


def test_buy_star_no_100_rounding():
    """科创板买入 250 股 → 不取整到 200（>=200 即可，按 1 股交易）。"""
    ctx = make_context(dt_str="2024-01-03 09:30:00")
    ctx.previous_date = "2024-01-02"
    result = order_buy("688001.SH", 250, ctx)
    assert result.status == 1
    assert result.amount == 250


# ------------------------------------------------------------------
# 不配 rule_volume_num 时不生效
# ------------------------------------------------------------------

def test_no_rule_volume_num():
    """rule_list 不含 rule_volume_num 时，50 股也能买。"""
    ctx = make_context(rule_list="rule_stop")
    result = order_buy("600519.SH", 50, ctx)
    assert result.status == 1
    assert result.amount == 50


if __name__ == "__main__":
    setup_module()
    test_buy_round_down_to_100()
    print("[PASS] test_buy_round_down_to_100")
    test_buy_exact_100()
    print("[PASS] test_buy_exact_100")
    test_buy_less_than_100_rejected()
    print("[PASS] test_buy_less_than_100_rejected")
    test_buy_350_rounds_to_300()
    print("[PASS] test_buy_350_rounds_to_300")
    test_sell_truncate_to_enable_amount()
    print("[PASS] test_sell_truncate_to_enable_amount")
    test_sell_enable_amount_zero_rejected()
    print("[PASS] test_sell_enable_amount_zero_rejected")
    test_sell_no_position_rejected()
    print("[PASS] test_sell_no_position_rejected")
    test_sell_clear_skip_rounding()
    print("[PASS] test_sell_clear_skip_rounding")
    test_sell_partial_still_rounds()
    print("[PASS] test_sell_partial_still_rounds")
    test_buy_star_200()
    print("[PASS] test_buy_star_200")
    test_buy_star_less_than_200_rejected()
    print("[PASS] test_buy_star_less_than_200_rejected")
    test_buy_star_over_50000_truncated()
    print("[PASS] test_buy_star_over_50000_truncated")
    test_buy_star_no_100_rounding()
    print("[PASS] test_buy_star_no_100_rounding")
    test_no_rule_volume_num()
    print("[PASS] test_no_rule_volume_num")
    print()
    print("All C4 tests passed.")
