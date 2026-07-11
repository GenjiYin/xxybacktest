"""
阶段3 · 提交与元数据管理 submitter 测试

验证 submit/list/get/update/delete 全流程 + SQL 校验。
主流程用临时目录 + validate=False(不碰 db); SQL 校验单独用真实 db 测(无则 skip)。
"""
import os
import pytest

from xxybacktest.factor import (submit_factor, list_factors, get_factor,
                                update_factor, delete_factor)

DATA_PATH = os.environ.get("XXY_DATA_PATH", r"D:\Desktop\最新回测框架\data")


def test_submit_and_get(tmp_path):
    dp = str(tmp_path)
    fid = submit_factor("EP因子", "SELECT date,instrument,ep AS value FROM t",
                        "价值", data_path=dp, validate=False)
    assert fid.startswith("fac_")
    meta = get_factor(fid, dp)
    assert meta["name"] == "EP因子"
    assert meta["category"] == "价值"
    assert meta["status"] == "registered"
    assert meta["base_period"] == 1  # periods[0]
    assert "created_at" in meta


def test_list_and_filter(tmp_path):
    dp = str(tmp_path)
    f1 = submit_factor("因子1", "SELECT 1 AS value", "动量", data_path=dp, validate=False)
    f2 = submit_factor("因子2", "SELECT 1 AS value", "价值", data_path=dp, validate=False)
    all_f = list_factors(dp)
    assert len(all_f) == 2
    # 按 status 过滤
    reg = list_factors(dp, status="registered")
    assert len(reg) == 2
    ok = list_factors(dp, status="ok")
    assert len(ok) == 0


def test_update(tmp_path):
    dp = str(tmp_path)
    fid = submit_factor("旧名", "SELECT 1 AS value", "动量", data_path=dp, validate=False)
    meta = update_factor(fid, dp, name="新名", category="质量", status="ok")
    assert meta["name"] == "新名"
    assert meta["category"] == "质量"
    assert meta["status"] == "ok"
    # 持久化了
    assert get_factor(fid, dp)["name"] == "新名"


def test_update_nonexistent(tmp_path):
    assert update_factor("fac_不存在", str(tmp_path), name="x") is None


def test_delete(tmp_path):
    dp = str(tmp_path)
    fid = submit_factor("待删", "SELECT 1 AS value", "动量", data_path=dp, validate=False)
    assert delete_factor(fid, dp) is True
    assert get_factor(fid, dp) is None


def test_base_period_default(tmp_path):
    dp = str(tmp_path)
    fid = submit_factor("x", "SELECT 1 AS value", "动量", data_path=dp,
                        periods=[5, 10, 20], validate=False)
    assert get_factor(fid, dp)["base_period"] == 5


# ---- 需真实 db 的 SQL 校验 ----
def _has_db():
    return os.path.exists(DATA_PATH)


@pytest.mark.skipif(not _has_db(), reason="无真实数据库")
def test_validate_missing_value_column(tmp_path):
    """SQL 不返回 value 列, 提交应报错。"""
    # 注意: validate=True 会用 data_path 当 db, 这里用真实 DATA_PATH 校验,
    # 但存储也写到 DATA_PATH 会污染——所以只验证"报错发生在写目录之前"。
    with pytest.raises(ValueError, match="value"):
        submit_factor("bad", "SELECT date, instrument FROM daily_bar LIMIT 10",
                      "测试", data_path=DATA_PATH, validate=True)


@pytest.mark.skipif(not _has_db(), reason="无真实数据库")
def test_validate_ok(tmp_path):
    """合法 SQL 通过校验并登记, 用完删除避免污染真实目录。"""
    fid = submit_factor(
        "临时校验因子",
        "SELECT date, instrument, close/pre_close-1 AS value FROM daily_bar "
        "WHERE date >= '2025-06-01'",
        "测试", data_path=DATA_PATH, validate=True)
    try:
        assert fid.startswith("fac_")
        assert get_factor(fid, DATA_PATH)["status"] == "registered"
    finally:
        delete_factor(fid, DATA_PATH)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
