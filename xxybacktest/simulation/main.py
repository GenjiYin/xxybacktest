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
    parser.add_argument(
        "--factor-time",
        default=None,
        help="因子分析每日重跑时间 HH:MM（默认比 --time 晚 30 分钟，因子分析依赖当天行情入库）",
    )
    return parser.parse_args()


def _plus_minutes(time_str, minutes):
    """把 HH:MM 加上若干分钟，返回 HH:MM（同日内，简单处理，超过 23:59 则封顶）。"""
    parts = time_str.split(":")
    h, m = int(parts[0]), int(parts[1])
    total = h * 60 + m + minutes
    total = min(total, 23 * 60 + 59)
    return f"{total // 60:02d}:{total % 60:02d}"


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
    """注册内置任务：每日模拟交易。使用包装函数，每次执行时自动 reload 最新代码。"""
    from xxybacktest.simulation.scheduler import add_func_job

    parts = time_str.split(":")
    h = int(parts[0])
    m = int(parts[1])
    cron = f"{m} {h} * * *"

    def _run_all_wrapper():
        import importlib
        import xxybacktest.simulation.runner as _sim_runner
        importlib.reload(_sim_runner)
        return _sim_runner.run_all(data_path=data_path)

    add_func_job("builtin_run_simulation", "模拟交易", _run_all_wrapper, cron, data_path)
    print(f"[内置任务] 模拟交易 已注册，触发时间: {time_str} (cron: {cron})")


def _register_live_jobs(data_path):
    """注册实盘任务：为每个运行中的实盘账户注册独立 cron job。使用包装函数，每次执行时自动 reload 最新代码。"""
    from xxybacktest.simulation.scheduler import add_func_job
    from xxybacktest.simulation.submitter import list_accounts

    accounts = list_accounts(status='running', data_path=data_path)
    live_accounts = [a for a in accounts if a.get('account_type') == 'live']

    if not live_accounts:
        return

    print(f"[实盘任务] 发现 {len(live_accounts)} 个运行中实盘账户")

    for acc in live_accounts:
        account_id = acc['account_id']
        task_id = f"live_{account_id}"
        name = f"实盘-{acc['name']}"
        cron = acc.get('trigger_cron', '30 9 * * *')

        def _make_live_runner(aid, dp):
            def _run():
                import importlib
                import xxybacktest.live.runner as _live_runner
                importlib.reload(_live_runner)
                return _live_runner.run_live(aid, dp)
            return _run

        wrapped = _make_live_runner(account_id, data_path)
        add_func_job(task_id, name, wrapped, cron, data_path)
        print(f"  [{task_id}] {name}  cron: {cron}")


def _register_factor_job(data_path, time_str):
    """注册内置任务：每日因子分析全量重跑。用包装函数每次 reload 最新代码。

    因子分析依赖当天行情已入库, 触发时间应晚于模拟交易。定时线程内用串行
    run_single(逐个因子)而非 ProcessPoolExecutor, 避免调度线程内 spawn 子进程。
    """
    from xxybacktest.simulation.scheduler import add_func_job

    parts = time_str.split(":")
    h, m = int(parts[0]), int(parts[1])
    cron = f"{m} {h} * * *"

    def _run_factors_wrapper():
        import importlib
        import xxybacktest.factor.runner as _f_runner
        import xxybacktest.factor.submitter as _f_sub
        importlib.reload(_f_runner)
        ids = [meta["factor_id"] for meta in _f_sub.list_factors(data_path)]
        if not ids:
            print("[因子分析] 无已登记因子, 跳过")
            return
        print(f"[因子分析] 开始全量重跑 {len(ids)} 个因子")
        ok = 0
        for fid in ids:
            r = _f_runner.run_single(fid, data_path=data_path)
            tag = "✓" if r["status"] == "success" else "✗"
            print(f"  [{tag}] {fid}  {r.get('reason', '')}")
            ok += (r["status"] == "success")
        print(f"[因子分析] 完成: 成功 {ok}, 失败 {len(ids) - ok}")

    add_func_job("builtin_run_factors", "因子分析", _run_factors_wrapper, cron, data_path)
    print(f"[内置任务] 因子分析 已注册，触发时间: {time_str} (cron: {cron})")


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

    # 注册实盘任务
    _register_live_jobs(data_path)

    # 因子分析不再每日定时全量重跑(开销大)。改为在因子看板逐个手动"更新"。
    # 如需恢复定时任务, 取消下面两行注释即可(_register_factor_job 函数仍保留)。
    # factor_time = args.factor_time or _plus_minutes(args.time, 30)
    # _register_factor_job(data_path, factor_time)

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
