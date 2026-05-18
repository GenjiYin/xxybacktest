"""
live/utils.py 测试

不依赖 QMT，可在任意环境运行。
运行：python tests/test_live_utils.py

数据路径：D:\Desktop\最新回测框架\data
schedule 测试写入真实路径（账户 ID 以 _test_ 开头），测试结束后自动清理。
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.live.utils import (
    _load_schedule,
    _load_strategy_state,
    _save_strategy_state,
    _schedule_path,
    _serialize_state,
    _update_schedule,
    is_trading_day,
)

DATA_PATH = r"D:\Desktop\最新回测框架\data"

# 测试用账户 ID，测试结束后从 live_schedule.json 中清理
_TEST_ACCOUNT = "_test_live_utils"


def _cleanup_test_account():
    """从 live_schedule.json 中删除测试账户条目。"""
    path = _schedule_path(DATA_PATH)
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for key in list(data.keys()):
        if key.startswith("_test_"):
            del data[key]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[cleanup] 已清理测试账户条目，live_schedule.json 路径: {path}")


# ---------------------------------------------------------------------------
# 测试：is_trading_day
# ---------------------------------------------------------------------------

def test_trading_day_returns_true():
    """已知交易日应返回 True。"""
    result = is_trading_day("2026-05-18", DATA_PATH)
    assert result is True, "2026-05-18（周一）应为交易日"
    print("[PASS] is_trading_day('2026-05-18') == True")


def test_weekend_returns_false():
    """周末应返回 False。"""
    result = is_trading_day("2026-05-16", DATA_PATH)
    assert result is False, "2026-05-16（周六）应为非交易日"
    print("[PASS] is_trading_day('2026-05-16') == False")


def test_holiday_returns_false():
    """节假日应返回 False（2026-01-01 元旦）。"""
    result = is_trading_day("2026-01-01", DATA_PATH)
    assert result is False, "2026-01-01（元旦）应为非交易日"
    print("[PASS] is_trading_day('2026-01-01') == False")


# ---------------------------------------------------------------------------
# 测试：_load_schedule / _update_schedule（写入真实路径）
# ---------------------------------------------------------------------------

def test_load_schedule_missing_account():
    """不存在的账户返回空 dict（文件可能已存在，但该账户条目不存在）。"""
    result = _load_schedule("_test_nonexistent_xyz", DATA_PATH)
    assert result == {}, f"期望空 dict，实际: {result}"
    print("[PASS] 不存在的账户 _load_schedule 返回 {}")


def test_update_and_load_schedule():
    """写入后读取内容一致，并可在真实文件中看到。"""
    _update_schedule(_TEST_ACCOUNT, {"last_run_date": "2026-05-18", "count": 3}, DATA_PATH)
    record = _load_schedule(_TEST_ACCOUNT, DATA_PATH)
    assert record["last_run_date"] == "2026-05-18"
    assert record["count"] == 3
    path = _schedule_path(DATA_PATH)
    print(f"[PASS] _update_schedule 写入成功，可查看: {path}")


def test_update_schedule_merges():
    """多次 update 应合并，不覆盖其他键。"""
    _update_schedule(_TEST_ACCOUNT, {"key_a": 1}, DATA_PATH)
    _update_schedule(_TEST_ACCOUNT, {"key_b": 2}, DATA_PATH)
    record = _load_schedule(_TEST_ACCOUNT, DATA_PATH)
    assert record["key_a"] == 1
    assert record["key_b"] == 2
    print("[PASS] _update_schedule 多次调用正确合并")


def test_update_schedule_multiple_accounts():
    """不同账户互不干扰。"""
    _update_schedule("_test_acc_a", {"x": 1}, DATA_PATH)
    _update_schedule("_test_acc_b", {"x": 99}, DATA_PATH)
    assert _load_schedule("_test_acc_a", DATA_PATH)["x"] == 1
    assert _load_schedule("_test_acc_b", DATA_PATH)["x"] == 99
    print("[PASS] 不同账户数据互不干扰")


# ---------------------------------------------------------------------------
# 测试：_save_strategy_state / _load_strategy_state（写入真实路径）
# ---------------------------------------------------------------------------

def test_strategy_state_roundtrip():
    """写入后读取内容一致（基础类型）。"""
    state = {"counter": 5, "last_weights": {"000001.SZ": 0.2, "600519.SH": 0.3}}
    _save_strategy_state(_TEST_ACCOUNT, state, DATA_PATH)
    loaded = _load_strategy_state(_TEST_ACCOUNT, DATA_PATH)
    assert loaded["counter"] == 5
    assert loaded["last_weights"]["000001.SZ"] == 0.2
    print("[PASS] strategy_state 写入后读取内容一致")


def test_strategy_state_empty():
    """不存在的账户返回空 dict。"""
    loaded = _load_strategy_state("_test_nonexistent_xyz", DATA_PATH)
    assert loaded == {}
    print("[PASS] 不存在账户 _load_strategy_state 返回 {}")


def test_strategy_state_overwrite():
    """二次写入覆盖旧状态。"""
    _save_strategy_state(_TEST_ACCOUNT, {"v": 1}, DATA_PATH)
    _save_strategy_state(_TEST_ACCOUNT, {"v": 2, "new_key": "hello"}, DATA_PATH)
    loaded = _load_strategy_state(_TEST_ACCOUNT, DATA_PATH)
    assert loaded["v"] == 2
    assert loaded["new_key"] == "hello"
    print("[PASS] 二次写入正确覆盖旧状态")


# ---------------------------------------------------------------------------
# 测试：numpy 类型序列化（仍用临时目录，纯逻辑测试）
# ---------------------------------------------------------------------------

def test_numpy_serialization():
    """numpy 类型序列化不报错，且值正确。"""
    try:
        import numpy as np
    except ImportError:
        print("[SKIP] numpy 未安装，跳过")
        return

    state = {
        "arr":      np.array([1.0, 2.0, 3.0]),
        "int_val":  np.int64(42),
        "flt_val":  np.float32(3.14),
        "bool_val": np.bool_(True),
    }
    with tempfile.TemporaryDirectory() as tmp:
        _save_strategy_state("live_001", state, tmp)
        loaded = _load_strategy_state("live_001", tmp)

    assert loaded["arr"] == [1.0, 2.0, 3.0]
    assert loaded["int_val"] == 42
    assert abs(loaded["flt_val"] - 3.14) < 0.01
    assert loaded["bool_val"] is True
    print("[PASS] numpy 类型序列化正确")


def test_pandas_serialization():
    """pandas Series 序列化不报错。"""
    try:
        import pandas as pd
    except ImportError:
        print("[SKIP] pandas 未安装，跳过")
        return

    state = {
        "series": pd.Series({"000001.SZ": 0.5, "600519.SH": 0.5}),
    }
    with tempfile.TemporaryDirectory() as tmp:
        _save_strategy_state("live_001", state, tmp)
        loaded = _load_strategy_state("live_001", tmp)

    assert loaded["series"]["000001.SZ"] == 0.5
    print("[PASS] pandas Series 序列化正确")


def test_serialize_nested():
    """嵌套结构（dict 内含 list 含 numpy）序列化正确。"""
    try:
        import numpy as np
    except ImportError:
        print("[SKIP] numpy 未安装，跳过")
        return

    state = {
        "history": [np.int64(1), np.int64(2), np.int64(3)],
        "meta": {"score": np.float64(0.95)},
    }
    serialized = _serialize_state(state)
    # 确保可以 JSON 序列化（不抛异常）
    json.dumps(serialized)
    assert serialized["history"] == [1, 2, 3]
    assert abs(serialized["meta"]["score"] - 0.95) < 1e-9
    print("[PASS] 嵌套 numpy 结构序列化正确")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("--- is_trading_day ---")
    test_trading_day_returns_true()
    test_weekend_returns_false()
    test_holiday_returns_false()

    print("\n--- _load_schedule / _update_schedule ---")
    test_load_schedule_missing_account()
    test_update_and_load_schedule()
    test_update_schedule_merges()
    test_update_schedule_multiple_accounts()

    print("\n--- strategy_state 持久化 ---")
    test_strategy_state_roundtrip()
    test_strategy_state_empty()
    test_strategy_state_overwrite()

    print("\n--- numpy/pandas 序列化 ---")
    test_numpy_serialization()
    test_pandas_serialization()
    test_serialize_nested()

    print("\n--- 清理测试数据 ---")
    _cleanup_test_account()

    print("\n========== All live/utils tests passed ==========")
