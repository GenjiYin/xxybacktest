"""
模拟交易服务入口函数

供 console_scripts 调用（xxy-sim 命令）以及 run_simulation.py 脚本使用。
"""

import argparse
import os
import sys


def _parse_args():
    parser = argparse.ArgumentParser(description="模拟交易服务")
    parser.add_argument(
        "--data",
        default="./data",
        help="行情数据目录路径（默认: ./data）",
    )
    parser.add_argument(
        "--time",
        default="22:00",
        help="每日触发时间，格式 HH:MM（默认: 22:00）",
    )
    return parser.parse_args()


def _validate_time(time_str):
    """校验时间格式 HH:MM 或兼容旧版 HH:MM:SS"""
    parts = time_str.split(":")
    if len(parts) == 3:
        # 兼容旧版 HH:MM:SS，忽略秒
        parts = parts[:2]
    if len(parts) != 2:
        raise ValueError(f"时间格式错误: '{time_str}'，应为 HH:MM（例如 22:00）")
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(f"时间格式错误: '{time_str}'，应为 HH:MM（例如 22:00）")
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"时间超出范围: '{time_str}'")


def _register_builtin_jobs(data_path, time_str):
    """注册内置任务：每日模拟交易"""
    from xxybacktest.simulation.scheduler import add_func_job
    from xxybacktest.simulation.runner import run_all

    parts = time_str.split(":")
    h = int(parts[0])
    m = int(parts[1])
    cron = f"{m} {h} * * *"

    add_func_job("builtin_run_simulation", "模拟交易", run_all, cron, data_path)
    print(f"[内置任务] 模拟交易 已注册，触发时间: {time_str} (cron: {cron})")


def main():
    args = _parse_args()

    try:
        _validate_time(args.time)
    except ValueError as e:
        print(f"[错误] {e}")
        sys.exit(1)

    data_path = os.path.abspath(args.data)

    # 环境变量（runner 等模块可能依赖）
    os.environ["XXY_DATA_PATH"] = data_path
    os.environ["XXY_TRIGGER_TIME"] = args.time

    # 启动 APScheduler
    from xxybacktest.simulation.scheduler import start_scheduler, add_script_job
    from xxybacktest.simulation.task_store import load_tasks
    start_scheduler(data_path)

    # 注册内置任务
    _register_builtin_jobs(data_path, args.time)

    # 加载用户任务
    user_tasks = load_tasks(data_path)
    for t in user_tasks:
        add_script_job(t["task_id"], t["name"], t["script"], t["cron"], data_path)
    if user_tasks:
        print(f"[定时任务] 已加载 {len(user_tasks)} 个用户任务")

    print("=" * 50)
    print("模拟交易系统已启动")
    print("=" * 50)
    print(f"数据目录:     {data_path}")
    print(f"每日触发时间: {args.time}")
    print("-" * 50)
    print("Web 界面: http://localhost:5000")
    print("=" * 50)

    # 启动 Flask（主线程，阻塞）
    from xxybacktest.web.app import create_app
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
