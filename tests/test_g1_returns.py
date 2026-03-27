"""G1: 收益率序列处理 测试

验证 Performance.analyse 将原始净值比转为 pd.Series，
基准收益率序列正确获取并对齐。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from xxybacktest.backtest import run_backtest

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data")


def test_returns_is_series():
    """回测结束后 returns 应为 pd.Series，DatetimeIndex。"""
    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=lambda ctx: None,
        start_date="2024-01-02",
        end_date="2024-01-10",
        capital=1000000,
        data_path=DATA_PATH,
    )
    returns = ctx.performance.returns
    assert isinstance(returns, pd.Series), f"Expected pd.Series, got {type(returns)}"
    assert isinstance(returns.index, pd.DatetimeIndex)


def test_bench_returns_is_series():
    """回测结束后 bench_returns 应为 pd.Series，DatetimeIndex。"""
    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=lambda ctx: None,
        start_date="2024-01-02",
        end_date="2024-01-10",
        capital=1000000,
        data_path=DATA_PATH,
    )
    bench = ctx.performance.bench_returns
    assert isinstance(bench, pd.Series), f"Expected pd.Series, got {type(bench)}"
    assert isinstance(bench.index, pd.DatetimeIndex)
    assert len(bench) > 0


def test_returns_values_reasonable():
    """无持仓时每日涨跌幅应为 0；有持仓时应在合理范围。"""
    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=lambda ctx: None,
        start_date="2024-01-02",
        end_date="2024-01-10",
        capital=1000000,
        data_path=DATA_PATH,
    )
    returns = ctx.performance.returns
    # 无持仓，净值比始终为 1.0 → 涨跌幅 0.0
    for val in returns:
        assert val == 0.0, f"Expected 0.0, got {val}"


def test_returns_range_with_position():
    """有持仓时，每日涨跌幅通常在 -0.1 ~ 0.1 之间。"""
    from xxybacktest.trading import order

    def my_strategy(ctx):
        if "000001.SZ" not in ctx.portfolio.positions:
            order("000001.SZ", 100, ctx)

    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=my_strategy,
        start_date="2024-01-02",
        end_date="2024-01-31",
        capital=1000000,
        data_path=DATA_PATH,
    )
    returns = ctx.performance.returns
    for val in returns:
        assert -0.2 < val < 0.2, f"Daily return {val} out of reasonable range"


def test_bench_returns_length():
    """bench_returns 长度应与交易日历一致。"""
    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=lambda ctx: None,
        start_date="2024-01-02",
        end_date="2024-01-31",
        capital=1000000,
        data_path=DATA_PATH,
    )
    bench = ctx.performance.bench_returns
    calendar = ctx.data.calendar
    # 基准指数的交易日数量应与日历一致
    assert len(bench) == len(calendar), (
        f"bench_returns length {len(bench)} != calendar length {len(calendar)}"
    )


def test_returns_length_matches_calendar():
    """策略 returns 长度应与交易日历一致。"""
    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=lambda ctx: None,
        start_date="2024-01-02",
        end_date="2024-01-31",
        capital=1000000,
        data_path=DATA_PATH,
    )
    returns = ctx.performance.returns
    calendar = ctx.data.calendar
    assert len(returns) == len(calendar), (
        f"returns length {len(returns)} != calendar length {len(calendar)}"
    )


if __name__ == "__main__":
    test_returns_is_series()
    test_bench_returns_is_series()
    test_returns_values_reasonable()
    test_returns_range_with_position()
    test_bench_returns_length()
    test_returns_length_matches_calendar()
    print("All G1 tests passed.")
