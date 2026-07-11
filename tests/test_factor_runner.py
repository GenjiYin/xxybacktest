"""
阶段4 · 调度 runner 集成测试(端到端)

提交真实因子 → run_single 落盘 → 读回验证 → run_all 并行。
需真实 db, 无则 skip。用完删除, 不污染真实目录。
run_all 的多进程测试放在 __main__ 手动跑(pytest 下 spawn 子进程较重, 仅测 run_single)。
"""
import os
import pytest

DATA_PATH = os.environ.get("XXY_DATA_PATH", r"D:\Desktop\最新回测框架\data")
pytestmark = pytest.mark.skipif(not os.path.exists(DATA_PATH), reason="无真实数据库")


def test_run_single_end_to_end():
    """提交 → run_single → 落盘 → 状态 ok → 读回一致。"""
    from xxybacktest.factor import (submit_factor, run_single, get_factor,
                                    delete_factor, store)
    sql = ("SELECT date, instrument, close/pre_close-1 AS value "
           "FROM daily_bar WHERE date >= '2025-06-01'")
    fid = submit_factor("集成测试因子", sql, "反转", data_path=DATA_PATH,
                        base_period=5)
    try:
        assert get_factor(fid, DATA_PATH)["status"] == "registered"
        r = run_single(fid, DATA_PATH)
        assert r["status"] == "success"

        # 落盘后 meta 状态变 ok
        assert get_factor(fid, DATA_PATH)["status"] == "ok"
        # metrics 读回
        m = store.load_metrics(fid, DATA_PATH)
        assert "ic_mean" in m and m["direction"] in ("long", "short")
        # detail 完整
        detail = store.load_detail(fid, DATA_PATH)
        assert len(detail["ic_series"]) > 0
        assert len(detail["groups"]) > 0
        # 列表汇总含 status(bug 回归: 之前 status 为 None)
        lst = store.list_factor_metrics(DATA_PATH)
        row = next(x for x in lst if x["factor_id"] == fid)
        assert row["status"] == "ok"
        assert "ic_mean" in row and "name" in row
    finally:
        delete_factor(fid, DATA_PATH)


def test_run_single_bad_sql_marks_error():
    """SQL 运行期失败 → 状态置 error, 不抛异常。"""
    from xxybacktest.factor import (submit_factor, run_single, get_factor,
                                    delete_factor)
    # 合法通过提交校验但引擎里会出问题的: 引用不存在的列在 validate 就会被拦,
    # 这里用 validate=False 提交一个引用不存在表的 SQL, 让 run_single 阶段失败
    fid = submit_factor("坏因子", "SELECT date,instrument,value FROM 不存在的表",
                        "测试", data_path=DATA_PATH, validate=False)
    try:
        r = run_single(fid, DATA_PATH)
        assert r["status"] == "error"
        assert get_factor(fid, DATA_PATH)["status"] == "error"
        assert get_factor(fid, DATA_PATH)["last_error"]
    finally:
        delete_factor(fid, DATA_PATH)


if __name__ == "__main__":
    # 手动跑 run_all 并行测试(需 __main__ 保护, Windows spawn)
    from xxybacktest.factor import submit_factor, run_all, delete_factor, store
    import time
    specs = [
        ("昨日涨幅", "close/pre_close-1", "反转"),
        ("20日动量", "close/lag(close,20) OVER (PARTITION BY instrument ORDER BY date)-1", "动量"),
    ]
    ids = []
    for name, expr, cat in specs:
        sql = f"SELECT date,instrument,{expr} AS value FROM daily_bar WHERE date>='2024-06-01'"
        ids.append(submit_factor(name, sql, cat, data_path=DATA_PATH, base_period=5))
    t = time.time()
    results = run_all(DATA_PATH)
    print(f"run_all {len(ids)} 因子并行耗时 {time.time()-t:.1f}s")
    assert all(r["status"] == "success" for r in results)
    for r in store.list_factor_metrics(DATA_PATH):
        assert r["status"] == "ok"
    for fid in ids:
        delete_factor(fid, DATA_PATH)
    print("run_all 并行测试通过, 已清理")
