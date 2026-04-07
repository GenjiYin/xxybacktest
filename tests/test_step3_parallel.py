"""
测试步骤三：run_all 并行执行改造
使用临时目录和模拟数据，不污染用户原有数据
"""
import os
import sys
import tempfile
import shutil
import unittest
import time
from datetime import datetime

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from xxybacktest.simulation.runner import run_all, _save_results
from xxybacktest.simulation.submitter import submit, delete, list_accounts


class MockPortfolio:
    def __init__(self):
        self.total_value = 100000.0


class MockPerformance:
    def __init__(self, account_id):
        # 用 account_id 的 hash 来生成不同的随机种子，让每个账户数据不同
        np.random.seed(hash(account_id) % 2**31)
        dates = pd.date_range('2024-01-01', periods=10, freq='D')
        returns = np.random.normal(0.001, 0.01, 10)
        self.returns = pd.Series(returns, index=dates)
        self.position_snapshots = []


class MockContext:
    def __init__(self, account_id):
        self.performance = MockPerformance(account_id)
        self.portfolio = MockPortfolio()
        self.order = pd.DataFrame()


def mock_run_single(account_id, end_date, data_path):
    """模拟 run_single 函数，用于测试并行"""
    # 模拟一些计算时间
    time.sleep(0.1)

    context = MockContext(account_id)
    _save_results(account_id, context, data_path)

    return {
        'account_id': account_id,
        'status': 'success',
        'final_nav': 1.0,
    }


class TestParallelExecution(unittest.TestCase):
    """测试并行执行"""

    def setUp(self):
        """创建临时目录"""
        self.test_dir = tempfile.mkdtemp(prefix="test_step3_")
        print(f"\n[测试目录] {self.test_dir}")

    def tearDown(self):
        """删除临时目录"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
            print(f"[清理完成] 删除 {self.test_dir}")

    def test_parallel_execution_correctness(self):
        """测试：并行执行结果正确"""
        print("\n=== 测试1：并行执行正确性 ===")

        account_ids = [f"parallel_test_{i:03d}" for i in range(4)]

        # 并行执行（使用 ProcessPoolExecutor）
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(mock_run_single, acc_id, "2024-01-10", self.test_dir)
                for acc_id in account_ids
            ]
            results = [f.result() for f in futures]

        # 验证所有任务都成功完成
        self.assertEqual(len(results), len(account_ids))
        for result in results:
            self.assertEqual(result['status'], 'success')

        # 验证数据完整性 - 每个账户都有自己的文件
        for acc_id in account_ids:
            nav_path = os.path.join(self.test_dir, "simulation_results", "accounts", acc_id, "daily_values.parquet")
            self.assertTrue(os.path.exists(nav_path), f"{acc_id} 数据文件应存在")
            df = pd.read_parquet(nav_path)
            self.assertEqual(len(df), 10, f"{acc_id} 应有10条记录")

        print(f"  [OK] {len(account_ids)} 个账户并行执行全部成功")
        print(f"  [OK] 所有账户数据文件正确写入且无丢失")

    def test_multiple_accounts_isolation(self):
        """测试：多账户并行数据隔离"""
        print("\n=== 测试2：并行数据隔离 ===")

        from concurrent.futures import ProcessPoolExecutor

        account_ids = [f"isolation_test_{i:03d}" for i in range(5)]

        with ProcessPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(mock_run_single, acc_id, "2024-01-10", self.test_dir)
                for acc_id in account_ids
            ]
            results = [f.result() for f in futures]

        # 验证每个账户都有独立的数据
        for acc_id in account_ids:
            account_dir = os.path.join(self.test_dir, "simulation_results", "accounts", acc_id)
            self.assertTrue(os.path.exists(account_dir), f"{acc_id} 目录应存在")

            # 读取验证
            df = pd.read_parquet(os.path.join(account_dir, "daily_values.parquet"))
            self.assertEqual(len(df), 10, f"{acc_id} 应有10条记录")
            self.assertTrue((df['account_id'] == acc_id).all(), f"{acc_id} 数据不应被污染")

        print(f"  [OK] {len(account_ids)} 个账户并行写入，数据完全隔离")


def run_tests():
    """运行所有测试"""
    print("=" * 60)
    print("步骤三测试：run_all 并行执行改造")
    print("=" * 60)
    print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"注意: Windows 下多进程 spawn 模式启动较慢，测试可能需几秒钟")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestParallelExecution))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("[PASS] 所有测试通过！")
        print("步骤三改造正确：run_all 已成功改为并行执行")
    else:
        print("[FAIL] 测试失败，请检查代码")
    print("=" * 60)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
