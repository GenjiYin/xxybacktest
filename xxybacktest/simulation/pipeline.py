"""
每日模拟交易更新 Pipeline - 阶段四

Pipeline:
    Task 1: update_market_data  → 执行数据更新脚本更新行情数据
    Task 2: run_simulation      → 对所有账户重跑回测并存库

触发时间: 由启动参数 --time 指定（默认每天 22:00:00，Asia/Shanghai）
"""

import asyncio
import functools
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from apscheduler.triggers.cron import CronTrigger
from plombery import get_logger, register_pipeline, task, Trigger


def _get_data_path() -> str:
    return os.environ.get("XXY_DATA_PATH", str(Path(__file__).parent.parent.parent / "data"))


def _get_data_renew_path() -> str:
    return os.environ.get("XXY_DATA_RENEW", str(Path(__file__).parent.parent.parent / "data_renew.py"))


def _parse_trigger_time() -> tuple:
    """解析触发时间环境变量，返回 (hour, minute, second)"""
    time_str = os.environ.get("XXY_TRIGGER_TIME", "22:00:00")
    parts = time_str.split(":")
    return int(parts[0]), int(parts[1]), int(parts[2])


@task
async def update_market_data():
    """执行数据更新脚本更新行情数据，失败则阻断后续任务"""
    logger = get_logger()

    script_path = Path(_get_data_renew_path())
    logger.info(f"数据更新脚本: {script_path}")

    if not script_path.exists():
        raise FileNotFoundError(
            f"未找到数据更新脚本: {script_path}\n"
            "请通过 --data-renew 参数指定脚本路径"
        )

    logger.info("开始执行数据更新脚本...")

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(script_path.parent),
    )

    # 实时捕获并转发脚本输出
    async for line in proc.stdout:
        text = line.decode("utf-8", errors="replace").rstrip()
        if text:
            logger.info(f"[data_renew] {text}")

    await proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(
            f"数据更新脚本执行失败，退出码: {proc.returncode}"
        )

    logger.info("数据更新脚本执行完成")
    return {"status": "success", "script": str(script_path)}


@task
async def run_simulation():
    """重跑所有 running 账户的回测并存库"""
    from xxybacktest.simulation.runner import run_all

    logger = get_logger()
    data_path = _get_data_path()
    logger.info(f"数据目录: {data_path}")
    logger.info("数据已就绪，开始批量模拟交易...")

    end_date = datetime.now().strftime("%Y-%m-%d")

    start = time.time()
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(
        None, functools.partial(run_all, end_date, data_path)
    )
    elapsed = time.time() - start

    success_count = sum(1 for r in results if r.get("status") == "success")
    failed_count = sum(1 for r in results if r.get("status") == "error")
    total_orders = sum(
        r.get("orders_count", 0)
        for r in results
        if r.get("status") == "success"
    )

    logger.info(f"批量模拟完成: {success_count}/{len(results)} 账户成功")
    if failed_count:
        logger.warning(f"失败账户数: {failed_count}")

    return {
        "status": "success",
        "date": end_date,
        "accounts_total": len(results),
        "accounts_success": success_count,
        "accounts_failed": failed_count,
        "orders_total": total_orders,
        "execution_time_sec": round(elapsed, 2),
        "details": [
            {
                "account_id": r.get("account_id"),
                "status": r.get("status"),
                "final_nav": (
                    round(r.get("final_nav", 1.0), 4)
                    if r.get("status") == "success"
                    else None
                ),
                "reason": r.get("reason") if r.get("status") != "success" else None,
            }
            for r in results
        ],
    }


_hour, _minute, _second = _parse_trigger_time()

register_pipeline(
    id="daily_simulation",
    name="每日模拟交易更新",
    description="每天定时自动更新行情数据并重跑所有模拟账户回测",
    tasks=[update_market_data, run_simulation],
    triggers=[
        Trigger(
            id="daily_trigger",
            name=f"每天 {os.environ.get('XXY_TRIGGER_TIME', '22:00:00')}",
            schedule=CronTrigger(
                hour=_hour,
                minute=_minute,
                second=_second,
                timezone="Asia/Shanghai",
            ),
        )
    ],
)
