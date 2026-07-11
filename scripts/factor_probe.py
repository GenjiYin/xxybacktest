"""
阶段0 · 数据勘探脚本(一次性)

目的:在写因子分析引擎前,摸清 daily_bar / stock_status 的真实字段、日期格式、
数据范围,并用一个最简因子验证「SQL 查因子值 → 算次日开盘收益 → 求 rank IC」全链路能通。

运行:  python scripts/factor_probe.py
"""
import os
import sys
import pandas as pd

# 允许直接从项目根运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xxydb import xxydb

DATA_PATH = os.environ.get("XXY_DATA_PATH", "./data")

pd.set_option("display.max_columns", 40)
pd.set_option("display.width", 200)


def section(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def main():
    section(f"连接 xxydb (path={DATA_PATH})")
    db = xxydb(path=DATA_PATH)

    # ---- 1. 有哪些表 ----
    section("1. 数据库中的表")
    try:
        tables = db.query("SHOW TABLES").df()
        print(tables)
    except Exception as e:
        print(f"[警告] SHOW TABLES 失败: {e}")

    # ---- 2. daily_bar 结构 ----
    section("2. daily_bar 字段 + 样例 + 日期范围")
    try:
        cols = db.query("DESCRIBE daily_bar").df()
        print("--- 字段 ---")
        print(cols)
    except Exception as e:
        print(f"[警告] DESCRIBE daily_bar 失败: {e}")
    try:
        sample = db.query("SELECT * FROM daily_bar LIMIT 5").df()
        print("\n--- 样例5行 ---")
        print(sample)
        print("\n--- 列名 ---")
        print(list(sample.columns))
    except Exception as e:
        print(f"[警告] 读 daily_bar 样例失败: {e}")
    try:
        rng = db.query(
            "SELECT MIN(date) AS min_date, MAX(date) AS max_date, "
            "COUNT(*) AS n_rows, COUNT(DISTINCT instrument) AS n_stocks, "
            "COUNT(DISTINCT date) AS n_days FROM daily_bar"
        ).df()
        print("\n--- 范围统计 ---")
        print(rng)
    except Exception as e:
        print(f"[警告] daily_bar 统计失败: {e}")

    # ---- 3. stock_status 结构 ----
    section("3. stock_status 字段 + suspended/st_status 取值分布")
    try:
        cols = db.query("DESCRIBE stock_status").df()
        print("--- 字段 ---")
        print(cols)
        sample = db.query("SELECT * FROM stock_status LIMIT 5").df()
        print("\n--- 样例5行 ---")
        print(sample)
        for col in ["suspended", "st_status"]:
            try:
                dist = db.query(
                    f"SELECT {col}, COUNT(*) AS n FROM stock_status GROUP BY {col} ORDER BY {col}"
                ).df()
                print(f"\n--- {col} 取值分布 ---")
                print(dist)
            except Exception as e:
                print(f"[警告] {col} 分布失败: {e}")
    except Exception as e:
        print(f"[警告] stock_status 勘探失败: {e}")

    # ---- 4. 全链路冒烟:昨日涨幅因子 → 次日开盘收益 → rank IC ----
    section("4. 全链路冒烟测试(最简因子:昨日涨幅)")
    smoke_test(db)

    db.close()
    section("勘探完成")


def smoke_test(db):
    """
    用一个最简因子验证全链路:
      因子 = 昨日涨幅 (close/pre_close - 1),T 日已知
      未来1日收益 = open(T+2)/open(T+1) - 1  (次日开盘口径)
      逐日 rank IC = corr(rank(因子), rank(未来收益))
    只取最近一段日期,快速验证逻辑通不通。
    """
    try:
        # 取最近 60 个交易日的行情(open/close/pre_close + 停牌ST)
        df = db.query("""
            SELECT d.date, d.instrument, d.open, d.close, d.pre_close,
                   s.suspended, s.st_status
            FROM daily_bar d
            INNER JOIN stock_status s
              ON d.instrument = s.instrument AND d.date = s.date
            WHERE d.date >= (SELECT MAX(date) FROM daily_bar) - INTERVAL 90 DAY
        """).df()
    except Exception as e:
        print(f"[警告] 冒烟取数失败(可能日期类型不支持 INTERVAL): {e}")
        print("      改用 fallback:取全表最后 90 个交易日")
        try:
            days = db.query(
                "SELECT DISTINCT date FROM daily_bar ORDER BY date DESC LIMIT 90"
            ).df()["date"].tolist()
            lo = min(days)
            df = db.query(f"""
                SELECT d.date, d.instrument, d.open, d.close, d.pre_close,
                       s.suspended, s.st_status
                FROM daily_bar d
                INNER JOIN stock_status s
                  ON d.instrument = s.instrument AND d.date = s.date
                WHERE d.date >= '{lo}'
            """).df()
        except Exception as e2:
            print(f"[错误] fallback 也失败: {e2}")
            return

    if df.empty:
        print("[错误] 冒烟查询返回空,无法继续")
        return

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["instrument", "date"]).reset_index(drop=True)
    print(f"取到 {len(df)} 行, {df['instrument'].nunique()} 只股票, "
          f"{df['date'].nunique()} 个交易日 [{df['date'].min().date()} ~ {df['date'].max().date()}]")

    # 因子:昨日涨幅(T日已知)
    df["factor"] = df["close"] / df["pre_close"] - 1

    # 次日开盘口径未来1日收益:每只股票,T 日对应 open(T+1)->open(T+2)
    df["open_next1"] = df.groupby("instrument")["open"].shift(-1)   # open(T+1)
    df["open_next2"] = df.groupby("instrument")["open"].shift(-2)   # open(T+2)
    df["fwd_ret_1"] = df["open_next2"] / df["open_next1"] - 1

    # 可交易过滤:剔停牌 + ST
    clean = df[(df["suspended"] == 0) & (df["st_status"] == 0)].copy()
    clean = clean.dropna(subset=["factor", "fwd_ret_1"])
    print(f"清洗后(剔停牌/ST/缺失): {len(clean)} 行")

    # 逐日 rank IC
    ics = []
    for date, g in clean.groupby("date"):
        if len(g) < 30:
            continue
        ic = g["factor"].rank().corr(g["fwd_ret_1"].rank())
        ics.append((date, ic, len(g)))

    if not ics:
        print("[警告] 没有足够样本算 IC")
        return

    ic_df = pd.DataFrame(ics, columns=["date", "rank_ic", "n"])
    print("\n--- 逐日 rank IC(最近10日)---")
    print(ic_df.tail(10).to_string(index=False))
    print(f"\n--- 汇总 ---")
    print(f"IC 均值    : {ic_df['rank_ic'].mean():+.4f}")
    print(f"IC 标准差  : {ic_df['rank_ic'].std():.4f}")
    print(f"IC 胜率    : {(ic_df['rank_ic'] > 0).mean():.2%}")
    print(f"有效天数   : {len(ic_df)}")
    print("\n[结论] 昨日涨幅是反转类因子,A股短期通常呈负 IC(隔日反转)。"
          "若 IC 均值为负号,说明全链路方向正确、逻辑通。")


if __name__ == "__main__":
    main()
