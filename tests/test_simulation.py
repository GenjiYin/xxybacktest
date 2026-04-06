"""
模拟交易模块测试
"""
import sys
sys.path.insert(0, 'D:/Desktop/github汇总/xxybacktest')

from xxybacktest.simulation import (
    submit, pause, resume, delete, list_accounts, get_account,
    run_all, run_single, get_account_nav, get_account_positions, get_account_orders,
    close_all
)


def initialize(context):
    """测试策略初始化"""
    context.stock = "000001.SZ"


def strategy(context):
    """测试策略：买入持有"""
    if not context.portfolio.positions:
        context.order_buy(context.stock, 100)


def test_submit():
    """测试提交账户"""
    print("\n=== 测试 submit ===")
    account_id = submit(
        name="测试策略-买入持有",
        initialize=initialize,
        handle_data=strategy,
        capital=100000,
        start_date="2025-01-01",
        data_path="./data",  # 指定数据源路径
        asset_type="stock",
    )
    print(f"创建账户: {account_id}")
    return account_id


def test_list_accounts():
    """测试列出账户"""
    print("\n=== 测试 list_accounts ===")
    accounts = list_accounts()
    print(f"所有账户数: {len(accounts)}")
    for acc in accounts:  # 只显示前3个
        print(f"  - {acc['account_id']}: {acc['name']} ({acc['status']})")
    return accounts


def test_get_account(account_id):
    """测试获取单个账户"""
    print(f"\n=== 测试 get_account ({account_id}) ===")
    account = get_account(account_id)
    if account:
        print(f"  名称: {account['name']}")
        print(f"  状态: {account['status']}")
        print(f"  初始资金: {account['initial_cash']}")
        print(f"  开始日期: {account['start_date']}")
        print(f"  数据源: {account.get('data_path', './data')}")
    else:
        print("  账户不存在")
    return account


def test_run_single(account_id):
    """测试单个账户回测"""
    print(f"\n=== 测试 run_single ({account_id}) ===")
    result = run_single(account_id, end_date="2025-02-01")
    print(f"结果: {result}")
    return result


def test_get_results(account_id):
    """测试获取回测结果"""
    print(f"\n=== 测试获取结果 ({account_id}) ===")

    nav = get_account_nav(account_id)
    print(f"净值记录: {len(nav)} 条")
    if not nav.empty:
        print(nav.head())

    positions = get_account_positions(account_id)
    print(f"\n最新持仓: {len(positions)} 条")
    if not positions.empty:
        print(positions)

    orders = get_account_orders(account_id)
    print(f"\n订单记录: {len(orders)} 条")
    if not orders.empty:
        print(orders)


def test_pause_resume(account_id):
    """测试暂停和恢复"""
    print(f"\n=== 测试 pause/resume ({account_id}) ===")

    pause(account_id)
    account = get_account(account_id)
    print(f"暂停后状态: {account['status']}")

    resume(account_id)
    account = get_account(account_id)
    print(f"恢复后状态: {account['status']}")


def test_delete(account_id):
    """测试删除账户及其所有数据"""
    print(f"\n=== 测试 delete ({account_id}) ===")

    # 删除前先验证数据存在
    print("\n[1] 删除前验证数据存在:")
    account_before = get_account(account_id)
    nav_before = get_account_nav(account_id)
    positions_before = get_account_positions(account_id)
    orders_before = get_account_orders(account_id)

    print(f"  账户存在: {account_before is not None}")
    print(f"  净值记录: {len(nav_before)} 条")
    print(f"  持仓记录: {len(positions_before)} 条")
    print(f"  订单记录: {len(orders_before)} 条")

    # 执行删除
    print("\n[2] 执行删除:")
    result = delete(account_id, './data')
    print(f"  delete() 返回: {result}")

    # 删除后验证数据已清空
    print("\n[3] 删除后验证数据已清空:")
    account_after = get_account(account_id)
    nav_after = get_account_nav(account_id)
    positions_after = get_account_positions(account_id)
    orders_after = get_account_orders(account_id)

    print(f"  账户存在: {account_after is not None} (应为 False)")
    print(f"  净值记录: {len(nav_after)} 条 (应为 0)")
    print(f"  持仓记录: {len(positions_after)} 条 (应为 0)")
    print(f"  订单记录: {len(orders_after)} 条 (应为 0)")

    # 验证通过
    all_cleared = (
        account_after is None and
        len(nav_after) == 0 and
        len(positions_after) == 0 and
        len(orders_after) == 0
    )
    print(f"\n[4] 删除验证: {'✓ 通过' if all_cleared else '✗ 失败'}")

    return result


def test_run_all():
    """测试批量回测"""
    print("\n=== 测试 run_all ===")
    results = run_all(end_date="2025-02-01")
    print(f"处理账户数: {len(results)}")
    for r in results:
        print(f"  - {r['account_id']}: {r['status']}")


if __name__ == "__main__":
    # 运行完整测试流程
    try:
        # 1. 提交账户
        # account_id = test_submit()

        # 2. 列出账户
        test_list_accounts()

        # # 3. 获取账户详情
        # test_get_account(account_id)

        # # 4. 执行回测
        # test_run_single(account_id)

        # # 5. 获取回测结果
        # test_get_results(account_id)

        # # 6. 测试暂停恢复
        # test_pause_resume(account_id)

        # # 7. 测试批量回测
        # test_run_all()

        # 8. 清理：删除测试账户（验证删除功能）
        test_delete("sim_20260405_190740_6f0c45")

        print("\n=== 所有测试完成 ===")

    except Exception as e:
        print(f"\n[错误] {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 关闭所有数据库连接
        close_all()
