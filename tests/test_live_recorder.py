"""
live/recorder.py 测试

不依赖 QMT，使用临时目录运行。
运行：python tests/test_live_recorder.py
"""

import os
import sys
import tempfile
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.context import create_context
from xxybacktest.objects import Order, Position
from xxybacktest.live.recorder import _save_live_results


# 模拟账户 ID
_TEST_ACCOUNT = "86962531"


def _make_context(cash=900000.0, total_value=1200000.0, starting_cash=1000000.0,
                  positions=None, orders=None, date_str="2026-05-20"):
    """构造一个最小化的实盘 context。"""
    ctx = create_context()
    ctx.portfolio.cash = cash
    ctx.portfolio.total_value = total_value
    ctx.portfolio.starting_cash = starting_cash
    ctx.current_dt = datetime.strptime(date_str, "%Y-%m-%d")
    ctx.logs.order_list = orders or []

    if positions:
        for code, pos_info in positions.items():
            p = Position(
                code=code,
                amount=pos_info["amount"],
                enable_amount=pos_info.get("enable_amount", pos_info["amount"]),
                last_sale_price=pos_info["last_price"],
            )
            p.cost_basis = pos_info.get("cost_basis", pos_info["last_price"])
            p.total_cost = p.amount * p.cost_basis
            p.total_value = p.amount * p.last_sale_price
            ctx.portfolio.positions[code] = p

    return ctx


def _make_order(code, amount, is_buy, price, status=1, date_str="2026-05-20"):
    """构造一个实盘 Order。"""
    o = Order(code, amount, is_buy, price, info=None)
    o.status = status
    o.date = datetime.strptime(date_str, "%Y-%m-%d")
    o.cost = 5.0 if status == 1 else 0.0
    return o


def _cleanup(data_path):
    """删除测试账户目录。"""
    import shutil
    d = os.path.join(data_path, "live", "accounts", _TEST_ACCOUNT)
    if os.path.exists(d):
        shutil.rmtree(d)


# ---------------------------------------------------------------------------
# 测试：首次运行生成三个 parquet 文件
# ---------------------------------------------------------------------------

def test_first_run_creates_all_files():
    """首次运行应生成 daily_values / positions / orders 三个 parquet。"""
    with tempfile.TemporaryDirectory() as tmp:
        _cleanup(tmp)
        ctx = _make_context(
            cash=900000.0,
            total_value=1200000.0,
            starting_cash=1000000.0,
            positions={
                "000001.SZ": {
                    "amount": 1000,
                    "last_price": 10.5,
                    "cost_basis": 10.0,
                },
                "600519.SH": {
                    "amount": 500,
                    "last_price": 200.0,
                    "cost_basis": 195.0,
                },
            },
            orders=[
                _make_order("000001.SZ", 1000, True, 10.5),
                _make_order("600519.SH", 500, True, 200.0),
            ],
        )
        _save_live_results(_TEST_ACCOUNT, ctx, tmp)

        account_dir = os.path.join(tmp, "live", "accounts", _TEST_ACCOUNT)
        for fname in ("daily_values.parquet", "positions.parquet", "orders.parquet"):
            path = os.path.join(account_dir, fname)
            assert os.path.exists(path), f"文件不存在: {fname}"

        print("[PASS] 首次运行生成三个 parquet 文件")
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# 测试：列结构与模拟交易一致
# ---------------------------------------------------------------------------

def test_columns_match_simulation():
    """各 parquet 的列名应与 simulation/runner.py 的 _save_results 一致。"""
    with tempfile.TemporaryDirectory() as tmp:
        _cleanup(tmp)
        ctx = _make_context(
            positions={"000001.SZ": {"amount": 1000, "last_price": 10.0, "cost_basis": 9.5}},
            orders=[_make_order("000001.SZ", 1000, True, 10.0)],
        )
        _save_live_results(_TEST_ACCOUNT, ctx, tmp)

        account_dir = os.path.join(tmp, "live", "accounts", _TEST_ACCOUNT)

        # daily_values
        df_nav = pd.read_parquet(os.path.join(account_dir, "daily_values.parquet"))
        assert list(df_nav.columns) == ["date", "nav", "daily_return"]

        # positions
        df_pos = pd.read_parquet(os.path.join(account_dir, "positions.parquet"))
        expected_pos_cols = [
            "date", "instrument", "name", "volume", "ratio",
            "cum_profit", "cum_return", "close_price", "avg_cost",
        ]
        assert list(df_pos.columns) == expected_pos_cols

        # orders
        df_ord = pd.read_parquet(os.path.join(account_dir, "orders.parquet"))
        expected_ord_cols = ["date", "instrument", "name", "volume", "side", "status", "price", "cost"]
        assert list(df_ord.columns) == expected_ord_cols

        print("[PASS] 列名与 simulation _save_results 一致")
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# 测试：nav 与 daily_return 计算
# ---------------------------------------------------------------------------

def test_nav_calculation():
    """nav = total_value / starting_cash。"""
    with tempfile.TemporaryDirectory() as tmp:
        _cleanup(tmp)
        ctx = _make_context(
            cash=800000.0,
            total_value=1500000.0,
            starting_cash=1000000.0,
        )
        _save_live_results(_TEST_ACCOUNT, ctx, tmp)

        df_nav = pd.read_parquet(os.path.join(tmp, "live", "accounts", _TEST_ACCOUNT, "daily_values.parquet"))
        assert len(df_nav) == 1
        assert abs(df_nav["nav"].iloc[0] - 1.5) < 1e-9
        assert abs(df_nav["daily_return"].iloc[0] - 0.0) < 1e-9  # 首次运行

        print("[PASS] nav 计算正确 (首次 daily_return = 0)")
        _cleanup(tmp)


def test_second_run_appends_nav():
    """二次运行 daily_values 应追加一行，daily_return 基于前一条 nav 计算。"""
    with tempfile.TemporaryDirectory() as tmp:
        _cleanup(tmp)

        # 第一次：nav = 1.0
        ctx1 = _make_context(
            cash=900000.0,
            total_value=1000000.0,
            starting_cash=1000000.0,
            date_str="2026-05-19",
        )
        _save_live_results(_TEST_ACCOUNT, ctx1, tmp)

        # 第二次：nav = 1.1
        ctx2 = _make_context(
            cash=900000.0,
            total_value=1100000.0,
            starting_cash=1000000.0,
            date_str="2026-05-20",
        )
        _save_live_results(_TEST_ACCOUNT, ctx2, tmp)

        df_nav = pd.read_parquet(os.path.join(tmp, "live", "accounts", _TEST_ACCOUNT, "daily_values.parquet"))
        assert len(df_nav) == 2
        assert abs(df_nav["nav"].iloc[0] - 1.0) < 1e-9
        assert abs(df_nav["nav"].iloc[1] - 1.1) < 1e-9
        assert abs(df_nav["daily_return"].iloc[1] - 0.1) < 1e-9

        print("[PASS] 二次运行 daily_values 正确追加，daily_return = 0.1")
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# 测试：positions 覆盖写入
# ---------------------------------------------------------------------------

def test_positions_overwrite():
    """每次运行 positions.parquet 应被覆盖为最新持仓。"""
    with tempfile.TemporaryDirectory() as tmp:
        _cleanup(tmp)

        # 第一天：2 只持仓
        ctx1 = _make_context(
            positions={
                "000001.SZ": {"amount": 1000, "last_price": 10.0, "cost_basis": 9.5},
                "600519.SH": {"amount": 500, "last_price": 200.0, "cost_basis": 195.0},
            },
            date_str="2026-05-19",
        )
        _save_live_results(_TEST_ACCOUNT, ctx1, tmp)

        df1 = pd.read_parquet(os.path.join(tmp, "live", "accounts", _TEST_ACCOUNT, "positions.parquet"))
        assert len(df1) == 2

        # 第二天：清仓一只，新增一只
        ctx2 = _make_context(
            positions={
                "000001.SZ": {"amount": 1000, "last_price": 11.0, "cost_basis": 9.5},
                "000002.SZ": {"amount": 2000, "last_price": 25.0, "cost_basis": 24.0},
            },
            date_str="2026-05-20",
        )
        _save_live_results(_TEST_ACCOUNT, ctx2, tmp)

        df2 = pd.read_parquet(os.path.join(tmp, "live", "accounts", _TEST_ACCOUNT, "positions.parquet"))
        assert len(df2) == 2
        codes = set(df2["instrument"])
        assert codes == {"000001.SZ", "000002.SZ"}
        # 最新价应更新
        row_1 = df2[df2["instrument"] == "000001.SZ"].iloc[0]
        assert abs(row_1["close_price"] - 11.0) < 1e-9

        print("[PASS] positions 每次覆盖为最新持仓")
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# 测试：orders 追加
# ---------------------------------------------------------------------------

def test_orders_append():
    """每次运行 orders.parquet 应追加新订单。"""
    with tempfile.TemporaryDirectory() as tmp:
        _cleanup(tmp)

        # 第一天：2 笔订单
        ctx1 = _make_context(
            orders=[
                _make_order("000001.SZ", 1000, True, 10.0, date_str="2026-05-19"),
                _make_order("600519.SH", 500, True, 200.0, date_str="2026-05-19"),
            ],
            date_str="2026-05-19",
        )
        _save_live_results(_TEST_ACCOUNT, ctx1, tmp)

        df1 = pd.read_parquet(os.path.join(tmp, "live", "accounts", _TEST_ACCOUNT, "orders.parquet"))
        assert len(df1) == 2

        # 第二天：1 笔新订单
        ctx2 = _make_context(
            orders=[
                _make_order("000001.SZ", 500, False, 11.0, date_str="2026-05-20"),
            ],
            date_str="2026-05-20",
        )
        _save_live_results(_TEST_ACCOUNT, ctx2, tmp)

        df2 = pd.read_parquet(os.path.join(tmp, "live", "accounts", _TEST_ACCOUNT, "orders.parquet"))
        assert len(df2) == 3
        # 排序后最新一条应是卖出
        latest = df2.sort_values("date", ascending=False).iloc[0]
        assert latest["instrument"] == "000001.SZ"
        assert latest["side"] == "sell"

        print("[PASS] orders 正确追加")
        _cleanup(tmp)


def test_no_orders_does_not_create_file():
    """没有订单时不应创建 orders.parquet（或保持为空时不新增）。"""
    with tempfile.TemporaryDirectory() as tmp:
        _cleanup(tmp)

        # 第一天：无订单
        ctx1 = _make_context(orders=[], date_str="2026-05-19")
        _save_live_results(_TEST_ACCOUNT, ctx1, tmp)

        order_path = os.path.join(tmp, "live", "accounts", _TEST_ACCOUNT, "orders.parquet")
        assert not os.path.exists(order_path), "无订单时不应生成 orders.parquet"

        # 第二天：有订单
        ctx2 = _make_context(
            orders=[_make_order("000001.SZ", 100, True, 10.0, date_str="2026-05-20")],
            date_str="2026-05-20",
        )
        _save_live_results(_TEST_ACCOUNT, ctx2, tmp)

        assert os.path.exists(order_path)
        df = pd.read_parquet(order_path)
        assert len(df) == 1

        print("[PASS] 无订单时未创建文件，有订单时正常追加")
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# 测试：空持仓
# ---------------------------------------------------------------------------

def test_empty_positions():
    """空仓时 positions.parquet 应包含正确的空结构（仅列名）。"""
    with tempfile.TemporaryDirectory() as tmp:
        _cleanup(tmp)
        ctx = _make_context(positions={})
        _save_live_results(_TEST_ACCOUNT, ctx, tmp)

        df = pd.read_parquet(os.path.join(tmp, "live", "accounts", _TEST_ACCOUNT, "positions.parquet"))
        assert df.empty
        expected_cols = [
            "date", "instrument", "name", "volume", "ratio",
            "cum_profit", "cum_return", "close_price", "avg_cost",
        ]
        assert list(df.columns) == expected_cols

        print("[PASS] 空仓时 positions 文件结构正确")
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("--- 首次运行生成三个文件 ---")
    test_first_run_creates_all_files()

    print("\n--- 列名一致性 ---")
    test_columns_match_simulation()

    print("\n--- nav 计算 ---")
    test_nav_calculation()
    test_second_run_appends_nav()

    print("\n--- positions 覆盖 ---")
    test_positions_overwrite()

    print("\n--- orders 追加 ---")
    test_orders_append()
    test_no_orders_does_not_create_file()

    print("\n--- 空仓 ---")
    test_empty_positions()

    print("\n========== All live/recorder tests passed ==========")
