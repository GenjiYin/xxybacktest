"""
simulation/submitter.py 实盘扩展测试

不依赖真实 QMT，全部 mock。
运行：python tests/test_live_submitter.py
"""

import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.simulation.submitter import (
    submit,
    list_accounts,
    get_account,
    delete,
)


def _make_initialize():
    """返回一个可序列化的 initialize 函数源码字符串。"""
    return "def initialize(ctx):\n    ctx.g['flag'] = 1\n"


# ---------------------------------------------------------------------------
# 测试：模拟账户提交不受影响（默认值兼容）
# ---------------------------------------------------------------------------

def test_sim_account_defaults():
    """不传新参数时，提交的是模拟账户，所有新字段有默认值。"""
    with tempfile.TemporaryDirectory() as tmp:
        account_id = submit(
            name="测试模拟账户",
            initialize=lambda ctx: None,
            capital=500000,
            data_path=tmp,
        )

        assert account_id.startswith("sim_"), f"模拟账户 ID 应以 sim_ 开头: {account_id}"

        account = get_account(account_id, tmp)
        assert account is not None
        assert account["account_type"] == "sim"
        assert account["initial_cash"] == 500000
        assert account["trigger_cron"] == "30 9 * * *"
        assert account["execution_mode"] == "daily"
        assert account["rebalance_interval"] == 1
        assert account.get("live_account_id") is None
        assert account.get("qmt_path") is None
        print(f"[PASS] 模拟账户提交成功: {account_id}")

        delete(account_id, tmp)


# ---------------------------------------------------------------------------
# 测试：实盘账户 ID 以 live_ 开头
# ---------------------------------------------------------------------------

def test_live_account_id_prefix():
    """account_type='live' 时 ID 应以 live_ 开头。"""
    with tempfile.TemporaryDirectory() as tmp:
        with patch("xxybacktest.live.trader.QMTTrader") as mock_cls:
            mock_trader = MagicMock()
            mock_trader.get_portfolio.return_value = {"total_asset": 888888.88}
            mock_cls.return_value = mock_trader

            account_id = submit(
                name="测试实盘账户",
                initialize=lambda ctx: None,
                capital=100000,  # 会被覆盖
                data_path=tmp,
                account_type="live",
                live_account_id="123456",
                qmt_path=r"D:\test\qmt",
            )

        assert account_id.startswith("live_"), f"实盘账户 ID 应以 live_ 开头: {account_id}"
        print(f"[PASS] 实盘账户 ID 前缀正确: {account_id}")

        delete(account_id, tmp)


# ---------------------------------------------------------------------------
# 测试：实盘账户 initial_cash 从 QMT 读取
# ---------------------------------------------------------------------------

def test_live_reads_qmt_total_asset():
    """account_type='live' 时，initial_cash 应等于 QMT 的 total_asset。"""
    with tempfile.TemporaryDirectory() as tmp:
        with patch("xxybacktest.live.trader.QMTTrader") as mock_cls:
            mock_trader = MagicMock()
            mock_trader.get_portfolio.return_value = {"total_asset": 1234567.89}
            mock_cls.return_value = mock_trader

            account_id = submit(
                name="测试实盘读取资金",
                initialize=lambda ctx: None,
                capital=999999,  # 应被覆盖
                data_path=tmp,
                account_type="live",
                live_account_id="888168",
                qmt_path=r"D:\test\qmt",
            )

            mock_trader.disconnect.assert_called_once()

        account = get_account(account_id, tmp)
        assert abs(account["initial_cash"] - 1234567.89) < 0.01
        print(f"[PASS] 实盘 initial_cash = {account['initial_cash']:,.2f}（来自 QMT）")

        delete(account_id, tmp)


# ---------------------------------------------------------------------------
# 测试：实盘缺少配置报错
# ---------------------------------------------------------------------------

def test_live_missing_qmt_config_raises():
    """account_type='live' 但缺少 qmt_path 或 live_account_id 时应抛 ValueError。"""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            submit(
                name="测试缺配置",
                initialize=lambda ctx: None,
                data_path=tmp,
                account_type="live",
                live_account_id="123",  # 有 id 但无 qmt_path
                qmt_path=None,
            )
            assert False, "应抛出 ValueError"
        except ValueError as e:
            assert "qmt_path" in str(e).lower() or "live_account_id" in str(e).lower()
            print(f"[PASS] 缺少 qmt_path 正确报错: {e}")

        try:
            submit(
                name="测试缺配置2",
                initialize=lambda ctx: None,
                data_path=tmp,
                account_type="live",
                live_account_id=None,  # 无 id
                qmt_path=r"D:\test\qmt",
            )
            assert False, "应抛出 ValueError"
        except ValueError as e:
            assert "qmt_path" in str(e).lower() or "live_account_id" in str(e).lower()
            print(f"[PASS] 缺少 live_account_id 正确报错: {e}")


# ---------------------------------------------------------------------------
# 测试：实盘字段完整存储
# ---------------------------------------------------------------------------

def test_live_fields_stored():
    """实盘扩展字段应完整写入数据库。"""
    with tempfile.TemporaryDirectory() as tmp:
        with patch("xxybacktest.live.trader.QMTTrader") as mock_cls:
            mock_trader = MagicMock()
            mock_trader.get_portfolio.return_value = {"total_asset": 500000}
            mock_cls.return_value = mock_trader

            account_id = submit(
                name="测试字段完整",
                initialize=lambda ctx: None,
                data_path=tmp,
                account_type="live",
                live_account_id="8881686799",
                qmt_path=r"D:\国金证券QMT交易端\userdata_mini",
                trigger_cron="0 10 * * 1-5",
                execution_mode="periodic",
                rebalance_interval=5,
            )

        account = get_account(account_id, tmp)
        assert account["live_account_id"] == "8881686799"
        assert account["qmt_path"] == r"D:\国金证券QMT交易端\userdata_mini"
        assert account["trigger_cron"] == "0 10 * * 1-5"
        assert account["execution_mode"] == "periodic"
        assert account["rebalance_interval"] == 5
        print(f"[PASS] 实盘扩展字段完整存储")

        delete(account_id, tmp)


# ---------------------------------------------------------------------------
# 测试：list_accounts 显示新字段
# ---------------------------------------------------------------------------

def test_list_accounts_includes_new_fields():
    """list_accounts 返回的数据应包含 account_type 等新字段。"""
    with tempfile.TemporaryDirectory() as tmp:
        with patch("xxybacktest.live.trader.QMTTrader") as mock_cls:
            mock_trader = MagicMock()
            mock_trader.get_portfolio.return_value = {"total_asset": 300000}
            mock_cls.return_value = mock_trader

            sim_id = submit("模拟", lambda ctx: None, data_path=tmp)
            live_id = submit(
                "实盘", lambda ctx: None, data_path=tmp,
                account_type="live",
                live_account_id="111",
                qmt_path=r"D:\qmt",
            )

        accounts = list_accounts(data_path=tmp)
        assert len(accounts) == 2

        sim_acc = next(a for a in accounts if a["account_id"] == sim_id)
        live_acc = next(a for a in accounts if a["account_id"] == live_id)

        assert sim_acc["account_type"] == "sim"
        assert live_acc["account_type"] == "live"
        assert "trigger_cron" in sim_acc
        assert "execution_mode" in live_acc
        print("[PASS] list_accounts 正确返回新字段")

        delete(sim_id, tmp)
        delete(live_id, tmp)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("--- 模拟账户兼容 ---")
    test_sim_account_defaults()

    print("\n--- 实盘账户 ID 前缀 ---")
    test_live_account_id_prefix()

    print("\n--- 实盘读取 QMT 资金 ---")
    test_live_reads_qmt_total_asset()

    print("\n--- 缺少配置报错 ---")
    test_live_missing_qmt_config_raises()

    print("\n--- 字段完整存储 ---")
    test_live_fields_stored()

    print("\n--- list_accounts 新字段 ---")
    test_list_accounts_includes_new_fields()

    print("\n========== All live/submitter tests passed ==========")
