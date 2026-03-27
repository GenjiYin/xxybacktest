"""B1 交易日历接口测试"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.data import Data

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data")


def setup_module():
    Data.init_db(DATA_PATH)


def test_basic_range():
    """基本区间查询，返回非空列表且元素格式正确。"""
    days = Data.get_trade_calendar("2024-01-01", "2024-01-31")
    assert len(days) > 0
    for d in days:
        assert len(d) == 10 and d[4] == "-" and d[7] == "-"


def test_sorted_order():
    """返回结果按日期升序。"""
    days = Data.get_trade_calendar("2024-01-01", "2024-12-31")
    assert days == sorted(days)


def test_excludes_weekends_and_holidays():
    """2024 春节假期（2月10~17日）不应出现交易日。"""
    days = Data.get_trade_calendar("2024-02-10", "2024-02-17")
    # 春节期间 A 股休市，这段时间内交易日应很少甚至为 0
    assert len(days) <= 1  # 最多只有节前最后一天或节后第一天


def test_boundary_inclusive():
    """起止日期如果本身是交易日，应包含在结果中。"""
    # 2024-01-02 是 A 股交易日（元旦后第一个工作日）
    days = Data.get_trade_calendar("2024-01-02", "2024-01-02")
    assert days == ["2024-01-02"]


def test_empty_range():
    """周末两天查询应返回空列表。"""
    # 2024-01-06 是周六，2024-01-07 是周日
    days = Data.get_trade_calendar("2024-01-06", "2024-01-07")
    assert days == []


def test_full_year_count():
    """2024 全年 A 股交易日数量应在 240~250 之间。"""
    days = Data.get_trade_calendar("2024-01-01", "2024-12-31")
    assert 240 <= len(days) <= 250


if __name__ == "__main__":
    setup_module()
    test_basic_range()
    test_sorted_order()
    test_excludes_weekends_and_holidays()
    test_boundary_inclusive()
    test_empty_range()
    test_full_year_count()
    print("All B1 tests passed.")
