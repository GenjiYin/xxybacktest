"""
阶段1 · 因子分析引擎单元测试

用构造数据验证 engine 的核心逻辑, 脱离数据库:
  1. 未来收益口径正确(次日开盘 + 后复权)
  2. 完美因子(= 未来收益本身) -> IC ≈ 1, 分组单调
  3. 可交易过滤生效
  4. 随机因子 -> IC ≈ 0
"""
import numpy as np
import pandas as pd
import pytest

from xxybacktest.factor import engine


# ---------- 构造数据 ----------
def _make_market(n_days=60, n_stocks=50, seed=42):
    """造一份行情 + 状态: n_days 个交易日, n_stocks 只股票, 无停牌无ST无涨跌停。"""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=n_days)
    stocks = [f"{i:06d}.SZ" for i in range(n_stocks)]

    rows = []
    for s in stocks:
        price = 10.0
        for d in dates:
            ret = rng.normal(0, 0.02)
            price *= (1 + ret)
            rows.append({"date": d, "instrument": s, "open": price,
                         "adjust_factor": 1.0})
    price_df = pd.DataFrame(rows)

    status = price_df[["date", "instrument"]].copy()
    status["suspended"] = 0
    status["st_status"] = 0
    status["price_limit_status"] = 2
    return price_df, status, dates, stocks


def test_forward_return_formula():
    """未来1日收益 = open(T+2)/open(T+1) - 1, 手工核对一只股票。"""
    price_df, _, _, _ = _make_market(n_days=10, n_stocks=1)
    fwd = engine.compute_forward_returns(price_df, [1])
    opens = price_df.sort_values("date")["open"].values
    # T=0 行的 fwd_ret_1 应 = open[2]/open[1] - 1
    expected = opens[2] / opens[1] - 1
    got = fwd.sort_values("date")["fwd_ret_1"].iloc[0]
    assert abs(got - expected) < 1e-9


def test_perfect_factor_ic_near_one():
    """
    完美因子: 因子值 = 未来1日收益本身。
    则 rank IC 应 ≈ 1, 且分组收益严格单调递增。
    """
    price_df, status, dates, stocks = _make_market(n_days=80, n_stocks=60)
    fwd = engine.compute_forward_returns(price_df, [1])
    # 因子值直接抄未来收益(制造完美预测)
    factor_df = fwd.rename(columns={"fwd_ret_1": "value"})[
        ["date", "instrument", "value"]].dropna()

    out = engine.analyze(factor_df, price_df, status, periods=[1], n_groups=5)
    ic_mean = out["metrics"]["ic_mean"]
    assert ic_mean > 0.95, f"完美因子 IC 应接近1, 实际 {ic_mean:.4f}"

    # 分组年化收益单调递增(Q1 < ... < Q5)
    summ = out["group_summary"].sort_values("group")
    ann = summ["ann_return"].values
    assert all(ann[i] <= ann[i + 1] for i in range(len(ann) - 1)), \
        f"完美因子分组应单调, 实际 {ann}"
    # 多空年化应为正且可观
    assert out["metrics"]["ls_return"] > 0


def test_random_factor_ic_near_zero():
    """纯随机因子 -> IC 均值应接近 0。"""
    price_df, status, dates, stocks = _make_market(n_days=80, n_stocks=60)
    rng = np.random.default_rng(7)
    factor_df = price_df[["date", "instrument"]].copy()
    factor_df["value"] = rng.normal(size=len(factor_df))

    out = engine.analyze(factor_df, price_df, status, periods=[1], n_groups=5)
    assert abs(out["metrics"]["ic_mean"]) < 0.1, \
        f"随机因子 IC 应近0, 实际 {out['metrics']['ic_mean']:.4f}"


def test_tradable_filter():
    """把某天某股设为停牌, 该样本应从 panel 中被剔除。"""
    price_df, status, dates, stocks = _make_market(n_days=30, n_stocks=20)
    # 让第10天所有股票停牌
    bad_day = dates[10]
    status.loc[status["date"] == bad_day, "suspended"] = 1

    factor_df = price_df[["date", "instrument"]].copy()
    factor_df["value"] = np.arange(len(factor_df), dtype=float)

    out = engine.analyze(factor_df, price_df, status, periods=[1], n_groups=5)
    # 停牌那天不应出现在 IC 时序里
    assert bad_day not in set(out["ic_series"]["date"]), \
        "停牌日应被过滤, 不该出现在 IC 时序"


def test_adjust_factor_removes_jump():
    """
    造一次除权: 某股在中途 open 腰斩但 adjust_factor 同步翻倍,
    后复权收益应平滑, 不出现 -50% 的假跌。
    """
    dates = pd.bdate_range("2024-01-01", periods=10)
    rows = []
    for i, d in enumerate(dates):
        if i < 5:
            open_, adj = 10.0, 2.0     # 复权后 = 20
        else:
            open_, adj = 5.0, 4.0      # 名义腰斩, 但复权后仍 = 20
        rows.append({"date": d, "instrument": "000001.SZ",
                     "open": open_, "adjust_factor": adj})
    price_df = pd.DataFrame(rows)
    fwd = engine.compute_forward_returns(price_df, [1])
    # 跨越除权点的那笔收益应接近 0, 而非 -50%
    r = fwd.sort_values("date")["fwd_ret_1"].dropna()
    assert (r.abs() < 0.01).all(), f"后复权应消除除权跳变, 实际 {r.values}"


def test_turnover_and_coverage_present():
    """metrics 应包含 turnover 和 coverage, 且取值在合理范围。"""
    price_df, status, dates, stocks = _make_market(n_days=100, n_stocks=60)
    rng = np.random.default_rng(3)
    factor_df = price_df[["date", "instrument"]].copy()
    factor_df["value"] = rng.normal(size=len(factor_df))

    out = engine.analyze(factor_df, price_df, status, periods=[5], n_groups=5)
    m = out["metrics"]
    assert "turnover" in m and "coverage" in m
    # 随机因子换手应偏高(0~1 之间)
    assert 0 <= m["turnover"] <= 1, f"换手应在[0,1], 实际 {m['turnover']}"
    # 全股票都有因子值, 覆盖度应接近 1
    assert m["coverage"] > 0.95, f"全覆盖时应≈1, 实际 {m['coverage']}"


def test_coverage_partial():
    """只给一半股票因子值, 覆盖度应接近 0.5。"""
    price_df, status, dates, stocks = _make_market(n_days=60, n_stocks=40)
    half = set(stocks[:20])
    factor_df = price_df[price_df["instrument"].isin(half)][
        ["date", "instrument"]].copy()
    factor_df["value"] = np.arange(len(factor_df), dtype=float)

    out = engine.analyze(factor_df, price_df, status, periods=[5], n_groups=5)
    assert abs(out["metrics"]["coverage"] - 0.5) < 0.05, \
        f"半覆盖应≈0.5, 实际 {out['metrics']['coverage']}"


def test_no_overlap_sampling():
    """
    验证分组回测按 base_period 不重叠采样: 100 个交易日、base_period=5,
    调仓期数应约为 100/5 ≈ 20 期(而非逐日 100 期), 证明样本不重叠。
    """
    price_df, status, dates, stocks = _make_market(n_days=100, n_stocks=50)
    rng = np.random.default_rng(1)
    factor_df = price_df[["date", "instrument"]].copy()
    factor_df["value"] = rng.normal(size=len(factor_df))

    out = engine.analyze(factor_df, price_df, status, periods=[5], n_groups=5)
    n_rebalance = out["ls_series"]["date"].nunique()
    # 末尾若干期因未来收益 NaN 会少几期, 允许区间 [15, 21]
    assert 15 <= n_rebalance <= 21, \
        f"不重叠采样应约 20 期, 实际 {n_rebalance}(逐日会是~100)"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
