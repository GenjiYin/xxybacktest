"""A1 测试用例：DictObj + create_context"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.context import DictObj, create_context


def test_dictobj_dual_access():
    """双模访问：属性式和字典式等价"""
    d = DictObj({"a": 1, "b": {"c": 2}})
    assert d.a == 1
    assert d["a"] == 1
    assert d.b.c == 2
    assert d["b"]["c"] == 2
    print("[PASS] 双模访问")


def test_dictobj_nested_auto_convert():
    """赋值 dict 时自动递归转为 DictObj"""
    d = DictObj()
    d.x = {"y": {"z": 42}}
    assert d.x.y.z == 42
    print("[PASS] 嵌套 dict 自动转 DictObj")


def test_dictobj_contains():
    """in 操作符"""
    d = DictObj({"a": 1})
    assert "a" in d
    assert "b" not in d
    print("[PASS] __contains__")


def test_dictobj_iter_len():
    """遍历和长度"""
    d = DictObj({"a": 1, "b": 2, "c": 3})
    assert len(d) == 3
    assert set(d) == {"a", "b", "c"}
    print("[PASS] __iter__ / __len__")


def test_dictobj_delete():
    """删除键"""
    d = DictObj({"a": 1, "b": 2})
    del d["a"]
    assert "a" not in d
    assert len(d) == 1
    print("[PASS] __delitem__")


def test_dictobj_to_json():
    """序列化为 JSON"""
    d = DictObj({"a": 1, "b": {"c": 2}})
    j = d.to_json()
    assert isinstance(j, str)
    assert '"a": 1' in j
    print("[PASS] to_json")


def test_create_context_isolation():
    """工厂函数返回独立实例（M1 Bug 修复验证）"""
    ctx1 = create_context()
    ctx2 = create_context()
    ctx1.portfolio.cash = 999
    assert ctx2.portfolio.cash == 0
    print("[PASS] 工厂函数实例隔离")


def test_create_context_fields():
    """context 字段完整性"""
    ctx = create_context()
    assert hasattr(ctx, "id")
    assert hasattr(ctx, "trade")
    assert hasattr(ctx, "account")
    assert hasattr(ctx, "portfolio")
    assert hasattr(ctx, "data")
    assert hasattr(ctx, "logs")
    assert hasattr(ctx, "performance")
    assert hasattr(ctx, "g")
    print("[PASS] 字段完整性")


def test_create_context_defaults():
    """context 默认值"""
    ctx = create_context()
    assert ctx.portfolio.cash == 0
    assert ctx.portfolio.starting_cash == 0
    assert ctx.account.close_tax == 0.001
    assert ctx.account.min_commission == 5
    assert ctx.trade.benchmark == "000001"
    assert ctx.data.calendar == []
    assert ctx.logs.trade_list == []
    assert ctx.performance.trade_num == 0
    print("[PASS] 默认值")


if __name__ == "__main__":
    test_dictobj_dual_access()
    test_dictobj_nested_auto_convert()
    test_dictobj_contains()
    test_dictobj_iter_len()
    test_dictobj_delete()
    test_dictobj_to_json()
    test_create_context_isolation()
    test_create_context_fields()
    test_create_context_defaults()
    print("\nAll A1 tests passed.")
