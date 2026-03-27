"""C8 成交量比例限制测试

验证 rule_volume_ratio 规则：
- 下单量 <= 当日成交量 × ratio → 通过
- 下单量 > 当日成交量 × ratio → 截断
- ratio=1（默认）→ 不截断
- 成交量为 0 → 拒绝

真实数据: 600519.SH 2026-03-20 volume（股）从数据库取
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.context import create_context
from xxybacktest.trading import order_buy
from xxybacktest.data import Data

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data")


def setup_module():
    Data.init_db(DATA_PATH)


def make_context(cash=1000000, rule_list="rule_stop,rule_volume_ratio",
                 dt_str="2026-03-20 09:30:00", ratio=0.25):
    ctx = create_context()
    ctx.portfolio.cash = cash
    ctx.portfolio.total_value = cash
    ctx.portfolio.starting_cash = cash
    ctx.trade.rule_list = rule_list
    ctx.trade.order_volume_ratio = ratio
    ctx.current_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    ctx.previous_date = "2026-03-19"
    return ctx


# ------------------------------------------------------------------
# 不超过限制 → 通过
# ------------------------------------------------------------------

def test_within_limit():
    """小单不触发截断，amount 不变。"""
    ctx = make_context(ratio=0.25)
    result = order_buy("600519.SH", 100, ctx)
    assert result.status == 1
    assert result.amount == 100


# ------------------------------------------------------------------
# 超过限制 → 截断
# ------------------------------------------------------------------

def test_exceeds_limit_truncated():
    """下单量超过 volume × ratio 时被截断。
    设 ratio=0.0001，600519.SH 日成交量很大但乘以极小比例后会小于下单量。
    """
    ctx = make_context(ratio=0.0001)
    # 先查出实际成交量来算预期
    info = Data.get_daily_info("600519.SH", ctx)
    max_amount = int(info.volume * 0.0001)

    result = order_buy("600519.SH", 10000, ctx)
    if max_amount <= 0:
        assert result.status == -1
    else:
        assert result.status == 1
        assert result.amount == max_amount


# ------------------------------------------------------------------
# ratio=1（默认）→ 不截断
# ------------------------------------------------------------------

def test_ratio_1_no_truncation():
    """ratio=1 时，只要 amount <= volume 就不截断。"""
    ctx = make_context(ratio=1)
    result = order_buy("600519.SH", 100, ctx)
    assert result.status == 1
    assert result.amount == 100


# ------------------------------------------------------------------
# 不配此规则时不生效
# ------------------------------------------------------------------

def test_no_rule_volume_ratio():
    """rule_list 不含 rule_volume_ratio 时不截断。"""
    ctx = make_context(rule_list="rule_stop", ratio=0.0001)
    result = order_buy("600519.SH", 10000, ctx)
    assert result.status == 1
    assert result.amount == 10000


if __name__ == "__main__":
    setup_module()
    test_within_limit()
    print("[PASS] test_within_limit")
    test_exceeds_limit_truncated()
    print("[PASS] test_exceeds_limit_truncated")
    test_ratio_1_no_truncation()
    print("[PASS] test_ratio_1_no_truncation")
    test_no_rule_volume_ratio()
    print("[PASS] test_no_rule_volume_ratio")
    print()
    print("All C8 tests passed.")
