"""
测试步骤一：_save_results 独立文件存储改造
使用临时目录，不污染用户原有 data 数据
"""
import os
import sys
import tempfile
import shutil
import unittest
from datetime import datetime

import pandas as pd
import numpy as np

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from xxybacktest.simulation.runner import _save_results


class MockPortfolio:
    """模拟 Portfolio 对象"""
    def __init__(self):
        self.total_value = 100000.0


class MockPerformance:
    """模拟 Performance 对象"""
    def __init__(self, has_data=True):
        if has_data:
            # 模拟30天的收益率数据
            dates = pd.date_range('2024-01-01', periods=30, freq='D')
            returns = np.random.normal(0.001, 0.02, 30)  # 随机日收益
            self.returns = pd.Series(returns, index=dates)

            # 模拟持仓快照
            self.position_snapshots = [
                {
                    'date': '2024-01-30',
                    'instrument': '000001.SZ',
                    'name': '平安银行',
                    'volume': 1000,
                    'ratio': 0.5,
                    'cum_profit': 5000.0,
                    'cum_return': 0.1,
                    'close_price': 10.5,
                    'avg_cost': 9.5,
                },
                {
                    'date': '2024-01-30',
                    'instrument': '000002.SZ',
                    'name': '万科A',
                    'volume': 500,
                    'ratio': 0.3,
                    'cum_profit': 2000.0,
                    'cum_return': 0.05,
                    'close_price': 20.0,
                    'avg_cost': 19.0,
                }
            ]
        else:
            self.returns = pd.Series(dtype=float)
            self.position_snapshots = []


class MockContext:
    """模拟回测 Context 对象"""
    def __init__(self, has_data=True):
        self.performance = MockPerformance(has_data)
        self.portfolio = MockPortfolio()

        # 模拟订单数据
        if has_data:
            self.order = pd.DataFrame([
                {'date': '2024-01-15', 'instrument': '000001.SZ', 'name': '平安银行',
                 'volume': 1000, 'side': 'buy', 'status': 'filled', 'cost': 9500.0},
                {'date': '2024-01-20', 'instrument': '000002.SZ', 'name': '万科A',
                 'volume': 500, 'side': 'buy', 'status': 'filled', 'cost': 9500.0},
            ])
        else:
            self.order = pd.DataFrame(columns=[
                'date', 'instrument', 'name', 'volume', 'side', 'status', 'cost'
            ])


class TestSaveResults(unittest.TestCase):
    """测试 _save_results 函数"""

    def setUp(self):
        """每个测试前创建临时目录"""
        self.test_dir = tempfile.mkdtemp(prefix="test_step1_")
        self.account_id = "test_sim_001"
        print(f"\n[测试目录] {self.test_dir}")

    def tearDown(self):
        """每个测试后删除临时目录"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
            print(f"[清理完成] 删除 {self.test_dir}")

    def test_save_results_creates_files(self):
        """测试：_save_results 是否正确创建独立文件"""
        print("\n=== 测试1：验证文件创建 ===")

        context = MockContext(has_data=True)
        _save_results(self.account_id, context, self.test_dir)

        # 验证目录结构
        account_dir = os.path.join(self.test_dir, "simulation_results", "accounts", self.account_id)
        self.assertTrue(os.path.exists(account_dir), f"账户目录不存在: {account_dir}")

        # 验证三个文件都存在
        daily_values_path = os.path.join(account_dir, "daily_values.parquet")
        positions_path = os.path.join(account_dir, "positions.parquet")
        orders_path = os.path.join(account_dir, "orders.parquet")

        self.assertTrue(os.path.exists(daily_values_path), "daily_values.parquet 不存在")
        self.assertTrue(os.path.exists(positions_path), "positions.parquet 不存在")
        self.assertTrue(os.path.exists(orders_path), "orders.parquet 不存在")

        print(f"  [OK] 目录创建成功: {account_dir}")
        print(f"  [OK] 文件: daily_values.parquet ({os.path.getsize(daily_values_path)} bytes)")
        print(f"  [OK] 文件: positions.parquet ({os.path.getsize(positions_path)} bytes)")
        print(f"  [OK] 文件: orders.parquet ({os.path.getsize(orders_path)} bytes)")

    def test_save_results_data_integrity(self):
        """测试：验证写入的数据内容是否正确"""
        print("\n=== 测试2：验证数据完整性 ===")

        context = MockContext(has_data=True)
        _save_results(self.account_id, context, self.test_dir)

        # 读取并验证净值数据
        daily_values_path = os.path.join(
            self.test_dir, "simulation_results", "accounts",
            self.account_id, "daily_values.parquet"
        )
        df_nav = pd.read_parquet(daily_values_path)

        self.assertEqual(len(df_nav), 30, "净值记录数量应为30")
        self.assertIn('account_id', df_nav.columns)
        self.assertIn('date', df_nav.columns)
        self.assertIn('nav', df_nav.columns)
        self.assertIn('daily_return', df_nav.columns)
        self.assertTrue(all(df_nav['account_id'] == self.account_id), "account_id 应一致")

        # 验证持仓数据
        positions_path = os.path.join(
            self.test_dir, "simulation_results", "accounts",
            self.account_id, "positions.parquet"
        )
        df_pos = pd.read_parquet(positions_path)

        self.assertEqual(len(df_pos), 2, "持仓记录应为2条")
        self.assertIn('instrument', df_pos.columns)
        self.assertIn('close_price', df_pos.columns)  # 验证重命名

        # 验证订单数据
        orders_path = os.path.join(
            self.test_dir, "simulation_results", "accounts",
            self.account_id, "orders.parquet"
        )
        df_orders = pd.read_parquet(orders_path)

        self.assertEqual(len(df_orders), 2, "订单记录应为2条")

        print(f"  [OK] 净值记录: {len(df_nav)} 条")
        print(f"  [OK] 持仓记录: {len(df_pos)} 条")
        print(f"  [OK] 订单记录: {len(df_orders)} 条")
        print(f"  [OK] 数据字段完整")

    def test_multiple_accounts_isolation(self):
        """测试：多账户数据隔离"""
        print("\n=== 测试3：验证多账户隔离 ===")

        account_ids = ["test_sim_001", "test_sim_002", "test_sim_003"]

        for acc_id in account_ids:
            context = MockContext(has_data=True)
            _save_results(acc_id, context, self.test_dir)

        # 验证每个账户都有独立的目录和文件
        accounts_dir = os.path.join(self.test_dir, "simulation_results", "accounts")

        for acc_id in account_ids:
            account_dir = os.path.join(accounts_dir, acc_id)
            self.assertTrue(os.path.exists(account_dir), f"{acc_id} 目录不存在")

            # 验证文件内容只属于该账户
            df_nav = pd.read_parquet(os.path.join(account_dir, "daily_values.parquet"))
            self.assertTrue(all(df_nav['account_id'] == acc_id), f"{acc_id} 数据被污染")

        print(f"  [OK] {len(account_ids)} 个账户目录创建成功")
        print(f"  [OK] 各账户数据完全隔离")

    def test_empty_data_handling(self):
        """测试：空数据处理"""
        print("\n=== 测试4：验证空数据处理 ===")

        context = MockContext(has_data=False)
        _save_results(self.account_id, context, self.test_dir)

        account_dir = os.path.join(
            self.test_dir, "simulation_results", "accounts", self.account_id
        )

        # 空数据时，净值文件不应创建（因为没有记录）
        daily_values_path = os.path.join(account_dir, "daily_values.parquet")
        self.assertFalse(os.path.exists(daily_values_path), "空净值不应创建文件")

        # 持仓和订单也不应创建
        self.assertFalse(os.path.exists(os.path.join(account_dir, "positions.parquet")))
        self.assertFalse(os.path.exists(os.path.join(account_dir, "orders.parquet")))

        print(f"  [OK] 空数据时未创建文件（符合预期）")


class TestNoDataPollution(unittest.TestCase):
    """验证测试不会污染用户原始 data 目录"""

    def test_uses_temp_directory(self):
        """测试：确认使用的是临时目录而非用户 data 目录"""
        print("\n=== 测试5：验证使用临时目录 ===")

        # 获取原始 data 目录的修改时间
        user_data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')

        if os.path.exists(user_data_dir):
            original_mtime = os.path.getmtime(user_data_dir)

            # 运行测试
            test_dir = tempfile.mkdtemp()
            try:
                context = MockContext(has_data=True)
                _save_results("test_account", context, test_dir)

                # 验证用户 data 目录未被修改
                current_mtime = os.path.getmtime(user_data_dir)
                self.assertEqual(original_mtime, current_mtime,
                    "测试修改了用户的 data 目录！这是不允许的！")

                print(f"  [OK] 用户 data 目录未被修改")
                print(f"  [OK] 测试数据写入临时目录: {test_dir}")

            finally:
                shutil.rmtree(test_dir)
        else:
            print(f"  [跳过] 用户 data 目录不存在，无需验证")


def run_tests():
    """运行所有测试"""
    print("=" * 60)
    print("步骤一测试：_save_results 独立文件存储改造")
    print("=" * 60)
    print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestSaveResults))
    suite.addTests(loader.loadTestsFromTestCase(TestNoDataPollution))

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # 输出结果
    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("✓ 所有测试通过！")
        print("步骤一改造正确：_save_results 已成功改为独立文件存储")
    else:
        print("✗ 测试失败，请检查代码")
    print("=" * 60)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
