"""
B 系列：数据接口层

Data 类以静态方法组织所有数据访问接口，与原项目结构对齐。
db 连接在回测启动时通过 Data.init_db() 初始化一次。
"""

import math
from dataclasses import dataclass
from datetime import time as dtime

import numpy as np
from xxydb import xxydb
import pandas as pd


# ------------------------------------------------------------------
# O5 方案 A：带 __slots__ 的 dataclass 替代 DictObj 存储行情/分红数据
# 每实例省 ~200 字节，250 万行内存从 ~1.2 GB 降至 ~500 MB。
# ------------------------------------------------------------------

@dataclass(slots=True)
class DailyInfo:
    """单只股票单日行情数据。"""
    ts_code: str
    name: str
    open: float
    high: float
    low: float
    close: float
    pre_close: float
    volume: int
    amount: float
    vwap: float
    upLimit: float
    downLimit: float
    stop: int
    st_status: int


@dataclass(slots=True)
class DividendInfo:
    """单只股票单次分红数据。"""
    stk_div: float
    cash_div_tax: float
    ex_date: str
    pay_date: str


class Data:
    _db = None  # 模块级 db 连接，由 init_db 初始化
    _daily_cache = None  # O1: {date_str: {code: DailyInfo}} 全区间日线缓存
    _dividend_reg_cache = None  # O2: {date_str: {code: DividendInfo}} 全区间分红缓存（按 register_date）
    _asset_type = "stock"  # F-B4: 资产类型，"stock" 或 "fund"
    _instrument_names = {}  # {code: name} 股票名称备用查找表（当日缓存无数据时回落用）

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    @staticmethod
    def init_db(path="./data", asset_type="stock"):
        """初始化 xxydb 连接，回测启动时调用一次。"""
        Data._db = xxydb(path=path)
        Data._asset_type = asset_type

    # ------------------------------------------------------------------
    # O1: 全区间批量预加载
    # ------------------------------------------------------------------

    @staticmethod
    def preload_daily(start_date, end_date):
        """一次性加载全区间日线行情到内存缓存。

        执行一条 SQL 把 [start_date, end_date] 内所有 daily_bar JOIN
        stock_status 的数据加载到嵌套字典中，后续 get_daily_info 变为
        纯字典查找，零 SQL 开销。

        参数:
            start_date: 起始日期 'YYYY-MM-DD'
            end_date:   结束日期 'YYYY-MM-DD'
        """
        df = Data._db.query(f"""
            SELECT
                d.instrument, d.date, d.name,
                d.open, d.high, d.low, d.close, d.pre_close,
                d.volume, d.amount, d.upper_limit, d.lower_limit,
                s.suspended, s.st_status
            FROM daily_bar d
            INNER JOIN stock_status s
                ON d.instrument = s.instrument AND d.date = s.date
            WHERE d.date >= '{start_date}' AND d.date <= '{end_date}'
        """).df()

        # 向量化预计算所有字段，避免逐行 Python 循环
        df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
        df["vwap"] = df["amount"] / (df["volume"] + 1)

        # 转成 records 列表后按日期分组构建嵌套字典
        records = df.to_dict("records")
        cache = {}
        for r in records:
            date_str = r["date_str"]
            code = r["instrument"]
            if date_str not in cache:
                cache[date_str] = {}
            cache[date_str][code] = DailyInfo(
                ts_code=code,
                name=r["name"],
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                pre_close=float(r["pre_close"]),
                volume=int(r["volume"]),
                amount=float(r["amount"]),
                vwap=float(r["vwap"]),
                upLimit=float(r["upper_limit"]),
                downLimit=float(r["lower_limit"]),
                stop=int(r["suspended"]),
                st_status=int(r["st_status"]),
            )

        Data._daily_cache = cache

        # 顺带填充名称备用表（向量化，只补充新 code，不覆盖已有记录）
        name_df = df[df["name"].notna() & (df["name"] != "")][["instrument", "name"]].drop_duplicates("instrument")
        for _, row in name_df.iterrows():
            if row["instrument"] not in Data._instrument_names:
                Data._instrument_names[row["instrument"]] = row["name"]

    @staticmethod
    def preload_fund_daily(start_date, end_date):
        """F-B1: 一次性加载全区间基金日线行情到内存缓存。

        与 preload_daily 对等，数据源为 daily_fund（无需 JOIN stock_status）。
        停牌从 volume=0 推断，st_status 固定为 0。

        参数:
            start_date: 起始日期 'YYYY-MM-DD'
            end_date:   结束日期 'YYYY-MM-DD'
        """
        df = Data._db.query(f"""
            SELECT
                instrument, date, name,
                open, high, low, close, pre_close,
                volume, amount, upper_limit, lower_limit
            FROM daily_fund
            WHERE date >= '{start_date}' AND date <= '{end_date}'
        """).df()

        # F-B0: 向量化 NaN 填充
        df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
        df["open"]        = df["open"].fillna(0.0)
        df["high"]        = df["high"].fillna(0.0)
        df["low"]         = df["low"].fillna(0.0)
        df["close"]       = df["close"].fillna(0.0)
        df["pre_close"]   = df["pre_close"].fillna(0.0)
        df["amount"]      = df["amount"].fillna(0.0)
        df["upper_limit"] = df["upper_limit"].fillna(float('inf'))
        df["lower_limit"] = df["lower_limit"].fillna(0.0)
        df["vwap"]        = df["amount"] / (df["volume"] + 1)
        df["stop"]        = (df["volume"] == 0).astype(int)

        records = df.to_dict("records")
        cache = {}
        for r in records:
            date_str = r["date_str"]
            code = r["instrument"]
            if date_str not in cache:
                cache[date_str] = {}
            cache[date_str][code] = DailyInfo(
                ts_code=code,
                name=r["name"],
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                pre_close=float(r["pre_close"]),
                volume=int(r["volume"]),
                amount=float(r["amount"]),
                vwap=float(r["vwap"]),
                upLimit=float(r["upper_limit"]),
                downLimit=float(r["lower_limit"]),
                stop=int(r["stop"]),
                st_status=0,
            )

        Data._daily_cache = cache

        # 顺带填充名称备用表（向量化，只补充新 code，不覆盖已有记录）
        name_df = df[df["name"].notna() & (df["name"] != "")][["instrument", "name"]].drop_duplicates("instrument")
        for _, row in name_df.iterrows():
            if row["instrument"] not in Data._instrument_names:
                Data._instrument_names[row["instrument"]] = row["name"]

        # 二次补充：从 daily_fund 近15天数据补充名称，
        # 解决部分基金在回测区间内 name 字段为空/NULL 的情况。
        try:
            df_recent = Data._db.query(f"""
                SELECT instrument, name
                FROM daily_fund
                WHERE date >= '{end_date}'::DATE - INTERVAL '15 days'
                  AND name IS NOT NULL AND name != ''
                QUALIFY ROW_NUMBER() OVER (PARTITION BY instrument ORDER BY date DESC) = 1
            """).df()
            for _, row in df_recent.iterrows():
                if row['name'] and row['instrument'] not in Data._instrument_names:
                    Data._instrument_names[row['instrument']] = row['name']
        except Exception:
            pass

        # 三次补充：fund_dividend / fund_split 是不分区的小表，直接全量扫描，
        # 作为 daily_fund.name 为空时的最终兜底。
        for _tbl in ('fund_dividend', 'fund_split'):
            try:
                df_tbl = Data._db.query(
                    f"SELECT DISTINCT instrument, name FROM {_tbl} "
                    f"WHERE name IS NOT NULL AND name != ''"
                ).df()
                for _, row in df_tbl.iterrows():
                    if row['name'] and row['instrument'] not in Data._instrument_names:
                        Data._instrument_names[row['instrument']] = row['name']
            except Exception:
                pass

    @staticmethod
    def clear_cache():
        """释放缓存内存，回测结束后可调用。"""
        Data._daily_cache = None
        Data._dividend_reg_cache = None
        Data._asset_type = "stock"
        Data._instrument_names = {}

    @staticmethod
    def preload_fund_dividend(start_date, end_date):
        """F-B2: 一次性加载全区间基金分红数据到内存缓存（按 register_date 索引）。

        与 preload_dividend 对等，数据源为 fund_dividend。
        基金只有现金分红，无送股/转增 → stk_div 恒为 0。
        pay_date 使用 dividend_distribution_date（基金数据完整，不需用 ex_date 代替）。

        参数:
            start_date: 起始日期 'YYYY-MM-DD'
            end_date:   结束日期 'YYYY-MM-DD'
        """
        df = Data._db.query(f"""
            SELECT
                instrument,
                register_date,
                COALESCE(cash_dividend, 0) AS cash_div_tax,
                date AS ex_date,
                dividend_distribution_date AS pay_date
            FROM fund_dividend
            WHERE register_date >= '{start_date}' AND register_date <= '{end_date}'
        """).df()

        reg_cache = {}
        for _, row in df.iterrows():
            reg_date = row["register_date"]
            if reg_date is None or row["pay_date"] is None:
                continue
            reg_date_str = reg_date.strftime("%Y-%m-%d") if hasattr(reg_date, 'strftime') else str(reg_date)[:10]
            code = row["instrument"]
            ex_date_str = row["ex_date"].strftime("%Y-%m-%d") if row["ex_date"] is not None else reg_date_str
            pay_date_str = row["pay_date"].strftime("%Y-%m-%d") if row["pay_date"] is not pd.NaT and row["pay_date"] is not None else ex_date_str
            reg_cache.setdefault(reg_date_str, {})[code] = DividendInfo(
                stk_div=0.0,
                cash_div_tax=float(row["cash_div_tax"]),
                ex_date=ex_date_str,
                pay_date=pay_date_str,
            )

        Data._dividend_reg_cache = reg_cache

    @staticmethod
    def preload_fund_split(start_date, end_date, calendar):
        """F-B5: 将基金拆分事件转化为 DividendInfo 并合并到 _dividend_reg_cache。

        基金拆分与股票送股本质相同（份额变化、总值不变），复用 stk_div 机制：
        - 拆分(1:4): split_conversion=4.0 → stk_div=3.0 → 新份额=旧×4
        - 合并(4:1): split_conversion=0.25 → stk_div=-0.75 → 新份额=旧×0.25

        F-B0 确认：fund_split.date 是折算基准日，当天价格不变，
        下一交易日 pre_close 才反映拆分后价格。因此：
        - register_date = fund_split.date（基准日，_after_market 在此日记录）
        - ex_date = calendar[idx+1]（下一交易日，_before_market 在此日执行份额调整）

        参数:
            start_date: 起始日期 'YYYY-MM-DD'
            end_date:   结束日期 'YYYY-MM-DD'
            calendar:   交易日历列表 List[str]
        """
        df = Data._db.query(f"""
            SELECT
                instrument, date, split_conversion
            FROM fund_split
            WHERE date >= '{start_date}' AND date <= '{end_date}'
        """).df()

        if df.empty:
            return

        # 确保 _dividend_reg_cache 已初始化（F-B2 preload_fund_dividend 应先调用）
        if Data._dividend_reg_cache is None:
            Data._dividend_reg_cache = {}

        # 构建 index 映射以快速查找下一交易日
        cal_index = {d: i for i, d in enumerate(calendar)}

        for _, row in df.iterrows():
            split_date = row["date"]
            split_date_str = split_date.strftime("%Y-%m-%d") if hasattr(split_date, 'strftime') else str(split_date)[:10]
            code = row["instrument"]
            stk_div = float(row["split_conversion"]) - 1.0

            # 推导 ex_date = 拆分基准日的下一个交易日
            idx = cal_index.get(split_date_str)
            if idx is None:
                # 拆分基准日不在交易日历中（非交易日），跳过
                continue
            if idx >= len(calendar) - 1:
                # 末日拆分：ex_date 不在回测区间内，跳过
                continue

            register_date_str = split_date_str       # 登记日 = 折算基准日
            ex_date_str = calendar[idx + 1]          # 生效日 = 下一个交易日

            div_info = DividendInfo(
                stk_div=stk_div,
                cash_div_tax=0.0,
                ex_date=ex_date_str,
                pay_date=ex_date_str,
            )

            # 合并到 _dividend_reg_cache（按 register_date 索引）
            if register_date_str not in Data._dividend_reg_cache:
                Data._dividend_reg_cache[register_date_str] = {}

            existing = Data._dividend_reg_cache[register_date_str].get(code)
            if existing:
                # 极少见：同一天既有分红又有拆分
                # 复合计算：新份额 = 旧份额 × (1 + 原stk_div) × split_conversion
                merged = (1 + existing.stk_div) * (1 + stk_div) - 1
                Data._dividend_reg_cache[register_date_str][code] = DividendInfo(
                    stk_div=merged,
                    cash_div_tax=existing.cash_div_tax,
                    ex_date=ex_date_str,
                    pay_date=existing.pay_date,
                )
            else:
                Data._dividend_reg_cache[register_date_str][code] = div_info

    @staticmethod
    def preload_dividend(start_date, end_date):
        """一次性加载全区间分红数据到内存缓存（按 register_date 索引）。

        后续 get_dividend 变为纯字典查找，零 SQL 开销。
        分红数据量极小（全市场每年 ~5000 条），内存 < 10MB。

        参数:
            start_date: 起始日期 'YYYY-MM-DD'
            end_date:   结束日期 'YYYY-MM-DD'
        """
        df = Data._db.query(f"""
            SELECT
                instrument,
                register_date,
                COALESCE(bonus_rate, 0) + COALESCE(conversed_rate, 0) AS stk_div,
                COALESCE(cash_after_tax, 0) AS cash_div_tax,
                ex_date
            FROM dividend
            WHERE register_date >= '{start_date}' AND register_date <= '{end_date}'
        """).df()

        reg_cache = {}
        for _, row in df.iterrows():
            reg_date = row["register_date"]
            if reg_date is None:
                continue
            reg_date_str = reg_date.strftime("%Y-%m-%d") if hasattr(reg_date, 'strftime') else str(reg_date)[:10]
            code = row["instrument"]
            ex_date_str = row["ex_date"].strftime("%Y-%m-%d") if row["ex_date"] is not None else reg_date_str
            reg_cache.setdefault(reg_date_str, {})[code] = DividendInfo(
                stk_div=float(row["stk_div"]),
                cash_div_tax=float(row["cash_div_tax"]),
                ex_date=ex_date_str,
                pay_date=ex_date_str,
            )

        Data._dividend_reg_cache = reg_cache

    # ------------------------------------------------------------------
    # B1. 交易日历
    # ------------------------------------------------------------------

    @staticmethod
    def get_trade_calendar(start_date, end_date):
        """返回 [start_date, end_date] 区间内的 A 股交易日列表。

        参数:
            start_date: 起始日期，格式 'YYYY-MM-DD'
            end_date:   结束日期，格式 'YYYY-MM-DD'

        返回:
            List[str]，每个元素格式 'YYYY-MM-DD'，按日期升序排列。
        """
        df = Data._db.query(f"""
            SELECT date FROM trading_days
            WHERE market_code = 'CN'
              AND date >= '{start_date}' AND date <= '{end_date}'
            ORDER BY date
        """).df()
        return df["date"].dt.strftime("%Y-%m-%d").tolist()

    @staticmethod
    def get_previous_trade_day(date_str):
        """返回 date_str 之前最近的一个交易日（不含 date_str 当天）。

        参数:
            date_str: 基准日期，格式 'YYYY-MM-DD'

        返回:
            str 'YYYY-MM-DD' — 上一个交易日；
            None — date_str 已是数据库最早交易日或更早（边界），无更早交易日。
        """
        df = Data._db.query(f"""
            SELECT MAX(date) AS d FROM trading_days
            WHERE market_code = 'CN' AND date < '{date_str}'
        """).df()
        if df.empty or pd.isna(df["d"].iloc[0]):
            return None
        return df["d"].iloc[0].strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # B2. 日线行情
    # ------------------------------------------------------------------

    @staticmethod
    def get_daily_info(code, context, date=None):
        """获取单只股票某日的行情数据。

        O1 优化后优先从内存缓存读取（纳秒级），缓存未命中时走原始 SQL 兜底。

        参数:
            code:    股票代码，如 '000001.SZ'
            context: 回测上下文（用于取 current_dt）
            date:    指定日期 'YYYY-MM-DD'，默认取 context.current_dt

        返回:
            DailyInfo 包含: open, high, low, close, volume, amount, name,
                          vwap, stop, upLimit, downLimit, pre_close, st_status
            查无数据时返回 None。
        """
        if date is None:
            date = context.current_dt.strftime("%Y-%m-%d")

        # O1: 缓存命中 → 直接返回（99.9% 的情况走这里）
        if Data._daily_cache is not None:
            day_data = Data._daily_cache.get(date)
            if day_data is not None:
                return day_data.get(code)  # 无数据则返回 None
            return None  # 日期不在缓存范围内

        # 兜底：无缓存时走原始 SQL（向后兼容）
        if Data._asset_type == "fund":
            # F-B4: 基金兜底查询 daily_fund
            df = Data._db.query(f"""
                SELECT
                    instrument, name,
                    open, high, low, close, pre_close,
                    volume, amount, upper_limit, lower_limit
                FROM daily_fund
                WHERE instrument = '{code}' AND date = '{date}'
            """).df()

            if df.empty:
                return None

            row = df.iloc[0]
            volume = row["volume"]
            amount = row["amount"]
            _open = float(row["open"]) if row["open"] == row["open"] else 0.0
            _high = float(row["high"]) if row["high"] == row["high"] else 0.0
            _low = float(row["low"]) if row["low"] == row["low"] else 0.0
            _close = float(row["close"]) if row["close"] == row["close"] else 0.0
            _pre_close = float(row["pre_close"]) if row["pre_close"] == row["pre_close"] else 0.0
            _amount = float(amount) if amount == amount else 0.0
            _up = float(row["upper_limit"]) if row["upper_limit"] == row["upper_limit"] else float('inf')
            _down = float(row["lower_limit"]) if row["lower_limit"] == row["lower_limit"] else 0.0

            return DailyInfo(
                ts_code=row["instrument"],
                name=row["name"],
                open=_open,
                high=_high,
                low=_low,
                close=_close,
                pre_close=_pre_close,
                volume=int(volume),
                amount=_amount,
                vwap=_amount / (volume + 1),
                upLimit=_up,
                downLimit=_down,
                stop=1 if volume == 0 else 0,
                st_status=0,
            )
        else:
            # 股票兜底查询 daily_bar JOIN stock_status
            df = Data._db.query(f"""
                SELECT
                    d.instrument,
                    d.name,
                    d.open,
                    d.high,
                    d.low,
                    d.close,
                    d.pre_close,
                    d.volume,
                    d.amount,
                    d.upper_limit,
                    d.lower_limit,
                    s.suspended,
                    s.st_status
                FROM daily_bar d
                INNER JOIN stock_status s
                    ON d.instrument = s.instrument AND d.date = s.date
                WHERE d.instrument = '{code}' AND d.date = '{date}'
            """).df()

            if df.empty:
                return None

            row = df.iloc[0]
            volume = row["volume"]
            amount = row["amount"]
            vwap = amount / (volume + 1)

            return DailyInfo(
                ts_code=row["instrument"],
                name=row["name"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                pre_close=float(row["pre_close"]),
                volume=int(volume),
                amount=float(amount),
                vwap=vwap,
                upLimit=float(row["upper_limit"]),
                downLimit=float(row["lower_limit"]),
                stop=int(row["suspended"]),
                st_status=int(row["st_status"]),
            )

    # ------------------------------------------------------------------
    # B4. 分红送股数据接口
    # ------------------------------------------------------------------

    @staticmethod
    def get_dividend(context, date=None):
        """查询某日有分红登记的股票（按 register_date 匹配）。

        O2 优化后优先从内存缓存读取，缓存未命中时走原始 SQL 兜底。

        参数:
            context: 回测上下文
            date:    指定日期 'YYYY-MM-DD'，默认取 context.current_dt

        返回:
            dict，以股票代码为 key，value 为 DividendInfo:
                stk_div       — 每股送转股合计（bonus_rate + conversed_rate）
                cash_div_tax  — 每股派息（税后）
                ex_date       — 除权除息日 'YYYY-MM-DD'
                pay_date      — 派息日 'YYYY-MM-DD'（数据缺失，用 ex_date 代替）
            无分红数据时返回空 dict。
        """
        if date is None:
            date = context.current_dt.strftime("%Y-%m-%d")

        # O2: 缓存命中 → 直接返回
        if Data._dividend_reg_cache is not None:
            return Data._dividend_reg_cache.get(date, {})

        # 兜底：无缓存时走原始 SQL（向后兼容）
        if Data._asset_type == "fund":
            # F-B4: 基金兜底查询 fund_dividend
            df = Data._db.query(f"""
                SELECT
                    instrument,
                    COALESCE(cash_dividend, 0) AS cash_div_tax,
                    date AS ex_date,
                    dividend_distribution_date AS pay_date
                FROM fund_dividend
                WHERE register_date = '{date}'
            """).df()

            if df.empty:
                return {}

            result = {}
            for _, row in df.iterrows():
                code = row["instrument"]
                ex_date_str = row["ex_date"].strftime("%Y-%m-%d") if row["ex_date"] is not None else date
                pay_date_str = row["pay_date"].strftime("%Y-%m-%d") if row["pay_date"] is not None else ex_date_str
                result[code] = DividendInfo(
                    stk_div=0.0,
                    cash_div_tax=float(row["cash_div_tax"]),
                    ex_date=ex_date_str,
                    pay_date=pay_date_str,
                )

            return result
        else:
            # 股票兜底查询 dividend
            df = Data._db.query(f"""
                SELECT
                    instrument,
                    COALESCE(bonus_rate, 0) + COALESCE(conversed_rate, 0) AS stk_div,
                    COALESCE(cash_after_tax, 0) AS cash_div_tax,
                    ex_date
                FROM dividend
                WHERE register_date = '{date}'
            """).df()

            if df.empty:
                return {}

            result = {}
            for _, row in df.iterrows():
                code = row["instrument"]
                ex_date_str = row["ex_date"].strftime("%Y-%m-%d") if row["ex_date"] is not None else date
                result[code] = DividendInfo(
                    stk_div=float(row["stk_div"]),
                    cash_div_tax=float(row["cash_div_tax"]),
                    ex_date=ex_date_str,
                    pay_date=ex_date_str,
                )

            return result

    @staticmethod
    def get_dividend_by_pay_date(start_date, end_date):
        """查询派息日（ex_date 代替）在指定区间内的所有分红记录。

        用于 F3 回测开始前的分红数据预加载：处理 register_date 在回测
        开始日期之前、但 pay_date(ex_date) 在回测期间内的分红。

        参数:
            start_date: 起始日期 'YYYY-MM-DD'
            end_date:   结束日期 'YYYY-MM-DD'

        返回:
            dict，以 pay_date(ex_date) 字符串为一级 key，股票代码为二级 key，
            value 为 DividendInfo（同 get_dividend 的单条记录结构）。
        """
        df = Data._db.query(f"""
            SELECT
                instrument,
                COALESCE(bonus_rate, 0) + COALESCE(conversed_rate, 0) AS stk_div,
                COALESCE(cash_after_tax, 0) AS cash_div_tax,
                register_date,
                ex_date
            FROM dividend
            WHERE ex_date >= '{start_date}' AND ex_date <= '{end_date}'
        """).df()

        if df.empty:
            return {}

        result = {}
        for _, row in df.iterrows():
            ex_date_str = row["ex_date"].strftime("%Y-%m-%d") if row["ex_date"] is not None else None
            if ex_date_str is None:
                continue
            code = row["instrument"]
            if ex_date_str not in result:
                result[ex_date_str] = {}
            result[ex_date_str][code] = DividendInfo(
                stk_div=float(row["stk_div"]),
                cash_div_tax=float(row["cash_div_tax"]),
                ex_date=ex_date_str,
                pay_date=ex_date_str,
            )

        return result

    @staticmethod
    def get_fund_dividend_by_pay_date(start_date, end_date):
        """F-B3: 查询派息日(dividend_distribution_date)在指定区间内的基金分红记录。

        用于 F3 回测开始前的分红数据预加载：处理 register_date 在回测
        开始日期之前、但 pay_date 在回测期间内的基金分红。

        参数:
            start_date: 起始日期 'YYYY-MM-DD'
            end_date:   结束日期 'YYYY-MM-DD'

        返回:
            dict，以 pay_date 字符串为一级 key，基金代码为二级 key，
            value 为 DividendInfo（stk_div 恒为 0）。
        """
        df = Data._db.query(f"""
            SELECT
                instrument,
                COALESCE(cash_dividend, 0) AS cash_div_tax,
                register_date,
                date AS ex_date,
                dividend_distribution_date AS pay_date
            FROM fund_dividend
            WHERE dividend_distribution_date >= '{start_date}'
              AND dividend_distribution_date <= '{end_date}'
        """).df()

        if df.empty:
            return {}

        result = {}
        for _, row in df.iterrows():
            pay_date = row["pay_date"]
            if pay_date is None:
                continue
            pay_date_str = pay_date.strftime("%Y-%m-%d") if hasattr(pay_date, 'strftime') else str(pay_date)[:10]
            code = row["instrument"]
            ex_date_str = row["ex_date"].strftime("%Y-%m-%d") if row["ex_date"] is not None else pay_date_str
            if pay_date_str not in result:
                result[pay_date_str] = {}
            result[pay_date_str][code] = DividendInfo(
                stk_div=0.0,
                cash_div_tax=float(row["cash_div_tax"]),
                ex_date=ex_date_str,
                pay_date=pay_date_str,
            )

        return result

    @staticmethod
    def get_fund_split_by_ex_date(start_date, end_date, calendar):
        """F-B6: 查询生效日(ex_date)在回测区间内的基金拆分记录。

        用于 F3 式预加载：处理折算基准日(fund_split.date)在回测开始前、
        但 ex_date(下一交易日)在回测区间内的拆分事件——这些事件不会被
        F-B5 的 _after_market 捕获。

        ex_date = fund_split.date 的下一个交易日（价格生效日）。
        需要 calendar 来推导 ex_date。

        实现策略：
        - 查询 fund_split.date 在 [start_date 前 30 天, end_date] 范围内的记录
        - 用 calendar 推导每条记录的 ex_date
        - 仅保留 ex_date 在 [start_date, end_date] 范围内、且 fund_split.date < start_date 的记录
        - fund_split.date >= start_date 的记录由 F-B5 处理，此处排除避免重复

        参数:
            start_date: 起始日期 'YYYY-MM-DD'
            end_date:   结束日期 'YYYY-MM-DD'
            calendar:   交易日历列表 List[str]

        返回:
            dict，以 ex_date 字符串为一级 key，基金代码为二级 key，
            value 为 DividendInfo（stk_div = split_conversion - 1, cash_div_tax = 0）。
        """
        # 向前扩展查询范围以捕获跨长假的拆分（如春节可能有 10+ 天间隔）
        # 30 天缓冲足以覆盖所有节假日场景
        from datetime import datetime, timedelta
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        buffer_start = (start_dt - timedelta(days=30)).strftime("%Y-%m-%d")

        df = Data._db.query(f"""
            SELECT
                instrument, date, split_conversion
            FROM fund_split
            WHERE date >= '{buffer_start}' AND date <= '{end_date}'
        """).df()

        if df.empty:
            return {}

        # 构建 calendar index 映射
        cal_index = {d: i for i, d in enumerate(calendar)}

        result = {}
        for _, row in df.iterrows():
            split_date = row["date"]
            split_date_str = split_date.strftime("%Y-%m-%d") if hasattr(split_date, 'strftime') else str(split_date)[:10]
            code = row["instrument"]
            stk_div = float(row["split_conversion"]) - 1.0

            # 推导 ex_date = 拆分基准日的下一个交易日
            idx = cal_index.get(split_date_str)
            if idx is None:
                # 拆分基准日不在交易日历中——可能在回测区间前
                # 需要查找 calendar 中第一个 > split_date_str 的交易日作为 ex_date
                ex_date_str = None
                for cal_date in calendar:
                    if cal_date > split_date_str:
                        ex_date_str = cal_date
                        break
                if ex_date_str is None:
                    continue  # ex_date 不在回测区间内
            else:
                if idx >= len(calendar) - 1:
                    continue  # 末日拆分，ex_date 不在区间内
                ex_date_str = calendar[idx + 1]

            # 仅保留：ex_date 在 [start_date, end_date] 且 split_date < start_date
            # split_date >= start_date 的由 F-B5 处理
            if ex_date_str < start_date or ex_date_str > end_date:
                continue
            if split_date_str >= start_date:
                continue

            div_info = DividendInfo(
                stk_div=stk_div,
                cash_div_tax=0.0,
                ex_date=ex_date_str,
                pay_date=ex_date_str,
            )

            if ex_date_str not in result:
                result[ex_date_str] = {}

            existing = result[ex_date_str].get(code)
            if existing:
                # 极少见：同一 ex_date 多条拆分记录
                merged = (1 + existing.stk_div) * (1 + stk_div) - 1
                result[ex_date_str][code] = DividendInfo(
                    stk_div=merged,
                    cash_div_tax=0.0,
                    ex_date=ex_date_str,
                    pay_date=ex_date_str,
                )
            else:
                result[ex_date_str][code] = div_info

        return result

    # ------------------------------------------------------------------
    # B3. 价格取值函数
    # ------------------------------------------------------------------

    @staticmethod
    def get_price(code, context, info=None):
        """根据当前时间返回该股票的成交参考价。

        时间规则（对标原项目 data.py:get_price）：
            time < 09:30  → 上一交易日 close（previous_date）
                           首日盘前 previous_date 为 None 时，用当日 pre_close
            09:30 <= time < 15:00 → 当日 open
            time >= 15:00 → 当日 close

        停牌股返回 None。

        参数:
            code:    股票代码，如 '000001.SZ'
            context: 回测上下文（需包含 current_dt, previous_date）
            info:    可选，调用方已有的当日行情 DailyInfo，传入后跳过内部查询

        返回:
            float 或 None（停牌 / 无数据时返回 None）
        """
        current_dt = context.current_dt
        current_time = current_dt.time()

        if current_time < dtime(9, 30):
            # 盘前：取上一交易日 close
            if context.previous_date is not None:
                # 需要的是 previous_date 的数据，与调用方传入的当日 info 不同，仍需查缓存
                prev_info = Data.get_daily_info(code, context, date=context.previous_date)
                if prev_info is None:
                    return None
                price = prev_info.close
            else:
                # 首日盘前无 previous_date，用当日 pre_close
                day_info = info if info is not None else Data.get_daily_info(code, context)
                if day_info is None:
                    return None
                price = day_info.pre_close
        else:
            # 盘中 / 盘后：需要当日行情，优先复用调用方传入的 info
            day_info = info if info is not None else Data.get_daily_info(code, context)
            if day_info is None:
                return None
            # 停牌检查
            if day_info.stop == 1:
                return None
            if current_time < dtime(15, 0):
                price = day_info.open
            else:
                price = day_info.close

        # 价格有效性检查（NaN / 0 视为无效）
        if price is None or (isinstance(price, float) and math.isnan(price)) or price == 0:
            return None

        return price

    # ------------------------------------------------------------------
    # B5. 指数行情接口
    # ------------------------------------------------------------------
    @staticmethod
    def history(context, instruments, fields=None, bar_count=1):
        """获取历史K线数据。

        防未来数据：从“上一个交易日”（不含当日）向前回溯 bar_count 根K线。
        当日 close/high/low/volume 在盘前/盘中尚不可知，纳入即构成未来函数泄漏，
        故 history 一律截止到上一交易日。

        参数:
            instruments: List[str] — 股票代码列表
            fields:      List[str] — 需要的字段，默认 ['close']
                         可选: open, high, low, close, pre_close, volume, amount, vwap
            bar_count:   int — 回溯的K线数量（含当日）

        返回:
            dict {instrument: np.recarray}
            每个 recarray 包含 date 字段 + 请求的 fields，可通过属性访问：
                his = context.history(['000001.SZ'], ['close', 'volume'], 10)
                his['000001.SZ'].close   # → float64 数组
                his['000001.SZ'].date    # → 日期字符串数组
        """
        if fields is None:
            fields = ["close"]

        if Data._daily_cache is None:
            return {}

        calendar = context.data.calendar
        current_date = context.current_dt.strftime("%Y-%m-%d")

        # 在 calendar 中定位当前日期
        try:
            idx = calendar.index(current_date)
        except ValueError:
            idx = -1
            for i, d in enumerate(calendar):
                if d <= current_date:
                    idx = i
                else:
                    break
            if idx == -1:
                return {}

        # 防未来数据：回溯终点为“上一交易日”（idx-1），不含当日。
        # 当日为日历首日时（idx==0）无历史可回溯，返回空。
        end_idx = idx - 1
        if end_idx < 0:
            return {}

        start_idx = max(0, end_idx - bar_count + 1)
        dates = calendar[start_idx:end_idx + 1]

        if not dates:
            return {}

        # 字段类型映射
        float_fields = {"open", "high", "low", "close", "pre_close", "amount", "vwap",
                        "upLimit", "downLimit"}
        int_fields = {"volume", "stop", "st_status"}

        dtype_list = [("date", "U10")]
        for f in fields:
            if f in float_fields:
                dtype_list.append((f, "f8"))
            elif f in int_fields:
                dtype_list.append((f, "i8"))
            else:
                dtype_list.append((f, "f8"))

        result = {}
        for code in instruments:
            rows = []
            for date_str in dates:
                day_data = Data._daily_cache.get(date_str, {})
                info = day_data.get(code)
                row = [date_str]
                for f in fields:
                    val = getattr(info, f, None) if info else None
                    row.append(val if val is not None else (0 if f in int_fields else np.nan))
                rows.append(tuple(row))
            arr = np.array(rows, dtype=dtype_list)
            result[code] = arr.view(np.recarray)

        return result

    @staticmethod
    def get_index_daily(index_code, start_date, end_date):
        """获取时间区间内的指数行情

        参数:
            index_code: 指数代码
            start_date: 起始日期 'YYYY-MM-DD'
            end_date:   结束日期 'YYYY-MM-DD'

        返回:
            DataFrame, 包含trade_date、close、pct_chg字段
        """
        df = Data._db.query(
            f"""
            SELECT date AS trade_date, close, change_ratio * 100 AS pct_chg
            FROM index_bar
            WHERE date >= '{start_date}'
            AND date <= '{end_date}'
            AND instrument = '{index_code}'
            """
        ).df()
        return df