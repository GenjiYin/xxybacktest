"""
D1~D3: 订单与资金结算

order_buy  — 买入结算（D1）
order_sell — 卖出结算（D2）
order / order_value / order_target_value — 下单入口（D3）
"""

from .objects import Position, Order
from .rules import Rules
from .data import Data


# ------------------------------------------------------------------
# D1: order_buy — 买入结算
# ------------------------------------------------------------------

def order_buy(code, amount, context):
    """买入指定数量的股票。

    流程: 创建 Order → Rules 校验 → 通过则结算（扣钱、建/加持仓）

    参数:
        code:    股票代码，如 '000001.SZ'
        amount:  买入数量（股，正数）
        context: 回测上下文

    返回:
        Order 对象（可通过 order.status 判断是否成交）
    """
    # 获取行情（一次查询），价格从 info 推算（O3+O4: 消除冗余查询）
    info = Data.get_daily_info(code, context)
    price = Data.get_price(code, context, info=info)

    # 创建订单
    order = Order(code, amount, is_buy=True, price=price, info=info)

    # 规则校验
    Rules(order, context).apply()

    # 记录订单
    order.date = context.current_dt
    context.logs.order_list.append(order)

    # 未通过规则，直接返回
    if order.status == -1:
        return order

    # ----------------------------------------------------------
    # 结算
    # ----------------------------------------------------------
    settled_amount = order.amount
    settled_price = order.last_sale_price
    value = order.value
    cost = order.cost
    slip_value = order.slip_value

    positions = context.portfolio.positions

    if code in positions:
        # 加仓
        pos = positions[code]
        pos.total_cost += cost + settled_amount * settled_price
        pos.amount += settled_amount
        pos.enable_amount += order.enable_amount  # rule_t1 下为 0，T+0 下为 settled_amount
        pos.cost_basis = pos.total_cost / pos.amount
        pos.last_sale_price = settled_price
        pos.total_value = pos.amount * settled_price
    else:
        # 新建持仓
        pos = Position(
            code=code,
            amount=settled_amount,
            enable_amount=order.enable_amount,  # T+1 规则下为 0
            last_sale_price=settled_price,
        )
        pos.total_cost += cost  # 手续费计入成本
        pos.cost_basis = pos.total_cost / pos.amount
        positions[code] = pos

    # 更新资金
    context.portfolio.cash -= (value + cost + slip_value)
    context.portfolio.positions_value += value
    context.portfolio.total_value = (
        context.portfolio.cash + context.portfolio.positions_value
    )

    # 记录成交
    context.logs.trade_list.append(order)

    return order


# ------------------------------------------------------------------
# D2: order_sell — 卖出结算
# ------------------------------------------------------------------

def order_sell(code, amount, context):
    """卖出指定数量的股票。

    流程: 创建 Order → Rules 校验 → 通过则结算（回钱、减/清持仓）

    参数:
        code:    股票代码，如 '000001.SZ'
        amount:  卖出数量（股，正数）
        context: 回测上下文

    返回:
        Order 对象（可通过 order.status 判断是否成交）
    """
    # 获取行情（一次查询），价格从 info 推算（O3+O4: 消除冗余查询）
    info = Data.get_daily_info(code, context)
    price = Data.get_price(code, context, info=info)

    # 创建订单
    order = Order(code, amount, is_buy=False, price=price, info=info)

    # 规则校验
    Rules(order, context).apply()

    # 记录订单
    order.date = context.current_dt
    context.logs.order_list.append(order)

    # 未通过规则，直接返回
    if order.status == -1:
        return order

    # ----------------------------------------------------------
    # 结算
    # ----------------------------------------------------------
    settled_amount = order.amount
    settled_price = order.last_sale_price
    value = order.value
    cost = order.cost
    slip_value = order.slip_value

    positions = context.portfolio.positions
    pos = positions[code]

    # 卖出前保存 cost_basis（清仓时 del 前需要用，修复原项目 M5 Bug）
    old_cost_basis = pos.cost_basis

    # 单笔收益率（修复原项目 S3 Bug：加上 slip_value）
    net_per_share = (value - cost - slip_value) / settled_amount
    trade_return = net_per_share / old_cost_basis - 1
    context.logs.trade_returns.append(trade_return)

    # 胜率统计
    context.performance.trade_num += 1
    if net_per_share > old_cost_basis:
        context.performance.win += 1

    if settled_amount >= pos.amount:
        # 清仓
        context.portfolio.cash += (value - cost - slip_value)
        context.portfolio.positions_value -= value
        del positions[code]
    else:
        # 部分卖出
        context.portfolio.cash += (value - cost - slip_value)
        pos.amount -= settled_amount
        pos.enable_amount -= settled_amount
        # 按比例减少总成本，保持成本价不变
        remaining_ratio = pos.amount / (pos.amount + settled_amount)
        pos.total_cost = pos.total_cost * remaining_ratio
        pos.cost_basis = pos.total_cost / pos.amount
        pos.last_sale_price = settled_price
        pos.total_value = pos.amount * settled_price
        context.portfolio.positions_value -= value

    context.portfolio.total_value = (
        context.portfolio.cash + context.portfolio.positions_value
    )

    # 记录成交
    context.logs.trade_list.append(order)

    return order


# ------------------------------------------------------------------
# D3: order / order_value / order_target_value — 下单入口
# ------------------------------------------------------------------

def order(security, amount, context):
    """按数量下单。

    参数:
        security: 股票代码
        amount:   正数买入，负数卖出
        context:  回测上下文

    返回:
        Order 对象，或 None（amount == 0 时不下单）
    """
    if amount > 0:
        return order_buy(security, amount, context)
    elif amount < 0:
        return order_sell(security, -amount, context)
    return None


def order_value(security, value, context):
    """按金额下单。

    参数:
        security: 股票代码
        value:    正数买入对应金额，负数卖出对应金额
        context:  回测上下文

    返回:
        Order 对象，或 None（计算出的数量为 0 时不下单）
    """
    price = Data.get_price(security, context)
    if price is None or price == 0:
        return None

    if value > 0:
        amt = int(value / price)
        if amt <= 0:
            return None
        return order_buy(security, amt, context)
    elif value < 0:
        amt = int(-value / price)
        if amt <= 0:
            return None
        return order_sell(security, amt, context)
    return None


def order_target_value(security, value, context):
    """调仓至目标市值。

    参数:
        security: 股票代码
        value:    目标持仓市值（0 表示清仓）
        context:  回测上下文

    返回:
        Order 对象，或 None（无需调仓时）
    """
    price = Data.get_price(security, context)
    if price is None or price == 0:
        return None

    target_amount = int(value / (price * 1.1))

    # 修复原项目 Bug：security 不在 positions 中且 value=0 时不应 KeyError
    current_amount = 0
    if security in context.portfolio.positions:
        current_amount = context.portfolio.positions[security].amount

    change = target_amount - current_amount
    return order(security, change, context)


def force_sell(code, context):
    """强制清仓，不走规则链（E3 退市股清仓专用）。

    退市股可能已无行情（get_daily_info 返回 None），
    此时用持仓的 last_sale_price 作为结算价。

    参数:
        code:    股票代码
        context: 回测上下文

    返回:
        Order 对象
    """
    positions = context.portfolio.positions
    if code not in positions:
        return None

    pos = positions[code]
    amount = pos.amount

    # 尝试获取当日行情（一次查询），价格从 info 推算（O3+O4: 消除冗余查询）
    info = Data.get_daily_info(code, context)
    price = Data.get_price(code, context, info=info)

    # 无行情时退回到持仓记录价
    if price is None or price == 0:
        price = pos.last_sale_price

    # 创建订单，直接标记为通过
    order_obj = Order(code, amount, is_buy=False, price=price, info=info)
    order_obj.status = 1

    # 手动计算费用（不经过 Rules）
    value = amount * price
    order_obj.value = value

    tax = value * context.account.close_tax
    commission = max(value * context.account.close_commission,
                     context.account.min_commission)
    cost = tax + commission
    order_obj.cost = cost

    slip = context.trade.slip
    slip_value = value * slip
    order_obj.slip_value = slip_value
    order_obj.last_sale_price = price

    # 记录订单
    order_obj.date = context.current_dt
    context.logs.order_list.append(order_obj)

    # 结算：全额清仓
    old_cost_basis = pos.cost_basis

    net_per_share = (value - cost - slip_value) / amount
    trade_return = net_per_share / old_cost_basis - 1
    context.logs.trade_returns.append(trade_return)

    context.performance.trade_num += 1
    if net_per_share > old_cost_basis:
        context.performance.win += 1

    context.portfolio.cash += (value - cost - slip_value)
    context.portfolio.positions_value -= pos.total_value
    del positions[code]

    context.portfolio.total_value = (
        context.portfolio.cash + context.portfolio.positions_value
    )

    context.logs.trade_list.append(order_obj)

    return order_obj


def order_target_percent(security, percent, context):
    """按总资产百分比调仓。

    参数:
        security: 股票代码
        percent:  目标占比，小数形式 [0.0, 1.0]，如 0.1 表示 10%
        context:  回测上下文

    返回:
        Order 对象，或 None（无需调仓 / 参数无效时）
    """
    if percent < 0 or percent > 1:
        return None
    target_value = context.portfolio.total_value * percent
    return order_target_value(security, target_value, context)


# ------------------------------------------------------------------
# D4: inout_cash — 出入金
# ------------------------------------------------------------------

def inout_cash(cash_amount, context):
    """回测过程中增减资金。

    参数:
        cash_amount: 正数入金，负数出金
        context:     回测上下文
    """
    context.portfolio.cash += cash_amount
    context.portfolio.total_value += cash_amount
    context.portfolio.starting_cash += cash_amount
