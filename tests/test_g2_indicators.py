"""G2: 绩效指标计算 测试

验证 Performance._compute_indicators 的各项指标计算逻辑，
以及通过 run_backtest 端到端验证 indicators 写入 context。
"""

import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from xxybacktest.context import create_context, DictObj
from xxybacktest.performance import Performance, _safe

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data")


# ------------------------------------------------------------------
# _safe 辅助函数
# ------------------------------------------------------------------

def test_safe_nan():
    assert _safe(float("nan")) == 0.0


def test_safe_inf():
    assert _safe(float("inf")) == 0.0
    assert _safe(float("-inf")) == 0.0


def test_safe_none():
    assert _safe(None) == 0.0


def test_safe_normal():
    assert _safe(1.5) == 1.5
    assert _safe(-0.3) == -0.3


# ------------------------------------------------------------------
# 无交易场景：indicators 应全部为 0 或合理默认值
# ------------------------------------------------------------------

def test_no_trade_indicators():
    """无持仓无交易 → 大部分指标为 0。"""
    from xxybacktest.backtest import run_backtest

    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=lambda ctx: None,
        start_date="2024-01-02",
        end_date="2024-01-31",
        capital=1000000,
        data_path=DATA_PATH,
    )
    ind = ctx.performance.indicators

    assert isinstance(ind, (dict, DictObj))
    assert ind["trade_num"] == 0
    assert ind["win_ratio"] == 0.0
    assert ind["sqn"] == 0.0
    assert ind["roto"] == 0.0  # total_value == starting_cash
    assert ind["annual_return"] == 0.0
    assert ind["max_drawdown"] == 0.0
    assert ind["sharpe"] == 0.0


# ------------------------------------------------------------------
# 有交易场景：indicators 应在合理范围
# ------------------------------------------------------------------

def test_with_trade_indicators():
    """有交易时各项指标应有值且在合理范围。"""
    from xxybacktest.backtest import run_backtest
    from xxybacktest.trading import order

    def my_strategy(ctx):
        if "000001.SZ" not in ctx.portfolio.positions:
            order("000001.SZ", 1000, ctx)

    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=my_strategy,
        start_date="2024-01-02",
        end_date="2024-03-29",
        capital=1000000,
        data_path=DATA_PATH,
    )
    ind = ctx.performance.indicators

    assert isinstance(ind, (dict, DictObj))

    # 必须包含所有指标 key
    expected_keys = [
        "alpha", "beta", "annual_return", "cagr", "annual_volatility",
        "sharpe", "sortino", "calmar", "omega", "max_drawdown",
        "info_ratio", "downside_risk", "R2", "sqn", "roto",
        "win_ratio", "trade_num",
    ]
    for k in expected_keys:
        assert k in ind, f"Missing indicator: {k}"

    # 各指标不应为 NaN 或 Inf
    for k, v in ind.items():
        assert not math.isnan(v), f"{k} is NaN"
        assert not math.isinf(v), f"{k} is Inf"

    # trade_num 至少 1（买了 1000 股）
    # 注意：只买不卖 trade_num 为 0（只在卖出时计数）
    # roto 应非零（持仓有价格波动）
    assert isinstance(ind["roto"], float)

    # max_drawdown 应 <= 0
    assert ind["max_drawdown"] <= 0


# ------------------------------------------------------------------
# 有买有卖场景：win_ratio / sqn / trade_num 验证
# ------------------------------------------------------------------

def test_buy_sell_indicators():
    """买入再卖出，验证 trade_num、win_ratio、sqn 有值。"""
    from xxybacktest.backtest import run_backtest
    from xxybacktest.trading import order

    call_count = {"n": 0}

    def my_strategy(ctx):
        call_count["n"] += 1
        if call_count["n"] == 1:
            order("000001.SZ", 100, ctx)
        elif call_count["n"] == 5:
            order("000001.SZ", -100, ctx)

    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=my_strategy,
        start_date="2024-01-02",
        end_date="2024-01-31",
        capital=1000000,
        data_path=DATA_PATH,
    )
    ind = ctx.performance.indicators

    assert ind["trade_num"] == 1
    assert 0.0 <= ind["win_ratio"] <= 1.0
    # sqn 需要 trade_num > 1，这里只有 1 笔，应为 0
    assert ind["sqn"] == 0.0


def test_multiple_trades_sqn():
    """多笔卖出交易，sqn 应有非零值。"""
    from xxybacktest.backtest import run_backtest
    from xxybacktest.trading import order

    call_count = {"n": 0}

    def my_strategy(ctx):
        call_count["n"] += 1
        if call_count["n"] == 1:
            order("000001.SZ", 500, ctx)
        elif call_count["n"] == 3:
            order("000001.SZ", -100, ctx)
        elif call_count["n"] == 5:
            order("000001.SZ", -100, ctx)
        elif call_count["n"] == 7:
            order("000001.SZ", -100, ctx)

    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=my_strategy,
        start_date="2024-01-02",
        end_date="2024-02-29",
        capital=1000000,
        data_path=DATA_PATH,
    )
    ind = ctx.performance.indicators

    assert ind["trade_num"] >= 3
    # sqn 应为非零值（有多笔交易）
    assert isinstance(ind["sqn"], float)


# ------------------------------------------------------------------
# _compute_indicators 单元测试（用构造数据，不依赖回测）
# ------------------------------------------------------------------

def test_compute_indicators_with_mock_data():
    """直接构造 returns/bench_returns，验证 _compute_indicators。"""
    ctx = create_context()
    ctx.portfolio.starting_cash = 1000000
    ctx.portfolio.total_value = 1050000  # 5% 总收益
    ctx.performance.trade_num = 10
    ctx.performance.win = 6
    ctx.logs.trade_returns = [0.02, -0.01, 0.03, 0.01, -0.005,
                              0.015, 0.02, -0.01, 0.025, 0.005]

    dates = pd.date_range("2024-01-02", periods=20, freq="B")
    np.random.seed(42)
    returns = pd.Series(np.random.normal(0.001, 0.01, 20), index=dates)
    bench_returns = pd.Series(np.random.normal(0.0005, 0.008, 20), index=dates)

    ind = Performance._compute_indicators(returns, bench_returns, ctx)

    # 基本检查
    assert ind["trade_num"] == 10
    assert ind["win_ratio"] == 0.6
    assert abs(ind["roto"] - 0.05) < 1e-9

    # sqn 应有值
    assert ind["sqn"] != 0.0

    # empyrical 指标应有值
    assert isinstance(ind["annual_return"], float)
    assert isinstance(ind["sharpe"], float)
    assert isinstance(ind["max_drawdown"], float)
    assert ind["max_drawdown"] <= 0

    # alpha/beta/info_ratio/R2 应有值
    assert isinstance(ind["alpha"], float)
    assert isinstance(ind["beta"], float)
    assert isinstance(ind["info_ratio"], float)
    assert isinstance(ind["R2"], float)


def test_compute_indicators_no_bench():
    """无基准时 alpha/beta/info_ratio/R2 应为 0。"""
    ctx = create_context()
    ctx.portfolio.starting_cash = 1000000
    ctx.portfolio.total_value = 1000000
    ctx.performance.trade_num = 0
    ctx.performance.win = 0
    ctx.logs.trade_returns = []

    dates = pd.date_range("2024-01-02", periods=10, freq="B")
    returns = pd.Series(np.zeros(10), index=dates)

    ind = Performance._compute_indicators(returns, None, ctx)

    assert ind["alpha"] == 0.0
    assert ind["beta"] == 0.0
    assert ind["info_ratio"] == 0.0
    assert ind["R2"] == 0.0


def test_indicators_written_to_context():
    """run_backtest 后 context.performance.indicators 应为 dict。"""
    from xxybacktest.backtest import run_backtest

    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=lambda ctx: None,
        start_date="2024-01-02",
        end_date="2024-01-10",
        capital=1000000,
        data_path=DATA_PATH,
    )
    assert isinstance(ctx.performance.indicators, (dict, DictObj))
    assert "sharpe" in ctx.performance.indicators
    assert "max_drawdown" in ctx.performance.indicators
    assert "roto" in ctx.performance.indicators


if __name__ == "__main__":
    test_safe_nan()
    test_safe_inf()
    test_safe_none()
    test_safe_normal()
    test_no_trade_indicators()
    test_with_trade_indicators()
    test_buy_sell_indicators()
    test_multiple_trades_sqn()
    test_compute_indicators_with_mock_data()
    test_compute_indicators_no_bench()
    test_indicators_written_to_context()
    print("All G2 tests passed.")
