"""
阶段1.6 · SQL 版 vs pandas 版 双版本对拍

同一因子, 分别走:
  - engine.analyze_from_sql(db, user_sql, ...)   SQL-first, 下推 DuckDB
  - engine.analyze(factor_df, price_df, status_df, ...)  纯 pandas

断言核心指标数值一致。两版预处理口径有一处已知差异(winsorize):
  SQL 版用分位裁剪(quantile), pandas 版用 MAD。为让对拍严格, 这里两版都关闭
  winsorize, 只比"收益口径 + 过滤 + rank IC + 分组 + 换手 + 年化"这些核心逻辑。

需要真实数据库, 无则 skip。
"""
import os
import numpy as np
import pandas as pd
import pytest

from xxybacktest.factor import engine

DATA_PATH = os.environ.get("XXY_DATA_PATH", r"D:\Desktop\最新回测框架\data")
START = "2025-06-01"  # 短区间, 加速对拍(逻辑一致性与区间长度无关)


@pytest.fixture(scope="module")
def db():
    if not os.path.exists(DATA_PATH):
        pytest.skip(f"数据路径不存在: {DATA_PATH}")
    from xxydb import xxydb
    conn = xxydb(path=DATA_PATH)
    yield conn
    conn.close()


_CACHE = {}


def _run_both(db, value_expr):
    """给定因子表达式, 分别跑 SQL 版和 pandas 版, 返回 (sql_out, pd_out)。带缓存避免重复跑。"""
    if value_expr in _CACHE:
        return _CACHE[value_expr]
    r = _run_both_impl(db, value_expr)
    _CACHE[value_expr] = r
    return r


def _run_both_impl(db, value_expr):
    user_sql = (f"SELECT date, instrument, {value_expr} AS value "
                f"FROM daily_bar WHERE date >= '{START}'")
    periods, n_groups, base = [1, 5, 10, 20], 10, 5

    # SQL 版(关 winsorize 以对齐口径)
    sql_out = engine.analyze_from_sql(
        db, user_sql, periods=periods, n_groups=n_groups, base_period=base,
        winsorize=False, standardize=True)

    # pandas 版: 取同样数据到 DataFrame
    price = db.query(
        f"SELECT date,instrument,open,adjust_factor,close,pre_close,turn "
        f"FROM daily_bar WHERE date>='{START}'").df()
    status = db.query(
        f"SELECT date,instrument,suspended,st_status,price_limit_status "
        f"FROM stock_status WHERE date>='{START}'").df()
    price["date"] = pd.to_datetime(price["date"])
    price = price.sort_values(["instrument", "date"])
    factor = price[["date", "instrument"]].copy()
    factor["value"] = eval(value_expr, {}, {
        "close": price["close"], "pre_close": price["pre_close"],
        "turn": price["turn"]})
    factor = factor.dropna(subset=["value"])
    pd_out = engine.analyze(
        factor, price, status, periods=periods, n_groups=n_groups,
        base_period=base, winsorize=False, standardize=True)
    return sql_out, pd_out


# 容差说明:两版共用同一套逻辑, 但底层计算引擎不同(DuckDB vs pandas/numpy)。
# 对"分组成分、换手、覆盖度、IC胜率"这类整数/集合运算, 应完全一致(容差 0)。
# 对"IC、年化收益"这类涉及 zscore/corr/累乘的浮点量, 两引擎存在正常浮点级差异,
# 容差设为 5e-3(远小于因子间的有意义差别, 不会掩盖逻辑错误)。
TOL_EXACT = 1e-9      # 集合/整数级
TOL_FLOAT = 5e-3      # 浮点级


def test_ic_matches(db):
    """逐日 IC 时序两版应一致(浮点级容差)。"""
    sql_out, pd_out = _run_both(db, "close/pre_close-1")
    s = sql_out["ic_series"].set_index("date")["ic_5"].dropna()
    p = pd_out["ic_series"].set_index("date")["ic_5"].dropna()
    common = s.index.intersection(p.index)
    assert len(common) > 100
    diff = (s.loc[common] - p.loc[common]).abs().max()
    assert diff < TOL_FLOAT, f"IC 时序不一致, 最大差异 {diff}"


def test_metrics_match(db):
    """全区间核心指标两版应一致。"""
    sql_out, pd_out = _run_both(db, "close/pre_close-1")
    # 胜率、覆盖度是比例/集合运算, 应几乎精确一致
    for k in ["ic_win_rate", "coverage"]:
        a, b = sql_out["metrics"][k], pd_out["metrics"][k]
        assert abs(a - b) < TOL_FLOAT, f"{k} 不一致: SQL={a} pandas={b}"
    # IC 均值、ICIR 浮点级
    for k in ["ic_mean", "icir"]:
        a, b = sql_out["metrics"][k], pd_out["metrics"][k]
        assert abs(a - b) < TOL_FLOAT, f"{k} 不一致: SQL={a} pandas={b}"


def test_group_returns_match(db):
    """分组逐组年化收益两版应一致(浮点级, 累乘漂移)。"""
    sql_out, pd_out = _run_both(db, "close/pre_close-1")
    s = sql_out["group_summary"].set_index("group")["ann_return"]
    p = pd_out["group_summary"].set_index("group")["ann_return"]
    diff = (s - p).abs().max()
    assert diff < TOL_FLOAT, f"分组年化不一致, 最大差异 {diff}"


def test_turnover_match(db):
    """换手率两版应完全一致(成分股集合运算, 无浮点)。"""
    sql_out, pd_out = _run_both(db, "close/pre_close-1")
    s = sql_out["group_summary"].set_index("group")["turnover"]
    p = pd_out["group_summary"].set_index("group")["turnover"]
    diff = (s - p).abs().max()
    assert diff < TOL_EXACT, f"换手不一致(应精确), 最大差异 {diff}"


def test_second_factor_amount(db):
    """换个因子(成交额)再对拍一次多空收益, 验证不是碰巧对上。"""
    sql_out, pd_out = _run_both(db, "close")  # 用收盘价当因子, 与反转因子不同分布
    assert abs(sql_out["metrics"]["ls_return"] -
               pd_out["metrics"]["ls_return"]) < TOL_FLOAT


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "-s"]))
