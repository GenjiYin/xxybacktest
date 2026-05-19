"""
用户任务持久化管理

将用户通过 schedule_task() 注册的任务持久化到 JSON 文件，
xxy-sim 启动时调用 load_tasks() 恢复，支持热注册和热删除。
"""

import json
import os
import random
import shutil
import string
from datetime import datetime

from apscheduler.triggers.cron import CronTrigger

from .scheduler import add_script_job, remove_job


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _time_to_cron(time_str: str) -> str:
    """time="17:30" → cron="30 17 * * *" """
    parts = time_str.split(":")
    if len(parts) != 2:
        raise ValueError(f"time 格式错误: '{time_str}'，应为 HH:MM")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"time 超出范围: '{time_str}'")
    return f"{m} {h} * * *"


def _gen_task_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"task_{ts}_{rand}"


def _tasks_path(data_path: str) -> str:
    path = os.path.join(data_path, "simulation_results", "scheduled_tasks.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _load_raw(data_path: str) -> list:
    path = _tasks_path(data_path)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception):
        return []


def _save_raw(data_path: str, tasks: list):
    path = _tasks_path(data_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)


def _validate_cron(cron: str):
    """校验 cron 表达式合法性"""
    try:
        parts = cron.strip().split()
        if len(parts) != 5:
            raise ValueError("cron 表达式应为 5 段")
        CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )
    except Exception as e:
        raise ValueError(f"cron 表达式无效: {cron} — {e}")


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------

def schedule_task(
    name: str,
    script: str,
    time: str = None,
    cron: str = None,
    data_path: str = "./data",
) -> str:
    """
    注册一个定时脚本任务。
    - 写入 JSON 持久化
    - 如果调度器已启动（xxy-sim 运行中），立即热注册到 APScheduler
    - 返回 task_id
    """
    if not name or not script:
        raise ValueError("name 和 script 不能为空")

    if time is None and cron is None:
        raise ValueError("time 和 cron 必须指定一个")
    if time is not None and cron is not None:
        raise ValueError("time 和 cron 只能指定一个")

    if time is not None:
        cron = _time_to_cron(time)

    _validate_cron(cron)

    # 脚本路径绝对化
    script = os.path.abspath(script)
    if not os.path.exists(script):
        raise FileNotFoundError(f"脚本不存在: {script}")

    tasks = _load_raw(data_path)

    # 防重：相同 name + script + cron 不再重复添加
    for t in tasks:
        if t["name"] == name and t["script"] == script and t["cron"] == cron:
            # 如果调度器已启动但 job 不在其中，补注册一次
            try:
                add_script_job(t["task_id"], t["name"], t["script"], t["cron"], data_path)
            except Exception:
                pass
            return t["task_id"]

    task_id = _gen_task_id()
    tasks.append(
        {
            "task_id": task_id,
            "name": name,
            "script": script,
            "cron": cron,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    _save_raw(data_path, tasks)

    # 热注册到 APScheduler（调度器未启动时可能抛异常，忽略即可）
    try:
        add_script_job(task_id, name, script, cron, data_path)
    except Exception:
        pass

    return task_id


def load_tasks(data_path: str = "./data") -> list:
    """读取所有已注册的用户任务，xxy-sim 启动时调用。"""
    return _load_raw(data_path)


def remove_task(task_id: str, data_path: str = "./data") -> bool:
    """
    删除指定任务。
    - 从 JSON 中移除
    - 如果调度器已启动，立即从 APScheduler 热删除
    - 同时删除该任务的所有日志和历史记录
    """
    tasks = _load_raw(data_path)
    new_tasks = [t for t in tasks if t["task_id"] != task_id]
    if len(new_tasks) == len(tasks):
        return False

    _save_raw(data_path, new_tasks)
    remove_job(task_id)

    # 清理日志文件
    log_dir = os.path.join(data_path, "simulation_results", "task_logs")
    for ext in [".log", ".status"]:
        path = os.path.join(log_dir, f"{task_id}{ext}")
        if os.path.exists(path):
            os.remove(path)

    # 清理历史日志目录
    history_dir = os.path.join(log_dir, "history", task_id)
    if os.path.exists(history_dir):
        shutil.rmtree(history_dir)

    return True
