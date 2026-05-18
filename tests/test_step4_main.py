"""
步骤四验证脚本：测试 main.py 改造后的内置任务注册逻辑。
运行后会在 ./data/simulation_results/task_logs/ 下生成日志目录。
"""
import os

from xxybacktest.simulation.scheduler import start_scheduler, get_all_jobs, remove_job, get_scheduler, _scheduler
from xxybacktest.simulation.main import _register_builtin_jobs

DATA_PATH = os.path.abspath("./data")
print(DATA_PATH)


def test_builtin_job():
    print(f"[0/3] _scheduler id: {id(_scheduler)}")

    # 先清理可能残留的旧任务，确保从干净状态开始
    print("[1/3] 先移除旧任务...")
    remove_job("builtin_run_simulation")
    print(f"      _scheduler id: {id(get_scheduler())}")

    print("[2/3] 启动 APScheduler...")
    start_scheduler(DATA_PATH)
    print(f"      _scheduler running: {get_scheduler().running}")
    print(f"      jobs before add: {len(get_scheduler().get_jobs())}")

    print("[3/3] 注册内置任务 '模拟交易' (22:00)...")
    _register_builtin_jobs(DATA_PATH, "22:00")
    print(f"      jobs after add: {len(get_scheduler().get_jobs())}")

    print("[4/3] 查询所有 jobs...")
    jobs = get_all_jobs(DATA_PATH)
    print(f"      get_all_jobs 返回 count: {len(jobs)}")
    for j in jobs:
        print(
            f"      {j['task_id']} | {j['name']} | cron={j['cron']} | "
            f"next={j['next_run_time']} | status={j['last_status']}"
        )

    assert len(jobs) == 1, f"期望 1 个 job，实际 {len(jobs)}"
    assert jobs[0]["task_id"] == "builtin_run_simulation"
    print("\n验证通过！")

    # 如需保留任务观察日志，请注释掉下面这行
    # remove_job("builtin_run_simulation")


if __name__ == "__main__":
    test_builtin_job()
