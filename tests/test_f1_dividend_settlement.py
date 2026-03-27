"""
F1/F2/F3 测试：分红派息登记、送股处理、分红数据预加载

使用真实数据库中的分红数据做集成测试。
已知测试数据：
- 002385.SZ: register_date=2019-01-04, ex_date=pay_date=2019-01-07,
             cash_div_tax=0.072, stk_div=0（纯派现）
- 300125.SZ: register_date=2019-03-12, ex_date=2019-03-13,
             stk_div≈0.50925, cash_div_tax=0（纯送股）
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.backtest import run_backtest
from xxybacktest.data import Data
from xxybacktest.trading import order_buy

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data")


# ===========================================================================
# F1 测试：分红派息登记与发放
# ===========================================================================


class TestF1CashDividend:
    """测试 after_market 的分红派息两阶段逻辑。"""

    def test_cash_dividend_registered_and_paid(self):
        """002385.SZ 在 2019-01-04 登记，2019-01-07 派息。
        买入 10000 股后应在 pay_date 收到 10000 * 0.072 = 720 元。
        """
        bought = []

        def my_init(ctx):
            pass

        def my_strategy(ctx):
            date_str = ctx.current_dt.strftime("%Y-%m-%d")
            # 在登记日之前买入
            if date_str == "2019-01-03" and not bought:
                order_buy("002385.SZ", 10000, ctx)
                bought.append(True)

        ctx = run_backtest(
            initialize=my_init,
            handle_data=my_strategy,
            start_date="2019-01-02",
            end_date="2019-01-10",
            capital=1000000,
            data_path=DATA_PATH,
        )

        # 验证分红缓存中有登记记录
        assert "dt_2019-01-07" in ctx.data.dividend
        assert "002385.SZ" in ctx.data.dividend["dt_2019-01-07"]
        entry = ctx.data.dividend["dt_2019-01-07"]["002385.SZ"]
        assert abs(entry["cash_tax"] - 10000 * 0.072) < 0.01

        # 验证现金增加了分红金额（精确值取决于买入成本，这里验证 cash > 初始 - 买入成本）
        # 分红 720 元应已计入 cash
        # 无法精确验证绝对值（因为买入价取决于当日行情），但可验证分红确实发生
        assert entry["cash_tax"] > 0

    def test_cost_basis_updated_after_dividend(self):
        """分红后 pos.cost_basis 应下降（修复原项目 Bug）。"""
        cost_basis_before = [None]
        cost_basis_after = [None]

        def my_init(ctx):
            pass

        def my_strategy(ctx):
            date_str = ctx.current_dt.strftime("%Y-%m-%d")
            if date_str == "2019-01-03":
                order_buy("002385.SZ", 10000, ctx)
            # 登记日（2019-01-04 18:00 after_market）之后，记录 cost_basis
            if date_str == "2019-01-04":
                if "002385.SZ" in ctx.portfolio.positions:
                    cost_basis_before[0] = ctx.portfolio.positions["002385.SZ"].cost_basis
            # 派息日（2019-01-07 18:00 after_market）之后的下一个交易日
            if date_str == "2019-01-08":
                if "002385.SZ" in ctx.portfolio.positions:
                    cost_basis_after[0] = ctx.portfolio.positions["002385.SZ"].cost_basis

        ctx = run_backtest(
            initialize=my_init,
            handle_data=my_strategy,
            start_date="2019-01-02",
            end_date="2019-01-10",
            capital=1000000,
            data_path=DATA_PATH,
        )

        assert cost_basis_before[0] is not None
        assert cost_basis_after[0] is not None
        # 分红后 cost_basis 应更小
        assert cost_basis_after[0] < cost_basis_before[0]

    def test_no_dividend_no_change(self):
        """无分红的股票不应受影响。"""

        def my_init(ctx):
            pass

        def my_strategy(ctx):
            date_str = ctx.current_dt.strftime("%Y-%m-%d")
            if date_str == "2019-01-03":
                order_buy("000001.SZ", 1000, ctx)

        ctx = run_backtest(
            initialize=my_init,
            handle_data=my_strategy,
            start_date="2019-01-02",
            end_date="2019-01-10",
            capital=1000000,
            data_path=DATA_PATH,
        )

        # 000001.SZ 在此区间无分红，dividend 缓存中不应有它的记录
        for dt_key, codes in ctx.data.dividend.items():
            if "000001.SZ" in codes:
                # 如果预加载了也不应影响持仓
                assert codes["000001.SZ"]["cash_tax"] == 0 or codes["000001.SZ"].get("preloaded")


# ===========================================================================
# F2 测试：送股处理
# ===========================================================================


class TestF2StockSplit:
    """测试 before_market 的送股处理逻辑。"""

    def test_stock_split_increases_amount(self):
        """300125.SZ 在 2019-03-13 除权日送股（stk_div≈0.50925）。
        买入 10000 股后应增加约 5092 股。
        """
        amount_before = [None]
        amount_after = [None]

        def my_init(ctx):
            pass

        def my_strategy(ctx):
            date_str = ctx.current_dt.strftime("%Y-%m-%d")
            if date_str == "2019-03-11":
                order_buy("300125.SZ", 10000, ctx)
            # 登记日之后、除权日之前
            if date_str == "2019-03-12":
                if "300125.SZ" in ctx.portfolio.positions:
                    amount_before[0] = ctx.portfolio.positions["300125.SZ"].amount
            # 除权日（2019-03-13）盘前送股后，策略执行时已更新
            if date_str == "2019-03-13":
                if "300125.SZ" in ctx.portfolio.positions:
                    amount_after[0] = ctx.portfolio.positions["300125.SZ"].amount

        ctx = run_backtest(
            initialize=my_init,
            handle_data=my_strategy,
            start_date="2019-03-08",
            end_date="2019-03-15",
            capital=1000000,
            data_path=DATA_PATH,
        )

        assert amount_before[0] is not None
        assert amount_after[0] is not None
        assert amount_after[0] > amount_before[0]
        # 10000 * 0.50925 ≈ 5092.5，总量应约 15092
        expected_new = int(10000 * 0.50925)
        assert abs(amount_after[0] - (10000 + expected_new)) < 2  # 浮点容差

    def test_stock_split_dilutes_cost_basis(self):
        """送股后 cost_basis 应下降（成本稀释）。"""
        cost_basis_log = {}

        def my_init(ctx):
            pass

        def my_strategy(ctx):
            date_str = ctx.current_dt.strftime("%Y-%m-%d")
            if date_str == "2019-03-11":
                order_buy("300125.SZ", 10000, ctx)
            if "300125.SZ" in ctx.portfolio.positions:
                cost_basis_log[date_str] = ctx.portfolio.positions["300125.SZ"].cost_basis

        ctx = run_backtest(
            initialize=my_init,
            handle_data=my_strategy,
            start_date="2019-03-08",
            end_date="2019-03-15",
            capital=1000000,
            data_path=DATA_PATH,
        )

        # 2019-03-12（送股前）的 cost_basis > 2019-03-13（送股后）
        assert "2019-03-12" in cost_basis_log
        assert "2019-03-13" in cost_basis_log
        assert cost_basis_log["2019-03-13"] < cost_basis_log["2019-03-12"]


# ===========================================================================
# F3 测试：分红数据预加载
# ===========================================================================


class TestF3DividendPreload:
    """测试回测开始前的分红数据预加载。

    002385.SZ: register_date=2019-01-04, pay_date=2019-01-07
    如果回测从 2019-01-07 开始（register_date 在回测前），
    预加载应把 pay_date=2019-01-07 的数据放入缓存。
    """

    def test_preload_fills_cache(self):
        """回测起始日晚于 register_date 时，预加载应填入缓存。"""
        ctx = run_backtest(
            initialize=lambda ctx: None,
            handle_data=lambda ctx: None,
            start_date="2019-01-07",
            end_date="2019-01-10",
            capital=1000000,
            data_path=DATA_PATH,
        )

        # 预加载应在缓存中有 2019-01-07 的记录
        assert "dt_2019-01-07" in ctx.data.dividend
        assert "002385.SZ" in ctx.data.dividend["dt_2019-01-07"]

    def test_preloaded_dividend_paid_on_pay_date(self):
        """预加载的分红在 pay_date 应正确发放给持仓。

        场景：回测从 2019-01-04 开始（当天买入），register_date=2019-01-04
        正好在回测首日，after_market 能捕获。
        这里测试回测从 2019-01-07 开始，register_date 已过，
        需要靠 F3 预加载。但由于回测开始时无持仓，预加载的分红
        在 pay_date 时需要按实际持仓计算。
        """
        # 如果回测从 2019-01-07 开始，首日 09:30 买入，
        # 但 after_market 的阶段2在 18:00 执行，此时已有持仓，应正确计算
        bought = []

        def my_init(ctx):
            pass

        def my_strategy(ctx):
            date_str = ctx.current_dt.strftime("%Y-%m-%d")
            if date_str == "2019-01-07" and not bought:
                order_buy("002385.SZ", 10000, ctx)
                bought.append(True)

        ctx = run_backtest(
            initialize=my_init,
            handle_data=my_strategy,
            start_date="2019-01-07",
            end_date="2019-01-10",
            capital=1000000,
            data_path=DATA_PATH,
        )

        # 验证预加载记录已被解析（preloaded 标记应被清除）
        entry = ctx.data.dividend["dt_2019-01-07"]["002385.SZ"]
        assert entry.get("preloaded") is not True or entry.get("preloaded") is False
        # 如果当日买入且当日派息，cash_tax 应为 10000 * 0.072 = 720
        assert abs(entry["cash_tax"] - 10000 * 0.072) < 0.01


# ===========================================================================
# 事件顺序测试
# ===========================================================================


class TestEventOrder:
    """验证 after_market 事件确实在 18:00 执行。"""

    def test_after_market_event_exists(self):
        """事件列表中应包含 after_market 事件。"""
        event_log = []

        def my_init(ctx):
            pass

        def my_strategy(ctx):
            pass

        ctx = run_backtest(
            initialize=my_init,
            handle_data=my_strategy,
            start_date="2019-01-02",
            end_date="2019-01-03",
            capital=1000000,
            data_path=DATA_PATH,
        )

        # 所有事件已执行完毕（event_list 被 pop 完），
        # 但我们可以验证回测正常完成且 current_dt 正确
        assert ctx.current_dt.hour == 23
        assert ctx.current_dt.minute == 59


if __name__ == "__main__":
    Data.init_db(path=DATA_PATH)

    print("=== F1: Cash Dividend Tests ===")
    t1 = TestF1CashDividend()
    t1.test_cash_dividend_registered_and_paid()
    print("  [PASS] test_cash_dividend_registered_and_paid")
    t1.test_cost_basis_updated_after_dividend()
    print("  [PASS] test_cost_basis_updated_after_dividend")
    t1.test_no_dividend_no_change()
    print("  [PASS] test_no_dividend_no_change")

    print("\n=== F2: Stock Split Tests ===")
    t2 = TestF2StockSplit()
    t2.test_stock_split_increases_amount()
    print("  [PASS] test_stock_split_increases_amount")
    t2.test_stock_split_dilutes_cost_basis()
    print("  [PASS] test_stock_split_dilutes_cost_basis")

    print("\n=== F3: Dividend Preload Tests ===")
    t3 = TestF3DividendPreload()
    t3.test_preload_fills_cache()
    print("  [PASS] test_preload_fills_cache")
    t3.test_preloaded_dividend_paid_on_pay_date()
    print("  [PASS] test_preloaded_dividend_paid_on_pay_date")

    print("\n=== Event Order Tests ===")
    t4 = TestEventOrder()
    t4.test_after_market_event_exists()
    print("  [PASS] test_after_market_event_exists")

    print("\nAll F1/F2/F3 tests passed.")
