"""
测试步骤二：三个查询函数改造
验证从独立 Parquet 文件读取数据
"""
import os
import sys
import tempfile
import shutil
import unittest
from datetime import datetime

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from xxybacktest.simulation.runner import (
    _save_results,
    get_account_nav,
    get_account_positions,
    get_account_orders
)


class MockPortfolio:
    def __init__(self):
        self.total_value = 100000.0


class MockPerformance:
    def __init__(self):
        dates = pd.date_range('2024-01-01', periods=30, freq='D')
        returns = np.random.normal(0.001, 0.02, 30)
        self.returns = pd.Series(returns, index=dates)

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


class MockContext:
    def __init__(self):
        self.performance = MockPerformance()
        self.portfolio = MockPortfolio()
        self.order = pd.DataFrame([
            {'date': '2024-01-15', 'instrument': '000001.SZ', 'name': '平安银行',
             'volume': 1000, 'side': 'buy', 'status': 'filled', 'cost': 9500.0},
            {'date': '2024-01-20', 'instrument': '000002.SZ', 'name': '万科A',
             'volume': 500, 'side': 'buy', 'status': 'filled', 'cost': 9500.0},
            {'date': '2024-01-25', 'instrument': '000001.SZ', 'name': '平安银行',
             'volume': 500, 'side': 'sell', 'status': 'filled', 'cost': 5250.0},
        ])


class TestQueryFunctions(unittest.TestCase):
    """测试三个查询函数"""

    def setUp(self):
        """创建临时目录并写入测试数据"""
        self.test_dir = tempfile.mkdtemp(prefix="test_step2_")
        self.account_id = "test_query_001"

        # 创建测试数据
        context = MockContext()
        _save_results(self.account_id, context, self.test_dir)

        print(f"\n[测试目录] {self.test_dir}")

    def tearDown(self):
        """删除临时目录"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
            print(f"[清理完成] 删除 {self.test_dir}")

    def test_get_account_nav(self):
        """测试：get_account_nav 正确读取净值数据"""
        print("\n=== 测试1：get_account_nav ===")

        df = get_account_nav(self.account_id, data_path=self.test_dir)

        # 验证返回结果
        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(len(df), 30, "应有30条净值记录")
        self.assertListEqual(list(df.columns), ['date', 'nav', 'daily_return'])

        # 验证按日期排序
        self.assertTrue(df['date'].is_monotonic_increasing, "日期应升序排列")

        print(f"  [OK] 读取到 {len(df)} 条净值记录")
        print(f"  [OK] 日期范围: {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
        print(f"  [OK] 最终净值: {df['nav'].iloc[-1]:.4f}")

    def test_get_account_nav_empty(self):
        """测试：账户不存在时返回空DataFrame"""
        print("\n=== 测试2：get_account_nav (空数据) ===")

        df = get_account_nav("non_existent_account", data_path=self.test_dir)

        self.assertTrue(df.empty)
        self.assertListEqual(list(df.columns), ['date', 'nav', 'daily_return'])

        print(f"  [OK] 空账户返回正确格式的空DataFrame")

    def test_get_account_positions(self):
        """测试：get_account_positions 正确读取持仓"""
        print("\n=== 测试3：get_account_positions ===")

        df = get_account_positions(self.account_id, data_path=self.test_dir)

        self.assertEqual(len(df), 2, "应有2条持仓记录")
        self.assertIn('instrument', df.columns)
        self.assertIn('close_price', df.columns)
        self.assertIn('ratio', df.columns)

        # 验证按ratio降序排列
        self.assertTrue(df['ratio'].is_monotonic_decreasing, "应按ratio降序排列")

        # 验证第一条是平安银行（ratio 0.5）
        self.assertEqual(df['instrument'].iloc[0], '000001.SZ')
        self.assertEqual(df['ratio'].iloc[0], 0.5)

        print(f"  [OK] 读取到 {len(df)} 条持仓记录")
        print(f"  [OK] 按ratio降序排列")
        for _, row in df.iterrows():
            print(f"       {row['name']}: {row['ratio']*100:.1f}%")

    def test_get_account_positions_with_date(self):
        """测试：指定日期过滤持仓"""
        print("\n=== 测试4：get_account_positions (指定日期) ===")

        # 指定存在的日期
        df = get_account_positions(self.account_id, date='2024-01-30', data_path=self.test_dir)
        self.assertEqual(len(df), 2, "2024-01-30应有2条持仓")

        # 指定不存在的日期
        df_empty = get_account_positions(self.account_id, date='2023-01-01', data_path=self.test_dir)
        self.assertEqual(len(df_empty), 0, "不存在的日期应返回空")

        print(f"  [OK] 指定日期过滤正确")

    def test_get_account_orders(self):
        """测试：get_account_orders 正确读取订单"""
        print("\n=== 测试5：get_account_orders ===")

        df = get_account_orders(self.account_id, limit=100, data_path=self.test_dir)

        self.assertEqual(len(df), 3, "应有3条订单记录")
        self.assertIn('instrument', df.columns)
        self.assertIn('side', df.columns)
        self.assertIn('status', df.columns)

        # 验证按日期降序排列
        self.assertTrue(df['date'].is_monotonic_decreasing, "应按日期降序排列")

        # 验证第一条是最新的
        self.assertEqual(df['date'].iloc[0], '2024-01-25')
        self.assertEqual(df['side'].iloc[0], 'sell')

        print(f"  [OK] 读取到 {len(df)} 条订单记录")
        print(f"  [OK] 按日期降序排列")
        for _, row in df.iterrows():
            print(f"       {row['date']} {row['name']} {row['side']} {row['volume']}股")

    def test_get_account_orders_limit(self):
        """测试：订单数量限制"""
        print("\n=== 测试6：get_account_orders (limit) ===")

        df = get_account_orders(self.account_id, limit=2, data_path=self.test_dir)
        self.assertEqual(len(df), 2, "limit=2应只返回2条")

        # 验证是最新的2条
        self.assertEqual(df['date'].iloc[0], '2024-01-25')
        self.assertEqual(df['date'].iloc[1], '2024-01-20')

        print(f"  [OK] limit=2 正确限制返回数量")

    def test_write_then_read_consistency(self):
        """测试：写入后立即读取数据一致性"""
        print("\n=== 测试7：读写一致性验证 ===")

        # 创建第二个账户
        account_id_2 = "test_query_002"
        context2 = MockContext()
        _save_results(account_id_2, context2, self.test_dir)

        # 验证两个账户数据完全隔离
        df1_nav = get_account_nav(self.account_id, data_path=self.test_dir)
        df2_nav = get_account_nav(account_id_2, data_path=self.test_dir)

        # 两个账户的数据应该独立（虽然模拟数据相同，但存储位置不同）
        self.assertEqual(len(df1_nav), len(df2_nav))

        # 验证文件确实分开存储
        account1_file = os.path.join(self.test_dir, "simulation_results", "accounts",
                                     self.account_id, "daily_values.parquet")
        account2_file = os.path.join(self.test_dir, "simulation_results", "accounts",
                                     account_id_2, "daily_values.parquet")

        self.assertTrue(os.path.exists(account1_file))
        self.assertTrue(os.path.exists(account2_file))
        self.assertNotEqual(account1_file, account2_file)

        print(f"  [OK] 账户 {self.account_id} 和 {account_id_2} 数据完全隔离")
        print(f"  [OK] 两个账户都有独立的存储文件")


class TestNoDataPollution(unittest.TestCase):
    """验证测试不会污染用户数据"""

    def test_query_uses_correct_path(self):
        """测试：查询函数使用正确的路径参数"""
        print("\n=== 测试8：验证路径参数 ===")

        test_dir = tempfile.mkdtemp()
        try:
            # 写入测试数据
            context = MockContext()
            _save_results("path_test_account", context, test_dir)

            # 从测试目录读取
            df = get_account_nav("path_test_account", data_path=test_dir)
            self.assertEqual(len(df), 30)

            # 从随机不存在的目录读取应返回空
            df_empty = get_account_nav("path_test_account",
                                        data_path=os.path.join(test_dir, "nonexistent"))
            self.assertTrue(df_empty.empty)

            print(f"  [OK] 查询函数正确使用 data_path 参数")
            print(f"  [OK] 不同路径返回不同结果")

        finally:
            shutil.rmtree(test_dir)


def run_tests():
    """运行所有测试"""
    print("=" * 60)
    print("步骤二测试：三个查询函数改造")
    print("=" * 60)
    print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestQueryFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestNoDataPollution))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("[PASS] 所有测试通过！")
        print("步骤二改造正确：三个查询函数已成功改为从独立文件读取")
    else:
        print("[FAIL] 测试失败，请检查代码")
    print("=" * 60)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
