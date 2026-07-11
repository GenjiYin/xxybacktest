"""
阶段2 · 存储层 store 测试

验证:
  - save_factor_result 写入独立目录
  - load_* 读回, 数值与写入一致
  - list_factor_metrics 汇总多因子
  - load_detail 打包完整
  - delete_factor_result 删除
用临时目录, 不碰真实数据。engine 用构造数据(不需 db)。
"""
import os
import numpy as np
import pandas as pd
import pytest

from xxybacktest.factor import engine, store
from xxybacktest.factor.result import FactorResult


def _make_result(seed=0):
    """用构造数据跑 engine, 包成 FactorResult。"""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=80)
    stocks = [f"{i:06d}.SZ" for i in range(40)]
    rows = []
    for s in stocks:
        price = 10.0
        for d in dates:
            price *= (1 + rng.normal(0, 0.02))
            rows.append({"date": d, "instrument": s, "open": price,
                         "adjust_factor": 1.0})
    price_df = pd.DataFrame(rows)
    status = price_df[["date", "instrument"]].copy()
    status["suspended"] = 0
    status["st_status"] = 0
    status["price_limit_status"] = 2
    factor = price_df[["date", "instrument"]].copy()
    factor["value"] = rng.normal(size=len(factor))
    out = engine.analyze(factor, price_df, status, periods=[1, 5], n_groups=5,
                         base_period=5)
    return FactorResult(out, name="测试因子")


def test_save_and_load(tmp_path):
    """存一个因子, 读回 metrics 和序列, 数值一致。"""
    dp = str(tmp_path)
    res = _make_result()
    meta = {"name": "测试因子", "category": "测试", "sql": "SELECT ...",
            "direction": None}
    store.save_factor_result("F001", res.to_dict(), meta=meta, data_path=dp)

    # 目录结构
    d = os.path.join(dp, "factor_analysis", "factors", "F001")
    assert os.path.exists(os.path.join(d, "metrics.json"))
    assert os.path.exists(os.path.join(d, "ic_series.parquet"))
    assert os.path.exists(os.path.join(d, "meta.json"))

    # metrics 读回一致
    m = store.load_metrics("F001", dp)
    assert abs(m["ic_mean"] - res.metrics["ic_mean"]) < 1e-12

    # ic_series 行数一致
    ic = store.load_ic_series("F001", dp)
    assert len(ic) == len(res.ic_series)

    # meta 读回 + 带上 updated_at
    meta_back = store.load_meta("F001", dp)
    assert meta_back["name"] == "测试因子"
    assert "updated_at" in meta_back


def test_list_factor_metrics(tmp_path):
    """存两个因子, 列表汇总应有两行, 含 meta + metrics 字段。"""
    dp = str(tmp_path)
    for fid, seed in [("F001", 1), ("F002", 2)]:
        res = _make_result(seed)
        store.save_factor_result(
            fid, res.to_dict(),
            meta={"name": f"因子{fid}", "category": "动量"}, data_path=dp)

    rows = store.list_factor_metrics(dp)
    assert len(rows) == 2
    ids = {r["factor_id"] for r in rows}
    assert ids == {"F001", "F002"}
    r0 = rows[0]
    assert "name" in r0 and "category" in r0  # meta 字段
    assert "ic_mean" in r0 and "icir" in r0   # metrics 字段


def test_load_detail(tmp_path):
    """详情打包结构完整, 日期为字符串/NaN为None。"""
    dp = str(tmp_path)
    res = _make_result()
    store.save_factor_result("F001", res.to_dict(),
                             meta={"name": "x", "category": "y"}, data_path=dp)
    detail = store.load_detail("F001", dp)
    assert set(detail.keys()) >= {"factor_id", "meta", "metrics", "ic_series",
                                  "yearly", "groups", "group_summary", "ls_series"}
    if detail["ic_series"]:
        assert isinstance(detail["ic_series"][0]["date"], str)


def test_overwrite(tmp_path):
    """重跑覆盖: 第二次保存应替换第一次, 不追加。"""
    dp = str(tmp_path)
    res1 = _make_result(1)
    store.save_factor_result("F001", res1.to_dict(), data_path=dp)
    n1 = len(store.load_ic_series("F001", dp))
    res2 = _make_result(2)
    store.save_factor_result("F001", res2.to_dict(), data_path=dp)
    n2 = len(store.load_ic_series("F001", dp))
    # 覆盖而非追加: 行数应仍是单次的量级(不翻倍)
    assert n2 == n1


def test_delete(tmp_path):
    dp = str(tmp_path)
    res = _make_result()
    store.save_factor_result("F001", res.to_dict(), data_path=dp)
    assert store.delete_factor_result("F001", dp) is True
    assert store.load_detail("F001", dp) is None
    assert store.delete_factor_result("F001", dp) is False  # 已删, 再删返回 False


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
