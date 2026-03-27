"""B2 日线行情接口测试"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.data import Data
from xxybacktest.context import DictObj

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data")


def setup_module():
    Data.init_db(DATA_PATH)


def make_context(dt_str):
    """构造一个带 current_dt 的简易 context。"""
    ctx = DictObj({"current_dt": datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")})
    return ctx


def test_basic_query():
    """查询正常交易日的平安银行，字段齐全。"""
    ctx = make_context("2024-01-02 09:30:00")
    info = Data.get_daily_info("000001.SZ", ctx)
    assert info is not None
    # 必须包含所有核心字段
    for field in ["open", "high", "low", "close", "volume", "amount",
                  "name", "vwap", "upLimit", "downLimit", "stop",
                  "pre_close", "st_status", "ts_code"]:
        assert hasattr(info, field), f"缺少字段: {field}"


def test_price_range():
    """价格字段的基本合理性：low <= open/close <= high。"""
    ctx = make_context("2024-01-02 15:00:00")
    info = Data.get_daily_info("000001.SZ", ctx)
    assert info.low <= info.open <= info.high
    assert info.low <= info.close <= info.high


def test_vwap_reasonable():
    """vwap 应在 low 和 high 之间。"""
    ctx = make_context("2024-01-02 15:00:00")
    info = Data.get_daily_info("000001.SZ", ctx)
    assert info.low <= info.vwap <= info.high, (
        f"vwap={info.vwap} 不在 [{info.low}, {info.high}] 区间"
    )


def test_limit_price():
    """涨停价 > 跌停价，且 close 在涨跌停之间。"""
    ctx = make_context("2024-01-02 15:00:00")
    info = Data.get_daily_info("000001.SZ", ctx)
    assert info.upLimit > info.downLimit
    assert info.downLimit <= info.close <= info.upLimit


def test_explicit_date():
    """通过 date 参数指定日期，忽略 context.current_dt。"""
    ctx = make_context("2099-01-01 10:00:00")  # 不存在的日期
    info = Data.get_daily_info("000001.SZ", ctx, date="2024-01-02")
    assert info is not None
    assert info.ts_code == "000001.SZ"


def test_nonexistent_returns_none():
    """查询不存在的股票/日期返回 None。"""
    ctx = make_context("2024-01-02 09:30:00")
    assert Data.get_daily_info("999999.SZ", ctx) is None
    # 周末查询
    assert Data.get_daily_info("000001.SZ", ctx, date="2024-01-06") is None


def test_stop_field():
    """正常交易日 stop 应为 0。"""
    ctx = make_context("2024-01-02 09:30:00")
    info = Data.get_daily_info("000001.SZ", ctx)
    assert info.stop == 0


def test_volume_is_shares():
    """volume 单位是股，应远大于 100。"""
    ctx = make_context("2024-01-02 09:30:00")
    info = Data.get_daily_info("000001.SZ", ctx)
    # 平安银行日成交量至少百万股级别
    assert info.volume > 1000000


if __name__ == "__main__":
    setup_module()
    test_basic_query()
    test_price_range()
    test_vwap_reasonable()
    test_limit_price()
    test_explicit_date()
    test_nonexistent_returns_none()
    test_stop_field()
    test_volume_is_shares()
    print("All B2 tests passed.")
