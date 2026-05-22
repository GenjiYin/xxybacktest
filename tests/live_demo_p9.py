#!/usr/bin/env python3
"""
P9 实盘集成测试 — 买卖双向，一次提交，全量覆盖

策略逻辑：
  - 510050.SH 有仓位 → 全仓卖出（target=0）
  - 510050.SH 无仓位 → 买入（target=3%）
  交替执行，同时测试买和卖两个方向。

策略函数里的所有 print 会被 scheduler 捕获到任务日志，
明天 9:31 触发后在 Web 日志详情页就能看到全部执行过程。

运行前提：
  - QMT 客户端已启动并登录
  - 已执行 pip install -e .

运行方式：
  python tests/live_demo_p9.py

提交后必须启动 Web 服务：
  xxy-sim --data "D:\Desktop\最新回测框架\data"
  （如果已在运行，需要重启才能加载新账户）

明天验证方式：
  1. Web → 定时任务 → 找到 "实盘-P9-全量覆盖" → 日志详情
  2. 日志中应出现：
     - [P9] initialize ... （策略初始化）
     - [P9] handle_data ... （每日调仓）
     - [P9] 实时资金 / 实时持仓 ... （get_portfolio / get_account_positions）
     - [P9] 当前有/无 510050.SH 仓位 → 买入/卖出 ... （order_target_percent）
     - [实盘存储] daily: X, positions: Y, orders: Z （结果保存）
     - [实盘调仓完成] ... （runner 收尾）
  3. QMT 委托记录有 510050.SH 的买入/卖出委托
  4. data/live/accounts/{account_id}/ 下有三个 parquet 文件
  5. Web 账户详情页能看到净值/持仓/订单
  6. 后天 9:31 第二次触发应反向操作（买入→卖出 或 卖出→买入）
"""

import os
import sys

import pandas as pd

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
DATA_PATH = r"D:\Desktop\最新回测框架\data"
QMT_PATH = r"D:\国金证券QMT交易端\userdata_mini"
LIVE_ACCOUNT_ID = "8881686799"

TARGET_CODE = "510050.SH"   # 上证50ETF，价格低、流动性好
TARGET_PCT = 0.03            # 目标仓位 3%，金额很小

# ---------------------------------------------------------------------------
# 策略函数 — 每个 print 都会进入任务日志
# ---------------------------------------------------------------------------

def initialize(context):
    """初始化：记录运行次数、设置目标参数。

    所有配置直接硬编码在函数内部，不依赖外部全局变量。
    """
    context.g.setdefault("run_count", 0)
    context.g["target_pct"] = 0.03
    context.g["target_code"] = "510050.SH"
    print("[P9] initialize: 目标标的=510050.SH, 目标仓位=3%")


def handle_data(context):
    """
    每日调仓：测试买卖双向。
    有仓位 → 全仓卖出，无仓位 → 买入。
    每条 print 都会进入任务日志，明天看日志即可判断是否正常。
    """
    context.g["run_count"] += 1
    count = context.g["run_count"]
    target_code = context.g.get("target_code", "510050.SH")
    target_pct = context.g.get("target_pct", 0.03)

    print(f"\n{'='*50}")
    print(f"[P9] handle_data 第 {count} 次执行")
    print(f"{'='*50}")

    # ---- P9-1: get_portfolio (context 内刷新) ----
    print("[P9] 测试 get_portfolio()")
    pf = context.get_portfolio()
    print(f"  cash={pf['cash']:,.2f}, frozen={pf['frozen_cash']:,.2f}, "
          f"market={pf['market_value']:,.2f}, total={pf['total_asset']:,.2f}")

    # ---- P9-2: get_account_positions (context 内刷新) ----
    print("[P9] 测试 get_account_positions()")
    positions = context.get_account_positions()
    print(f"  持仓数: {len(positions)}")
    for code, pos in positions.items():
        print(f"  {code}: {pos['volume']}股, 可卖={pos['can_sell_volume']}, "
              f"成本={pos['cost_price']:.3f}, 最新={pos['last_price']:.3f}")

    # ---- P9-3: order_target_percent (买卖双向测试) ----
    has_position = (target_code in context.portfolio.positions
                    and context.portfolio.positions[target_code].amount > 0)

    if has_position:
        target = 0.0
        action = "卖出"
    else:
        target = target_pct
        action = "买入"

    print(f"[P9] 当前{'有' if has_position else '无'} {target_code} 仓位 → {action} (target={target})")
    order = context.order_target_percent(target_code, target)
    if order:
        print(f"  委托结果: code={order.code}, amount={order.amount}, "
              f"is_buy={order.is_buy}, status={order.status}")
    else:
        print("  无需调仓，返回 None")

    # ---- P9-4: inout_cash (实盘应被忽略) ----
    print("[P9] 测试 inout_cash(10000) — 实盘不支持，应被忽略")
    context.inout_cash(10000)

    print(f"[P9] handle_data 完成，本次共产生 {len(context.logs.order_list)} 条订单")
    print(f"{'='*50}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    from xxybacktest.simulation.submitter import submit, get_account

    print("=" * 60)
    print("P9 实盘集成测试 — 买卖双向，一次提交，全量覆盖")
    print("=" * 60)
    print(f"数据路径: {DATA_PATH}")
    print(f"QMT 路径: {QMT_PATH}")
    print(f"资金账号: {LIVE_ACCOUNT_ID}")
    print(f"目标标的: {TARGET_CODE}")
    print(f"策略逻辑: 有仓位→卖出, 无仓位→买入 {TARGET_PCT * 100:.0f}%")
    print("=" * 60)

    # ---- 提交实盘账户 ----
    print("\n>>> 提交实盘账户（submit 内部连接 QMT 读取总资产）")
    try:
        account_id = submit(
            name="P9-全量覆盖",
            initialize=initialize,
            handle_data=handle_data,
            account_type="live",
            live_account_id=LIVE_ACCOUNT_ID,
            qmt_path=QMT_PATH,
            data_path=DATA_PATH,
            trigger_cron="31 9 * * *",
            execution_mode="daily",
            asset_type="stock",
            benchmark="000001.SH",
        )
    except Exception as e:
        print(f"[错误] 提交失败: {e}")
        sys.exit(1)

    # ---- 验证 initial_cash ----
    acc = get_account(account_id, DATA_PATH)
    print(f"\n  账户: {acc['account_id']} ({acc['name']})")
    print(f"  initial_cash: {acc['initial_cash']:,.2f} ← 从 QMT 自动读取")
    print(f"  trigger_cron: {acc['trigger_cron']}")
    print(f"  status: {acc['status']}")

    # ---- 收尾 ----
    print("\n" + "=" * 60)
    print("提交完成。明天 9:31 自动触发，看任务日志即可验证全部 P9 项。")
    print("=" * 60)
    print(f"\n  account_id: {account_id}")
    print("\n  必须操作：")
    print(f'    xxy-sim --data "{DATA_PATH}"')
    print("  （已在运行则需重启才能加载新账户）")
    print("\n  明天验证：")
    print("    1. Web → 定时任务 → 日志详情，搜索 [P9] 关键字")
    print("    2. QMT 委托记录有 510050.SH 的买入/卖出委托")
    print(f"    3. {os.path.join(DATA_PATH, 'live', 'accounts', account_id)} 下有三个 parquet")
    print(f"    4. Web 账户详情页显示净值/持仓/订单")
    print("    5. 后天 9:31 第二次触发应反向操作（买入→卖出）")
    print("=" * 60)


if __name__ == "__main__":
    main()
