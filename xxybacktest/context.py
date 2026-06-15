"""
A1: Context 上下文对象

DictObj  — 支持 obj.key 和 obj['key'] 双模访问的字典封装
create_context() — 工厂函数，每次调用返回全新 context（修复原项目 M1 Bug）
"""

import json


class DictObj:
    """同时支持字典式和属性式访问的容器。

    赋值 dict 时自动递归转为 DictObj，保证链式属性访问始终可用。
    """

    def __init__(self, attr=None):
        if attr is None:
            attr = {}
        for key, value in attr.items():
            if isinstance(value, dict):
                attr[key] = DictObj(value)
        super().__setattr__("_attributes", attr)

    # ---- 序列化 / 反序列化 ----

    def __getstate__(self):
        state = self._attributes.copy()
        for key, value in state.items():
            if isinstance(value, DictObj):
                state[key] = value.__getstate__()
        return state

    def __setstate__(self, state):
        for key, value in state.items():
            if isinstance(value, dict):
                state[key] = DictObj(value)
        super().__setattr__("_attributes", state)

    # ---- 字典协议 ----

    def __getitem__(self, key):
        return self._attributes[key]

    def __setitem__(self, key, value):
        if isinstance(value, dict):
            value = DictObj(value)
        self._attributes[key] = value

    def __delitem__(self, key):
        del self._attributes[key]

    def __contains__(self, key):
        return key in self._attributes

    def __iter__(self):
        return iter(self._attributes)

    def __len__(self):
        return len(self._attributes)

    def get(self, key, default=None):
        return self._attributes.get(key, default)

    def setdefault(self, key, default=None):
        """同 dict.setdefault，缺失时创建并返回默认值。"""
        if key not in self._attributes:
            if isinstance(default, dict):
                default = DictObj(default)
            self._attributes[key] = default
        return self._attributes[key]

    def keys(self):
        return self._attributes.keys()

    def values(self):
        return self._attributes.values()

    def items(self):
        return self._attributes.items()

    def push(self, key, value):
        self[key] = value

    def pop(self, key, default=None):
        return self._attributes.pop(key, default)

    # ---- 属性协议 ----

    def __getattr__(self, name):
        try:
            return self._attributes[name]
        except KeyError:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )

    def __setattr__(self, name, value):
        if name == "_attributes":
            super().__setattr__(name, value)
        else:
            if isinstance(value, dict):
                value = DictObj(value)
            self._attributes[name] = value

    # ---- 表示 ----

    def __str__(self):
        attrs = ", ".join(f"{k}={v!r}" for k, v in self._attributes.items())
        return f"{type(self).__name__}({attrs})"

    def __repr__(self):
        return self.__str__()

    def to_json(self):
        return json.dumps(self.__getstate__(), ensure_ascii=False)


# ---------------------------------------------------------------------------
# 工厂函数：每次调用返回全新 context
# ---------------------------------------------------------------------------

def create_context():
    """创建并返回一个全新的回测上下文对象。

    字段结构对标原项目 context_attr，所有嵌套 dict 自动转为 DictObj。
    """
    return DictObj({
        "id": "",
        "universe": [],
        "previous_date": None,
        "previous_dt": None,
        "current_dt": None,
        "params": None,

        "trade": {
            "market": "",
            "model_id": "",
            "start_time": "",
            "end_time": "",
            "benchmark": "000001",
            "log_type": "",
            "record_type": "",
            "strategy": "",
            "order_volume_ratio": 1,
            "slip": 0,
            "sliptype": "pricerelated",
            "rule_list": "",
            "asset_type": "stock",
        },

        "g": {},

        "account": {
            "username": "",
            "password": "",
            "account_id": "",
            "open_tax": 0,
            "close_tax": 0.001,
            "open_commission": 0.0003,
            "close_commission": 0.0003,
            "close_today_commission": 0,
            "min_commission": 5,
        },

        "portfolio": {
            "inout_cash": 0,
            "cash": 0,
            "transferable_cash": 0,
            "locked_cash": 0,
            "margin": 0,
            "total_value": 0,
            "previous_value": 0,
            "returns": 0,
            "starting_cash": 0,
            "positions_value": 0,
            "portfolio_value": 0,
            "locked_cash_by_purchase": 0,
            "locked_cash_by_redeem": 0,
            "locked_amound_by_redeen": 0,
            "positions": {},
        },

        "data": {
            "calendar": [],
            "event_list": [],
            "data_source": "file",
            "daily_info": None,
            "dividend": {},
            "quote": None,
            "client": None, 
            "data_path": None
        },

        "logs": {
            "trade_list": [],
            "order_list": [],
            "position_list": [],
            "return_list": [],
            "trade_returns": [],
            "history": {},
        },

        "performance": {
            "returns": [],
            "bench_returns": [],
            "turnover": [],
            "position_ratio": [],
            "position_snapshots": [],
            "win": 0,
            "win_ratio": 0,
            "trade_num": 0,
            "indicators": {},
        },
    })
