"""
live/context.py — 实盘上下文构建

从 QMT 读取真实资金和持仓，构建与回测完全兼容的 context 对象。
策略代码无需感知自己运行在回测还是实盘环境。
"""

from datetime import datetime

from ..context import create_context
from ..objects import Position
from .trader import QMTTrader


def create_live_context(account: dict, trader: QMTTrader,
                        strategy_state: dict = None):
    """
    构建实盘 context。

    参数:
        account:        submitter.get_account() 返回的账户配置 dict
        trader:         已连接的 QMTTrader 实例
        strategy_state: 上次持久化的策略状态（即 context.g 的内容），
                        首次运行传 None 或 {}

    返回:
        DictObj — 与 run_backtest 返回的 context 结构完全一致
    """
    ctx = create_context()

    # ------------------------------------------------------------------
    # 资金
    # ------------------------------------------------------------------
    portfolio = trader.get_portfolio()

    ctx.portfolio.cash            = portfolio['cash']
    ctx.portfolio.total_value     = portfolio['total_asset']
    ctx.portfolio.positions_value = portfolio['market_value']
    ctx.portfolio.starting_cash   = float(account['initial_cash'])

    # ------------------------------------------------------------------
    # 持仓 → Position 对象
    # ------------------------------------------------------------------
    for code, pos in trader.get_positions().items():
        p = Position(
            code=code,
            amount=pos['volume'],
            enable_amount=pos['can_sell_volume'],
            last_sale_price=pos['last_price'],
        )
        p.cost_basis  = pos['cost_price']
        p.total_cost  = pos['volume'] * pos['cost_price']
        p.total_value = pos['market_value']
        ctx.portfolio.positions[code] = p

    # ------------------------------------------------------------------
    # 交易配置
    # ------------------------------------------------------------------
    ctx.trade.asset_type = account.get('asset_type', 'stock')
    ctx.trade.benchmark  = account.get('benchmark', '000300.SH')
    ctx.trade.start_time = account.get('start_date', '')
    ctx.trade.end_time   = datetime.now().strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # 数据路径
    # ------------------------------------------------------------------
    ctx.data.data_path = account.get('data_path', './data')

    # ------------------------------------------------------------------
    # 时间
    # ------------------------------------------------------------------
    ctx.current_dt = datetime.now()

    # ------------------------------------------------------------------
    # 策略状态恢复（context.g）
    # ------------------------------------------------------------------
    if strategy_state:
        for k, v in strategy_state.items():
            ctx.g[k] = v

    # ------------------------------------------------------------------
    # 挂载 trader，供 live/trading.py 内部调用
    # ------------------------------------------------------------------
    ctx._trader = trader

    # ------------------------------------------------------------------
    # 订单列表初始化（live/trading.py 填充）
    # ------------------------------------------------------------------
    ctx.logs.order_list = []

    return ctx
