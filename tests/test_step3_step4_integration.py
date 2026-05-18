"""
步骤三 + 步骤四 联调测试

模拟 main.py 启动流程：
1. 先注册一个用户任务（写入 scheduled_tasks.json）
2. 启动 scheduler，加载内置任务 + 用户任务
3. 确认所有任务都在 APScheduler 中

测试结束后会自动清理。
"""
import os
import tempfile

from xxybacktest.simulation.scheduler import (
    start_scheduler,
    get_all_jobs,
    remove_job,
    get_scheduler,
)
from xxybacktest.simulation.task_store import schedule_task, load_tasks, remove_task
from xxybacktest.simulation.main import _register_builtin_jobs

DATA_PATH = os.path.abspath("./data")


def _make_temp_script():
    """在 ./data 目录下创建临时脚本"""
    fd, path = tempfile.mkstemp(suffix=".py", dir=DATA_PATH, text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("print('hello from user task')\n")
    return path


def test_integration():
    print("=" * 50)
    print("联调测试：task_store + scheduler + main.py 启动流程")
    print("=" * 50)

    # --------------------------------------------------
    # 前置清理
    # --------------------------------------------------
    print("\n[前置] 清理旧数据...")
    remove_job("builtin_run_simulation")

    # --------------------------------------------------
    # 步骤 1：注册用户任务（模拟用户调用 schedule_task）
    # --------------------------------------------------
    print("\n[步骤 1] 注册用户任务 '数据更新' (time=17:30)...")
    script = _make_temp_script()
    try:
        tid = schedule_task(
            name="数据更新",
            script=script,
            time="17:30",
            data_path=DATA_PATH,
        )
        print(f"      task_id: {tid}")
    except Exception as e:
        os.remove(script)
        raise e

    # 验证 JSON 已写入
    tasks = load_tasks(DATA_PATH)
    assert any(t["task_id"] == tid for t in tasks), "JSON 中未找到刚注册的任务"
    print(f"      JSON 已写入，共 {len(tasks)} 个任务")

    # --------------------------------------------------
    # 步骤 2：模拟 main.py 启动流程
    # --------------------------------------------------
    print("\n[步骤 2] 模拟 main.py 启动...")
    start_scheduler(DATA_PATH)
    print(f"      scheduler running: {get_scheduler().running}")

    _register_builtin_jobs(DATA_PATH, "22:00")
    print("      内置任务 '模拟交易' 已注册")

    user_tasks = load_tasks(DATA_PATH)
    for t in user_tasks:
        from xxybacktest.simulation.scheduler import add_script_job
        add_script_job(t["task_id"], t["name"], t["script"], t["cron"], DATA_PATH)
    print(f"      已加载 {len(user_tasks)} 个用户任务")

    # --------------------------------------------------
    # 步骤 3：验证所有任务都在调度器中
    # --------------------------------------------------
    print("\n[步骤 3] 查询所有 jobs...")
    jobs = get_all_jobs(DATA_PATH)
    print(f"      jobs count: {len(jobs)}")
    for j in jobs:
        print(
            f"      {j['task_id']} | {j['name']} | cron={j['cron']} | "
            f"next={j['next_run_time']} | status={j['last_status']}"
        )

    assert len(jobs) == 2, f"期望 2 个 job（内置+用户），实际 {len(jobs)}"

    task_ids = {j["task_id"] for j in jobs}
    assert "builtin_run_simulation" in task_ids, "内置任务未注册"
    assert tid in task_ids, "用户任务未加载到调度器"

    print("\n" + "=" * 50)
    print("联调测试通过！")
    print("=" * 50)

    # --------------------------------------------------
    # 清理
    # --------------------------------------------------
    print("\n[清理] 删除测试数据...")
    remove_job("builtin_run_simulation")
    remove_task(tid, DATA_PATH)
    os.remove(script)
    print("完成。")


if __name__ == "__main__":
    test_integration()
