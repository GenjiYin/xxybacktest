"""
live/trading.py — 实盘版交易函数与 Portfolio 刷新

API 签名与回测 trading.py 完全一致。
所有函数通过 live/runner.py 用 lambda 绑定到 context 上，
策略代码无需感知自己运行在回测还是实盘环境。

核心设计：
    - 持仓/资金始终以 QMT 为准
    - 交易函数实时查询 QMT，不依赖 context 快照
    - 交易函数内部不自动刷新 context.portfolio
      （由 runner.py 在 handle_data 结束后统一刷新）
"""

import time
from datetime import datetime

from ..objects import Order, Position


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _round_volume(volume: float) -> int:
    """将股数向下取整到 100 的倍数（A 股 100 股为 1 手）。"""
    return int(volume // 100 * 100)


def _make_order(security: str, amount: int, is_buy: bool,
                price: float | None, status: int) -> Order:
    """构造实盘版 Order 对象（info=None，status 由下单结果决定）。"""
    order = Order(security, amount, is_buy, price, info=None)
    order.status = status
    order.date = datetime.now().strftime('%Y-%m-%d')
    return order


# ---------------------------------------------------------------------------
# 实时刷新接口（策略可直接调用）
# ---------------------------------------------------------------------------

def get_portfolio(context) -> dict:
    """
    从 QMT 实时拉取资金概况，同步到 context.portfolio，并返回 dict。

    策略可直接调用 context.get_portfolio() 获取最新资金。

    返回:
        {
            'cash': float,          # 可用资金
            'frozen_cash': float,   # 冻结资金
            'market_value': float,  # 持仓市值
            'total_asset': float,   # 总资产
        }
    """
    trader = context._trader
    p = trader.get_portfolio()

    context.portfolio.cash = p['cash']
    context.portfolio.total_value = p['total_asset']
    context.portfolio.positions_value = p['market_value']

    return p


def get_account_positions(context) -> dict:
    """
    从 QMT 实时拉取全部持仓，同步到 context.portfolio.positions，并返回 dict。

    策略可直接调用 context.get_account_positions() 获取最新持仓。

    返回:
        {
            '000001.SZ': {
                'volume': int,
                'can_sell_volume': int,
                'cost_price': float,
                'last_price': float,
                'market_value': float,
            },
            ...
        }
    """
    trader = context._trader
    positions = trader.get_positions()

    # 清空现有持仓，重新填充
    context.portfolio.positions = {}
    for code, pos in positions.items():
        p = Position(
            code=code,
            amount=pos['volume'],
            enable_amount=pos['can_sell_volume'],
            last_sale_price=pos['last_price'],
        )
        p.cost_basis = pos['cost_price']
        p.total_cost = pos['volume'] * pos['cost_price']
        p.total_value = pos['market_value']
        context.portfolio.positions[code] = p

    return positions


def _refresh_portfolio(context):
    """
    同时刷新资金与持仓，供 runner.py 在 handle_data 结束后统一调用。
    """
    get_portfolio(context)
    get_account_positions(context)


def get_price(context, security: str) -> float | None:
    """
    获取股票最新价（实盘：QMT 实时 tick）。

    接口与回测 context.get_price 一致，策略可直接调用 context.get_price(code)，
    回测/实盘无需感知差异。

    实时 tick 拿不到时（如未订阅行情），退回该股持仓的 last_price；
    仍无则返回 None（停牌 / 无行情）。

    参数:
        security: 股票代码，如 '000001.SZ'

    返回:
        float 或 None
    """
    trader = context._trader

    price = trader.get_price(security)
    if price:
        return price

    # tick 不可用时退回持仓最新价
    pos = trader.get_position(security)
    if pos and pos.get('last_price'):
        return pos['last_price']

    return None


# ---------------------------------------------------------------------------
# 交易函数（API 签名与回测 trading.py 完全一致）
# ---------------------------------------------------------------------------

def order_buy(security: str, amount: int, context) -> Order | None:
    """直接买入指定数量。

    参数:
        security: 股票代码，如 '000001.SZ'
        amount:   买入数量（股，正整数）
        context:  实盘上下文

    返回:
        Order 对象，或 None（参数无效时）
    """
    if amount <= 0:
        return None

    trader = context._trader
    price = trader.get_price(security)

    result = trader.order_stock(security, amount, 'BUY')
    status = 1 if result['status'] == 'submitted' else -1

    order = _make_order(security, amount, is_buy=True, price=price, status=status)
    context.logs.order_list.append(order)

    time.sleep(0.5)
    return order


def order_sell(security: str, amount: int, context) -> Order | None:
    """直接卖出指定数量。

    参数:
        security: 股票代码
        amount:   卖出数量（股，正整数）
        context:  实盘上下文

    返回:
        Order 对象，或 None（参数无效时）
    """
    if amount <= 0:
        return None

    trader = context._trader
    price = trader.get_price(security)

    result = trader.order_stock(security, amount, 'SELL')
    status = 1 if result['status'] == 'submitted' else -1

    order = _make_order(security, amount, is_buy=False, price=price, status=status)
    context.logs.order_list.append(order)

    time.sleep(0.5)
    return order


def order(security: str, amount: int, context) -> Order | None:
    """按差量下单。正数买，负数卖。

    参数:
        security: 股票代码
        amount:   正数买入，负数卖出
        context:  实盘上下文

    返回:
        Order 对象，或 None（amount == 0 时）
    """
    if amount > 0:
        return order_buy(security, amount, context)
    elif amount < 0:
        return order_sell(security, -amount, context)
    return None


def order_value(security: str, value: float, context) -> Order | None:
    """按金额下单。正数买入，负数卖出。

    参数:
        security: 股票代码
        value:    正数买入对应金额，负数卖出对应金额
        context:  实盘上下文

    返回:
        Order 对象，或 None（价格无效 / 计算数量为 0 时）
    """
    trader = context._trader
    price = trader.get_price(security)
    if price is None or price == 0:
        return None

    if value > 0:
        amt = _round_volume(value / price)
        if amt <= 0:
            return None
        return order_buy(security, amt, context)
    elif value < 0:
        amt = _round_volume(-value / price)
        if amt <= 0:
            return None
        return order_sell(security, amt, context)
    return None


def order_target_value(security: str, value: float, context) -> Order | None:
    """调仓至目标市值。0 表示清仓。

    参数:
        security: 股票代码
        value:    目标持仓市值（元）
        context:  实盘上下文

    返回:
        Order 对象，或 None（无需调仓 / 价格无效时）
    """
    trader = context._trader
    price = trader.get_price(security)
    if price is None or price == 0:
        return None

    # 目标股数（100 股取整）
    target_volume = _round_volume(value / price)

    # 当前持仓股数
    pos = trader.get_position(security)
    current_volume = pos['volume'] if pos else 0

    change = target_volume - current_volume
    return order(security, change, context)


def order_target_percent(security: str, percent: float, context) -> Order | None:
    """按总资产百分比调仓。

    参数:
        security: 股票代码
        percent:  目标占比，小数形式 [0.0, 1.0]
        context:  实盘上下文

    返回:
        Order 对象，或 None（参数无效 / 无需调仓时）
    """
    if percent < 0 or percent > 1:
        return None

    trader = context._trader
    total_asset = trader.get_portfolio()['total_asset']
    target_value = total_asset * percent

    return order_target_value(security, target_value, context)


def inout_cash(cash_amount: float, context):
    """实盘不支持出入金，调用时记录 warning 并跳过。"""
    print(f"[WARNING] inout_cash({cash_amount}) 在实盘中被忽略，"
          f"实盘不支持出入金操作。")
