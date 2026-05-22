"""
测试：用 order_target_percent 把某只 ETF 调到总资产的 1%

运行：python tests/test_order_target_percent.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.live.trader import QMTTrader
from xxybacktest.live.context import create_live_context
from xxybacktest.live.trading import order_target_percent

QMT_PATH   = r"D:\国金QMT交易端模拟\userdata_mini"
ACCOUNT_ID = "86962531"

ACCOUNT_CONFIG = {
    "account_id":   ACCOUNT_ID,
    "name":         "测试实盘账户",
    "initial_cash": 1000000.0,
    "start_date":   "2024-01-01",
    "data_path":    r"D:\Desktop\最新回测框架\data",
    "asset_type":   "stock",
    "benchmark":    "000300.SH",
}

if __name__ == "__main__":
    print("[1/4] 连接 QMT 模拟盘 ...")
    trader = QMTTrader(QMT_PATH, ACCOUNT_ID)

    print("[2/4] 构建 context ...")
    ctx = create_live_context(ACCOUNT_CONFIG, trader)

    code = "159941.SZ"
    percent = 0.01  # 目标占总资产的 1%

    print(f"[3/4] 查询当前持仓 ...")
    pos = trader.get_position(code)
    current_vol = pos['volume'] if pos else 0
    print(f"       {code} 当前持仓: {current_vol} 股")

    total_asset = trader.get_portfolio()['total_asset']
    target_value = total_asset * percent
    price = trader.get_price(code)
    target_vol = int(target_value / price // 100 * 100) if price else 0
    expected_change = target_vol - current_vol

    print(f"[4/4] order_target_percent({code}, {percent})")
    print(f"       总资产: {total_asset:,.2f}")
    print(f"       目标市值: {target_value:,.2f} ({percent:.1%})")
    print(f"       最新价: {price}")
    print(f"       目标股数: {target_vol} 股")
    print(f"       预计差值: {expected_change} 股")

    result = order_target_percent(code, 0, ctx)

    print(f"\n结果:")
    if result is None:
        print("  无需调仓（目标与当前持仓一致）")
    else:
        print(f"  订单对象: {result}")
        print(f"  方向: {'买入' if result.is_buy else '卖出'}")
        print(f"  数量: {result.amount} 股")
        print(f"  状态: {'成功' if result.status == 1 else '失败'}")

    print(f"\n[完成] 请检查 QMT 客户端确认委托。")
    trader.disconnect()
