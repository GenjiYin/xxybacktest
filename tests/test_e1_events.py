"""E1 事件定义与加载测试"""

import sys
import os
from datetime import datetime, time as dtime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.events import Event, load_events, insert_event, register_daily


# ------------------------------------------------------------------
# Event 基础
# ------------------------------------------------------------------

def test_event_creation():
    """Event 构造和属性访问。"""
    dt = datetime(2024, 1, 2, 9, 30, 0)
    called = []
    func = lambda ctx: called.append(1)
    e = Event(dt, func, "test")

    assert e.dt == dt
    assert e.name == "test"
    e.func(None)
    assert called == [1]


def test_event_ordering():
    """Event 按 dt 排序。"""
    e1 = Event(datetime(2024, 1, 2, 9, 0, 0), lambda c: None, "early")
    e2 = Event(datetime(2024, 1, 2, 23, 59, 59), lambda c: None, "late")
    e3 = Event(datetime(2024, 1, 3, 9, 0, 0), lambda c: None, "next_day")

    events = [e3, e1, e2]
    events.sort()
    assert events[0].name == "early"
    assert events[1].name == "late"
    assert events[2].name == "next_day"


# ------------------------------------------------------------------
# load_events
# ------------------------------------------------------------------

def test_load_events_basic():
    """3 个交易日应生成 6 个事件（每天 2 个内置事件）。"""
    calendar = ["2024-01-02", "2024-01-03", "2024-01-04"]
    calls = []
    handlers = {
        "before_market": lambda ctx: calls.append("bm"),
        "end_interval": lambda ctx: calls.append("ei"),
    }
    events = load_events(calendar, handlers)

    assert len(events) == 6  # 3 天 × 2 事件


def test_load_events_sorted():
    """生成的事件列表严格按时间升序。"""
    calendar = ["2024-01-02", "2024-01-03", "2024-01-04"]
    handlers = {
        "before_market": lambda ctx: None,
        "end_interval": lambda ctx: None,
    }
    events = load_events(calendar, handlers)

    for i in range(len(events) - 1):
        assert events[i].dt <= events[i + 1].dt


def test_load_events_daily_order():
    """同一天内事件顺序：before_market(09:00) < end_interval(23:59:59)。"""
    calendar = ["2024-01-02"]
    handlers = {
        "before_market": lambda ctx: None,
        "end_interval": lambda ctx: None,
    }
    events = load_events(calendar, handlers)

    assert len(events) == 2
    assert events[0].name == "before_market"
    assert events[0].dt == datetime(2024, 1, 2, 9, 0, 0)
    assert events[1].name == "end_interval"
    assert events[1].dt == datetime(2024, 1, 2, 23, 59, 59)


def test_load_events_datetime_type():
    """事件的 dt 是 datetime 对象（含时间分量），不是纯 date。"""
    calendar = ["2024-01-02"]
    handlers = {
        "before_market": lambda ctx: None,
        "end_interval": lambda ctx: None,
    }
    events = load_events(calendar, handlers)

    for e in events:
        assert isinstance(e.dt, datetime)
        assert e.dt.time() != dtime(0, 0, 0) or e.name == "start_interval"


def test_load_events_partial_handlers():
    """只传部分 handler 时，只生成对应事件。"""
    calendar = ["2024-01-02"]
    handlers = {
        "end_interval": lambda ctx: None,
    }
    events = load_events(calendar, handlers)

    assert len(events) == 1
    assert events[0].name == "end_interval"


def test_load_events_empty_calendar():
    """空日历返回空列表。"""
    handlers = {
        "before_market": lambda ctx: None,
        "end_interval": lambda ctx: None,
    }
    events = load_events([], handlers)
    assert events == []


def test_load_events_callback_executable():
    """回调函数能正确执行。"""
    calendar = ["2024-01-02"]
    results = []
    handlers = {
        "before_market": lambda ctx: results.append("bm"),
        "end_interval": lambda ctx: results.append("ei"),
    }
    events = load_events(calendar, handlers)

    for e in events:
        e.func(None)

    assert results == ["bm", "ei"]


# ------------------------------------------------------------------
# insert_event
# ------------------------------------------------------------------

def test_insert_event_maintains_order():
    """插入事件后列表仍保持有序。"""
    calendar = ["2024-01-02", "2024-01-03"]
    handlers = {
        "before_market": lambda ctx: None,
        "end_interval": lambda ctx: None,
    }
    events = load_events(calendar, handlers)

    # 在 1/2 下午插入一个事件
    new_event = Event(datetime(2024, 1, 2, 15, 0, 0), lambda ctx: None, "custom")
    insert_event(events, new_event)

    assert len(events) == 5
    for i in range(len(events) - 1):
        assert events[i].dt <= events[i + 1].dt

    # 确认插入位置正确：before_market(09:00) < custom(15:00) < end_interval(23:59)
    jan2_events = [e for e in events if e.dt.date().day == 2]
    assert jan2_events[0].name == "before_market"
    assert jan2_events[1].name == "custom"
    assert jan2_events[2].name == "end_interval"


# ------------------------------------------------------------------
# register_daily
# ------------------------------------------------------------------

def test_register_daily_basic():
    """register_daily 为每个交易日插入用户事件。"""
    calendar = ["2024-01-02", "2024-01-03", "2024-01-04"]
    handlers = {
        "before_market": lambda ctx: None,
        "end_interval": lambda ctx: None,
    }
    events = load_events(calendar, handlers)
    assert len(events) == 6

    register_daily(events, calendar, lambda ctx: None, "9:30", "my_strategy")
    assert len(events) == 9  # 多了 3 个用户事件

    # 列表仍有序
    for i in range(len(events) - 1):
        assert events[i].dt <= events[i + 1].dt


def test_register_daily_time_parsing():
    """支持多种时间格式。"""
    calendar = ["2024-01-02"]
    events = []

    register_daily(events, calendar, lambda ctx: None, "9:30", "t1")
    assert events[0].dt == datetime(2024, 1, 2, 9, 30, 0)

    events.clear()
    register_daily(events, calendar, lambda ctx: None, "09:30", "t2")
    assert events[0].dt == datetime(2024, 1, 2, 9, 30, 0)

    events.clear()
    register_daily(events, calendar, lambda ctx: None, "09:30:00", "t3")
    assert events[0].dt == datetime(2024, 1, 2, 9, 30, 0)

    events.clear()
    register_daily(events, calendar, lambda ctx: None, "14:55:30", "t4")
    assert events[0].dt == datetime(2024, 1, 2, 14, 55, 30)


def test_register_daily_position_in_day():
    """用户事件(09:30)应在 before_market(09:00) 之后、end_interval(23:59) 之前。"""
    calendar = ["2024-01-02"]
    handlers = {
        "before_market": lambda ctx: None,
        "end_interval": lambda ctx: None,
    }
    events = load_events(calendar, handlers)
    register_daily(events, calendar, lambda ctx: None, "9:30", "strategy")

    assert len(events) == 3
    assert events[0].name == "before_market"    # 09:00
    assert events[1].name == "strategy"          # 09:30
    assert events[2].name == "end_interval"      # 23:59:59


if __name__ == "__main__":
    test_event_creation()
    test_event_ordering()
    test_load_events_basic()
    test_load_events_sorted()
    test_load_events_daily_order()
    test_load_events_datetime_type()
    test_load_events_partial_handlers()
    test_load_events_empty_calendar()
    test_load_events_callback_executable()
    test_insert_event_maintains_order()
    test_register_daily_basic()
    test_register_daily_time_parsing()
    test_register_daily_position_in_day()
    print("All E1 tests passed.")
