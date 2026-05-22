"""
live/runner.py 测试

不依赖真实 QMT，全部 mock。
运行：python tests/test_live_runner.py
"""

import os
import sys
import tempfile
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.context import create_context
from xxybacktest.live.runner import run_live

_TEST_ACCOUNT = "86962531"


def _make_account(data_path, account_type="live", status="running"):
    """构造一个 mock 账户配置。"""
    return {
        "account_id": _TEST_ACCOUNT,
        "account_type": account_type,
        "status": status,
        "name": "测试实盘账户",
        "initial_cash": 1000000.0,
        "start_date": "2024-01-01",
        "data_path": data_path,
        "asset_type": "stock",
        "benchmark": "000300.SH",
        "qmt_path": r"D:\国金QMT交易端模拟\userdata_mini",
        "live_account_id": "123456",
        "initialize_code": "",
        "handle_data_code": "",
    }


def _make_ctx():
    """构造一个最小化实盘 context。"""
    ctx = create_context()
    ctx.g = {}
    ctx.logs.order_list = []
    ctx.portfolio.cash = 900000.0
    ctx.portfolio.total_value = 1200000.0
    ctx.portfolio.positions_value = 300000.0
    ctx.portfolio.starting_cash = 1000000.0
    ctx.current_dt = datetime.now()
    ctx.data.calendar = []
    return ctx


def _mock_load_func(code, name="user_func"):
    """供 patch _load_func 使用，返回预定义函数。"""
    if name == "initialize":
        def initialize(context):
            context.g["initialized"] = True
            context.g["counter"] = 1
        return initialize
    elif name == "handle_data":
        def handle_data(context):
            context.g["handle_data_ran"] = True
            context.g["counter"] = context.g.get("counter", 0) + 1
        return handle_data
    return None


# ---------------------------------------------------------------------------
# 测试：非交易日返回 skipped
# ---------------------------------------------------------------------------

def test_not_trading_day_returns_skipped():
    """is_trading_day 返回 False 时应直接返回 skipped。"""
    with tempfile.TemporaryDirectory() as tmp:
        account = _make_account(tmp)
        with patch("xxybacktest.simulation.submitter.get_account", return_value=account), \
             patch("xxybacktest.live.runner.is_trading_day", return_value=False):
            result = run_live(_TEST_ACCOUNT, tmp)

        assert result["status"] == "skipped"
        assert result["reason"] == "not_trading_day"
        print("[PASS] 非交易日返回 skipped")


# ---------------------------------------------------------------------------
# 测试：账户非 running 返回 skipped
# ---------------------------------------------------------------------------

def test_not_running_returns_skipped():
    """账户状态不为 running 时应返回 skipped。"""
    with tempfile.TemporaryDirectory() as tmp:
        account = _make_account(tmp, status="paused")
        with patch("xxybacktest.simulation.submitter.get_account", return_value=account), \
             patch("xxybacktest.live.runner.is_trading_day", return_value=True):
            result = run_live(_TEST_ACCOUNT, tmp)

        assert result["status"] == "skipped"
        assert result["reason"] == "not_running"
        print("[PASS] 非 running 状态返回 skipped")


# ---------------------------------------------------------------------------
# 测试：非 live 账户返回 error
# ---------------------------------------------------------------------------

def test_not_live_returns_error():
    """account_type 不为 live 时应返回 error。"""
    with tempfile.TemporaryDirectory() as tmp:
        account = _make_account(tmp, account_type="sim")
        with patch("xxybacktest.simulation.submitter.get_account", return_value=account):
            result = run_live(_TEST_ACCOUNT, tmp)

        assert result["status"] == "error"
        assert result["reason"] == "非实盘账户"
        print("[PASS] 非 live 账户返回 error")


# ---------------------------------------------------------------------------
# 测试：策略执行后 context.g 被持久化
# ---------------------------------------------------------------------------

def test_strategy_state_persisted():
    """run_live 成功后应调用 _save_strategy_state 并写入 ctx.g 内容。"""
    with tempfile.TemporaryDirectory() as tmp:
        account = _make_account(tmp)
        account["handle_data_code"] = "def handle_data(ctx): pass"
        ctx = _make_ctx()

        with patch("xxybacktest.simulation.submitter.get_account", return_value=account), \
             patch("xxybacktest.live.runner.is_trading_day", return_value=True), \
             patch("xxybacktest.live.runner._load_schedule", return_value={}), \
             patch("xxybacktest.live.runner._load_strategy_state", return_value={}), \
             patch("xxybacktest.live.runner._update_schedule"), \
             patch("xxybacktest.live.runner.QMTTrader"), \
             patch("xxybacktest.live.runner.create_live_context", return_value=ctx), \
             patch("xxybacktest.live.runner.Data") as mock_Data, \
             patch("xxybacktest.live.runner._save_live_results"), \
             patch("xxybacktest.live.runner._save_strategy_state") as mock_save_state, \
             patch("xxybacktest.live.runner._load_func", side_effect=_mock_load_func), \
             patch("xxybacktest.live.runner._refresh_portfolio"):

            mock_Data.get_trade_calendar.return_value = ["2026-05-20"]
            result = run_live(_TEST_ACCOUNT, tmp)

        assert result["status"] == "success"
        assert mock_save_state.called, "_save_strategy_state 应被调用"

        # 验证传入的 state 包含策略修改后的内容
        args, kwargs = mock_save_state.call_args
        state = args[1]
        assert state.get("initialized") is True
        assert state.get("handle_data_ran") is True
        assert state.get("counter") == 2
        print("[PASS] 策略执行后 context.g 正确持久化")


# ---------------------------------------------------------------------------
# 测试：执行后调用 _save_live_results
# ---------------------------------------------------------------------------

def test_parquet_save_called():
    """run_live 成功后应调用 _save_live_results。"""
    with tempfile.TemporaryDirectory() as tmp:
        account = _make_account(tmp)
        ctx = _make_ctx()

        with patch("xxybacktest.simulation.submitter.get_account", return_value=account), \
             patch("xxybacktest.live.runner.is_trading_day", return_value=True), \
             patch("xxybacktest.live.runner._load_schedule", return_value={}), \
             patch("xxybacktest.live.runner._load_strategy_state", return_value={}), \
             patch("xxybacktest.live.runner._update_schedule"), \
             patch("xxybacktest.live.runner.QMTTrader"), \
             patch("xxybacktest.live.runner.create_live_context", return_value=ctx), \
             patch("xxybacktest.live.runner.Data") as mock_Data, \
             patch("xxybacktest.live.runner._save_live_results") as mock_save_results, \
             patch("xxybacktest.live.runner._save_strategy_state"), \
             patch("xxybacktest.live.runner._load_func", side_effect=_mock_load_func), \
             patch("xxybacktest.live.runner._refresh_portfolio"):

            mock_Data.get_trade_calendar.return_value = ["2026-05-20"]
            result = run_live(_TEST_ACCOUNT, tmp)

        assert result["status"] == "success"
        assert mock_save_results.called, "_save_live_results 应被调用"

        # 验证参数
        args, kwargs = mock_save_results.call_args
        assert args[0] == _TEST_ACCOUNT
        assert args[1] is ctx
        assert args[2] == tmp
        print("[PASS] _save_live_results 正确调用，参数匹配")


# ---------------------------------------------------------------------------
# 测试：防并发 — running=True 时跳过
# ---------------------------------------------------------------------------

def test_concurrent_run_skipped():
    """同一账户正在运行时再次触发应返回 skipped。"""
    with tempfile.TemporaryDirectory() as tmp:
        account = _make_account(tmp)
        with patch("xxybacktest.simulation.submitter.get_account", return_value=account), \
             patch("xxybacktest.live.runner.is_trading_day", return_value=True), \
             patch("xxybacktest.live.runner._load_schedule", return_value={"running": True}):
            result = run_live(_TEST_ACCOUNT, tmp)

        assert result["status"] == "skipped"
        assert result["reason"] == "already_running"
        print("[PASS] 并发时返回 skipped")


# ---------------------------------------------------------------------------
# 测试：QMT 连接失败返回 error
# ---------------------------------------------------------------------------

def test_qmt_connection_error():
    """QMTTrader 连接失败时应返回 error。"""
    with tempfile.TemporaryDirectory() as tmp:
        account = _make_account(tmp)
        with patch("xxybacktest.simulation.submitter.get_account", return_value=account), \
             patch("xxybacktest.live.runner.is_trading_day", return_value=True), \
             patch("xxybacktest.live.runner._load_schedule", return_value={}), \
             patch("xxybacktest.live.runner._update_schedule"), \
             patch("xxybacktest.live.runner.QMTTrader") as mock_trader_cls:

            from xxybacktest.live.trader import QMTConnectionError
            mock_trader_cls.side_effect = QMTConnectionError("连接超时")

            result = run_live(_TEST_ACCOUNT, tmp)

        assert result["status"] == "error"
        assert "QMT 连接失败" in result["reason"]
        print("[PASS] QMT 连接失败返回 error")


# ---------------------------------------------------------------------------
# 测试：缺少 QMT 配置返回 error
# ---------------------------------------------------------------------------

def test_missing_qmt_config():
    """qmt_path 或 live_account_id 为空时应返回 error。"""
    with tempfile.TemporaryDirectory() as tmp:
        account = _make_account(tmp)
        account["qmt_path"] = ""
        with patch("xxybacktest.simulation.submitter.get_account", return_value=account), \
             patch("xxybacktest.live.runner.is_trading_day", return_value=True), \
             patch("xxybacktest.live.runner._load_schedule", return_value={}), \
             patch("xxybacktest.live.runner._update_schedule"):
            result = run_live(_TEST_ACCOUNT, tmp)

        assert result["status"] == "error"
        assert "缺少 QMT 配置" in result["reason"]
        print("[PASS] 缺少 QMT 配置返回 error")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("--- 状态校验 ---")
    test_not_trading_day_returns_skipped()
    test_not_running_returns_skipped()
    test_not_live_returns_error()

    print("\n--- 异常场景 ---")
    test_concurrent_run_skipped()
    test_qmt_connection_error()
    test_missing_qmt_config()

    print("\n--- 正常流程 ---")
    test_strategy_state_persisted()
    test_parquet_save_called()

    print("\n========== All live/runner tests passed ==========")
