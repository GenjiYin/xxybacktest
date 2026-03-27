"""H3 回测主循环测试

验证主循环能端到端跑通：事件驱动、时间更新、日终估值。
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.backtest import run_backtest

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data")


# ------------------------------------------------------------------
# 基础：主循环能跑通
# ------------------------------------------------------------------

def test_empty_strategy():
    """空策略（什么都不做）能跑完，返回 context。"""
    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=lambda ctx: None,
        start_date="2024-01-02",
        end_date="2024-01-05",
        capital=1000000,
        data_path=DATA_PATH,
    )
    assert ctx is not None
    assert ctx.portfolio.cash == 1000000
    assert ctx.portfolio.total_value == 1000000


def test_calendar_stored():
    """交易日历应存入 context.data.calendar。"""
    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=lambda ctx: None,
        start_date="2024-01-02",
        end_date="2024-01-05",
        capital=1000000,
        data_path=DATA_PATH,
    )
    assert len(ctx.data.calendar) > 0
    for d in ctx.data.calendar:
        assert len(d) == 10  # 'YYYY-MM-DD'


# ------------------------------------------------------------------
# current_dt 约定验证（B3 依赖的关键点）
# ------------------------------------------------------------------

def test_current_dt_is_datetime():
    """回测结束后 current_dt 应为 datetime 对象（含时间分量）。"""
    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=lambda ctx: None,
        start_date="2024-01-02",
        end_date="2024-01-03",
        capital=1000000,
        data_path=DATA_PATH,
    )
    # 最后一个事件执行完后 current_dt 应是最后一天的 end_interval
    assert isinstance(ctx.current_dt, datetime)
    assert ctx.current_dt.hour == 23
    assert ctx.current_dt.minute == 59


def test_current_dt_during_strategy():
    """策略执行时 current_dt 应为 09:30。"""
    recorded_times = []

    def my_strategy(ctx):
        recorded_times.append(ctx.current_dt)

    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=my_strategy,
        start_date="2024-01-02",
        end_date="2024-01-03",
        capital=1000000,
        data_path=DATA_PATH,
    )

    assert len(recorded_times) == len(ctx.data.calendar)
    for dt in recorded_times:
        assert dt.hour == 9
        assert dt.minute == 30


# ------------------------------------------------------------------
# previous_date 更新
# ------------------------------------------------------------------

def test_previous_date_updates():
    """策略执行时 previous_date 应为上一个交易日。"""
    records = []

    def my_strategy(ctx):
        records.append({
            "current": ctx.current_dt.strftime("%Y-%m-%d"),
            "previous": ctx.previous_date,
        })

    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=my_strategy,
        start_date="2024-01-02",
        end_date="2024-01-05",
        capital=1000000,
        data_path=DATA_PATH,
    )

    calendar = ctx.data.calendar
    # 第一天 previous_date 为 None
    assert records[0]["previous"] is None
    # 后续每天的 previous_date 为前一个交易日
    for i in range(1, len(records)):
        assert records[i]["previous"] == calendar[i - 1]


# ------------------------------------------------------------------
# 日终估值（E4）
# ------------------------------------------------------------------

def test_daily_returns_recorded():
    """每个交易日应记录一条净值比（G1 后 returns 为 pd.Series 涨跌幅）。"""
    import pandas as pd

    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=lambda ctx: None,
        start_date="2024-01-02",
        end_date="2024-01-05",
        capital=1000000,
        data_path=DATA_PATH,
    )
    # G1 后 returns 是 pd.Series（涨跌幅），无持仓时每日涨跌幅 = 0.0
    assert isinstance(ctx.performance.returns, pd.Series)
    assert len(ctx.performance.returns) == len(ctx.data.calendar)
    for ret in ctx.performance.returns:
        assert ret == 0.0  # 净值比 1.0 → 涨跌幅 0.0


def test_no_position_value_unchanged():
    """无持仓时 total_value 应始终等于初始资金。"""
    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=lambda ctx: None,
        start_date="2024-01-02",
        end_date="2024-01-10",
        capital=500000,
        data_path=DATA_PATH,
    )
    assert ctx.portfolio.cash == 500000
    assert ctx.portfolio.total_value == 500000
    assert ctx.portfolio.positions_value == 0


# ------------------------------------------------------------------
# run_daily 注册
# ------------------------------------------------------------------

def test_run_daily_in_initialize():
    """用户在 initialize 中通过 run_daily 注册策略。"""
    call_count = []

    def my_init(ctx):
        ctx.run_daily(lambda c: call_count.append(1), "9:30")

    ctx = run_backtest(
        initialize=my_init,
        handle_data=None,
        start_date="2024-01-02",
        end_date="2024-01-05",
        capital=1000000,
        data_path=DATA_PATH,
    )
    # 每个交易日执行一次
    assert len(call_count) == len(ctx.data.calendar)


def test_event_order_within_day():
    """同一天内事件顺序：before_market(09:00) → strategy(09:30) → end_interval(23:59)。"""
    event_log = []

    def my_init(ctx):
        pass

    # 用 handle_data 记录策略执行时间
    def my_strategy(ctx):
        event_log.append(("strategy", ctx.current_dt))

    # 我们无法直接记录内置事件，但可以验证策略执行时 enable_amount 已刷新
    # 这里只验证策略确实在 09:30 执行
    ctx = run_backtest(
        initialize=my_init,
        handle_data=my_strategy,
        start_date="2024-01-02",
        end_date="2024-01-02",
        capital=1000000,
        data_path=DATA_PATH,
    )
    assert len(event_log) == 1
    assert event_log[0][1].hour == 9
    assert event_log[0][1].minute == 30


# ------------------------------------------------------------------
# 参数传递
# ------------------------------------------------------------------

def test_capital_setting():
    """初始资金参数正确传入 context。"""
    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=lambda ctx: None,
        start_date="2024-01-02",
        end_date="2024-01-03",
        capital=2000000,
        data_path=DATA_PATH,
    )
    assert ctx.portfolio.starting_cash == 2000000
    assert ctx.portfolio.cash == 2000000


def test_empty_calendar():
    """无交易日（如周末到周末）时应正常返回。"""
    ctx = run_backtest(
        initialize=lambda ctx: None,
        handle_data=lambda ctx: None,
        start_date="2024-01-06",
        end_date="2024-01-07",  # 周六到周日
        capital=1000000,
        data_path=DATA_PATH,
    )
    assert ctx.portfolio.cash == 1000000
    assert len(ctx.data.calendar) == 0

def test_print_date():
    from xxybacktest.data import Data
    from xxybacktest.types import Context

    def initial(context):
        pass

    def handle_data(context: Context):
        print(Data.get_daily_info('000001.SZ', context))

    ctx = run_backtest(
        initialize=initial,
        handle_data=handle_data,
        start_date="2023-12-20",
        end_date="2024-01-07",  # 周六到周日
        capital=1000000,
        data_path=DATA_PATH,
    )
    


if __name__ == "__main__":
    test_empty_strategy()
    test_calendar_stored()
    test_current_dt_is_datetime()
    test_current_dt_during_strategy()
    test_previous_date_updates()
    test_daily_returns_recorded()
    test_no_position_value_unchanged()
    test_run_daily_in_initialize()
    test_event_order_within_day()
    test_capital_setting()
    test_empty_calendar()
    print("All H3 tests passed.")

    test_print_date()
