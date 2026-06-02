"""
APScheduler 全局单例封装

管理所有 job 的增删查执，支持外部脚本任务和 Python 函数任务两种类型。
日志按任务独立存储，每次执行覆盖写入（只保留最近一次）。
"""

import json
import os
import shutil
import subprocess
import sys
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

_scheduler = None


def _parse_cron(cron: str) -> dict:
    """将5段 cron 表达式解析为 CronTrigger 参数"""
    parts = cron.strip().split()
    if len(parts) != 5:
        raise ValueError(f"cron 表达式应为 5 段: 分 时 日 月 周, 收到: {cron}")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def _log_dir(data_path: str) -> str:
    path = os.path.join(data_path, "simulation_results", "task_logs")
    os.makedirs(path, exist_ok=True)
    return path


def _log_path(task_id: str, data_path: str) -> str:
    return os.path.join(_log_dir(data_path), f"{task_id}.log")


def _status_path(task_id: str, data_path: str) -> str:
    return os.path.join(_log_dir(data_path), f"{task_id}.status")


def _history_dir(task_id: str, data_path: str) -> str:
    path = os.path.join(_log_dir(data_path), "history", task_id)
    os.makedirs(path, exist_ok=True)
    return path


def _archive_log(task_id: str, data_path: str, log_file: str):
    """将最新日志复制到历史目录，按执行时间命名。"""
    if not os.path.exists(log_file):
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    history_file = os.path.join(_history_dir(task_id, data_path), f"{ts}.log")
    shutil.copy2(log_file, history_file)


def _write_status(task_id: str, data_path: str, status: str, exit_code: int = None):
    path = _status_path(task_id, data_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "status": status,
                "exit_code": exit_code,
                "executed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            f,
            ensure_ascii=False,
        )


def get_scheduler() -> BackgroundScheduler:
    """获取全局调度器，未初始化则创建"""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


def start_scheduler(data_path: str):
    """启动调度器，xxy-sim 启动时调用一次"""
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        print("[scheduler] APScheduler 已启动")

        # 每 30 秒自动同步 JSON 中的用户任务到当前 scheduler
        # 解决跨进程调用 schedule_task() 时热注册到错误 scheduler 的问题
        scheduler.add_job(
            sync_user_jobs,
            "interval",
            seconds=30,
            args=[data_path],
            id="__sync_user_jobs",
            replace_existing=True,
        )


def add_script_job(task_id: str, name: str, script: str, cron: str, data_path: str):
    """
    向调度器添加一个外部脚本 job（用户自定义任务）。
    cron 格式："分 时 日 月 周"（标准 5 段 cron）
    热注册：调度器运行中也可调用，立即生效。
    """
    scheduler = get_scheduler()
    log_file = _log_path(task_id, data_path)

    def _run_script():
        _write_status(task_id, data_path, "running")
        with open(log_file, "w", encoding="utf-8") as lf:
            lf.write(f"===== 任务开始: {name} ({task_id}) =====\n")
            lf.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            lf.write(f"脚本: {script}\n")
            lf.write("-" * 40 + "\n")
            lf.flush()
            try:
                result = subprocess.run(
                    [sys.executable, script],
                    stdout=lf,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )
                lf.write("-" * 40 + "\n")
                lf.write(f"退出码: {result.returncode}\n")
                if result.returncode == 0:
                    status = "success"
                    lf.write("结果: 成功\n")
                else:
                    status = "failed"
                    lf.write("结果: 失败\n")
                _write_status(task_id, data_path, status, result.returncode)
            except Exception as e:
                lf.write(f"异常: {e}\n")
                _write_status(task_id, data_path, "error")

        _archive_log(task_id, data_path, log_file)

    trigger = CronTrigger(**_parse_cron(cron))
    scheduler.add_job(
        _run_script,
        trigger=trigger,
        id=task_id,
        name=name,
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=3600,
    )


def add_func_job(task_id: str, name: str, func, cron: str, data_path: str):
    """
    向调度器添加一个 Python 函数 job（内置任务，如 run_all）。
    执行时直接调用 func()，stdout 同样重定向到日志文件。
    cron 格式与 add_script_job 相同。
    """
    scheduler = get_scheduler()
    log_file = _log_path(task_id, data_path)

    def _run_func():
        _write_status(task_id, data_path, "running")
        with open(log_file, "w", encoding="utf-8") as lf:
            with redirect_stdout(lf), redirect_stderr(lf):
                func_name = getattr(func, '__name__', None) or getattr(getattr(func, 'func', None), '__name__', str(func))
                print(f"===== 任务开始: {name} ({task_id}) =====")
                print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"函数: {func_name}")
                print("-" * 40)
                try:
                    func()
                    print("-" * 40)
                    print("结果: 成功")
                    _write_status(task_id, data_path, "success", 0)
                except Exception as e:
                    import traceback
                    print("-" * 40)
                    print(f"异常: {e}")
                    traceback.print_exc()
                    print("结果: 失败")
                    _write_status(task_id, data_path, "error", 1)

        _archive_log(task_id, data_path, log_file)

    trigger = CronTrigger(**_parse_cron(cron))
    scheduler.add_job(
        _run_func,
        trigger=trigger,
        id=task_id,
        name=name,
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=3600,
    )


def remove_job(task_id: str):
    """从调度器移除 job，热删除立即生效。"""
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(task_id)
    except Exception:
        pass


def is_job_running(task_id: str, data_path: str) -> bool:
    """检查任务是否正在执行中（通过状态文件判断）。"""
    sp = _status_path(task_id, data_path)
    if not os.path.exists(sp):
        return False
    try:
        with open(sp, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("status") == "running"
    except Exception:
        return False


def _format_job(job, data_path: str) -> dict:
    """将 APScheduler job 格式化为展示用的 dict。"""
    # 从 trigger 字段反推 cron 字符串
    cron_parts = ["*", "*", "*", "*", "*"]
    if hasattr(job.trigger, "fields"):
        field_map = {f.name: str(f) for f in job.trigger.fields}
        cron_parts = [
            field_map.get("minute", "*"),
            field_map.get("hour", "*"),
            field_map.get("day", "*"),
            field_map.get("month", "*"),
            field_map.get("day_of_week", "*"),
        ]
    cron = " ".join(cron_parts)

    next_run = job.next_run_time
    if next_run:
        next_run = next_run.strftime("%Y-%m-%d %H:%M:%S")

    # 读取上次执行状态
    last_status = "-"
    sp = _status_path(job.id, data_path)
    if os.path.exists(sp):
        try:
            with open(sp, "r", encoding="utf-8") as f:
                data = json.load(f)
                last_status = data.get("status", "-")
        except Exception:
            pass

    return {
        "task_id": job.id,
        "name": job.name,
        "cron": cron,
        "next_run_time": next_run,
        "last_status": last_status,
    }


def _read_last_status(task_id: str, data_path: str) -> str:
    """从状态文件读取任务上次执行状态。"""
    sp = _status_path(task_id, data_path)
    if not os.path.exists(sp):
        return "-"
    try:
        with open(sp, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("status", "-")
    except Exception:
        return "-"


def sync_user_jobs(data_path: str):
    """
    自动同步三类任务到当前 APScheduler：
      1. 用户脚本任务（JSON 持久化）
      2. 模拟内置任务（builtin_run_simulation）
      3. 实盘账户任务（数据库中的 running live 账户）

    解决跨进程调用 submit/schedule_task 时热注册到错误 scheduler 的问题。
    """
    from functools import partial

    scheduler = get_scheduler()
    if not scheduler.running:
        return

    existing_ids = {job.id for job in scheduler.get_jobs()}

    # ── 1. 用户脚本任务（JSON）──
    from .task_store import load_tasks
    for t in load_tasks(data_path):
        if t["task_id"] not in existing_ids:
            try:
                add_script_job(
                    t["task_id"], t["name"], t["script"], t["cron"], data_path
                )
            except Exception:
                pass

    # ── 2. 实盘账户任务（数据库）──
    try:
        from .submitter import list_accounts
        from ..live.runner import run_live

        live_accounts = [
            a for a in list_accounts(status="running", data_path=data_path)
            if a.get("account_type") == "live"
        ]
        for acc in live_accounts:
            task_id = f"live_{acc['account_id']}"
            if task_id not in existing_ids:
                try:
                    wrapped = partial(run_live, acc["account_id"], data_path)
                    cron = acc.get("trigger_cron", "30 9 * * *")
                    add_func_job(
                        task_id, f"实盘-{acc['name']}", wrapped, cron, data_path
                    )
                except Exception:
                    pass
    except Exception:
        pass


def trigger_job(task_id: str, data_path: str):
    """立即触发一次 job（手动触发）。"""
    scheduler = get_scheduler()
    job = scheduler.get_job(task_id)
    if job is None:
        # 尝试从 JSON 同步后再查找
        sync_user_jobs(data_path)
        job = scheduler.get_job(task_id)
        if job is None:
            raise ValueError(f"job {task_id} 不存在")
    if is_job_running(task_id, data_path):
        raise RuntimeError("任务正在执行中，请稍后再试")
    scheduler.modify_job(task_id, next_run_time=datetime.now())


def get_all_jobs(data_path: str) -> list:
    """
    返回所有 job 的状态列表，供 /tasks 页面展示。
    同时从 APScheduler 内存和 JSON 持久化读取，确保跨进程注册的任务也能显示。
    """
    # 先同步 JSON 中缺失的任务到当前 scheduler
    sync_user_jobs(data_path)

    scheduler = get_scheduler()
    scheduled_jobs = {job.id: job for job in scheduler.get_jobs()}

    # 延迟导入避免循环依赖
    from .task_store import load_tasks
    user_tasks = load_tasks(data_path)

    BUILTIN_ID = "builtin_run_simulation"
    result = []

    # 内置任务
    if BUILTIN_ID in scheduled_jobs:
        result.append(_format_job(scheduled_jobs[BUILTIN_ID], data_path))

    # 用户任务：JSON 中的全部显示
    for t in user_tasks:
        task_id = t["task_id"]
        if task_id in scheduled_jobs:
            result.append(_format_job(scheduled_jobs[task_id], data_path))
        else:
            # 补注册失败，只显示基本信息
            result.append({
                "task_id": task_id,
                "name": t["name"],
                "cron": t["cron"],
                "next_run_time": None,
                "last_status": _read_last_status(task_id, data_path),
            })

    # 补充其他 jobs（如实盘任务等），排除内部任务
    used_ids = {r["task_id"] for r in result}
    for job_id, job in scheduled_jobs.items():
        if job_id not in used_ids and not job_id.startswith("__"):
            result.append(_format_job(job, data_path))
            used_ids.add(job_id)

    # ── 兜底：数据库中 running 但尚未注册到 scheduler 的实盘账户 ──
    try:
        from .submitter import list_accounts
        live_accounts = [
            a for a in list_accounts(status="running", data_path=data_path)
            if a.get("account_type") == "live"
        ]
        for acc in live_accounts:
            task_id = f"live_{acc['account_id']}"
            if task_id not in used_ids:
                result.append({
                    "task_id": task_id,
                    "name": f"实盘-{acc['name']}",
                    "cron": acc.get("trigger_cron", "30 9 * * *"),
                    "next_run_time": None,
                    "last_status": _read_last_status(task_id, data_path),
                })
                used_ids.add(task_id)
    except Exception:
        pass

    return result


def get_task_history(task_id: str, data_path: str) -> list:
    """
    返回任务的历史运行记录列表。

    每条记录包含:
        - executed_at: 执行时间 (YYYY-MM-DD HH:MM:SS)
        - content: 该次执行的完整日志内容
    """
    history_dir = os.path.join(_log_dir(data_path), "history", task_id)
    if not os.path.exists(history_dir):
        return []

    records = []
    for filename in sorted(os.listdir(history_dir), reverse=True):
        if not filename.endswith(".log"):
            continue
        # 文件名格式: YYYYMMDD_HHMMSS.log
        ts = filename[:-4]
        try:
            dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
            executed_at = dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            executed_at = ts

        filepath = os.path.join(history_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            content = "[读取日志失败]"

        # 从日志内容中解析执行状态（从末尾往前找，最后的状态标记为准）
        status = "unknown"
        for line in reversed(content.splitlines()):
            line_s = line.strip()
            if "结果: 成功" in line_s:
                status = "success"
                break
            elif "结果: 失败" in line_s:
                status = "failed"
                break
            elif "异常:" in line_s:
                status = "error"
                break

        # 兜底：如果日志中有 Traceback / Error 关键字，但前面没明确标记失败，
        # 仍判定为 error（防止任务内部吞异常导致最后写了"结果: 成功"）
        if status in ("success", "unknown") and (
            "Traceback (most recent call last):" in content
            or "Error:" in content
            or "[ERROR]" in content
        ):
            status = "error"
        elif status == "unknown" and "===== 任务开始" in content:
            status = "running"

        records.append({
            "executed_at": executed_at,
            "content": content,
            "status": status,
        })

    return records
