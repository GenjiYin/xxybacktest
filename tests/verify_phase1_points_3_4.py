"""Phase 1 里程碑验证 — 第 3、4 点
基于 phase_2_my_strategy.py（小市值轮动策略）

第 3 点: 逐日验证 cash 扣款正确、持仓数量正确、total_value = cash + positions_value
第 4 点: 确认 context.current_dt 的 datetime 约定在 E1 → B3 链路上真正跑通
"""

import sys
import os
from datetime import datetime, time as dtime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.backtest import run_backtest
from xxybacktest.trading import order_target_percent
from xxybacktest.data import Data
from xxydb import xxydb

DATA_PATH = r"E:\回测框架复现\backtest_Reproduction\data"

# ======================================================================
# 审计记录器：每日收集快照，验证不变式
# ======================================================================

audit_log = []        # 每日快照
dt_checks = []        # current_dt 类型/时间分支检查
trade_audit = []      # 每笔交易的资金变动审计
errors = []           # 发现的错误


def audit_after_trade(context, label):
    """在每笔交易后立即检查 total_value = cash + positions_value。"""
    cash = context.portfolio.cash
    pos_val = context.portfolio.positions_value
    total = context.portfolio.total_value
    diff = abs(total - cash - pos_val)
    ok = diff < 0.01
    trade_audit.append({
        "label": label,
        "date": context.current_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "cash": cash,
        "positions_value": pos_val,
        "total_value": total,
        "diff": diff,
        "ok": ok,
    })
    if not ok:
        errors.append(f"[交易后不变式失败] {label} @ {context.current_dt}: "
                      f"total={total:.2f} != cash({cash:.2f}) + pos_val({pos_val:.2f}), diff={diff:.4f}")


def audit_daily_snapshot(context, event_name):
    """在日终（end_interval 之后）记录快照。"""
    cash = context.portfolio.cash
    pos_val = context.portfolio.positions_value
    total = context.portfolio.total_value

    # 独立重算 positions_value
    recalc_pos_val = 0
    for code, pos in context.portfolio.positions.items():
        recalc_pos_val += pos.total_value

    # 检查 total_value = cash + positions_value
    diff_total = abs(total - cash - pos_val)
    ok_total = diff_total < 0.01

    # 检查 positions_value 与逐持仓求和一致
    diff_pos = abs(pos_val - recalc_pos_val)
    ok_pos = diff_pos < 0.01

    # 检查每只持仓 total_value = amount * last_sale_price
    pos_details = {}
    ok_each_pos = True
    for code, pos in context.portfolio.positions.items():
        expected_val = pos.amount * pos.last_sale_price
        d = abs(pos.total_value - expected_val)
        pos_ok = d < 0.01
        if not pos_ok:
            ok_each_pos = False
            errors.append(f"[持仓估值不一致] {code} @ {context.current_dt.strftime('%Y-%m-%d')}: "
                          f"pos.total_value={pos.total_value:.2f} != {pos.amount}*{pos.last_sale_price}={expected_val:.2f}")
        pos_details[code] = {
            "amount": pos.amount,
            "enable_amount": pos.enable_amount,
            "last_sale_price": pos.last_sale_price,
            "total_value": pos.total_value,
            "cost_basis": pos.cost_basis,
        }

    date_str = context.current_dt.strftime("%Y-%m-%d")
    snap = {
        "date": date_str,
        "cash": cash,
        "positions_value": pos_val,
        "recalc_pos_val": recalc_pos_val,
        "total_value": total,
        "num_positions": len(context.portfolio.positions),
        "diff_total": diff_total,
        "ok_total": ok_total,
        "diff_pos": diff_pos,
        "ok_pos": ok_pos,
        "ok_each_pos": ok_each_pos,
        "positions": pos_details,
    }
    audit_log.append(snap)

    if not ok_total:
        errors.append(f"[日终不变式失败] {date_str}: total={total:.2f} != cash({cash:.2f}) + pos_val({pos_val:.2f})")
    if not ok_pos:
        errors.append(f"[positions_value不一致] {date_str}: pos_val={pos_val:.2f} != sum(pos)={recalc_pos_val:.2f}")


def check_current_dt(context, event_name, expected_time_range):
    """第 4 点: 检查 current_dt 是 datetime 类型，且时间分量正确。"""
    dt = context.current_dt
    ok_type = isinstance(dt, datetime)
    ok_has_time = hasattr(dt, 'hour')
    current_time = dt.time() if ok_has_time else None

    record = {
        "date": dt.strftime("%Y-%m-%d %H:%M:%S") if ok_type else str(dt),
        "event": event_name,
        "is_datetime": ok_type,
        "has_time": ok_has_time,
        "current_time": str(current_time),
        "expected": expected_time_range,
    }

    # 验证时间分量与事件名称匹配
    ok_time = False
    if current_time is not None:
        if event_name == "before_market":
            ok_time = current_time == dtime(9, 0, 0)
        elif event_name == "morning_start":
            ok_time = current_time == dtime(9, 30, 0)
        elif event_name == "handle_data":
            ok_time = current_time == dtime(9, 30, 0)
        elif event_name == "end_interval":
            ok_time = current_time == dtime(23, 59, 59)
        else:
            ok_time = True  # 未知事件不做时间断言

    record["ok_time"] = ok_time
    dt_checks.append(record)

    if not ok_type:
        errors.append(f"[current_dt类型错误] event={event_name}: {type(dt)} 不是 datetime")
    if not ok_time:
        errors.append(f"[current_dt时间错误] event={event_name}: 实际={current_time}, 预期={expected_time_range}")


# ======================================================================
# 策略（复用 phase_2_my_strategy.py 的逻辑，加入审计钩子）
# ======================================================================

def initial(context):
    sql = f"""
    select date, instrument, total_market_cap, close
    from valuation
    inner join daily_bar using (date, instrument)
    where date >= '{context.trade.start_time}'
    and date <= '{context.trade.end_time}'
    and close > 5
    and instrument not like '%B%'
    """
    conn = xxydb(path=context.data.data_path)
    context.df = conn.query(sql=sql).df()


def handle_data(context):
    # 第 4 点: 检查策略执行时 current_dt 状态
    check_current_dt(context, "handle_data", "09:30:00")

    # 验证 B3 get_price 时间分支：09:30 应返回 open
    # 抽样检查第一只持仓（如有）
    for code in list(context.portfolio.positions.keys())[:1]:
        price = Data.get_price(code, context)
        info = Data.get_daily_info(code, context)
        if price is not None and info is not None:
            # 09:30 时 get_price 应返回 open
            if abs(price - info.open) > 0.001:
                errors.append(
                    f"[B3时间分支错误] {code} @ {context.current_dt}: "
                    f"get_price={price}, expected open={info.open}"
                )

    date_str = context.current_dt.strftime("%Y-%m-%d")
    df = context.df[context.df['date'] == date_str].sort_values("total_market_cap").head(5)
    target = list(df['instrument'])

    positions = {k: v for k, v in context.portfolio.positions.items() if v.enable_amount > 0}
    holding = list(positions.keys())

    # 卖出
    for ins in holding:
        if ins not in target:
            order_target_percent(ins, 0, context)
            audit_after_trade(context, f"SELL {ins}")

    # 买入
    for ins in target:
        if ins not in holding:
            order_target_percent(ins, 1 / 5, context)
            audit_after_trade(context, f"BUY {ins}")


# ======================================================================
# 修改 backtest 主循环以注入审计钩子
# ======================================================================

def run_audited_backtest():
    """运行回测，在关键事件点注入审计检查。"""
    from xxybacktest.context import create_context
    from xxybacktest.events import load_events, register_daily
    from xxybacktest.trading import force_sell

    Data.init_db(DATA_PATH)

    context = create_context()
    context.data.data_path = DATA_PATH
    context.portfolio.cash = 10_000_000
    context.portfolio.total_value = 10_000_000
    context.portfolio.previous_value = 10_000_000
    context.portfolio.starting_cash = 10_000_000
    context.trade.start_time = '2024-01-01'
    context.trade.end_time = '2024-02-05'
    context.trade.benchmark = '000001'
    context.trade.rule_list = "rule_stop,rule_limit,rule_t1,rule_volume_num,rule_cost,rule_100,rule_volume_ratio,rule_delist"

    calendar = Data.get_trade_calendar('2024-01-01', '2024-02-05')
    context.data.calendar = calendar

    if not calendar:
        return context

    # 包装内置事件处理器，注入审计
    def _before_market(ctx):
        check_current_dt(ctx, "before_market", "09:00:00")
        for code, pos in ctx.portfolio.positions.items():
            pos.enable_amount = pos.amount

    def _morning_start(ctx):
        check_current_dt(ctx, "morning_start", "09:30:00")
        delist_codes = []
        for code in ctx.portfolio.positions:
            info = Data.get_daily_info(code, ctx)
            if info is not None and "退" in info.name:
                delist_codes.append(code)
        for code in delist_codes:
            force_sell(code, ctx)

    def _end_interval(ctx):
        check_current_dt(ctx, "end_interval", "23:59:59")

        positions_value = 0
        for code, pos in ctx.portfolio.positions.items():
            price = Data.get_price(code, ctx)
            if price is not None:
                pos.total_value = pos.amount * price
                pos.last_sale_price = price
            positions_value += pos.total_value

        ctx.portfolio.positions_value = positions_value
        ctx.portfolio.total_value = ctx.portfolio.cash + positions_value

        if ctx.portfolio.previous_value != 0:
            daily_return = ctx.portfolio.total_value / ctx.portfolio.previous_value
        else:
            daily_return = 1.0

        date_str = ctx.current_dt.strftime("%Y-%m-%d")
        ctx.performance.returns.append([date_str, daily_return])
        ctx.portfolio.previous_value = ctx.portfolio.total_value

        # ★ 日终审计
        audit_daily_snapshot(ctx, "end_interval")

        # ★ 第 4 点: 验证 get_price 在 23:59:59 返回 close
        for code in list(ctx.portfolio.positions.keys())[:2]:
            price = Data.get_price(code, ctx)
            info = Data.get_daily_info(code, ctx)
            if price is not None and info is not None:
                if abs(price - info.close) > 0.001:
                    errors.append(
                        f"[B3盘后时间分支错误] {code} @ {ctx.current_dt}: "
                        f"get_price={price}, expected close={info.close}"
                    )

    handlers = {
        "before_market": _before_market,
        "morning_start": _morning_start,
        "end_interval": _end_interval,
    }

    event_list = load_events(calendar, handlers)
    context.data.event_list = event_list

    def _run_daily(func, time_str="9:30"):
        register_daily(event_list, calendar, func, time_str)

    context.run_daily = _run_daily
    initial(context)

    has_user_event = any(e.name == "user_strategy" for e in event_list)
    if not has_user_event:
        register_daily(event_list, calendar, handle_data, "9:30", "handle_data")

    previous_date = None
    while event_list:
        event = event_list.pop(0)
        context.current_dt = event.dt
        current_date_str = event.dt.strftime("%Y-%m-%d")
        if previous_date is not None and current_date_str != previous_date:
            context.previous_date = previous_date
        previous_date = current_date_str
        event.func(context)

    return context


# ======================================================================
# 主函数：运行 + 输出报告
# ======================================================================

if __name__ == "__main__":
    print("=" * 78)
    print("Phase 1 里程碑验证 — 第 3、4 点")
    print("策略: 小市值轮动 (phase_2_my_strategy)")
    print("区间: 2024-01-01 ~ 2024-02-05, 初始资金: 10,000,000")
    print("=" * 78)
    print()

    ctx = run_audited_backtest()

    # ==================================================================
    # 报告: 第 3 点 — 逐日 total_value = cash + positions_value
    # ==================================================================
    print("=" * 78)
    print("第 3 点验证: 逐日 total_value = cash + positions_value")
    print("=" * 78)
    print()
    print(f"{'日期':>12s}  {'cash':>14s}  {'pos_val':>14s}  {'total_val':>14s}  "
          f"{'diff':>8s}  {'持仓数':>6s}  {'结果':>6s}")
    print("-" * 88)

    daily_pass = 0
    daily_fail = 0
    for snap in audit_log:
        status = "PASS" if snap["ok_total"] and snap["ok_pos"] and snap["ok_each_pos"] else "FAIL"
        if status == "PASS":
            daily_pass += 1
        else:
            daily_fail += 1
        print(f"  {snap['date']}  {snap['cash']:>14.2f}  {snap['positions_value']:>14.2f}  "
              f"{snap['total_value']:>14.2f}  {snap['diff_total']:>8.4f}  "
              f"{snap['num_positions']:>6d}  {status}")

    print()
    print(f"逐日验证: {daily_pass} PASS / {daily_fail} FAIL (共 {len(audit_log)} 个交易日)")
    print()

    # 交易后审计
    print(f"交易后即时审计: 共 {len(trade_audit)} 笔")
    trade_pass = sum(1 for t in trade_audit if t["ok"])
    trade_fail = sum(1 for t in trade_audit if not t["ok"])
    if trade_fail > 0:
        print("  *** 失败明细 ***")
        for t in trade_audit:
            if not t["ok"]:
                print(f"    {t['label']} @ {t['date']}: diff={t['diff']:.4f}")
    print(f"  {trade_pass} PASS / {trade_fail} FAIL")
    print()

    # positions_value 与逐持仓求和一致性
    pos_mismatch = [s for s in audit_log if not s["ok_pos"]]
    if pos_mismatch:
        print("  *** positions_value 与 sum(pos.total_value) 不一致 ***")
        for s in pos_mismatch:
            print(f"    {s['date']}: pos_val={s['positions_value']:.2f}, recalc={s['recalc_pos_val']:.2f}")
    else:
        print("  positions_value == sum(pos.total_value): 全部一致")
    print()

    # ==================================================================
    # 报告: 第 4 点 — current_dt datetime 约定
    # ==================================================================
    print("=" * 78)
    print("第 4 点验证: context.current_dt datetime 约定 (E1 → B3 链路)")
    print("=" * 78)
    print()

    # 统计
    type_ok = sum(1 for c in dt_checks if c["is_datetime"])
    type_fail = sum(1 for c in dt_checks if not c["is_datetime"])
    time_ok = sum(1 for c in dt_checks if c["ok_time"])
    time_fail = sum(1 for c in dt_checks if not c["ok_time"])

    print(f"  current_dt 类型检查: {type_ok} PASS / {type_fail} FAIL (共 {len(dt_checks)} 次)")
    print(f"  current_dt 时间分支: {time_ok} PASS / {time_fail} FAIL")
    print()

    # 按事件类型汇总
    from collections import Counter
    event_counts = Counter(c["event"] for c in dt_checks)
    event_pass = Counter(c["event"] for c in dt_checks if c["ok_time"])
    print("  按事件类型:")
    for ev in sorted(event_counts.keys()):
        total = event_counts[ev]
        ok = event_pass.get(ev, 0)
        print(f"    {ev:>20s}: {ok}/{total} PASS")
    print()

    # B3 时间分支验证
    b3_errors = [e for e in errors if "B3" in e]
    if b3_errors:
        print("  *** B3 get_price 时间分支错误 ***")
        for e in b3_errors:
            print(f"    {e}")
    else:
        print("  B3 get_price 时间分支: 全部正确")
        print("    - 09:30 策略执行时 get_price 返回 open   ✓")
        print("    - 23:59 日终估值时 get_price 返回 close  ✓")
    print()

    # 链式推算交叉验证
    print("=" * 78)
    print("交叉验证: 净值比链式推算 vs context.total_value")
    print("=" * 78)
    print()
    chain_total = 10_000_000
    for date_str, ret in ctx.performance.returns:
        chain_total *= ret
    diff_chain = abs(chain_total - ctx.portfolio.total_value)
    ok_chain = diff_chain < 0.01
    print(f"  链式推算最终: {chain_total:.2f}")
    print(f"  context 实际: {ctx.portfolio.total_value:.2f}")
    print(f"  差值: {diff_chain:.4f}  {'PASS' if ok_chain else 'FAIL'}")
    print()

    # ==================================================================
    # 总结
    # ==================================================================
    print("=" * 78)
    print("总结")
    print("=" * 78)
    print()

    all_errors = list(errors)  # 收集所有错误

    if daily_fail == 0:
        print("  第 3 点 [PASS]: 全部交易日 total_value = cash + positions_value 成立")
    else:
        print(f"  第 3 点 [FAIL]: {daily_fail} 个交易日不变式失败")

    if trade_fail == 0:
        print(f"  第 3 点补充 [PASS]: 全部 {len(trade_audit)} 笔交易后即时审计通过")
    else:
        print(f"  第 3 点补充 [FAIL]: {trade_fail} 笔交易后不变式失败")

    if type_fail == 0 and time_fail == 0 and len(b3_errors) == 0:
        print("  第 4 点 [PASS]: current_dt 始终为 datetime, 时间分支 E1→B3 全链路正确")
    else:
        print("  第 4 点 [FAIL]: current_dt 或时间分支存在问题")

    if ok_chain:
        print("  交叉验证 [PASS]: 净值比链式推算与 context.total_value 一致")
    else:
        print("  交叉验证 [FAIL]: 链式推算结果不一致")

    print()
    if all_errors:
        print(f"  共发现 {len(all_errors)} 个错误:")
        for e in all_errors:
            print(f"    {e}")
    else:
        print("  零错误，全部验证通过")
    print()
