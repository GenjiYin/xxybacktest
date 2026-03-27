"""
A2~A4: 回测核心数据对象

Position  — 单只股票的持仓记录
Order     — 单笔订单（买/卖）
OrderCost — 费率配置
Slippage  — 滑点配置
"""

import hashlib
import time


class Position:
    """单只股票的持仓记录。

    参数:
        code:            股票代码，如 '000001'
        amount:          总持仓数量（股）
        enable_amount:   可卖数量（T+1 规则下，今日买入的不可卖）
        last_sale_price: 最新成交价格

    派生字段（构造时自动计算）:
        cost_basis:  持仓均价，初始等于买入价，后续加仓时由结算模块更新
        total_cost:  持仓总成本 = amount × last_sale_price（不含手续费，手续费由结算模块叠加）
        total_value: 持仓市值 = amount × last_sale_price（每日收盘后由事件模块按收盘价刷新）
    """

    def __init__(self, code, amount, enable_amount, last_sale_price):
        self.code = code
        self.amount = amount
        self.enable_amount = enable_amount
        self.last_sale_price = last_sale_price

        # 派生字段
        self.cost_basis = last_sale_price
        self.total_cost = amount * last_sale_price
        self.total_value = amount * last_sale_price

    def __repr__(self):
        return (
            f"Position(code={self.code!r}, amount={self.amount}, "
            f"enable_amount={self.enable_amount}, "
            f"last_sale_price={self.last_sale_price}, "
            f"cost_basis={self.cost_basis}, "
            f"total_value={self.total_value})"
        )


class Order:
    """单笔订单。

    由 trading 模块在调用 order_buy / order_sell 时创建。
    原项目在构造函数内部调用 Data 层获取行情和价格，
    我们改为由调用方传入 info 和 price，解耦数据依赖。

    参数:
        code:   股票代码
        amount: 下单数量（正数，买卖方向由 is_buy 决定）
        is_buy: True=买入, False=卖出
        price:  当前成交价（由 get_price 返回，None 表示无法成交）
        info:   当日行情 dict/DictObj（由 get_daily_info 返回，含 open/high/low/close/volume 等）

    自动生成:
        order_id:        基于 code + amount + 时间戳 + 自增序号 的 SHA256 哈希
        enable_amount:   传给 Position 的可卖数量（初始等于 amount，T+1 规则会改为 0）
        status:          1=正常, -1=取消（price 为 None 时自动取消）
        cost:            手续费（由规则引擎 C0 的 apply 末尾填入）
        slip_value:      滑点损失（由规则引擎填入）
        last_sale_price: 最终成交价（由规则引擎填入）
        value:           成交金额（由规则引擎填入）
    """

    _counter = 0  # 类级自增计数器，保证同一微秒内创建的订单 ID 也不重复

    def __init__(self, code, amount, is_buy, price, info):
        self.code = code
        self.amount = amount
        self.is_buy = is_buy
        self.price = price
        self.info = info

        # 自动生成
        self.order_id = self._generate_order_id()
        self.enable_amount = amount
        self.status = -1 if (price is None or info is None) else 1

        # 以下字段由规则引擎（C0 apply）填入
        self.cost = 0
        self.slip_value = 0
        self.last_sale_price = None
        self.value = 0
        self.date = None  # 下单日期，由 trading 模块在 append 前赋值

    def _generate_order_id(self):
        """基于 code + amount + 微秒时间戳 + 自增序号生成唯一订单号。"""
        Order._counter += 1
        timestamp = str(int(time.time() * 1000000))
        data = f"{self.code}_{self.amount}_{timestamp}_{Order._counter}".encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    def __repr__(self):
        side = "BUY" if self.is_buy else "SELL"
        status = "OK" if self.status == 1 else "CANCEL"
        return (
            f"Order({side} {self.code} x{self.amount} "
            f"price={self.price} status={status})"
        )


class OrderCost:
    """交易费率配置。

    策略在 initialize 中调用 set_order_cost(OrderCost(...)) 来自定义费率，
    引擎会将各字段写入 context.account 供结算时使用。

    参数:
        open_tax:                买入税费（A 股为 0）
        close_tax:               卖出税费（印花税，A 股千分之一）
        open_commission:         买入佣金率（默认万三）
        close_commission:        卖出佣金率（默认万三）
        close_today_commission:  日内卖出佣金（A 股 T+1 下通常为 0）
        min_commission:          单笔最低佣金（默认 5 元）
    """

    def __init__(
        self,
        open_tax=0,
        close_tax=0.001,
        open_commission=0.0003,
        close_commission=0.0003,
        close_today_commission=0,
        min_commission=5,
    ):
        self.open_tax = open_tax
        self.close_tax = close_tax
        self.open_commission = open_commission
        self.close_commission = close_commission
        self.close_today_commission = close_today_commission
        self.min_commission = min_commission

    def __repr__(self):
        return (
            f"OrderCost(open_tax={self.open_tax}, close_tax={self.close_tax}, "
            f"open_comm={self.open_commission}, close_comm={self.close_commission}, "
            f"min_comm={self.min_commission})"
        )


class FixedSlippage:
    """固定金额滑点。

    每股固定滑掉 value 元。
    例如 FixedSlippage(0.02) 表示每股滑点 0.02 元。
    """

    def __init__(self, value):
        self.value = value
        self.type = "fixed"

    def __repr__(self):
        return f"FixedSlippage(value={self.value})"


class PriceRelatedSlippage:
    """按比例滑点（默认类型）。

    滑点 = 成交金额 × value。
    例如 PriceRelatedSlippage(0.002) 表示千分之二的滑点。
    """

    def __init__(self, value):
        self.value = value
        self.type = "pricerelated"

    def __repr__(self):
        return f"PriceRelatedSlippage(value={self.value})"
