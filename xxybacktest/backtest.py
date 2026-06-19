"""
H3: 回测主循环（Phase 1 简化版）

run_backtest — 接收用户回调函数，驱动整个回测流程。
"""

import pandas as pd

from .context import create_context
from .data import Data
from .events import load_events, register_daily
from .performance import Performance
from .trading import (
    force_sell,
    order as _order,
    order_buy as _order_buy,
    order_sell as _order_sell,
    order_value as _order_value,
    order_target_value as _order_target_value,
    order_target_percent as _order_target_percent,
    inout_cash as _inout_cash,
)


def run_backtest(
    initialize,
    handle_data,
    start_date,
    end_date,
    capital=1000000,
    data_path="./data",
    order_cost=None,
    slippage=None,
    benchmark=None,
    asset_type="stock",
    plot=True,
):
    """运行一次完整的回测。

    参数:
        initialize:  callable(context) — 用户初始化函数
                     在此函数中可调用 run_daily 注册策略事件
        handle_data: callable(context) — 用户策略函数（默认每日 09:30 执行）
                     如果为 None，则用户需在 initialize 中自行 run_daily
        start_date:  str 'YYYY-MM-DD' — 回测起始日
        end_date:    str 'YYYY-MM-DD' — 回测结束日
        capital:     float — 初始资金（默认 100 万）
        data_path:   str — xxydb 数据目录
        order_cost:  OrderCost 实例（可选，默认用 context 内置值）
        slippage:    Slippage 实例（可选，默认用 context 内置值）
        benchmark:   str — 基准指数代码
        asset_type:  str — 资产类型，'stock' 或 'fund'（默认 'stock'）
        plot:        bool — 是否在 Notebook 中展示回测曲线和绩效指标（默认 False）

    返回:
        context — 回测结束后的完整上下文，包含持仓、资金、日志、绩效等
    """
    # ------------------------------------------------------------------
    # 0. 根据 asset_type 确定规则链
    # ------------------------------------------------------------------
    if asset_type == "stock":
        rule_list = "rule_stop,rule_limit,rule_t1,rule_volume_num,rule_cost,rule_100,rule_volume_ratio,rule_delist"
    elif asset_type == "fund":
        rule_list = "rule_stop,rule_limit,rule_t1,rule_volume_num,rule_cost,rule_100,rule_volume_ratio"
    else:
        raise ValueError(f"unsupported asset_type: {asset_type!r}")

    # ------------------------------------------------------------------
    # 1. 初始化数据库连接 + O1/O2 全区间预加载（按 asset_type 分流）
    # ------------------------------------------------------------------
    Data.init_db(data_path, asset_type=asset_type)
    if asset_type == "fund":
        Data.preload_fund_daily(start_date, end_date)
        Data.preload_fund_dividend(start_date, end_date)
    else:
        Data.preload_daily(start_date, end_date)
        Data.preload_dividend(start_date, end_date)

    # ------------------------------------------------------------------
    # 2. 创建 context
    # ------------------------------------------------------------------
    context = create_context()

    context.data.data_path = data_path
    context.portfolio.cash = capital
    context.portfolio.total_value = capital
    context.portfolio.previous_value = capital
    context.portfolio.starting_cash = capital

    # 绑定与实盘兼容的持仓/资金查询接口，确保同一套策略代码在回测中也能运行
    def _get_portfolio():
        p = context.portfolio
        return {
            'cash': float(p.cash),
            'frozen_cash': float(p.locked_cash),
            'market_value': float(p.positions_value),
            'total_asset': float(p.total_value),
        }
    context.get_portfolio = _get_portfolio

    def _get_account_positions():
        result = {}
        for code, pos in context.portfolio.positions.items():
            result[code] = {
                'volume': int(pos.amount),
                'can_sell_volume': int(pos.enable_amount),
                'cost_price': float(pos.cost_basis),
                'last_price': float(pos.last_sale_price),
                'market_value': float(pos.total_value),
            }
        return result
    context.get_account_positions = _get_account_positions

    # 获取最新参考价（与实盘 context.get_price 接口一致）
    # 回测：按当前时间返回模拟撮合价（盘前=上一交易日close，盘中=当日open，盘后=当日close）
    def _get_price(security):
        return Data.get_price(security, context)
    context.get_price = _get_price

    if benchmark is None:
        benchmark = "000001.SH"

    context.trade.start_time = start_date
    context.trade.end_time = end_date
    context.trade.benchmark = benchmark
    context.trade.rule_list = rule_list
    context.trade.asset_type = asset_type

    if order_cost is not None:
        context.account.open_tax = order_cost.open_tax
        context.account.close_tax = order_cost.close_tax
        context.account.open_commission = order_cost.open_commission
        context.account.close_commission = order_cost.close_commission
        context.account.min_commission = order_cost.min_commission
    elif asset_type == "fund":
        # 基金默认无印花税
        context.account.close_tax = 0

    if slippage is not None:
        context.trade.slip = slippage.value
        context.trade.sliptype = slippage.type

    # ------------------------------------------------------------------
    # 3. 获取交易日历
    # ------------------------------------------------------------------
    calendar = Data.get_trade_calendar(start_date, end_date)
    context.data.calendar = calendar

    if not calendar:
        return context

    # F-H1: 基金拆分预加载（需要 calendar 来推导 ex_date = 基准日的下一个交易日）
    if asset_type == "fund":
        Data.preload_fund_split(start_date, end_date, calendar)

    # ------------------------------------------------------------------
    # 4. 定义内置事件处理器
    # ------------------------------------------------------------------
    def _before_market(ctx):
        """E2: 盘前刷新 enable_amount + F2: 送股处理。"""
        # E2: 刷新可卖数量
        for code, pos in ctx.portfolio.positions.items():
            pos.enable_amount = pos.amount

        # F2: 送股处理（除权日盘前，先送股再交易）
        now_date = ctx.current_dt.strftime("%Y-%m-%d")
        dt_key = "dt_" + now_date
        if dt_key in ctx.data.dividend:
            div_today = ctx.data.dividend[dt_key]
            for code, pos in ctx.portfolio.positions.items():
                if code not in div_today:
                    continue
                entry = div_today[code]
                # F3 预加载的记录需按当前持仓量计算实际股数
                if entry.get("preloaded"):
                    entry["cash_tax"] = pos.amount * entry["cash_tax_per_share"]
                    entry["cash_stk"] = pos.amount * entry["stk_div_per_share"]
                    entry["preloaded"] = False
                if entry["cash_stk"] != 0:
                    new_amount = int(entry["cash_stk"])  # 截尾取整，券商按整股派发
                    if new_amount <= 0:
                        continue
                    pos.amount += new_amount
                    pos.enable_amount = pos.amount
                    if pos.amount > 0:
                        # 送股是免费赠股，不改变持仓总成本，只摊薄每股均价
                        pos.total_value = pos.amount * pos.last_sale_price
                        pos.cost_basis = pos.total_cost / pos.amount
                    ctx.portfolio.positions_value += new_amount * pos.last_sale_price
                    ctx.portfolio.total_value += new_amount * pos.last_sale_price

    def _morning_start(ctx):
        """E3: 开盘自动卖出退市股 + 散股。"""
        if ctx.trade.asset_type == "fund":
            return  # 基金无退市股/散股自动卖出机制

        # 先收集要处理的 code（避免遍历中修改字典）
        delist_codes = []
        frac_codes = []
        for code, pos in ctx.portfolio.positions.items():
            info = Data.get_daily_info(code, ctx)
            if info is not None and "退" in info.name:
                delist_codes.append(code)
                continue
            # 散股检测：持仓数量不足一手（分红配股后可能产生）
            min_lot = 200 if code.startswith("688") else 100
            if 0 < pos.amount < min_lot:
                frac_codes.append(code)

        for code in delist_codes:
            force_sell(code, ctx)

        # 散股强制清仓：用当日行情价（无行情则用持仓记录价），获得现金等价
        for code in frac_codes:
            force_sell(code, ctx)

    def _end_interval(ctx):
        """E4: 日终估值。"""
        positions_value = 0
        for code, pos in ctx.portfolio.positions.items():
            price = Data.get_price(code, ctx)
            if price is not None:
                pos.total_value = pos.amount * price
                pos.last_sale_price = price
            positions_value += pos.total_value

        ctx.portfolio.positions_value = positions_value
        ctx.portfolio.total_value = ctx.portfolio.cash + positions_value

        # 记录当日净值比
        # previous_value 是昨日 end_interval 末尾设置的（首日为 capital）
        if ctx.portfolio.previous_value != 0:
            daily_return = ctx.portfolio.total_value / ctx.portfolio.previous_value
        else:
            daily_return = 1.0

        date_str = ctx.current_dt.strftime("%Y-%m-%d")
        ctx.performance.returns.append([date_str, daily_return])

        # 记录持仓占比
        if ctx.portfolio.total_value != 0:
            pos_ratio = positions_value / ctx.portfolio.total_value
        else:
            pos_ratio = 0.0
        ctx.performance.position_ratio.append([date_str, pos_ratio])

        # 记录每只持仓的日终快照
        total_val = ctx.portfolio.total_value
        for code, pos in ctx.portfolio.positions.items():
            if total_val != 0:
                ratio = pos.total_value / total_val
            else:
                ratio = 0.0
            # 累计收益 = 当前价 / 持仓均价 - 1
            cum_return = pos.last_sale_price / pos.cost_basis - 1 if pos.cost_basis != 0 else 0.0
            cum_profit = pos.amount * (pos.last_sale_price - pos.cost_basis)
            _day_cache = Data._daily_cache.get(date_str, {}) if Data._daily_cache else {}
            _info = _day_cache.get(code)
            name = (_info.name if _info is not None else "") or Data._instrument_names.get(code, "")
            ctx.performance.position_snapshots.append({
                "date": date_str,
                "instrument": code,
                "name": name,
                "volume": pos.amount,
                "ratio": ratio,
                "cum_profit": cum_profit,
                "cum_return": cum_return,
                "close": pos.last_sale_price,
                "avg_cost": pos.cost_basis,
            })

        # 更新 previous_value 供明天使用
        ctx.portfolio.previous_value = ctx.portfolio.total_value

    def _after_market(ctx):
        """F1: 盘后分红派息登记与发放。"""
        now_date = ctx.current_dt.strftime("%Y-%m-%d")

        # 阶段1：登记日 — 查询当日 register_date 的分红，按 pay_date 存入缓存
        dividend = Data.get_dividend(ctx)
        if dividend:
            for code, pos in ctx.portfolio.positions.items():
                if code in dividend:
                    div_info = dividend[code]
                    stk_div = div_info.stk_div
                    cash_div_tax = div_info.cash_div_tax
                    pay_date = div_info.pay_date
                    if pay_date is None:
                        continue

                    amount = pos.amount
                    dt_key = "dt_" + pay_date
                    if dt_key not in ctx.data.dividend:
                        ctx.data.dividend[dt_key] = {}
                    ctx.data.dividend[dt_key][code] = {
                        "cash_tax": amount * cash_div_tax,
                        "cash_stk": amount * stk_div,
                    }

        # 阶段2：派息日 — 发放现金红利
        dt_key = "dt_" + now_date
        if dt_key in ctx.data.dividend:
            div_today = ctx.data.dividend[dt_key]
            for code, pos in ctx.portfolio.positions.items():
                if code not in div_today:
                    continue
                entry = div_today[code]
                # F3 预加载的记录需按当前持仓量计算实际金额
                if entry.get("preloaded"):
                    entry["cash_tax"] = pos.amount * entry["cash_tax_per_share"]
                    entry["cash_stk"] = pos.amount * entry["stk_div_per_share"]
                    entry["preloaded"] = False
                if entry["cash_tax"] > 0:
                    cash_amount = entry["cash_tax"]
                    ctx.portfolio.cash += cash_amount
                    # 修复原项目 Bug：分红后更新 cost_basis
                    pos.total_cost -= cash_amount
                    pos.cost_basis = pos.total_cost / pos.amount

    handlers = {
        "before_market": _before_market,
        "morning_start": _morning_start,
        "after_market": _after_market,
        "end_interval": _end_interval,
    }

    # ------------------------------------------------------------------
    # 4b. F3: 分红数据预加载（按 asset_type 分流）
    # ------------------------------------------------------------------
    # 处理 register_date 在回测开始前、但 pay_date(ex_date) 在回测期间内的分红
    # 这些分红的登记日不在回测区间内，after_market 的阶段1不会捕获到
    if asset_type == "fund":
        pre_div = Data.get_fund_dividend_by_pay_date(start_date, end_date)
    else:
        pre_div = Data.get_dividend_by_pay_date(start_date, end_date)
    for pay_date_str, code_dict in pre_div.items():
        dt_key = "dt_" + pay_date_str
        if dt_key not in context.data.dividend:
            context.data.dividend[dt_key] = {}
        for code, div_info in code_dict.items():
            # 预加载时持仓未知，先存每股数据；实际发放时需要乘以持仓量
            # 但原项目设计是在登记日（after_market）按当时持仓量算好总量存入缓存
            # 预加载的这些记录，其 register_date 在回测前，回测期间不会再触发登记
            # 所以这里只存每股比例，待 after_market / before_market 按持仓量计算
            context.data.dividend[dt_key][code] = {
                "cash_tax_per_share": float(div_info.cash_div_tax),
                "stk_div_per_share": float(div_info.stk_div),
                "cash_tax": 0,   # 占位，需在派息日按实际持仓计算
                "cash_stk": 0,   # 占位，需在送股日按实际持仓计算
                "preloaded": True,
            }

    # F-H1: 基金拆分 F3 预加载（基准日在回测前，ex_date 在回测区间内的拆分事件）
    if asset_type == "fund":
        pre_split = Data.get_fund_split_by_ex_date(start_date, end_date, calendar)
        for ex_date_str, code_dict in pre_split.items():
            dt_key = "dt_" + ex_date_str
            if dt_key not in context.data.dividend:
                context.data.dividend[dt_key] = {}
            for code, div_info in code_dict.items():
                if code not in context.data.dividend[dt_key]:
                    context.data.dividend[dt_key][code] = {
                        "cash_tax_per_share": 0.0,
                        "stk_div_per_share": float(div_info.stk_div),
                        "cash_tax": 0,
                        "cash_stk": 0,
                        "preloaded": True,
                    }
                else:
                    # 已有分红记录（F3 pre_div），合并 stk_div
                    entry = context.data.dividend[dt_key][code]
                    existing_stk = entry.get("stk_div_per_share", 0)
                    entry["stk_div_per_share"] = (1 + existing_stk) * (1 + float(div_info.stk_div)) - 1

    # ------------------------------------------------------------------
    # 5. 生成事件列表
    # ------------------------------------------------------------------
    event_list = load_events(calendar, handlers)
    context.data.event_list = event_list

    # ------------------------------------------------------------------
    # 6. 提供 run_daily 接口并调用用户 initialize
    # ------------------------------------------------------------------
    def _run_daily(func, time_str="9:30"):
        """供用户在 initialize 中调用，注册每日定时事件。"""
        register_daily(event_list, calendar, func, time_str)

    # 将 run_daily 挂到 context 上，用户通过 context 调用
    context.run_daily = _run_daily

    # 将 history 挂到 context 上，用户通过 context.history(...) 获取历史行情
    def _history(instruments, fields=None, bar_count=1):
        return Data.history(context, instruments, fields, bar_count)
    context.history = _history

    # 将下单函数绑定到 context，用户无需手动导入、无需传 context
    context.order = lambda security, amount: _order(security, amount, context)
    context.order_buy = lambda code, amount: _order_buy(code, amount, context)
    context.order_sell = lambda code, amount: _order_sell(code, amount, context)
    context.order_value = lambda security, value: _order_value(security, value, context)
    context.order_target_value = lambda security, value: _order_target_value(security, value, context)
    context.order_target_percent = lambda security, percent: _order_target_percent(security, percent, context)
    context.inout_cash = lambda cash_amount: _inout_cash(cash_amount, context)

    initialize(context)

    # 如果用户传了 handle_data 但没在 initialize 中自行注册，自动注册到 09:30
    if handle_data is not None:
        # 检查用户是否已手动注册过（通过查看是否有 user_strategy 事件）
        has_user_event = any(e.name == "user_strategy" for e in event_list)
        if not has_user_event:
            register_daily(event_list, calendar, handle_data, "9:30", "handle_data")

    # ------------------------------------------------------------------
    # 7. 主循环：逐事件执行
    # ------------------------------------------------------------------
    # 首日的“上一交易日”：从 trading_days 表取 start_date 之前最近交易日，
    # 使首日（含）起 previous_date / previous_dt 即为真实值，而非 None。
    # 数据库边界（无更早交易日）时为 None。
    prev_init = Data.get_previous_trade_day(start_date)
    context.previous_date = prev_init
    context.previous_dt = pd.to_datetime(prev_init) if prev_init is not None else None
    previous_date = prev_init

    while event_list:
        event = event_list.pop(0)

        # 更新时间上下文
        context.current_dt = event.dt
        current_date_str = event.dt.strftime("%Y-%m-%d")

        # previous_date / previous_dt: 上一个交易日（字符串 + datetime）
        # 当日期切换时更新
        if previous_date is not None and current_date_str != previous_date:
            context.previous_date = previous_date
            context.previous_dt = pd.to_datetime(previous_date)
        previous_date = current_date_str

        # 执行事件回调
        event.func(context)

    # 回测结束，计算收益率序列 + 绩效指标
    Performance.analyse(context)

    # ------------------------------------------------------------------
    # 8. 构建结果 DataFrame: context.order / context.pos（无论 plot 如何都构建）
    # ------------------------------------------------------------------
    # order DataFrame
    order_records = []
    for o in context.logs.order_list:
        # 从 order.info 取名称（info 可能为 None，如停牌被拒单）
        name = o.info.name if o.info is not None else ""
        order_records.append({
            "date": o.date.strftime("%Y-%m-%d") if o.date else "",
            "instrument": o.code,
            "name": name,
            "volume": o.amount,
            "side": "buy" if o.is_buy else "sell",
            "status": "filled" if o.status == 1 else "rejected",
            "price": round(o.last_sale_price, 4) if o.last_sale_price else 0,
            "cost": round(o.cost + o.slip_value, 2),
        })
    if order_records:
        context.order = pd.DataFrame(order_records)
    else:
        context.order = pd.DataFrame(
            columns=["date", "instrument", "name", "volume", "side", "status", "price", "cost"]
        )

    # pos DataFrame（取最后一天的持仓作为当前持仓）
    snap_list = context.performance.position_snapshots
    if snap_list:
        pos_rows = []
        for s in snap_list:
            # return 字段格式: "收益绝对数/累计收益率"
            ret_str = f"{s['cum_profit']:.2f}/{s['cum_return']:.2%}"
            pos_rows.append({
                "date": s["date"],
                "instrument": s["instrument"],
                "name": s.get("name", ""),
                "volume": s["volume"],
                "ratio": round(s["ratio"], 4),
                "return": ret_str,
                "close": s["close"],
                "avg_cost": round(s["avg_cost"], 4),
            })
        context.pos = pd.DataFrame(pos_rows)
    else:
        context.pos = pd.DataFrame(
            columns=["date", "instrument", "name", "volume", "ratio",
                    "return", "close", "avg_cost"]
        )

    # G3: 展示回测曲线和绩效（仅在 plot=True 时）
    if plot:
        from itables import show
        Performance.plot(context)
        show(context.pos, buttons=["copyHtml5", "csvHtml5", "excelHtml5"], table_id='position_table')
        show(context.order, buttons=["copyHtml5", "csvHtml5", "excelHtml5"], table_id='order_table')


    # 释放缓存内存
    Data.clear_cache()
    Data._db.close()
 
    return context
