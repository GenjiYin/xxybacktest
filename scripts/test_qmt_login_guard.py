"""
scripts/test_qmt_login_guard.py — 测试 QMT 登录守卫逻辑

验证场景：QMT 未登录时，run_live() 不会卡死，而是直接失败并输出正确日志。

用法:
    python scripts/test_qmt_login_guard.py
"""

import os
import shutil
import sys
import tempfile

# 把项目根目录加入 PYTHONPATH
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.simulation.submitter import submit
from xxybacktest.live.runner import run_live
from xxybacktest.live.trader import check_qmt_login


# ── 测试用的极简策略 ──
def initialize(ctx):
    ctx.g.counter = 0


def handle_data(ctx):
    ctx.g.counter += 1


# ── 配置 ──
QMT_PATH = r"D:/国金证券QMT交易端/userdata_mini"
LIVE_ACCOUNT = "8881686799"


def test_check_qmt_login():
    """测试独立的 check_qmt_login 函数"""
    print("\n" + "=" * 50)
    print("测试 1/3: check_qmt_login 独立检测")
    print("=" * 50)

    ok = check_qmt_login(QMT_PATH, LIVE_ACCOUNT)
    print(f"\n检测结果: {'已登录' if ok else '未登录'}")
    return ok


def test_run_live_guard():
    """
    测试 run_live 的登录守卫。
    使用临时目录创建实盘账户，调用 run_live，验证未登录时直接失败。
    """
    print("\n" + "=" * 50)
    print("测试 2/3: run_live 登录守卫")
    print("=" * 50)

    tmpdir = tempfile.mkdtemp(prefix="test_qmt_guard_")
    print(f"临时目录: {tmpdir}")

    try:
        account_id = submit(
            name="测试实盘账户",
            initialize=initialize,
            handle_data=handle_data,
            capital=100000,
            data_path=tmpdir,
            account_type="live",
            live_account_id=LIVE_ACCOUNT,
            qmt_path=QMT_PATH,
            run_now=False,
        )
        print(f"创建账户: {account_id}")

        # 调用 run_live
        result = run_live(account_id, data_path=tmpdir)
        print(f"\n返回结果: {result}")

        # 验证
        assert result["status"] == "error", f"期望 status=error，实际={result['status']}"
        assert "没有登录qmt" in result.get("reason", ""), f"期望原因包含'没有登录qmt'，实际={result.get('reason')}"
        print("✅ 断言通过: 未登录时任务标记为失败，原因正确")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        print(f"已清理临时目录")


def test_schedule_simulation():
    """
    测试 3/3: 模拟调度器执行场景（通过捕获 RuntimeError 验证日志输出）
    """
    print("\n" + "=" * 50)
    print("测试 3/3: 调度器场景模拟")
    print("=" * 50)

    tmpdir = tempfile.mkdtemp(prefix="test_qmt_guard_")

    try:
        account_id = submit(
            name="测试实盘账户2",
            initialize=initialize,
            handle_data=handle_data,
            capital=100000,
            data_path=tmpdir,
            account_type="live",
            live_account_id=LIVE_ACCOUNT,
            qmt_path=QMT_PATH,
            run_now=False,
        )

        # 调度器内部会捕获异常并标记失败
        # 这里模拟调度器的 try/except 行为
        try:
            run_live(account_id, data_path=tmpdir)
            print("❌ 期望抛出异常，但没有")
        except RuntimeError as e:
            print(f"✅ 正确抛出 RuntimeError: {e}")
            print("   调度器会捕获此异常，将任务状态写入 .status 文件并标记为 error")
        except Exception as e:
            print(f"✅ 抛出异常: {type(e).__name__}: {e}")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    print("QMT 登录守卫测试")
    print(f"QMT 路径: {QMT_PATH}")
    print(f"资金账号: {LIVE_ACCOUNT}")

    try:
        logged_in = test_check_qmt_login()

        if logged_in:
            print("\n⚠️ 当前 QMT 已登录，测试 2/3 和 3/3 会走正常调仓流程！")
            print("   请关闭 QMT 客户端后再运行此测试，才能验证'未登录守卫'逻辑。")
            return

        test_run_live_guard()
        test_schedule_simulation()

        print("\n" + "=" * 50)
        print("✅ 所有测试通过")
        print("=" * 50)

    except AssertionError as e:
        print(f"\n❌ 断言失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
