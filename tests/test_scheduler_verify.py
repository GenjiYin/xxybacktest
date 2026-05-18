"""
验证 scheduler.py 功能：启动调度器、添加脚本任务、确认日志生成。
"""
import os
import time

from xxybacktest.simulation.scheduler import start_scheduler, add_script_job, get_all_jobs

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data")


def test_scheduler_full():
    start_scheduler(DATA_PATH)

    test_script = os.path.join(DATA_PATH, "_test_script.py")
    with open(test_script, "w", encoding="utf-8") as f:
        f.write("print('Hello from test script')\n")

    add_script_job("test_001", "测试脚本任务", test_script, "* * * * *", DATA_PATH)

    print("[验证] 已添加 test_001 脚本 job，等待 65 秒执行...")
    time.sleep(65)

    jobs = get_all_jobs(DATA_PATH)
    for j in jobs:
        print(
            f"[验证] job: {j['task_id']} | {j['name']} | cron={j['cron']} | "
            f"next={j['next_run_time']} | status={j['last_status']}"
        )

    log_path = os.path.join(DATA_PATH, "simulation_results", "task_logs", "test_001.log")
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            print("[验证] 日志内容:\n" + f.read())
    else:
        print("[错误] 日志文件未生成!")

    os.remove(test_script)


if __name__ == "__main__":
    test_scheduler_full()
