"""
阶段1.5 · 即时接口 analyze_factor + FactorResult 测试

验证:
  - analyze_factor 端到端跑通(需真实 db, 无则 skip)
  - SQL 三列校验(缺列报错)
  - FactorResult.to_dict 结构完整、JSON 友好
  - summary / plot 不报错
"""
import os
import matplotlib
matplotlib.use("Agg")  # 无头环境

import pytest

from xxybacktest.factor import analyze_factor, FactorResult

DATA_PATH = os.environ.get("XXY_DATA_PATH", r"D:\Desktop\最新回测框架\data")
START = "2025-06-01"


@pytest.fixture(scope="module")
def db():
    if not os.path.exists(DATA_PATH):
        pytest.skip(f"数据路径不存在: {DATA_PATH}")
    from xxydb import xxydb
    conn = xxydb(path=DATA_PATH)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def res(db):
    sql = (f"SELECT date, instrument, close/pre_close-1 AS value "
           f"FROM daily_bar WHERE date >= '{START}'")
    return analyze_factor(sql, name="昨日涨幅", base_period=5, db=db)


def test_analyze_factor_runs(res):
    """端到端返回 FactorResult, 核心指标存在。"""
    assert isinstance(res, FactorResult)
    m = res.metrics
    for k in ["ic_mean", "icir", "ls_return", "turnover", "coverage", "direction"]:
        assert k in m


def test_summary_no_error(res):
    """summary 打印不报错, 返回 metrics。"""
    m = res.summary(verbose=True)
    assert "ic_mean" in m


def test_to_dict_structure(res):
    """to_dict 结构完整, 日期转字符串, 无 NaN(转成 None)。"""
    d = res.to_dict()
    assert set(d.keys()) >= {"name", "metrics", "ic_series", "groups",
                             "group_summary", "ls_series", "yearly", "params"}
    # ic_series 里 date 应是字符串
    if d["ic_series"]:
        assert isinstance(d["ic_series"][0]["date"], str)
    # metrics 里不应有 float nan(应为 None)
    import math
    for v in d["metrics"].values():
        assert not (isinstance(v, float) and math.isnan(v))


def test_plots_no_error(res):
    """三张图 + 组合图都能画(Agg backend)不报错。"""
    assert res.plot_ic() is not None
    assert res.plot_groups() is not None
    assert res.plot_ls() is not None
    assert res.plot() is not None


def test_missing_columns_raises(db):
    """SQL 不返回 value 列应报错。"""
    bad_sql = f"SELECT date, instrument FROM daily_bar WHERE date >= '{START}'"
    with pytest.raises(ValueError, match="value"):
        analyze_factor(bad_sql, db=db)


def test_sql_window_factor(db):
    """用户可在 SQL 里用窗口函数写复杂因子(5日换手率均值)。"""
    sql = (f"SELECT date, instrument, "
           f"avg(turn) OVER (PARTITION BY instrument ORDER BY date "
           f"ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS value "
           f"FROM daily_bar WHERE date >= '{START}'")
    r = analyze_factor(sql, name="5日换手率", base_period=5, db=db)
    # 换手率因子应为显著负 IC
    assert r.metrics["ic_mean"] < 0


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
