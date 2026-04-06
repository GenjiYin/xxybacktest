"""
C0: 规则引擎框架
C1~C9: 全部交易规则

Rules 类负责对每笔订单执行可配置的规则链，
全部通过后统一计算费用并填入 Order 字段。
"""

import math


class Rules:
    """规则引擎。

    使用方式:
        rules = Rules(order, context)
        rules.apply()
        # 之后检查 order.status: 1=通过, -1=被拦截

    规则链由 context.trade.rule_list 配置（逗号分隔），如:
        "rule_stop"                          — Phase 1 最小配置
        "rule_stop,rule_limit,rule_t1,..."   — Phase 2 完整配置

    每个规则是 Rules 类上的一个方法，签名 def rule_xxx(self) -> bool。
    规则可以修改 self.order.amount（如缩量），返回 False 表示拦截。
    """

    def __init__(self, order, context):
        self.order = order
        self.context = context

    def apply(self):
        """执行规则链，通过后计算费用。"""
        order = self.order
        context = self.context

        # 已经被取消的订单（price=None 等）直接跳过
        if order.status == -1:
            return

        # 数量为 0 直接取消
        if order.amount <= 0:
            order.status = -1
            return

        # ----------------------------------------------------------
        # 逐个执行规则
        # ----------------------------------------------------------
        rule_list_str = context.trade.rule_list.strip()
        if rule_list_str:
            rule_names = [r.strip() for r in rule_list_str.split(",") if r.strip()]
            for rule_name in rule_names:
                rule_func = getattr(self, rule_name, None)
                if rule_func is None:
                    continue  # 未实现的规则跳过（容错）
                passed = rule_func()
                if not passed:
                    order.status = -1
                    return

        # 规则修改后数量可能变为 0
        if order.amount <= 0:
            order.status = -1
            return

        # ----------------------------------------------------------
        # 全部通过：计算费用
        # ----------------------------------------------------------
        price = order.price
        amount = order.amount

        # 成交金额
        value = amount * price
        order.value = value

        # 税费
        if order.is_buy:
            tax = value * context.account.open_tax
            commission_rate = context.account.open_commission
        else:
            tax = value * context.account.close_tax
            commission_rate = context.account.close_commission

        commission = max(value * commission_rate, context.account.min_commission)
        cost = tax + commission
        order.cost = cost

        # 滑点
        slip = context.trade.slip
        order.slip_value = value * slip

        # 成交价
        order.last_sale_price = price

    # ==================================================================
    # C1: rule_stop — 停牌检查
    # ==================================================================

    def rule_stop(self):
        """停牌 / 价格无效时拒绝交易。"""
        price = self.order.price
        info = self.order.info

        if info is None:
            return False
        if info.stop == 1:
            return False
        if price is None or price == 0:
            return False
        if isinstance(price, float) and math.isnan(price):
            return False

        return True

    # ==================================================================
    # C2: rule_limit — 涨跌停检查
    # ==================================================================

    def rule_limit(self):
        """封板股票无法交易。

        买入：price >= upLimit 且 price == high → 涨停封板，拒绝
        卖出：price <= downLimit 且 price == low → 跌停封板，拒绝

        如果盘中打开过（high > upLimit 或 low < downLimit），允许交易。
        """
        info = self.order.info
        price = self.order.price

        if info is None:
            return False

        if self.order.is_buy:
            if price >= info.upLimit and price == info.high:
                return False
        else:
            if price <= info.downLimit and price == info.low:
                return False

        return True

    # ==================================================================
    # C3: rule_t1 — T+1 限制
    # ==================================================================

    def rule_t1(self):
        """买入当天不可卖出（A股 T+1）。

        买入订单：将 enable_amount 设为 0，结算时新建持仓的可卖数量为 0。
        卖出订单：不做任何修改，直接通过。

        不配此规则（如美股 T+0）时，enable_amount 保持默认值 amount，
        买入当天即可卖出。
        """
        if self.order.is_buy:
            self.order.enable_amount = 0
        return True

    # ==================================================================
    # C4: rule_volume_num — 数量校验
    # ==================================================================

    def rule_volume_num(self):
        """卖出不超过可用数量 + 买卖取整到手数。

        卖出时：
        1. amount 截断为 min(amount, pos.enable_amount)
        2. 清仓（amount == pos.amount）时跳过取整，允许零碎卖出

        取整规则：
        - 非科创板：< 100 股归零，否则取 100 整数倍
        - 科创板(688)：< 200 股归零，> 50000 截断（200 以上按 1 股交易）
        """
        order = self.order
        code = order.code

        # ---- 卖出：截断到可卖数量 ----
        if not order.is_buy:
            positions = self.context.portfolio.positions
            if code not in positions:
                return False
            pos = positions[code]
            order.amount = min(order.amount, pos.enable_amount)
            if order.amount <= 0:
                return False
            # 清仓时跳过取整
            if order.amount == pos.amount:
                return True
            # 避免遗留零散股：卖出后剩余不足一手时，自动清仓
            remaining = pos.amount - order.amount
            min_lot = 200 if code.startswith("688") else 100
            if 0 < remaining < min_lot:
                order.amount = pos.amount
                return True

        # ---- 取整 ----
        if code.startswith("688"):
            # 科创板
            if order.amount < 200:
                order.amount = 0
            elif order.amount > 50000:
                order.amount = 50000
        else:
            # 非科创板：取整到 100 股
            if order.amount < 100:
                order.amount = 0
            else:
                order.amount = int(order.amount / 100) * 100

        if order.amount <= 0:
            return False

        return True

    # ==================================================================
    # C6: rule_cost — 现金充足性检查（含滑点）
    # ==================================================================

    def rule_cost(self):
        """买入时检查现金是否够付 value + 手续费 + 滑点。

        原设计 C6（手续费）和 C7（滑点）合并为一个规则。
        slip=0 时滑点项自然为 0，兼容无滑点场景。

        逻辑：
        1. 计算 total_needed = value + cost + slip_value
        2. cash >= total_needed → 通过
        3. cash < total_needed → 尝试缩量
           - overhead = cost + slip_value
           - cash < overhead → 连开销都不够，拒绝
           - 否则 → amount = int((cash - overhead) / price)

        注意：缩量后 cost/slip_value 会变化，此处用原始值近似。
        缩量后可能产生非整手数量，由后续 C5 rule_100 兜底取整。
        """
        if not self.order.is_buy:
            return True

        order = self.order
        ctx = self.context
        price = order.price
        cash = ctx.portfolio.cash
        slip = ctx.trade.slip

        value = order.amount * price
        tax = value * ctx.account.open_tax
        commission = max(value * ctx.account.open_commission,
                         ctx.account.min_commission)
        cost = tax + commission
        slip_value = value * slip

        total_needed = value + cost + slip_value

        if cash >= total_needed:
            return True

        # 现金不足，尝试缩量
        overhead = cost + slip_value
        if cash - overhead < 0:
            return False

        order.amount = int((cash - overhead) / price)

        if order.amount <= 0:
            return False

        return True

    # ==================================================================
    # C5: rule_100 — 兜底取整
    # ==================================================================

    def rule_100(self):
        """放在 C6 之后，对缩量后可能产生的非整手数量重新取整。

        仅对买入生效：rule_cost 缩量后可能产生非整手数量，此规则兜底取整。
        卖出不处理：卖出取整（含散股清仓）由 rule_volume_num 全权负责。
        若 rule_100 对卖出再次取整，会破坏 rule_volume_num 的清仓判断，
        导致散股永远卖不出去。

        科创板买入：rule_cost 缩量后只需保证 >= 200 股即可，
        无需按 200 整除（科创板 200 股以上可按 1 股交易）。
        """
        order = self.order

        if not order.is_buy:
            return True  # 卖出由 rule_volume_num 全权负责，此处直接通过

        code = order.code
        if code.startswith("688"):
            # 科创板：只保证最低 200 股，不按 200 整除
            if order.amount < 200:
                order.amount = 0
        else:
            # 非科创板：取整到 100 股
            order.amount = int(order.amount / 100) * 100

        if order.amount <= 0:
            return False
        return True

    # ==================================================================
    # C8: rule_volume_ratio — 成交量比例限制
    # ==================================================================

    def rule_volume_ratio(self):
        """单笔成交不超过当日成交量的一定比例。

        比例由 context.trade.order_volume_ratio 控制（默认 1 即 100%）。
        超出部分截断，截断后为 0 则拒绝。
        """
        info = self.order.info
        if info is None:
            return False

        ratio = self.context.trade.order_volume_ratio
        max_amount = int(info.volume * ratio)

        if self.order.amount > max_amount:
            self.order.amount = max_amount

        if self.order.amount <= 0:
            return False

        return True

    # ==================================================================
    # C9: rule_delist — 退市股买入拦截
    # ==================================================================

    def rule_delist(self):
        """禁止买入退市股（名称含 '退'），卖出不拦。"""
        if not self.order.is_buy:
            return True

        info = self.order.info
        if info is None:
            return False

        if "退" in info.name:
            return False

        return True
