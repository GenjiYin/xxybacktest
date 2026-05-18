from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from datetime import datetime, timedelta
from xtquant.xttype import StockAccount
from bigdatasource import DataSource
from scipy.optimize import minimize
from xtquant import xtconstant
from xtquant import xtdata
import duckdb as ddb
import pandas as pd
import numpy as np
import schedule
import time
import json
import os

xtdata.enable_hello = False

# 获取买入股票
def get_sig():
    return ['000001.SZ', '000002.SZ']

# 获取基金信号
def get_fund_sig():
    return {'511000.SH': 0.3, '521000.SH': 0.7}

# 判断是否为交易日
def is_tradeingday():
    ed = datetime.now()
    sd = ed - timedelta(days=10)
    data = DataSource('all_trading_days').read(
        start_date=sd.strftime('%Y-%m-%d'), 
        end_date=ed.strftime('%Y-%m-%d')
    )
    data = data[data['market_code']=='CN']
    date = data['date'].apply(lambda x: x.strftime('%Y-%m-%d')).to_list()
    if ed.strftime('%Y-%m-%d') in date:
        return True
    else:
        return False
    
class Trade:
    def __init__(self, account_id='xxxxxxxxxx', balance_days=30):
        """
        :params account_id: 账户名
        :params balance_days: 调仓周期
        """
        path = r'D:\国金证券QMT交易端\userdata_mini'
        session_id = int(time.time())
        self.xt_trader = XtQuantTrader(path, session_id)

        self.acc = StockAccount(account_id, 'STOCK')
        self.callback = XtQuantTraderCallback()
        self.xt_trader.register_callback(self.callback)

        print('启动线程......')
        self.xt_trader.start()

        connect_result = self.xt_trader.connect()
        if connect_result != 0:
            import sys
            sys.exit('连接失败, 程序即将退出')
        print('建立交易连接')

        subscribe_result = self.xt_trader.subscribe(self.acc)
        print(f'订阅结果: {subscribe_result}, 0表示成功')

        # 获取持仓
        self.positions = self.get_account_positions()

    def get_portfolio(self):
        asset = self.xt_trader.query_stock_asset(self.acc)
        assset_dict = {
                '账户类型':asset.account_type,
                '资金账户':asset.account_id,
                '可用资金':asset.cash,
                '冻结金额':asset.frozen_cash,
                '持仓市值':asset.market_value,
                '总资产':asset.total_asset
            }
        return assset_dict

    
    def get_account_positions(self):
        """获取持仓"""
        positions = self.xt_trader.query_stock_positions(self.acc)
        pos_dict = {}
        for pos in positions:
            if pos.volume > 0:
                pos_dict[pos.stock_code] = {"volume": pos.volume, "cost_price": pos.avg_price, "last_price": pos.last_price}
        return pos_dict
    
    def order_target_percent(self, ins, weight):
        """
        按比例下单
        :params ins: 个股代码
        :params weight: 预计买入权重
        """
        total_cash = self.get_portfolio()['总资产']
        last_price = xtdata.get_full_tick([ins])[ins]['lastClose']
        expect_amount = weight * total_cash
        expect_volume = expect_amount / last_price
        expect_volume -= (expect_volume % 100)
        
        position = self.xt_trader.query_stock_position(self.acc, ins)
        if position is None:
            volume = 0
        else:
            volume = position.volume

        if volume > expect_volume:
            # 卖出操作
            print(f'卖出{volume - expect_volume}股', ins)
            self.xt_trader.order_stock(
                account=self.acc, 
                stock_code=ins, 
                order_type=xtconstant.STOCK_SELL, 
                order_volume=volume - expect_volume, 
                price_type=xtconstant.MARKET_SH_CONVERT_5_CANCEL, 
                price=0
            )
        
        if volume < expect_volume:
            # 买入操作
            print(f'买入{expect_volume - volume}股', ins)
            self.xt_trader.order_stock(
                account=self.acc, 
                stock_code=ins, 
                order_type=xtconstant.STOCK_BUY, 
                order_volume=expect_volume - volume, 
                price_type=xtconstant.MARKET_SH_CONVERT_5_CANCEL, 
                price=0
            )

    def strategy_1(self, percent: float):
        """多因子策略"""
        print("多因子调仓")
        instruments: list = get_sig()    # 获取交易股票
        position = self.get_account_positions()
        p = list(position.keys())
        stock_position = [i for i in p if i[0]!= '5' and i[0]!='1']

        # 卖出
        for ins in stock_position:
            if ins not in instruments:
                self.order_target_percent(ins, 0)
                time.sleep(0.5)

        time.sleep(2)

        # 买入
        for ins in instruments:
            if ins not in stock_position:
                self.order_target_percent(ins, percent / len(instruments))

    def strategy_2(self, percent: float):
        """风险平价策略"""
        etf_weight = get_fund_sig()
        target = list(etf_weight.keys())
        position = self.get_account_positions()
        p = list(position.keys())
        etf_position = [i for i in p if i[0]== '5' or i[0]=='1']
        # 卖出
        for ins in etf_position:
            if ins not in target:
                self.order_target_percent(ins, 0)
                time.sleep(0.5)

        time.sleep(2)

        # 买入
        for k, v in etf_weight.items():
            self.order_target_percent(k, v * percent)

    def execute_strategy(self):
        """执行交易"""
        # print('策略执行')
        # 是否为交易日
        now = datetime.now().strftime('%Y-%m-%d')
        hour = datetime.now().strftime('%H:%M')
        cond = is_tradeingday()
        if not cond:
            print(now, '非交易日')
            return

        if os.path.exists("schedule_log.json"):
            with open("schedule_log.json", "r") as f:
                before_date = pd.to_datetime(json.load(f))
        else:
            before_date = datetime.now() - timedelta(days=31)  # 确保首次运行时不会跳过调仓
        
        # 不足调仓日期时跳过
        delta = pd.to_datetime(now) - before_date
        if delta.days < 27:
            return
            
        if hour >= '09:30':
            # 到了调仓日重新保存日期
            print(now, '调仓期')

            # 两个策略的权重
            stock_percent = 0.45
            etf_percent = 0.4


            self.strategy_2(etf_percent)
            self.strategy_1(stock_percent)


            with open("schedule_log.json", "w") as f:
                json.dump(now, f)

if __name__ == '__main__':
    trade = Trade()

    # trade.execute_strategy()

    # # 设置每天9点30执行任务
    # schedule.every().day.at("09:30").do(trade.execute_strategy)
    schedule.every().seconds.do(trade.execute_strategy)

    while True:
        schedule.run_pending()
        time.sleep(1)   # 每分钟检查一次