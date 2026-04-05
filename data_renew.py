"""bigquant数据"""
from bigquant.api import dai, user
import pandas as pd
from datetime import datetime
from xxydb import xxydb

user.login(username='xuxiaoyin', password='q6504368')

db = xxydb('./data')

def renew_daily_bar(sd, ed):
    """更新日线数据"""
    sql = """
    select * from cn_stock_real_bar1d
    """
    schema = {
        "date":  {"desc": "交易日期"},
        "instrument":  {"desc": "股票代码（6位）"},
        "name": {"desc": "证券简称"},
        "adjust_factor": {"desc": "累积后复权因子"}, 
        "pre_close": {"desc": "昨收盘价"}, 
        "open": {"desc": "开盘价"},
        'close':	{'desc':	'收盘价'}, 
        'high':	{'desc':	'最高价'}, 
        'low':	{'desc':	'最低价'}, 
        'volume':	{'desc':	'成交量'}, 
        'deal_number':	{'desc':	'成交笔数'}, 
        'amount':	{'desc':	'成交金额'}, 
        'change_ratio':	{'desc':	'涨跌幅'},
        'turn':	{'desc':	'换手率'}, 
        'upper_limit':	{'desc':	'涨停价'}, 
        'lower_limit':	{'desc':	'跌停价'}, 
    }

    data = dai.query(sql, filters={'date': [sd, ed]}).df()
    db.write_data(
        data=data, 
        id='daily_bar', 
        date_col='date', 
        partitioning='年', 
        unique_together=['date', 'instrument'], 
        rewrite=False, 
        schema=schema
    )
    print(f"日线数据更新成功: {sd} -> {ed}")

def renew_valuation(sd, ed):
    """更新估值数据"""
    sql = """
    select * from cn_stock_valuation
    """
    data = dai.query(sql, filters={'date': [sd, ed]}).df()
    db.write_data(
        data=data, 
        id='valuation', 
        date_col='date', 
        partitioning='年', 
        unique_together=['date', 'instrument'], 
        rewrite=False
    )
    print(f"估值数据更新成功: {sd} -> {ed}")

def renew_stock_status(sd, ed):
    """更新个股状态数据"""
    sql = """
    select * from cn_stock_status
    """
    data = dai.query(sql, filters={'date': [sd, ed]}).df()
    db.write_data(
        data=data, 
        id='stock_status', 
        date_col='date', 
        partitioning='年', 
        unique_together=['date', 'instrument'], 
        rewrite=False
    )
    print(f"个股状态数据更新成功: {sd} -> {ed}")

def renew_trading_days():
    """更新交易日历"""
    sql = """
    select * from all_trading_days
    """
    data = dai.query(sql).df()
    db.write_data(
        data=data, 
        id='trading_days', 
        date_col='date', 
        partitioning=None, 
        unique_together=['date', 'market_code'], 
        rewrite=False
    )
    print(f"交易日历更新成功")

def renew_dividend():
    """更新分红信息"""
    sql = """
    select * from cn_stock_dividend
    """
    data = dai.query(sql).df()

    schema = {
        "date":  {"desc": "交易日期"},
        "instrument":  {"desc": "股票代码（6位）"},
        "report_date": {"desc": "报告期"},
        "publish_date": {"desc": "公告日期"}, 
        "bonus_rate": {"desc": "每股送股比例"}, 
        "conversed_rate": {"desc": "每股转增比例"},
        'cash_before_tax':	{'desc':	'每股派现(税前)'}, 
        'cash_after_tax':	{'desc':	'每股派现(税后)'}, 
        'register_date':	{'desc':	'股权登记日'}, 
        'ex_date':	{'desc':	'除权除息日'}, 
    }

    db.write_data(
        data=data, 
        id='dividend', 
        date_col='date', 
        partitioning=None, 
        unique_together=['date', 'instrument'], 
        rewrite=False, 
        schema=schema
    )
    print(f"分红信息更新成功")

def renew_index_bar(sd, ed):
    """更新指数数据"""
    sql = """
    select * from cn_stock_index_bar1d
    """
    data = dai.query(sql, filters={'date': [sd, ed]}).df()
    db.write_data(
        data=data, 
        id='index_bar', 
        date_col='date', 
        partitioning='年', 
        unique_together=['date', 'instrument'], 
        rewrite=False
    )
    print(f"指数数据更新成功: {sd} -> {ed}")

def renew_basic_info(sd, ed):
    """更新全市场股票信息"""
    sql = """
    select date, instrument, 
    list_sector, list_days, 
    is_risk_warning, 
    from cn_stock_prefactors
    qualify columns(*) is not null
    """
    data = dai.query(sql, filters={'date': [sd, ed]}).df()

    schema = {
        "date":  {"desc": "交易日期"},
        "instrument":  {"desc": "股票代码（6位）"},
        "list_sector": {"desc": "上市板块代码: 0-未知；1-主板；2-创业板；3-科创板；4-北交所"},
        "list_days": {"desc": "已上市天数 (按自然日)"}, 
        "is_risk_warning": {"desc": "风险警示: 0-正常, 1-风险警示"}
    }

    db.write_data(
        data=data, 
        id='basic_info', 
        date_col='date', 
        partitioning='年', 
        unique_together=['date', 'instrument'], 
        rewrite=False, 
        schema=schema
    )
    print(f"个股信息更新成功: {sd} -> {ed}")

def renew_daily_fund(sd, ed):
    """每日基金行情更新"""
    sql = """
    select * from cn_fund_real_bar1d
    """
    schema = {
        "date":  {"desc": "交易日期"},
        "instrument":  {"desc": "股票代码（6位）"},
        "name": {"desc": "基金简称"},
        "adjust_factor": {"desc": "累积后复权因子"}, 
        "pre_close": {"desc": "昨收盘价"}, 
        "open": {"desc": "开盘价"},
        'close':	{'desc':	'收盘价'}, 
        'high':	{'desc':	'最高价'}, 
        'low':	{'desc':	'最低价'}, 
        'volume':	{'desc':	'成交量'}, 
        'deal_number':	{'desc':	'成交笔数'}, 
        'amount':	{'desc':	'成交金额'}, 
        'change_ratio':	{'desc':	'涨跌幅'},
        'turn':	{'desc':	'换手率'}, 
        'upper_limit':	{'desc':	'涨停价'}, 
        'lower_limit':	{'desc':	'跌停价'}, 
        'iopv': {'desc': ""}
    }

    data = dai.query(sql, filters={'date': [sd, ed]}).df()
    db.write_data(
        data=data, 
        id='daily_fund', 
        date_col='date', 
        partitioning='年', 
        unique_together=['date', 'instrument'], 
        rewrite=False, 
        schema=schema
    )
    print(f"基金日线数据更新成功: {sd} -> {ed}")

def renew_fund_dividend():
    """更新分红信息"""
    sql = """
    select * from cn_fund_dividend
    """
    data = dai.query(sql).df()

    schema = {
        "date":  {"desc": "除息日"},
        "instrument":  {"desc": "基金代码"},
        "name":  {"desc": "基金简称"},
        'register_date':	{'desc':	'权益登记日'}, 
        'cash_dividend':	{'desc':	'分红(元/份)'}, 
        'dividend_distribution_date': {'desc': "分红发放日"}, 
        'fund_type':	{'desc':	'基金类型'}, 
    }

    db.write_data(
        data=data, 
        id='fund_dividend', 
        date_col='date', 
        partitioning=None, 
        unique_together=['date', 'instrument'], 
        rewrite=False, 
        schema=schema
    )
    print(f"基金分红信息更新成功")

def renew_fund_split():
    sql = """
    select * from cn_fund_split
    """
    schema = {
        "date":  {"desc": "拆分折算日"},
        "instrument":  {"desc": "基金代码"},
        "name": {"desc": "基金简称"},
        "split_type": {"desc": "拆分类型"}, 
        "split_conversion": {"desc": "	拆分折算(每份)"}, 
        "fund_type": {"desc": "基金类型"},
    }

    data = dai.query(sql).df()
    db.write_data(
        data=data, 
        id='fund_split', 
        date_col='date', 
        partitioning='年', 
        unique_together=['date', 'instrument'], 
        rewrite=False, 
        schema=schema
    )
    print(f"基金拆分数据更新成功: {sd} -> {ed}")

if __name__ == '__main__':
    now = datetime.now()
    sd = now - pd.Timedelta(days=50)

    ed = now.strftime("%Y-%m-%d")
    sd = sd.strftime("%Y-%m-%d")

    # 数据增量
    renew_daily_bar(sd, ed)
    renew_valuation(sd, ed)
    renew_stock_status(sd, ed)
    renew_trading_days()
    renew_dividend()
    renew_index_bar(sd, ed)
    renew_basic_info(sd, ed)

    # 基金数据增量
    renew_fund_split()
    renew_fund_dividend()
    renew_daily_fund(sd, ed)

    # # 数据入库
    # date = [
    #     ['2019-01-01', '2020-01-01'], 
    #     ['2020-01-01', '2021-01-01'], 
    #     ['2021-01-01', '2022-01-01'], 
    #     ['2022-01-01', '2023-01-01'], 
    #     ['2023-01-01', '2024-01-01'], 
    #     ['2024-01-01', '2025-01-01'], 
    #     ['2025-01-01', '2026-01-01'], 
    #     ['2026-01-01', '2026-03-28'], 
    # ]

    # for i in date:
    #     sd = i[0]
    #     ed = i[-1]
    #     renew_daily_fund(sd, ed)
