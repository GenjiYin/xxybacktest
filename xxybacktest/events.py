"""
E1: 事件定义与加载

Event        — 单个事件（时间 + 回调 + 名称）
load_events  — 根据交易日历生成完整的事件列表
"""

from datetime import datetime, time as dtime


class Event:
    """回测事件。

    属性:
        dt:   datetime — 事件触发时刻（含日期和时间）
        func: callable — 回调函数，签名 func(context)
        name: str      — 事件名称（调试/日志用）
    """

    __slots__ = ("dt", "func", "name")

    def __init__(self, dt, func, name=""):
        self.dt = dt
        self.func = func
        self.name = name

    def __lt__(self, other):
        return self.dt < other.dt

    def __repr__(self):
        return f"Event({self.dt}, {self.name!r})"


# ------------------------------------------------------------------
# 每日内置事件模板
# ------------------------------------------------------------------
# (time, name) — func 在 load_events 中绑定
# Phase 1 先启用: before_market / end_interval
# Phase 2+ 追加: start_interval / morning_start / after_market

_DAILY_EVENT_TEMPLATES = [
    # (时间,          事件名,              阶段说明)
    (dtime(9, 0, 0),    "before_market"),   # E2: 刷新 enable_amount + 送股(F2)
    (dtime(9, 30, 0),   "morning_start"),   # E3: 自动卖出退市股
    (dtime(18, 0, 0),   "after_market"),    # F1: 分红派息登记与发放
    (dtime(23, 59, 59), "end_interval"),    # E4: 日终估值 + 记录收益率
]


def load_events(calendar, handlers):
    """根据交易日历和事件处理器生成完整的事件列表。

    参数:
        calendar: List[str] — 交易日列表，格式 'YYYY-MM-DD'
        handlers: dict      — 事件名 → 回调函数的映射
            必须包含:
                'before_market': func(context)  — 盘前处理
                'end_interval':  func(context)  — 日终估值
            可选包含:
                'start_interval': func(context) — 数据加载（Phase 2+）
                'morning_start':  func(context) — 退市处理（Phase 2+）
                'after_market':   func(context) — 分红派息（Phase 3+）

    返回:
        List[Event]，按 dt 升序排列。

    说明:
        用户策略事件（通过 run_daily 注册）不在此处生成，
        由 E6 run_daily 在 initialize 阶段动态插入。
    """
    event_list = []

    for date_str in calendar:
        date_part = datetime.strptime(date_str, "%Y-%m-%d").date()

        for t, name in _DAILY_EVENT_TEMPLATES:
            if name in handlers:
                dt = datetime.combine(date_part, t)
                event_list.append(Event(dt, handlers[name], name))

    # 按时间排序（同一时刻的事件保持插入顺序）
    event_list.sort()

    return event_list


def insert_event(event_list, event):
    """将单个事件按时间顺序插入已排序的事件列表。

    用于 E6 run_daily 动态注册用户策略事件。
    使用二分查找保持列表有序。

    参数:
        event_list: List[Event] — 已排序的事件列表（原地修改）
        event:      Event       — 要插入的事件
    """
    import bisect
    bisect.insort(event_list, event)


def register_daily(event_list, calendar, func, time_str, name="user_strategy"):
    """将用户回调注册为每个交易日的定时事件（E6 run_daily 的底层实现）。

    参数:
        event_list: List[Event] — 已排序的事件列表（原地修改）
        calendar:   List[str]   — 交易日列表
        func:       callable    — 用户回调，签名 func(context)
        time_str:   str         — 执行时间，如 '9:30' 或 '09:30:00'
        name:       str         — 事件名称
    """
    # 解析时间字符串，支持 'H:MM' / 'HH:MM' / 'HH:MM:SS'
    parts = time_str.strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) >= 2 else 0
    second = int(parts[2]) if len(parts) >= 3 else 0
    t = dtime(hour, minute, second)

    for date_str in calendar:
        date_part = datetime.strptime(date_str, "%Y-%m-%d").date()
        dt = datetime.combine(date_part, t)
        insert_event(event_list, Event(dt, func, name))
