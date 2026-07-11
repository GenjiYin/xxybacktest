"""
阶段7 · 定时任务注册测试

验证 _register_factor_job 能把因子分析每日任务注册进 APScheduler,
以及 _plus_minutes 时间计算。不实际等待触发(cron 逻辑由 APScheduler 保证)。
"""
import pytest

from xxybacktest.simulation.main import _plus_minutes


def test_plus_minutes():
    assert _plus_minutes("22:00", 30) == "22:30"
    assert _plus_minutes("09:30", 30) == "10:00"
    assert _plus_minutes("23:50", 30) == "23:59"   # 封顶
    assert _plus_minutes("00:00", 90) == "01:30"


def test_register_factor_job(tmp_path):
    """注册后 scheduler 里应有 builtin_run_factors 任务, cron 正确。"""
    from xxybacktest.simulation.scheduler import start_scheduler, get_scheduler
    from xxybacktest.simulation.main import _register_factor_job

    dp = str(tmp_path)
    start_scheduler(dp)
    try:
        _register_factor_job(dp, "22:30")
        job = get_scheduler().get_job("builtin_run_factors")
        assert job is not None
        assert job.name == "因子分析"
        assert job.next_run_time is not None
    finally:
        get_scheduler().remove_job("builtin_run_factors")


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
