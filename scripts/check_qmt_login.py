"""
scripts/check_qmt_login.py — 检测 QMT 客户端是否已登录

用法:
    python scripts/check_qmt_login.py --qmt "D:/QMT/bin.x64" --account "88888888"
"""

import argparse
import random
import sys

try:
    from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
    from xtquant.xttype import StockAccount
    _XTQUANT_AVAILABLE = True
except ImportError:
    _XTQUANT_AVAILABLE = False


def check(qmt_path: str, account_id: str) -> bool:
    """快速检测 QMT 是否已登录（只做一次连接尝试，不重试）"""
    if not _XTQUANT_AVAILABLE:
        print("[结果] xtquant 未安装")
        print("        请从 QMT 客户端目录安装：pip install <QMT目录>/userdata/xtquant")
        return False

    session_id = random.randint(100000, 999999)
    trader = None

    try:
        print(f"[步骤1] 创建 XtQuantTrader (session={session_id})")
        trader = XtQuantTrader(qmt_path, session_id)

        callback = XtQuantTraderCallback()
        trader.register_callback(callback)

        print("[步骤2] 启动 trader...")
        trader.start()

        print("[步骤3] 连接...")
        ret = trader.connect()
        if ret != 0:
            print(f"[结果] connect() 返回 {ret}，连接失败")
            print("        → QMT 客户端可能未启动或未登录")
            return False

        print("[步骤4] 查询账户资产（验证登录状态）...")
        acc = StockAccount(account_id, 'STOCK')
        asset = trader.query_stock_asset(acc)

        if asset is None:
            print("[结果] query_stock_asset 返回 None")
            print("        → 已连接到 QMT，但该资金账号未登录或未订阅")
            return False

        print("[结果] QMT 已登录，账号可用")
        print(f"        可用资金: {asset.cash:,.2f}")
        print(f"        总资产:   {asset.total_asset:,.2f}")
        return True

    except Exception as e:
        print(f"[结果] 异常: {e}")
        return False

    finally:
        if trader is not None:
            try:
                print("[清理] 断开连接...")
                trader.stop()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="检测 QMT 客户端是否已登录")
    parser.add_argument("--qmt", required=True, help="QMT 安装目录（含 XtQuantClient 的目录）")
    parser.add_argument("--account", required=True, help="QMT 资金账号")
    args = parser.parse_args()

    ok = check(args.qmt, args.account)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
