"""
模拟交易服务入口函数

供 console_scripts 调用（xxy-sim 命令）以及 run_simulation.py 脚本使用。
"""

import argparse
import os
import sys
import threading


def _parse_args():
    parser = argparse.ArgumentParser(description="模拟交易服务")
    parser.add_argument(
        "--data",
        default="./data",
        help="行情数据目录路径（默认: ./data）",
    )
    parser.add_argument(
        "--data-renew",
        default="./data_renew.py",
        dest="data_renew",
        help="数据更新脚本路径（默认: ./data_renew.py）",
    )
    parser.add_argument(
        "--time",
        default="22:00:00",
        help="每日触发时间，格式 HH:MM:SS（默认: 22:00:00）",
    )
    return parser.parse_args()


def _validate_time(time_str):
    """校验时间格式 HH:MM:SS"""
    parts = time_str.split(":")
    if len(parts) != 3:
        raise ValueError(f"时间格式错误: '{time_str}'，应为 HH:MM:SS（例如 22:00:00）")
    try:
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        raise ValueError(f"时间格式错误: '{time_str}'，应为 HH:MM:SS（例如 22:00:00）")
    if not (0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59):
        raise ValueError(f"时间超出范围: '{time_str}'")


def _run_flask():
    """在后台线程运行 Flask"""
    from xxybacktest.web.app import create_app
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)


def main():
    args = _parse_args()

    try:
        _validate_time(args.time)
    except ValueError as e:
        print(f"[错误] {e}")
        sys.exit(1)

    # 将参数写入环境变量，pipeline.py 在 import 时会读取
    os.environ["XXY_DATA_PATH"] = os.path.abspath(args.data)
    os.environ["XXY_DATA_RENEW"] = os.path.abspath(args.data_renew)
    os.environ["XXY_TRIGGER_TIME"] = args.time

    # 必须在设置环境变量之后再 import pipeline
    import xxybacktest.simulation.pipeline  # noqa: F401 - 注册 Pipeline

    import uvicorn
    from plombery import get_app as get_plombery_app

    print("=" * 50)
    print("模拟交易系统已启动")
    print("=" * 50)
    print(f"数据目录:     {os.environ['XXY_DATA_PATH']}")
    print(f"更新脚本:     {os.environ['XXY_DATA_RENEW']}")
    print(f"每日触发时间: {os.environ['XXY_TRIGGER_TIME']}")
    print("-" * 50)
    print("Web 界面: http://localhost:5000")
    print("任务面板: http://localhost:8000")
    print("=" * 50)

    # 启动 Flask（后台线程）
    flask_thread = threading.Thread(target=_run_flask, daemon=True)
    flask_thread.start()

    # 启动 Plombery（主线程）
    uvicorn.run(
        get_plombery_app(),
        host="0.0.0.0",
        port=8000,
    )
