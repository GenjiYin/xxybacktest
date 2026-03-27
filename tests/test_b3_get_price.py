"""B3 价格取值函数测试"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.data import Data
from xxybacktest.context import DictObj

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data")


def setup_module():
    Data.init_db(DATA_PATH)


def make_context(dt_str, previous_date=None):
    """构造带 current_dt 和 previous_date 的简易 context。"""
    return DictObj({
        "current_dt": datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S"),
        "previous_date": previous_date,
    })


# ------------------------------------------------------------------
# 盘前取价（time < 09:30）
# ------------------------------------------------------------------

def test_before_market_uses_previous_close():
    """盘前取价应返回上一交易日 close。"""
    # 2024-01-03 盘前，previous_date = 2024-01-02
    ctx = make_context("2024-01-03 09:00:00", previous_date="2024-01-02")
    price = Data.get_price("000001.SZ", ctx)
    assert price is not None

    # 应等于 2024-01-02 的 close
    info_prev = Data.get_daily_info("000001.SZ", ctx, date="2024-01-02")
    assert price == info_prev.close


def test_before_market_first_day_uses_pre_close():
    """首日盘前无 previous_date，应返回当日 pre_close。"""
    ctx = make_context("2024-01-02 09:00:00", previous_date=None)
    price = Data.get_price("000001.SZ", ctx)
    assert price is not None

    # 应等于当日 pre_close
    info = Data.get_daily_info("000001.SZ", ctx)
    assert price == info.pre_close


# ------------------------------------------------------------------
# 盘中取价（09:30 <= time < 15:00）
# ------------------------------------------------------------------

def test_morning_open_uses_open():
    """09:30 开盘时返回当日 open。"""
    ctx = make_context("2024-01-02 09:30:00")
    price = Data.get_price("000001.SZ", ctx)
    info = Data.get_daily_info("000001.SZ", ctx)
    assert price == info.open


def test_intraday_uses_open():
    """盘中 10:30 仍返回当日 open（日线精度）。"""
    ctx = make_context("2024-01-02 10:30:00")
    price = Data.get_price("000001.SZ", ctx)
    info = Data.get_daily_info("000001.SZ", ctx)
    assert price == info.open


def test_before_close_uses_open():
    """14:59 仍返回 open（< 15:00）。"""
    ctx = make_context("2024-01-02 14:59:00")
    price = Data.get_price("000001.SZ", ctx)
    info = Data.get_daily_info("000001.SZ", ctx)
    assert price == info.open


# ------------------------------------------------------------------
# 盘后取价（time >= 15:00）
# ------------------------------------------------------------------

def test_after_market_uses_close():
    """15:00 收盘后返回当日 close。"""
    ctx = make_context("2024-01-02 15:00:00")
    price = Data.get_price("000001.SZ", ctx)
    info = Data.get_daily_info("000001.SZ", ctx)
    assert price == info.close


def test_end_of_day_uses_close():
    """23:59 日终估值时返回 close。"""
    ctx = make_context("2024-01-02 23:59:59")
    price = Data.get_price("000001.SZ", ctx)
    info = Data.get_daily_info("000001.SZ", ctx)
    assert price == info.close


# ------------------------------------------------------------------
# 停牌 / 无数据
# ------------------------------------------------------------------

def test_nonexistent_stock_returns_none():
    """不存在的股票返回 None。"""
    ctx = make_context("2024-01-02 09:30:00")
    assert Data.get_price("999999.SZ", ctx) is None


def test_nonexistent_date_returns_none():
    """非交易日（周末）返回 None。"""
    ctx = make_context("2024-01-06 10:00:00")  # 周六
    assert Data.get_price("000001.SZ", ctx) is None


# ------------------------------------------------------------------
# 边界条件
# ------------------------------------------------------------------

def test_midnight_before_market():
    """00:00 属于盘前，应走 previous_date 分支。"""
    ctx = make_context("2024-01-03 00:00:00", previous_date="2024-01-02")
    price = Data.get_price("000001.SZ", ctx)
    info_prev = Data.get_daily_info("000001.SZ", ctx, date="2024-01-02")
    assert price == info_prev.close


def test_price_is_float():
    """返回值应为 float 类型。"""
    ctx = make_context("2024-01-02 09:30:00")
    price = Data.get_price("000001.SZ", ctx)
    assert isinstance(price, float)


if __name__ == "__main__":
    setup_module()
    test_before_market_uses_previous_close()
    test_before_market_first_day_uses_pre_close()
    test_morning_open_uses_open()
    test_intraday_uses_open()
    test_before_close_uses_open()
    test_after_market_uses_close()
    test_end_of_day_uses_close()
    test_nonexistent_stock_returns_none()
    test_nonexistent_date_returns_none()
    test_midnight_before_market()
    test_price_is_float()
    print("All B3 tests passed.")
