"""
测试：买入一手贵州茅台（600519.SH）

运行：python tests/test_buy_maotai.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.live.trader import QMTTrader
from xxybacktest.live.context import create_live_context
from xxybacktest.live.trading import order_buy

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

    print(f"[3/4] 查询 {code} 最新价 ...")
    price = trader.get_price(code)
    print(f"       最新价: {price}")

    print(f"[4/4] 买入 100 股 {code} ...")
    result = order_buy(code, 100, ctx)

    print(f"\n结果:")
    print(f"  订单对象: {result}")
    print(f"  状态: {'成功' if result.status == 1 else '失败'}")
    print(f"  日期: {result.date}")
    print(f"  context.logs.order_list 数量: {len(ctx.logs.order_list)}")

    print("\n[完成] 请检查 QMT 客户端确认委托是否提交。")

    trader.disconnect()
