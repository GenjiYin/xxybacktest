#!/usr/bin/env python3
"""
测试 delete() 中 close_db 的异常行为。
"""

import traceback
from pathlib import Path

DATA_PATH = r"D:\Desktop\最新回测框架\data"


def test_close_db_directly():
    """直接测试 close_db 在真实路径上的行为。"""
    from xxybacktest.simulation.db_utils import get_db, close_db, _db_cache

    print("=" * 60)
    print("测试1: get_db → close_db 基本流程")
    print("=" * 60)

    # 主数据库
    print(f"\n[1] get_db('{DATA_PATH}')")
    db1 = get_db(DATA_PATH)
    print(f"    返回: {type(db1).__name__}")
    print(f"    _db_cache keys: {list(_db_cache.keys())}")

    # 模拟结果数据库
    sim_path = str(Path(DATA_PATH) / "simulation_results")
    print(f"\n[2] get_db('{sim_path}')")
    db2 = get_db(sim_path)
    print(f"    返回: {type(db2).__name__}")
    print(f"    _db_cache keys: {list(_db_cache.keys())}")

    # close_db 主数据库
    print(f"\n[3] close_db('{DATA_PATH}')")
    try:
        close_db(DATA_PATH)
        print("    成功")
    except Exception as e:
        print(f"    异常: {type(e).__name__}: {e}")
        traceback.print_exc()

    print(f"    _db_cache keys after: {list(_db_cache.keys())}")

    # close_db 模拟结果数据库
    print(f"\n[4] close_db('{sim_path}')")
    try:
        close_db(sim_path)
        print("    成功")
    except Exception as e:
        print(f"    异常: {type(e).__name__}: {e}")
        traceback.print_exc()

    print(f"    _db_cache keys after: {list(_db_cache.keys())}")


def test_delete_account():
    """测试删除一个真实账户。"""
    from xxybacktest.simulation.submitter import list_accounts, delete

    print("\n" + "=" * 60)
    print("测试2: 删除真实账户")
    print("=" * 60)

    accounts = list_accounts(data_path=DATA_PATH)
    if not accounts:
        print("[跳过] 无账户可删")
        return

    # 找一个 paused 或 stopped 的账户来删（避免删运行中的）
    target = None
    for acc in accounts:
        if acc["status"] in ("paused", "stopped"):
            target = acc
            break

    if target is None:
        target = accounts[-1]  # 删最后一个

    account_id = target["account_id"]
    print(f"\n[1] 准备删除账户: {account_id} ({target['name']}) status={target['status']}")

    print(f"\n[2] 调用 delete('{account_id}', '{DATA_PATH}')")
    try:
        result = delete(account_id, DATA_PATH)
        print(f"    返回: {result}")
    except Exception as e:
        print(f"    异常: {type(e).__name__}: {e}")
        traceback.print_exc()


def test_delete_nonexistent():
    """测试删除不存在的账户（模拟残留清理场景）。"""
    from xxybacktest.simulation.submitter import delete

    print("\n" + "=" * 60)
    print("测试3: 删除不存在的账户")
    print("=" * 60)

    fake_id = "sim_99999999_000000_xxxxxx"
    print(f"\n[1] 调用 delete('{fake_id}', '{DATA_PATH}')")
    try:
        result = delete(fake_id, DATA_PATH)
        print(f"    返回: {result}")
    except Exception as e:
        print(f"    异常: {type(e).__name__}: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    test_close_db_directly()
    test_delete_account()
    test_delete_nonexistent()
