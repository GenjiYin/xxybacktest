"""
simulation/main.py + scheduler.py 实盘调度测试

不依赖真实 QMT，全部 mock。
运行：python tests/test_live_scheduler.py
"""

import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.simulation.main import _register_live_jobs
from xxybacktest.simulation.scheduler import get_all_jobs


# ---------------------------------------------------------------------------
# 测试：无实盘账户时不注册
# ---------------------------------------------------------------------------

def test_no_live_accounts():
    """没有运行中实盘账户时，_register_live_jobs 不做任何操作。"""
    with tempfile.TemporaryDirectory() as tmp:
        with patch("xxybacktest.simulation.submitter.list_accounts", return_value=[]):
            # 不应抛异常，不应调用 add_func_job
            _register_live_jobs(tmp)
        print("[PASS] 无实盘账户时不抛异常")


# ---------------------------------------------------------------------------
# 测试：实盘账户被注册为独立 cron job
# ---------------------------------------------------------------------------

def test_live_jobs_registered():
    """运行中的实盘账户应被注册为 live_ 前缀的 job。"""
    with tempfile.TemporaryDirectory() as tmp:
        mock_jobs = {}

        def _mock_add_func_job(task_id, name, func, cron, data_path):
            mock_jobs[task_id] = {
                "name": name, "func": func, "cron": cron, "data_path": data_path
            }

        accounts = [
            {
                "account_id": "live_20260521_001",
                "name": "茅台策略",
                "account_type": "live",
                "status": "running",
                "trigger_cron": "30 9 * * *",
            },
            {
                "account_id": "live_20260521_002",
                "name": "ETF轮动",
                "account_type": "live",
                "status": "running",
                "trigger_cron": "0 14 * * 1-5",
            },
        ]

        with patch("xxybacktest.simulation.submitter.list_accounts", return_value=accounts), \
             patch("xxybacktest.simulation.scheduler.add_func_job", side_effect=_mock_add_func_job):
            _register_live_jobs(tmp)

        assert len(mock_jobs) == 2

        assert "live_live_20260521_001" in mock_jobs
        assert mock_jobs["live_live_20260521_001"]["name"] == "实盘-茅台策略"
        assert mock_jobs["live_live_20260521_001"]["cron"] == "30 9 * * *"

        assert "live_live_20260521_002" in mock_jobs
        assert mock_jobs["live_live_20260521_002"]["name"] == "实盘-ETF轮动"
        assert mock_jobs["live_live_20260521_002"]["cron"] == "0 14 * * 1-5"

        print("[PASS] 实盘账户注册为独立 cron job，ID 前缀为 live_")


# ---------------------------------------------------------------------------
# 测试：模拟账户不被注册
# ---------------------------------------------------------------------------

def test_sim_accounts_skipped():
    """模拟账户不应被 _register_live_jobs 注册。"""
    with tempfile.TemporaryDirectory() as tmp:
        mock_jobs = {}

        def _mock_add_func_job(task_id, name, func, cron, data_path):
            mock_jobs[task_id] = True

        accounts = [
            {
                "account_id": "sim_20260521_001",
                "name": "模拟测试",
                "account_type": "sim",
                "status": "running",
            },
            {
                "account_id": "live_20260521_003",
                "name": "实盘策略",
                "account_type": "live",
                "status": "running",
            },
        ]

        with patch("xxybacktest.simulation.submitter.list_accounts", return_value=accounts), \
             patch("xxybacktest.simulation.scheduler.add_func_job", side_effect=_mock_add_func_job):
            _register_live_jobs(tmp)

        assert len(mock_jobs) == 1
        assert "live_live_20260521_003" in mock_jobs
        assert "sim_20260521_001" not in mock_jobs
        print("[PASS] 模拟账户被跳过，仅注册实盘账户")


# ---------------------------------------------------------------------------
# 测试：非 running 状态被跳过
# ---------------------------------------------------------------------------

def test_paused_live_skipped():
    """状态为 paused 的实盘账户不应被注册。"""
    with tempfile.TemporaryDirectory() as tmp:
        mock_jobs = {}

        def _mock_add_func_job(task_id, name, func, cron, data_path):
            mock_jobs[task_id] = True

        accounts = [
            {
                "account_id": "live_20260521_004",
                "name": "暂停实盘",
                "account_type": "live",
                "status": "paused",
                "trigger_cron": "30 9 * * *",
            },
        ]

        with patch("xxybacktest.simulation.submitter.list_accounts") as mock_list, \
             patch("xxybacktest.simulation.scheduler.add_func_job", side_effect=_mock_add_func_job):

            mock_list.side_effect = lambda status=None, data_path=None: [
                a for a in accounts if status is None or a.get("status") == status
            ]
            _register_live_jobs(tmp)

        assert len(mock_jobs) == 0
        print("[PASS] paused 状态的实盘账户被跳过")


# ---------------------------------------------------------------------------
# 测试：默认 trigger_cron
# ---------------------------------------------------------------------------

def test_default_trigger_cron():
    """未设置 trigger_cron 的实盘账户使用默认值 '30 9 * * *'。"""
    with tempfile.TemporaryDirectory() as tmp:
        mock_jobs = {}

        def _mock_add_func_job(task_id, name, func, cron, data_path):
            mock_jobs[task_id] = {"cron": cron}

        accounts = [
            {
                "account_id": "live_20260521_005",
                "name": "默认时间",
                "account_type": "live",
                "status": "running",
                # trigger_cron 未设置
            },
        ]

        with patch("xxybacktest.simulation.submitter.list_accounts", return_value=accounts), \
             patch("xxybacktest.simulation.scheduler.add_func_job", side_effect=_mock_add_func_job):
            _register_live_jobs(tmp)

        assert mock_jobs["live_live_20260521_005"]["cron"] == "30 9 * * *"
        print("[PASS] 默认 trigger_cron = 30 9 * * *")


# ---------------------------------------------------------------------------
# 测试：get_all_jobs 展示实盘 job
# ---------------------------------------------------------------------------

def test_get_all_jobs_includes_live():
    """get_all_jobs 应返回 scheduler 中的实盘 job。"""
    # mock scheduler 中的 jobs
    mock_job = MagicMock()
    mock_job.id = "live_live_test_001"
    mock_job.name = "实盘-测试"
    mock_job.trigger.fields = []
    mock_job.next_run_time = None

    scheduler = MagicMock()
    scheduler.get_jobs.return_value = [mock_job]

    with patch("xxybacktest.simulation.scheduler.get_scheduler", return_value=scheduler), \
         patch("xxybacktest.simulation.scheduler.sync_user_jobs"):
        jobs = get_all_jobs("/tmp")

    task_ids = [j["task_id"] for j in jobs]
    assert "live_live_test_001" in task_ids
    print("[PASS] get_all_jobs 包含实盘 job")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("--- 注册逻辑 ---")
    test_no_live_accounts()
    test_live_jobs_registered()
    test_sim_accounts_skipped()
    test_paused_live_skipped()
    test_default_trigger_cron()

    print("\n--- 展示逻辑 ---")
    test_get_all_jobs_includes_live()

    print("\n========== All live/scheduler tests passed ==========")
