"""
B 系列：数据接口层

Data 类以静态方法组织所有数据访问接口，与原项目结构对齐。
db 连接在回测启动时通过 Data.init_db() 初始化一次。
"""

import math
from dataclasses import dataclass
from datetime import time as dtime

from xxydb import xxydb


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

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    @staticmethod
    def init_db(path="./data"):
        """初始化 xxydb 连接，回测启动时调用一次。"""
        Data._db = xxydb(path=path)

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

        cache = {}
        for date_val, group in df.groupby("date"):
            date_str = date_val.strftime("%Y-%m-%d") if hasattr(date_val, 'strftime') else str(date_val)[:10]
            day_dict = {}
            for row in group.itertuples(index=False):
                code = row.instrument
                volume = row.volume
                amount = row.amount
                day_dict[code] = DailyInfo(
                    ts_code=code,
                    name=row.name,
                    open=float(row.open),
                    high=float(row.high),
                    low=float(row.low),
                    close=float(row.close),
                    pre_close=float(row.pre_close),
                    volume=int(volume),
                    amount=float(amount),
                    vwap=amount / (volume + 1),
                    upLimit=float(row.upper_limit),
                    downLimit=float(row.lower_limit),
                    stop=int(row.suspended),
                    st_status=int(row.st_status),
                )
            cache[date_str] = day_dict

        Data._daily_cache = cache

    @staticmethod
    def clear_cache():
        """释放缓存内存，回测结束后可调用。"""
        Data._daily_cache = None
        Data._dividend_reg_cache = None

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
        volume = row["volume"]       # 单位：股
        amount = row["amount"]       # 单位：元
        vwap = amount / (volume + 1)  # +1 防除零

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
                pay_date=ex_date_str,  # pay_date 缺失，用 ex_date 代替
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