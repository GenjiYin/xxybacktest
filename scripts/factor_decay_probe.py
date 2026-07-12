"""
因子有效时限探针(一次性验证脚本)
================================================================================
回答一个问题: T 日算出因子信号后, 它还能有效预测未来多少天的收益, 多久失效?

两条互相印证的主线:
  1. 滞后 IC 衰减曲线(截面统计)
     IC_lag_k = 逐日 corr(因子值_T, 第 k 个持有日当天的收益), 再对所有 T 取均值。
     累积 IC(引擎里的 ic_5/ic_10) 只要不反转就一直往上爬, 看不出衰减拐点;
     边际/滞后 IC 会随 k 衰减到 0, 衰减到 0 的那个 k 才是有效时限。
     收益口径与引擎完全一致: 第 k 个持有日当天收益 = adj_open(T+1+k)/adj_open(T+k)-1,
     lag=1..N 累乘 == 引擎的累积 fwd_ret_N。
  2. 多空按持有期扫描(可交易组合验证)
     对不同 base_period 各跑一次分组多空, 看多空夏普随持有期怎么变。
     峰值持有期 == 最优调仓周期, 应与 IC 半衰期互相印证。

派生指标: 半衰期 / 显著性临界 k / 信息占比 / 指数拟合时间尺度 τ。

运行:  python scripts/factor_decay_probe.py [因子SQL文件路径]
       不传参则用内置示例因子(20日动量)。
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xxydb import xxydb
from xxybacktest.factor.engine_sql import _tradable_where
from xxybacktest.factor.engine import analyze_from_sql

DATA_PATH = os.environ.get("XXY_DATA_PATH", "./data")
# 只跑这个日期之后的截面, 快速验证。设为 None(或环境变量留空)跑全量。
START = os.environ.get("XXY_START", "2025-01-01")

# 看多远。默认 1~30 个持有日, 覆盖绝大多数股票 alpha 的保鲜期。
LAGS = list(range(1, 31))
# 多空持有期扫描点(交易日)
HOLDING_PERIODS = [1, 2, 3, 5, 8, 10, 15, 20, 30, 40, 60]

# 内置示例因子: 20日动量(复权收盘价), 方向由 direction 自动判定
DEFAULT_SQL = """
SELECT date, instrument,
       close * adjust_factor
         / LAG(close * adjust_factor, 20) OVER (PARTITION BY instrument ORDER BY date)
         - 1 AS value
FROM daily_bar
"""

pd.set_option("display.max_columns", 40)
pd.set_option("display.width", 200)


def section(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def apply_start(user_sql, start):
    """把日期下限包在用户因子 SQL 外层, 只算 start 之后的截面(未来价仍全量可取)。"""
    if not start:
        return user_sql
    return f"SELECT * FROM (\n{user_sql}\n) _uf WHERE date >= '{start}'"


# ==============================================================================
# 滞后 IC 的 SQL: 照抄 engine_sql 的 JOIN/过滤/winsor/zscore 结构,
# 只把收益列从"累积 fwd_ret_N"换成"第 k 个持有日当天的单日收益":
#     r_lag_k = adj_open(T+1+k) / adj_open(T+k) - 1
#   其中 T+1 是买入日(信号次日开盘), 故 lag=1 是买入当天(持有第1天)的收益。
#   lag=1..N 的 (1+r) 连乘 == engine 的累积 fwd_ret_N, 口径严格一致。
# ==============================================================================
def build_lagged_ic_sql(user_sql, lags, ic_method,
                        exclude_suspended, exclude_st, exclude_limit,
                        winsorize, standardize, winsor_q=0.01):
    where = _tradable_where(exclude_suspended, exclude_st, exclude_limit)

    lag_selects = []
    for k in lags:
        lag_selects.append(
            f"        LEAD(d.open * d.adjust_factor, {1 + k}) OVER w "
            f"/ NULLIF(LEAD(d.open * d.adjust_factor, {k}) OVER w, 0) - 1 "
            f"AS r_lag_{k}"
        )
    lag_sql = ",\n".join(lag_selects)
    lag_cols = [f"r_lag_{k}" for k in lags]
    lag_col_list = ", ".join(lag_cols)

    if winsorize:
        winsor_val = (
            f"LEAST(GREATEST(a.value, "
            f"quantile_cont(a.value, {winsor_q}) OVER (PARTITION BY a.date)), "
            f"quantile_cont(a.value, {1 - winsor_q}) OVER (PARTITION BY a.date))"
        )
    else:
        winsor_val = "a.value"

    if standardize:
        value_final = (
            "(w.value - avg(w.value) OVER (PARTITION BY w.date)) / "
            "NULLIF(stddev_samp(w.value) OVER (PARTITION BY w.date), 0)"
        )
    else:
        value_final = "w.value"

    cte = f"""
WITH uf AS (
{user_sql}
),
aligned AS (
    SELECT
        uf.date, uf.instrument, uf.value,
{lag_sql}
    FROM uf
    JOIN daily_bar d
      ON uf.instrument = d.instrument AND uf.date = d.date
    JOIN stock_status s
      ON uf.instrument = s.instrument AND uf.date = s.date
    WHERE uf.value IS NOT NULL{where}
    WINDOW w AS (PARTITION BY uf.instrument ORDER BY d.date)
),
winsor AS (
    SELECT a.date, a.instrument, {winsor_val} AS value, {lag_col_list}
    FROM aligned a
),
prep AS (
    SELECT w.date, w.instrument, {value_final} AS value, {lag_col_list}
    FROM winsor w
)"""

    if ic_method == "rank":
        rank_selects = ["date", "value"]
        for k in lags:
            rank_selects.append(
                f"RANK() OVER (PARTITION BY date ORDER BY r_lag_{k}) AS rr_{k}")
            rank_selects.append(
                f"CASE WHEN r_lag_{k} IS NOT NULL "
                f"THEN RANK() OVER (PARTITION BY date ORDER BY value) END AS rv_{k}")
        ranked = "SELECT " + ", ".join(rank_selects) + " FROM prep"
        ic_selects = ["date", "count(*) AS n"]
        for k in lags:
            ic_selects.append(f"corr(rv_{k}, rr_{k}) AS ic_lag_{k}")
        return (f"{cte},\nranked AS (\n{ranked}\n)\n"
                f"SELECT {', '.join(ic_selects)} FROM ranked "
                f"GROUP BY date ORDER BY date")
    else:
        ic_selects = ["date", "count(*) AS n"]
        for k in lags:
            ic_selects.append(f"corr(value, r_lag_{k}) AS ic_lag_{k}")
        return (f"{cte}\n"
                f"SELECT {', '.join(ic_selects)} FROM prep "
                f"GROUP BY date ORDER BY date")


# ==============================================================================
# 由逐日滞后 IC 汇总出衰减曲线 + 派生时限指标
# ==============================================================================
def build_decay_curve(ic_lag_df, lags):
    """把逐日 ic_lag_k 汇总成每个 lag 一行的衰减曲线(均值/标准差/t值/信息比)。"""
    rows = []
    for k in lags:
        col = f"ic_lag_{k}"
        s = ic_lag_df[col].dropna()
        if len(s) == 0:
            continue
        mean, std, nobs = s.mean(), s.std(), len(s)
        t_stat = mean / (std / np.sqrt(nobs)) if std > 0 else np.nan
        rows.append({
            "lag": k,
            "ic_mean": mean,
            "ic_std": std,
            "t_stat": t_stat,              # 该 lag 的 IC 是否显著异于 0
            "ic_ir": mean / std if std > 0 else np.nan,
            "n_days": nobs,
        })
    return pd.DataFrame(rows)


def derive_horizon(curve, sig_t=2.0):
    """
    从衰减曲线推出几个"有效时限"标量。曲线以 lag=1 的 IC 定符号(因子主方向),
    统一乘符号后按同向强度衰减来算, 负向因子(反转类)也能正确处理。
    """
    if curve.empty:
        return {}
    sign = np.sign(curve.iloc[0]["ic_mean"]) or 1.0
    ic = (curve["ic_mean"] * sign).values      # 主方向强度, 起点为正
    lag = curve["lag"].values
    tstat = (curve["t_stat"] * sign).values     # 同向的 t 值

    ic0 = ic[0]

    # 1) 半衰期: 同向 IC 首次跌破 ic0/2 的 lag(线性插值到小数)
    half = np.nan
    target = ic0 / 2.0
    for i in range(1, len(ic)):
        if ic[i] <= target:
            x0, x1 = ic[i - 1], ic[i]
            l0, l1 = lag[i - 1], lag[i]
            half = l0 + (target - x0) / (x1 - x0) * (l1 - l0) if x1 != x0 else l1
            break

    # 2) 显著性临界 lag: 同向 t 值最后一次 >= sig_t 的 lag(此后信号不再显著)
    sig_lags = lag[tstat >= sig_t]
    last_sig = int(sig_lags.max()) if len(sig_lags) else 0

    # 3) 信息占比: 前 k 个 lag 的同向 IC 之和占全部同向正 IC 之和的比例达 80% 的 k
    pos = np.clip(ic, 0, None)
    total = pos.sum()
    info80 = np.nan
    if total > 0:
        cum = np.cumsum(pos) / total
        idx = np.argmax(cum >= 0.8)
        if cum[idx] >= 0.8:
            info80 = int(lag[idx])

    # 4) 指数拟合特征时间尺度 τ: 对同向且为正的 IC 拟合 ln(IC) = ln(ic0) - lag/τ
    tau = np.nan
    fit_mask = ic > 0
    if fit_mask.sum() >= 3:
        x = lag[fit_mask].astype(float)
        y = np.log(ic[fit_mask])
        slope = np.polyfit(x, y, 1)[0]
        if slope < 0:
            tau = -1.0 / slope

    return {
        "sign": "正向(顺势)" if sign > 0 else "反向(反转)",
        "ic_lag1": ic0 * sign,
        "half_life": half,
        "last_sig_lag": last_sig,
        "info80_lag": info80,
        "tau": tau,
        "tau_half": tau * np.log(2) if not np.isnan(tau) else np.nan,
    }


# ==============================================================================
# 多空按持有期扫描: 复用引擎 analyze_from_sql, 只换 base_period
# ==============================================================================
def scan_holding_periods(db, user_sql, holding_periods, ic_method,
                         exclude_suspended, exclude_st, exclude_limit,
                         winsorize, standardize):
    rows = []
    for bp in holding_periods:
        try:
            out = analyze_from_sql(
                db, user_sql, periods=(bp,), n_groups=10, ic_method=ic_method,
                base_period=bp, exclude_suspended=exclude_suspended,
                exclude_st=exclude_st, exclude_limit=exclude_limit,
                winsorize=winsorize, standardize=standardize)
            m = out["metrics"]
            rows.append({
                "holding": bp,
                "ls_ann": m.get("ls_return"),
                "ls_sharpe": m.get("ls_sharpe"),
                "ls_maxdd": m.get("ls_maxdd"),
                "turnover": m.get("turnover"),
            })
        except Exception as e:
            print(f"[警告] holding={bp} 扫描失败: {e}")
    return pd.DataFrame(rows)


def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            user_sql = f.read().strip()
        print(f"[因子] 读自 {sys.argv[1]}")
    else:
        user_sql = DEFAULT_SQL.strip()
        print("[因子] 使用内置示例: 20日动量")

    user_sql = apply_start(user_sql, START)
    if START:
        print(f"[范围] 只算 {START} 之后的截面(快速验证; 设 XXY_START= 空跑全量)")

    section(f"连接 xxydb (path={DATA_PATH})")
    db = xxydb(path=DATA_PATH)
    try:
        # ---- 主线1: 滞后 IC 衰减曲线 ----
        section("主线1 · 滞后 IC 衰减曲线")
        sql = build_lagged_ic_sql(
            user_sql, LAGS, "rank",
            exclude_suspended=True, exclude_st=True, exclude_limit=True,
            winsorize=True, standardize=True)
        ic_lag_df = db.query(sql).df()
        ic_lag_df["date"] = pd.to_datetime(ic_lag_df["date"])
        print(f"逐日滞后 IC: {len(ic_lag_df)} 个截面日 "
              f"[{ic_lag_df['date'].min().date()} ~ {ic_lag_df['date'].max().date()}]")

        curve = build_decay_curve(ic_lag_df, LAGS)
        print("\n--- 衰减曲线(每个持有日当天的边际 IC)---")
        disp = curve.copy()
        for c in ["ic_mean", "ic_std", "t_stat", "ic_ir"]:
            disp[c] = disp[c].map(lambda v: f"{v:+.4f}")
        print(disp.to_string(index=False))

        # ASCII 衰减曲线, 直观看拐点
        print("\n--- IC 衰减形态(每行一个 lag, 竖线为 0) ---")
        ic_vals = curve["ic_mean"].values
        amax = np.nanmax(np.abs(ic_vals)) or 1.0
        for _, r in curve.iterrows():
            v = r["ic_mean"]
            width = int(round(abs(v) / amax * 30))
            if v >= 0:
                bar = " " * 30 + "|" + "#" * width
            else:
                bar = " " * (30 - width) + "#" * width + "|"
            print(f"lag {int(r['lag']):>2} {bar}  {v:+.4f}")

        # ---- 派生时限指标 ----
        section("派生时限指标")
        h = derive_horizon(curve)
        print(f"因子主方向     : {h.get('sign')}")
        print(f"lag1 边际 IC   : {h.get('ic_lag1'):+.4f}")
        hl = h.get("half_life")
        print(f"IC 半衰期      : {hl:.1f} 个交易日" if hl == hl else "IC 半衰期      : 未在观测窗内衰减到一半")
        print(f"显著临界 lag   : 第 {h.get('last_sig_lag')} 天后 IC 不再显著(|t|>=2)")
        i80 = h.get("info80_lag")
        print(f"信息80%耗尽    : 前 {i80} 天用掉八成预测力" if i80 == i80 else "信息80%耗尽    : 窗口内未达80%")
        tau = h.get("tau")
        if tau == tau:
            print(f"指数时间尺度 τ : {tau:.1f} 天 (指数半衰期 {h.get('tau_half'):.1f} 天)")
        else:
            print("指数时间尺度 τ : 拟合失败(非单调衰减)")

        # ---- 主线2: 多空按持有期扫描 ----
        section("主线2 · 多空绩效随持有期变化(可交易组合验证)")
        scan = scan_holding_periods(
            db, user_sql, HOLDING_PERIODS, "rank",
            exclude_suspended=True, exclude_st=True, exclude_limit=True,
            winsorize=True, standardize=True)
        if not scan.empty:
            disp2 = scan.copy()
            disp2["ls_ann"] = disp2["ls_ann"].map(lambda v: f"{v:+.2%}")
            disp2["ls_sharpe"] = disp2["ls_sharpe"].map(lambda v: f"{v:+.2f}")
            disp2["ls_maxdd"] = disp2["ls_maxdd"].map(lambda v: f"{v:.2%}")
            disp2["turnover"] = disp2["turnover"].map(lambda v: f"{v:.2%}")
            print(disp2.to_string(index=False))
            best = scan.loc[scan["ls_sharpe"].idxmax()]
            print(f"\n[峰值] 多空夏普最高在 holding={int(best['holding'])} 天 "
                  f"(sharpe={best['ls_sharpe']:+.2f})")
            print("      该持有期应与上面的 IC 半衰期互相印证:")
            print("      若半衰期短而峰值持有期长, 说明信号虽衰减但累积仍占优, 可拉长持有;")
            print("      若两者一致, 时限结论稳健。")

        # ---- 结论提示 ----
        section("怎么读这份报告")
        print("1. 衰减曲线单调掉到 0    -> 典型 alpha, 半衰期就是有效时限")
        print("2. 快速衰减后转负(#跑到左侧) -> 信号会反转, 过了保鲜期反被套")
        print("3. 长期不衰减的平台      -> 慢变量因子, 时限长, 可低频调仓")
        print("4. 半衰期 vs 多空夏普峰值持有期 二者印证, 定出调仓周期")
    finally:
        db.close()
    section("探针完成")


if __name__ == "__main__":
    main()
