from xxybacktest import run_backtest, OrderCost, FixedSlippage
from xxybacktest import Context, Data
from xxybacktest.simulation import submit, run_single, get_account_nav

cost = OrderCost(
    open_tax=0,            # 买入税费（A股为0）
    close_tax=0.001,       # 卖出印花税（千分之一）
    open_commission=0.0003,  # 买入佣金（万三）
    close_commission=0.0003, # 卖出佣金（万三）
    min_commission=5,        # 单笔最低佣金（5元）
)

def init(context):
    import pandas as pd
    from xxybacktest import Context, Data

    sd = (pd.to_datetime(context.trade.start_time) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    sql = f"""
    with t1 as (
        select date, instrument, total_market_cap as cap, dividend_yield_ratio, 
        RANK() OVER (PARTITION BY date ORDER BY dividend_yield_ratio DESC) / COUNT(*) OVER (PARTITION BY date) AS rank_ratio, 
        from valuation
        inner join daily_bar using (date, instrument)
        inner join basic_info using (date, instrument)
        inner join stock_status using (date, instrument)
        where close <= 20
        and list_days >= 200
        and st_status = 0
        and suspended = 0
        and list_sector = 1
        and stock_status.is_risk_warning = 0
        and date >= '{sd}'
        and date <= '{context.trade.end_time}'
        QUALIFY rank_ratio < 0.25
    )
    select date, instrument, RANK() OVER (PARTITION BY date ORDER BY cap) / COUNT(*) OVER (PARTITION BY date) as score
    from t1
    order by date, score, dividend_yield_ratio DESC
    """
    context.df = Data._db.query(sql).df()

    context.g.index = -1

def handle_bar(context):
    context.g.index += 1
    if context.g.index % 22 != 0:
        return
    
    df = context.df[context.df['date']==context.current_dt.strftime("%Y-%m-%d")].head(5)
    target = list(df['instrument'])

    positions = {k: v for k, v in context.portfolio.positions.items() if v.amount > 0}
    holding = list(positions.keys())

    for ins in holding:
        if ins not in target:
            context.order_target_percent(ins, 0)

    for ins in target:
        if ins not in holding:
            context.order_target_percent(ins, 1 / 5)


# result = run_backtest(
#     initialize=init,
#     handle_data=handle_bar,
#     start_date="2020-11-01",
#     end_date="2026-04-03",
#     capital=60000,
#     data_path="./data",          # 你的数据目录路径
#     benchmark="000001.SH",
#     plot=True,                   # 在 Notebook 中展示回测曲线
#     order_cost=cost
# )


account_id = submit(
    name="红利", 
    initialize=init, 
    handle_data=handle_bar, 
    capital=100000, 
    start_date='2024-05-01', 
    data_path='./data', 
    asset_type='stock', 
    run_now=True
)

# # 运行模拟交易
# result = run_single(account_id)

# print(get_account_nav(account_id))