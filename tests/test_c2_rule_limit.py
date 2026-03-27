"""C2 涨跌停检查测试

用真实数据验证（2026-03-20）:
- 涨停封板 → 拒绝买入
- 跌停封板 → 拒绝卖出
- 涨停打开（盘中触及但未封住）→ 允许买入
- 跌停不影响买入，涨停不影响卖出

真实数据来源:
  一字涨停: 000908.SZ  open=6.45 high=6.45 low=6.45 close=6.45 upLimit=6.45 downLimit=5.83
  一字跌停: 000638.SZ  2026-03-19 open=1.34 high=1.34 low=1.34 close=1.34 upLimit=1.48 downLimit=1.34
  涨停打开: 000821.SZ  open=12.80 high=13.24 close=13.05 upLimit=13.24 (high==upLimit 但 close<upLimit)
  正常股票: 600519.SH  open=1452.96 close=1445.00
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


def make_context(cash=1000000, rule_list="rule_stop,rule_limit",
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
# 涨停封板 → 拒绝买入
# ------------------------------------------------------------------

def test_limit_up_buy_rejected():
    """一字涨停股票（000908.SZ）买入被拒。
    2026-03-20: open=6.45, high=6.45, close=6.45, upLimit=6.45
    09:30 price=open=6.45 >= upLimit=6.45 且 price==high=6.45 → 拒绝买入
    """
    ctx = make_context()
    result = order_buy("000908.SZ", 100, ctx)
    assert result.status == -1
    assert "000908.SZ" not in ctx.portfolio.positions


def test_limit_up_sell_allowed():
    """涨停封板股票卖出不受影响（涨停只拦买入）。
    涨停时有人愿意以涨停价买，卖方当然能卖出。
    """
    ctx = make_context()
    ctx.portfolio.positions["000908.SZ"] = Position(
        code="000908.SZ", amount=1000, enable_amount=1000, last_sale_price=6.0
    )
    result = order_sell("000908.SZ", 1000, ctx)
    assert result.status == 1


# ------------------------------------------------------------------
# 跌停封板 → 拒绝卖出
# ------------------------------------------------------------------

def test_limit_down_sell_rejected():
    """一字跌停股票（000638.SZ）卖出被拒。
    2026-03-19: open=1.34, high=1.34, low=1.34, close=1.34, downLimit=1.34
    09:30 price=open=1.34 <= downLimit=1.34 且 price==low=1.34 → 拒绝卖出
    """
    ctx = make_context(dt_str="2026-03-19 09:30:00")
    ctx.previous_date = "2026-03-18"
    ctx.portfolio.positions["000638.SZ"] = Position(
        code="000638.SZ", amount=1000, enable_amount=1000, last_sale_price=1.50
    )
    result = order_sell("000638.SZ", 1000, ctx)
    assert result.status == -1
    assert ctx.portfolio.positions["000638.SZ"].amount == 1000


def test_limit_down_buy_allowed():
    """跌停封板股票买入不受影响（跌停只拦卖出）。
    跌停时有人愿意以跌停价卖，买方当然能买入。
    """
    ctx = make_context(dt_str="2026-03-19 09:30:00")
    ctx.previous_date = "2026-03-18"
    result = order_buy("000638.SZ", 100, ctx)
    assert result.status == 1


# ------------------------------------------------------------------
# 涨停打开 → 允许买入
# ------------------------------------------------------------------

def test_limit_up_opened_buy_allowed():
    """盘中触及涨停但打开的股票（000821.SZ）允许买入。
    2026-03-20: open=12.80, high=13.24, close=13.05, upLimit=13.24
    09:30 price=open=12.80 < upLimit=13.24 → 不满足 price >= upLimit，允许买入
    """
    ctx = make_context()
    result = order_buy("000821.SZ", 100, ctx)
    assert result.status == 1


# ------------------------------------------------------------------
# 正常股票不受影响
# ------------------------------------------------------------------

def test_normal_stock_unaffected():
    """正常股票（600519.SH）买卖都不受涨跌停规则影响。
    2026-03-20: open=1452.96, close=1445.00
    """
    ctx = make_context()
    result = order_buy("600519.SH", 10, ctx)
    assert result.status == 1


# ------------------------------------------------------------------
# 只配 rule_stop 时，涨跌停不生效
# ------------------------------------------------------------------

def test_limit_not_checked_without_rule():
    """rule_list 不含 rule_limit 时，涨停股也能买入。"""
    ctx = make_context(rule_list="rule_stop")
    result = order_buy("000908.SZ", 100, ctx)
    assert result.status == 1


if __name__ == "__main__":
    setup_module()
    test_limit_up_buy_rejected()
    print("[PASS] test_limit_up_buy_rejected")
    test_limit_up_sell_allowed()
    print("[PASS] test_limit_up_sell_allowed")
    test_limit_down_sell_rejected()
    print("[PASS] test_limit_down_sell_rejected")
    test_limit_down_buy_allowed()
    print("[PASS] test_limit_down_buy_allowed")
    test_limit_up_opened_buy_allowed()
    print("[PASS] test_limit_up_opened_buy_allowed")
    test_normal_stock_unaffected()
    print("[PASS] test_normal_stock_unaffected")
    test_limit_not_checked_without_rule()
    print("[PASS] test_limit_not_checked_without_rule")
    print()
    print("All C2 tests passed.")
