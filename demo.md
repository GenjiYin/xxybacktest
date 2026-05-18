# 优质基本面
```python
from xxybacktest import run_backtest, OrderCost, FixedSlippage
from xxybacktest import Context, Data
import pandas as pd

cost = OrderCost(
    open_tax=0,            # 买入税费（A股为0）
    close_tax=0.001,       # 卖出印花税（千分之一）
    open_commission=0.0003,  # 买入佣金（万三）
    close_commission=0.0003, # 卖出佣金（万三）
    min_commission=5,        # 单笔最低佣金（5元）
)

def init(context: Context):
    sd = (pd.to_datetime(context.trade.start_time) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    sql = f"""
    with t1 as (
        select date, instrument, pe_ttm, pb, roe_avg_lf, 
        net_cffoa_lf, total_operating_revenue_lf_yoy, dividend_yield_ratio, 
        pe_ttm / NULLIF(total_operating_revenue_lf_yoy, 0) as peg
        from valuation
        inner join prefactors using (date, instrument)
        inner join basic_info using (date, instrument)
        inner join stock_status using (date, instrument)
        where list_days >= 200
        and st_status = 0
        and suspended = 0
        and list_sector = 1
        and stock_status.is_risk_warning = 0
        and pe_ttm BETWEEN 0 AND 25
        and pb BETWEEN 0 AND 10
        and net_cffoa_lf > 0
        and roe_avg_lf > 0.03
        and total_operating_revenue_lf_yoy > 0.05
        and net_profit_lf_yoy > 0.1
        and dividend_yield_ratio > 0.02
        -- and peg < 3
        and date >= '{sd}'
        and date <= '{context.trade.end_time}'
    )
    select date, instrument, dividend_yield_ratio
    from t1
    order by date, dividend_yield_ratio DESC
    """
    context.df = Data._db.query(sql).df()

    context.g.index = -1

def handle_bar(context: Context):
    context.g.index += 1
    if context.g.index % 22 != 0:
        return
    
    df = context.df[context.df['date']==context.current_dt.strftime("%Y-%m-%d")].head(5)
    target = list(df['instrument'])
    print(context.current_dt.strftime("%Y-%m-%d"), target)

    positions = {k: v for k, v in context.portfolio.positions.items() if v.amount > 0}
    holding = list(positions.keys())

    for ins in holding:
        if ins not in target:
            context.order_target_percent(ins, 0)

    for ins in target:
        if ins not in holding:
            context.order_target_percent(ins, 1 / 5)


result = run_backtest(
    initialize=init,
    handle_data=handle_bar,
    start_date="2020-11-01",
    end_date="2026-03-12",
    capital=60000,
    data_path="./data",          # 你的数据目录路径
    benchmark="000001.SH",
    plot=True,                   # 在 Notebook 中展示回测曲线
    order_cost=cost
)
```

# 换手率+市值策略
```python
from xxybacktest import run_backtest, order_target_percent, OrderCost, FixedSlippage

cost = OrderCost(
    open_tax=0,            # 买入税费（A股为0）
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
        select date, instrument, 
        (rank() over (partition by date order by total_market_cap)) / (count(1) over (partition by date)) as f1,
        (rank() over (partition by date order by float_market_cap)) / (count(1) over (partition by date)) as f2,
        (rank() over (partition by date order by close)) / (count(1) over (partition by date)) as f3,
        2 * f1 + 2 * f2 + f3 as score
        from valuation
        inner join daily_bar using (date, instrument)
        inner join basic_info using (date, instrument)
        inner join stock_status using (date, instrument)
        where list_sector = 1
        and st_status = 0
        and pe_ttm > 0
        and total_market_cap > 500000000
        and stock_status.is_risk_warning = 0
        and list_days > 252
    ),
    t2 as (
        select date, instrument, row_number() over (partition by date order by score) as rn
        from t1
    )
    select * from t2
    where rn <= 5
    """

    context.df = Data._db.query(sql).df()

    sql = f"""
    with t1 as (
        select date, instrument, STDDEV_SAMP(turn) over (partition by instrument order by date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) as turn_std, 
        from daily_bar
        inner join basic_info using (date, instrument)
        inner join stock_status using (date, instrument)
        inner join valuation using (date, instrument)
        where list_sector = 1
        and st_status = 0
        and stock_status.is_risk_warning = 0
        and list_days > 252
        qualify (rank() over (partition by date order by float_market_cap)) / (count(1) over (partition by date)) > 0.1
    ),
    t2 as (
        select date, instrument, rank() over (partition by date order by turn_std) as rn, 
        from t1
    )
    select date, instrument, rn as score
    from t2
    where rn <= 5
    """

    context.df_2 = Data._db.query(sql).df()

    context.g.index = -1

def handle_bar(context):
    context.g.index += 1
    if context.g.index % 22 != 0:
        return
        
    import pandas as pd
    df = pd.concat([context.df[context.df["date"] == context.current_dt.strftime("%Y-%m-%d")], context.df_2[context.df_2["date"] == context.current_dt.strftime("%Y-%m-%d")]])
    target = list(df['instrument'])

    positions = {k: v for k, v in context.portfolio.positions.items() if v.enable_amount > 0}
    holding = list(positions.keys())

    for ins in holding:
        if ins not in target:
            context.order_target_percent(ins, 0)

    for ins in target:
        if ins not in holding:
            context.order_target_percent(ins, 1 / 10)

result = run_backtest(
    initialize=init,
    handle_data=handle_bar,
    start_date="2019-04-01",
    end_date="2026-04-16",
    capital=100000,
    data_path="./data",          # 你的数据目录路径
    benchmark="000001.SH",
    plot=True,                   # 在 Notebook 中展示回测曲线
    order_cost=cost
)
```

# 大类资产(ETF)
```python
from xxybacktest import run_backtest, order_target_percent, OrderCost, FixedSlippage

cost = OrderCost(
    open_tax=0,            # 买入税费（A股为0）
    open_commission=0.0003,  # 买入佣金（万三）
    close_commission=0.0003, # 卖出佣金（万三）
    min_commission=5,        # 单笔最低佣金（5元）
)

def init(context):
    import pandas as pd
    from xxybacktest import Context, Data

    sd = (pd.to_datetime(context.trade.start_time) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")

    specified_etfs = (
        '513100.SH',    # 纳指ETF
        '518880.SH',    # 黄金ETF
        '510300.SH',    # 沪深300ETF
        '159985.SZ',    # 豆粕ETF
        '159980.SZ',    # 有色ETF
        '513520.SH',      # 日经
        '159561.SZ',    # 德国etf
        '159981.SZ',    # 能源化工
        '511260.SH',    # 国债
    )

    sql = f"""
    with t1 as (
        select date, instrument, 
        close/(lag(close, 20) over (partition by instrument order by date)) - 1 as return, 
        from daily_fund
        WHERE date >= '{sd}' AND 
        date <= '{context.trade.end_time}' AND 
        instrument in {specified_etfs}
    )
    select date, instrument, STDDEV_SAMP(return) OVER (ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) as vol
    from t1
    """
    context.df = Data._db.query(sql).df().dropna()

    context.g.index = -1

def handle_bar(context):
    context.g.index += 1
    if context.g.index % 22 != 0:
        return

    def risk_parity(returns, min_weight=0.05, max_weight=0.3):
        import pandas as pd
        from scipy.optimize import minimize
        import numpy as np

        """风险平价优化"""
        cov = returns.cov() * 252
        ins_num = len(cov)
        # 初始化权重
        x = np.random.uniform(0, 1, ins_num)
        x = np.exp(x) / np.sum(np.exp(x))

        def f(x):
            # 风险平价的目标函数, 要求每个资产的风险贡献一样
            total_risk = (cov.values@x)@x  # 二次型
            margin_risk = (cov.values@x) / total_risk
            asset_risk = x * margin_risk
            return np.std(asset_risk)
        
        # 约束
        cons = [
            {'type': 'eq', 'fun': lambda x: np.sum(x) - 1}, 
            {"type": "ineq", "fun": lambda x: x - min_weight},         # 无杠杆下界约束
            {"type": "ineq", "fun": lambda x: max_weight - x},         # 持仓约束
        ]
        result = minimize(
            f, 
            x, 
            method='SLSQP', 
            constraints=cons
        )
        weights = np.ones(ins_num) / ins_num if not result['success'] else result['x']
        weights = weights / weights.sum()
        return pd.Series(weights, index=returns.columns).to_dict()


    dt = context.current_dt.strftime('%Y-%m-%d')
    df = context.df[context.df['date']==dt]
    instruments = df['instrument'].unique()
    df['weight'] = (1 / df['vol']) / (1 / df['vol']).sum()
    positions = {k: v for k, v in context.portfolio.positions.items() if v.amount > 0}
    holding = list(positions.keys())

    # 卖出
    for ins in holding:
        if ins not in instruments:
            context.order_target_percent(ins, 0)
    
    # 买入
    for i in range(len(df)):
        ins = df.iloc[i]['instrument']
        w = df.iloc[i]['weight']
        context.order_target_percent(ins, w)


result = run_backtest(
    initialize=init,
    handle_data=handle_bar,
    start_date="2020-01-01",
    end_date="2026-01-08",
    capital=1000000,
    data_path="./data",          # 你的数据目录路径
    benchmark="000001.SH",
    plot=True,                   # 在 Notebook 中展示回测曲线
    order_cost=cost, 
    asset_type='fund'
)
```