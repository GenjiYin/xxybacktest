"""
B4 测试：分红送股数据接口

测试 Data.get_dividend() 和 Data.get_dividend_by_pay_date()
"""

import sys
import os
from datetime import datetime

# 让 import xxybacktest 能找到
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.data import Data, DividendInfo
from xxybacktest.context import create_context


# ---------------------------------------------------------------------------
# 固定测试数据路径
# ---------------------------------------------------------------------------
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data")


def setup_module():
    """模块级初始化 db 连接。"""
    Data.init_db(path=DATA_PATH)


# ===========================================================================
# get_dividend 测试
# ===========================================================================


class TestGetDividend:
    """测试 Data.get_dividend —— 按 register_date 查询当日分红登记。"""

    def _make_context(self, date_str):
        ctx = create_context()
        ctx.current_dt = datetime.strptime(date_str, "%Y-%m-%d")
        return ctx

    def test_no_dividend_date(self):
        """非分红登记日应返回空 dict。"""
        ctx = self._make_context("2019-01-01")
        result = Data.get_dividend(ctx)
        assert result == {}

    def test_has_dividend_cash_only(self):
        """2019-01-04 是 002385.SZ 的 register_date，纯派现。"""
        ctx = self._make_context("2019-01-04")
        result = Data.get_dividend(ctx)
        assert "002385.SZ" in result
        rec = result["002385.SZ"]
        # 纯派现：bonus_rate=NaN, conversed_rate=NaN → stk_div=0
        assert rec.stk_div == 0.0
        # cash_after_tax = 0.072
        assert abs(rec.cash_div_tax - 0.072) < 1e-6
        # ex_date = 2019-01-07
        assert rec.ex_date == "2019-01-07"
        assert rec.pay_date == "2019-01-07"

    def test_has_dividend_with_stock(self):
        """找一个有送股/转增的 register_date，验证 stk_div = bonus_rate + conversed_rate。"""
        # 2019-03-12 是 300125.SZ 的 register_date，conversed_rate=0.50925
        ctx = self._make_context("2019-03-12")
        result = Data.get_dividend(ctx)
        assert "300125.SZ" in result
        rec = result["300125.SZ"]
        # bonus_rate=NaN → 0, conversed_rate=0.50925 → stk_div ≈ 0.50925
        assert abs(rec.stk_div - 0.50925) < 1e-5
        # cash_after_tax=NaN → 0
        assert rec.cash_div_tax == 0.0
        assert rec.ex_date == "2019-03-13"

    def test_explicit_date_param(self):
        """传入 date 参数覆盖 context.current_dt。"""
        ctx = self._make_context("2000-01-01")  # 无关日期
        result = Data.get_dividend(ctx, date="2019-01-04")
        assert "002385.SZ" in result

    def test_multiple_dividends_same_date(self):
        """同一 register_date 可能有多只股票分红。"""
        # 2019-03-27 有 600276.SH 和 603225.SH
        ctx = self._make_context("2019-03-27")
        result = Data.get_dividend(ctx)
        assert "600276.SH" in result
        assert "603225.SH" in result

    def test_return_type(self):
        """返回值的每条记录应为 DividendInfo。"""
        ctx = self._make_context("2019-01-04")
        result = Data.get_dividend(ctx)
        for code, rec in result.items():
            assert isinstance(rec, DividendInfo)
            assert hasattr(rec, "stk_div")
            assert hasattr(rec, "cash_div_tax")
            assert hasattr(rec, "ex_date")
            assert hasattr(rec, "pay_date")


# ===========================================================================
# get_dividend_by_pay_date 测试
# ===========================================================================


class TestGetDividendByPayDate:
    """测试 Data.get_dividend_by_pay_date —— 按 ex_date 区间查询。"""

    def test_empty_range(self):
        """无分红数据的日期区间应返回空 dict。"""
        result = Data.get_dividend_by_pay_date("2000-01-01", "2000-01-31")
        assert result == {}

    def test_known_range(self):
        """2019-01-07 ~ 2019-01-09 区间内有 3 条分红记录。"""
        result = Data.get_dividend_by_pay_date("2019-01-07", "2019-01-09")
        # 应有以下 ex_date keys
        assert "2019-01-07" in result  # 002385.SZ
        assert "2019-01-08" in result  # 002607.SZ
        assert "2019-01-09" in result  # 603113.SH

        # 验证具体记录
        rec = result["2019-01-07"]["002385.SZ"]
        assert abs(rec.cash_div_tax - 0.072) < 1e-6
        assert rec.stk_div == 0.0

    def test_structure(self):
        """返回值为两层嵌套 dict：pay_date -> code -> DividendInfo。"""
        result = Data.get_dividend_by_pay_date("2019-01-07", "2019-01-07")
        assert isinstance(result, dict)
        for pay_date, codes_dict in result.items():
            assert isinstance(pay_date, str)
            assert isinstance(codes_dict, dict)
            for code, rec in codes_dict.items():
                assert isinstance(rec, DividendInfo)

    def test_includes_stock_dividend(self):
        """区间内包含有送转股的记录。"""
        # 300125.SZ ex_date=2019-03-13
        result = Data.get_dividend_by_pay_date("2019-03-13", "2019-03-13")
        assert "2019-03-13" in result
        assert "300125.SZ" in result["2019-03-13"]
        rec = result["2019-03-13"]["300125.SZ"]
        assert abs(rec.stk_div - 0.50925) < 1e-5

if __name__ == '__main__':
    setup_module()

    t1 = TestGetDividend()
    t1.test_no_dividend_date()
    print("  [PASS] test_no_dividend_date")
    t1.test_has_dividend_cash_only()
    print("  [PASS] test_has_dividend_cash_only")
    t1.test_has_dividend_with_stock()
    print("  [PASS] test_has_dividend_with_stock")
    t1.test_explicit_date_param()
    print("  [PASS] test_explicit_date_param")
    t1.test_multiple_dividends_same_date()
    print("  [PASS] test_multiple_dividends_same_date")
    t1.test_return_type()
    print("  [PASS] test_return_type")

    t2 = TestGetDividendByPayDate()
    t2.test_empty_range()
    print("  [PASS] test_empty_range")
    t2.test_known_range()
    print("  [PASS] test_known_range")
    t2.test_structure()
    print("  [PASS] test_structure")
    t2.test_includes_stock_dividend()
    print("  [PASS] test_includes_stock_dividend")

    print("\nAll B4 tests passed.")