import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xxybacktest.backtest import run_backtest
from xxybacktest.types import Context
from xxybacktest.trading import order_target_percent
from xxydb import xxydb

def initial(context: Context):
    # 获取数据
    # sql = f"""
    # select date, instrument, total_market_cap, close
    # from valuation
    # inner join daily_bar using (date, instrument)
    # where date >= '{context.trade.start_time}'
    # and date <= '{context.trade.end_time}'
    # and close > 5
    # and instrument not like '%B%'
    # """
    # conn = xxydb(path=context.data.data_path)
    # context.df = conn.query(sql=sql).df()
    # print(context.df.head(5))
    pass

def handle_data(context: Context):
    # df = context.df[context.df['date']==context.current_dt.strftime("%Y-%m-%d")].sort_values("total_market_cap").head(5)
    # target = list(df['instrument'])

    positions = {k: v for k, v in context.portfolio.positions.items() if v.amount > 0}
    holding = list(positions.keys())

    print(context.current_dt)

    if '601288.SH' not in holding:
        order_target_percent('601288.SH', 1, context)

    # print(holding)

    # for ins in holding:
    #     if ins not in target:
    #         order_target_percent(ins, 0, context)

    # for ins in target:
    #     if ins not in holding:
    #         order_target_percent(ins, 1 / 5, context)
    

result = run_backtest(
    initialize=initial, 
    handle_data=handle_data, 
    start_date='2019-01-01', 
    end_date='2022-02-05',
    data_path=r"E:\回测框架复现\backtest_Reproduction\data", 
    capital=10000000
)

print(result.performance)