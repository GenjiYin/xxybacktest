"""
================================================================================
engine —— 因子分析计算引擎(纯函数)
================================================================================
整个系统的心脏。喂三张 DataFrame, 出四张 DataFrame, 不碰文件、不碰数据库连接,
因此可脱离数据库单测。api.py(即时) 和 runner.py(落盘) 都调它, 口径必然一致。

核心入口: analyze(factor_df, price_df, status_df, ...) -> dict

流程(严格对应建设方案):
  1. 算未来 N 日收益   (次日开盘 + 后复权)
  2. 清洗票池          (剔停牌/ST/涨跌停)
  3. 横截面预处理      (去极值 MAD + zscore)
  4. 逐日 rank IC      -> ic_series
  5. 分 N 组回测       -> groups(每组收益/净值曲线) + 多空
  6. 汇总             -> yearly(年度) + metrics(全区间)
================================================================================
"""
import numpy as np
import pandas as pd

# 一年的交易日数, 用于把周期化的 IC/收益年化
TRADING_DAYS = 252


# ==============================================================================
# 步骤 1: 未来收益(次日开盘 + 后复权)
# ==============================================================================
def compute_forward_returns(price_df, periods, tradable_mask=None):
    """
    计算每只股票在每个截面日 T 的未来 N 日收益(次日开盘口径 + 后复权)。

    口径: T 日收盘后算出因子, 最早 T+1 开盘才能成交, 故
          fwd_N = (open*adj)(T+1+N) / (open*adj)(T+1) - 1
    这样买入价 open(T+1) 是算出因子之后才发生的价, 零未来函数。

    重要 —— 与 SQL 版对齐的停牌口径:
      "未来第 N 日"指未来第 N 个**可交易日**, 而非日历行。若中途某日停牌,
      应跳过该日、顺延到下一个可交易日的开盘价成交(真实交易也是如此:
      持有到第 N 日想卖但停牌, 只能等复牌首日卖)。因此传入 tradable_mask 后,
      先剔除不可交易行, 再在剩余的连续可交易序列上做 shift。
      不传 tradable_mask 时退化为在原始行上 shift(仅供无状态数据的单测使用)。

    参数:
        price_df:      含 date / instrument / open / adjust_factor 的行情表
        periods:       未来周期列表, 如 [1, 5, 10, 20]
        tradable_mask: 可选, DataFrame[date, instrument, tradable], 用于先过滤停牌

    返回:
        DataFrame[date, instrument, fwd_ret_{N}...], date 为 T(因子对齐日)
    """
    df = price_df[["date", "instrument", "open", "adjust_factor"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    # 后复权开盘价: 消除除权除息造成的价格跳变
    df["adj_open"] = df["open"] * df["adjust_factor"]

    # 先剔除不可交易行(与 SQL 的"过滤后再 LEAD"一致), 再 shift
    if tradable_mask is not None:
        m = tradable_mask.copy()
        m["date"] = pd.to_datetime(m["date"])
        df = df.merge(m[["date", "instrument", "tradable"]],
                      on=["date", "instrument"], how="left")
        df = df[df["tradable"].fillna(False)]
    # open 为 NaN(停牌但有行)的也剔除, 避免污染 shift 序列
    df = df.dropna(subset=["adj_open"])
    df = df.sort_values(["instrument", "date"])

    g = df.groupby("instrument", sort=False)["adj_open"]
    # buy = 次一个可交易日开盘价 open(T+1)
    buy = g.shift(-1)
    out = df[["date", "instrument"]].copy()
    for n in periods:
        # sell = 第 (1+N) 个可交易日开盘价
        sell = g.shift(-(1 + n))
        out[f"fwd_ret_{n}"] = sell / buy - 1
    return out


# ==============================================================================
# 步骤 2: 可交易过滤
# ==============================================================================
def build_tradable_mask(status_df, exclude_suspended=True, exclude_st=True,
                        exclude_limit=True):
    """
    根据 stock_status 生成"这一天这只股票能不能作为样本"的布尔表。

    过滤口径(勘探已验证):
        suspended = 0            不停牌
        st_status = 0            非 ST/*ST
        price_limit_status = 2   不涨停不跌停(次日无法按预期开盘价成交)

    参数:
        status_df: 含 date / instrument / suspended / st_status /
                   price_limit_status 的状态表
    返回:
        DataFrame[date, instrument, tradable(bool)]
    """
    s = status_df.copy()
    s["date"] = pd.to_datetime(s["date"])
    mask = pd.Series(True, index=s.index)
    if exclude_suspended:
        mask &= (s["suspended"] == 0)
    if exclude_st:
        mask &= (s["st_status"] == 0)
    if exclude_limit:
        mask &= (s["price_limit_status"] == 2)
    s["tradable"] = mask.values
    return s[["date", "instrument", "tradable"]]


# ==============================================================================
# 步骤 3: 横截面预处理(去极值 + 标准化)
# ==============================================================================
def preprocess_cross_section(s, winsorize=True, standardize=True, n_mad=5):
    """
    对单个截面日的因子值做去极值 + zscore。传入/返回都是一个 Series。

    去极值用 MAD(绝对中位差)法: 比 3σ 更抗异常值。
    标准化用 zscore: 均值0 标准差1, 让不同日期可比。
    """
    x = s.astype(float).copy()
    if winsorize:
        med = x.median()
        mad = (x - med).abs().median()
        if mad > 0:
            upper = med + n_mad * 1.4826 * mad   # 1.4826 使 MAD 与标准差同尺度
            lower = med - n_mad * 1.4826 * mad
            x = x.clip(lower, upper)
    if standardize:
        std = x.std()
        if std > 0:
            x = (x - x.mean()) / std
    return x


# ==============================================================================
# 步骤 4: 逐日 IC
# ==============================================================================
def compute_ic_series(panel, periods, ic_method="rank"):
    """
    逐个截面日算 IC = corr(因子值, 未来收益)。

    rank(Spearman): 先转秩再求相关, 抗异常值, 主流选择
    normal(Pearson): 直接线性相关, 对极端值敏感

    参数:
        panel: 已对齐 + 预处理的长表, 含 date / value / fwd_ret_{N}...
    返回:
        DataFrame[date, ic_{N}..., n], 每行一个截面日
    """
    rows = []
    for date, g in panel.groupby("date", sort=True):
        rec = {"date": date, "n": len(g)}
        for n in periods:
            col = f"fwd_ret_{n}"
            sub = g[["value", col]].dropna()
            if len(sub) < 2:
                rec[f"ic_{n}"] = np.nan
                continue
            if ic_method == "rank":
                # method='min' 与 SQL 的 RANK() 并列处理一致(并列取最小秩)
                rec[f"ic_{n}"] = (sub["value"].rank(method="min")
                                  .corr(sub[col].rank(method="min")))
            else:
                rec[f"ic_{n}"] = sub["value"].corr(sub[col])
        rows.append(rec)
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


# ==============================================================================
# 步骤 5: 分组回测
# ==============================================================================
def compute_groups(panel, base_period, n_groups=10):
    """
    分组回测: 每个调仓期按因子值分 N 组, 算每组等权未来 base_period 日收益。
    Q0 = 因子值最低组, Q(N-1) = 最高组。

    口径说明(严谨性):
      收益列 fwd_ret_{base_period} 是"未来 base_period 日收益", 逐日都算一个,
      相邻日样本高度重叠。若直接把每日收益累乘, 会把同一段涨跌重复计入 base_period 次,
      净值和年化严重虚高。故这里**按 base_period 取不重叠调仓期**(每隔 base_period 天
      调一次仓, 持有 base_period 天), 样本互不重叠, 累乘即真实净值, 年化才准确。

    返回:
        group_returns: DataFrame[date, group, ret]  逐调仓期逐组收益(不重叠)
        summary:       DataFrame[group, ann_return, nav_end, turnover]  各组汇总
        ls_series:     DataFrame[date, ret]  多空(最高-最低组)逐期收益
    """
    col = f"fwd_ret_{base_period}"
    all_dates = np.sort(panel["date"].unique())
    # 不重叠调仓日: 每隔 base_period 取一个
    rebalance_dates = set(all_dates[::base_period])

    recs = []
    # members[group] = 上一调仓期该组的股票集合, 用于算换手
    prev_members = {}
    turnover_acc = {gi: [] for gi in range(n_groups)}

    for date, g in panel.groupby("date", sort=True):
        if date not in rebalance_dates:
            continue
        sub = g[["instrument", "value", col]].dropna(subset=["value", col])
        if len(sub) < n_groups:
            continue
        # 与 SQL 的 NTILE(n) OVER(ORDER BY value, instrument) 精确对齐:
        # 按 (value, instrument) 升序排位, 前 (total % n) 组每组 ceil(total/n) 个, 其余 floor 个。
        total = len(sub)
        sub = sub.sort_values(["value", "instrument"]).reset_index(drop=True)
        order = np.arange(total)  # 已按 (value,instrument) 排序, 0-based 排位
        base_sz, rem = divmod(total, n_groups)
        # 每组容量: 前 rem 组 base_sz+1, 其余 base_sz; 前缀边界
        sizes = np.array([base_sz + 1 if i < rem else base_sz
                          for i in range(n_groups)])
        bounds = np.cumsum(sizes)  # 每组的右开边界(排位 < bounds[g] 属于组 g)
        grp = np.searchsorted(bounds, order, side="right")
        sub = sub.assign(group=grp)
        gm = sub.groupby("group")[col].mean()
        for gi, r in gm.items():
            recs.append({"date": date, "group": int(gi), "ret": r})
        # 换手: 本期成分与上期成分的差异比例
        for gi, gg in sub.groupby("group"):
            cur = set(gg["instrument"])
            gi = int(gi)
            if gi in prev_members and prev_members[gi]:
                old = prev_members[gi]
                # 换手 = 换出比例 = 1 - 交集/旧集合大小
                changed = len(old - cur) / len(old)
                turnover_acc[gi].append(changed)
            prev_members[gi] = cur

    group_returns = pd.DataFrame(recs)
    if group_returns.empty:
        return group_returns, pd.DataFrame(), pd.DataFrame()

    # 全区间实际跨越的交易日数, 用于年化。用实际有收益的调仓期数(与 SQL 版 groups_from_detail 对齐),
    # 而非采样点总数——末尾若干采样点可能因无未来收益被剔除。
    n_rebalance = group_returns["date"].nunique()
    hold_days = max(n_rebalance * base_period, 1)

    summ = []
    for gi, gg in group_returns.groupby("group"):
        r = gg["ret"].values
        nav_end = float(np.prod(1 + r))               # 不重叠, 累乘=真实净值
        ann = nav_end ** (TRADING_DAYS / hold_days) - 1 if nav_end > 0 else -1.0
        tvals = turnover_acc.get(int(gi), [])
        turnover = float(np.mean(tvals)) if tvals else np.nan
        summ.append({"group": int(gi), "ann_return": ann, "nav_end": nav_end,
                     "mean_ret": gg["ret"].mean(), "turnover": turnover})
    summary = pd.DataFrame(summ).sort_values("group").reset_index(drop=True)

    # 多空(最高组 - 最低组)逐期收益
    piv = group_returns.pivot(index="date", columns="group", values="ret")
    hi, lo = piv.columns.max(), piv.columns.min()
    ls_series = pd.DataFrame({"date": piv.index,
                              "ret": (piv[hi] - piv[lo]).values})
    return group_returns, summary, ls_series


# ==============================================================================
# 步骤 6: 汇总(年度 + 全区间)
# ==============================================================================
def _cumulative_curve(daily_ret):
    """把一列逐期收益累乘成净值曲线(起点 1.0)。"""
    return (1 + pd.Series(daily_ret).fillna(0)).cumprod()


def summarize(ic_series, group_returns, group_summary, ls_series,
              periods, base_period, direction=None):
    """
    把逐日结果汇总成 metrics(全区间单行) 和 yearly(逐年多行)。

    metrics: 列表页那一行要的所有标量(IC均值/ICIR/多空年化/胜率/...)
    yearly:  详情页年度表(每年的 IC / ICIR / 多空收益 / 多头收益)

    direction: 因子方向。None 则按 IC 符号自动判定(ic_mean>=0 → long)。
      多空组合与"多头组"都跟随 direction:
        long  → 做多高分位(Q_high), 空低分位;  多头组 = 最高分位组
        short → 做多低分位(Q_low),  空高分位;  多头组 = 最低分位组
      这样负向因子(如换手率, 低分位涨得多)的多空年化也为正, 且方向依据是
      IC 符号(全样本统计规律), 不是事后挑哪组收益高 —— 无数据窥探。

    返回: (metrics, yearly, ls_series)  —— ls_series 为按 direction 重构后的多空序列
    """
    base_ic = f"ic_{base_period}"

    # ---- 全区间 metrics ----
    ic = ic_series[base_ic].dropna()
    ic_mean = ic.mean()
    ic_std = ic.std()
    # ICIR 年化: 截面 IC 是"未来 base_period 日"的, 一年约 TRADING_DAYS/base_period 期
    n_per_year = TRADING_DAYS / base_period
    icir = (ic_mean / ic_std * np.sqrt(n_per_year)) if ic_std > 0 else np.nan

    # 方向判定: 参数优先, 否则按 IC 符号
    if direction not in ("long", "short"):
        direction = "long" if (ic_mean or 0) >= 0 else "short"

    # 按 direction 重构多空序列(做多正确的一端)
    long_group = None
    if not group_returns.empty:
        piv = group_returns.pivot(index="date", columns="group", values="ret")
        hi, lo = piv.columns.max(), piv.columns.min()
        if direction == "short":
            ls_ret = piv[lo] - piv[hi]      # 做多低分位, 空高分位
            long_group = lo
        else:
            ls_ret = piv[hi] - piv[lo]      # 做多高分位, 空低分位
            long_group = hi
        ls_series = pd.DataFrame({"date": piv.index, "ret": ls_ret.values})

    # 多空: ls_series 已是不重叠调仓期收益(每期持有 base_period 天)
    ls_ann, ls_sharpe, ls_maxdd = np.nan, np.nan, np.nan
    if not ls_series.empty:
        lr = ls_series["ret"].dropna()
        nav = _cumulative_curve(lr)
        nav_end = float(nav.iloc[-1])
        hold_days = max(len(lr) * base_period, 1)
        ls_ann = nav_end ** (TRADING_DAYS / hold_days) - 1 if nav_end > 0 else -1.0
        # 夏普: 每期收益, 一年约 TRADING_DAYS/base_period 期
        n_per_year = TRADING_DAYS / base_period
        ls_sharpe = (lr.mean() / lr.std() * np.sqrt(n_per_year)
                     if lr.std() > 0 else np.nan)
        ls_maxdd = float((nav / nav.cummax() - 1).min())

    # 多头组换手(跟随 direction 选高/低分位组)
    long_turnover = np.nan
    if not group_summary.empty and "turnover" in group_summary and long_group is not None:
        val = group_summary.loc[group_summary["group"] == long_group, "turnover"]
        long_turnover = float(val.iloc[0]) if len(val) else np.nan

    metrics = {
        "ic_mean": ic_mean,
        "ic_std": ic_std,
        "icir": icir,
        "ic_win_rate": float((ic > 0).mean()) if len(ic) else np.nan,
        "ls_return": ls_ann,
        "ls_sharpe": ls_sharpe,
        "ls_maxdd": ls_maxdd,
        "turnover": long_turnover,
        "n_days": int(len(ic)),
        "base_period": base_period,
        "direction": direction,
    }
    # 各周期 IC 均值也带上, 详情页可切换
    for n in periods:
        metrics[f"ic_mean_{n}"] = ic_series[f"ic_{n}"].dropna().mean()

    # ---- 年度 yearly ----
    ic_series = ic_series.copy()
    ic_series["year"] = pd.to_datetime(ic_series["date"]).dt.year
    yearly_rows = []
    # 年度收益: 该年内不重叠调仓期收益累乘(年内累计收益, 非年化)
    def _year_cum(df, year_col="year"):
        out = {}
        for y, gg in df.groupby(year_col):
            out[y] = float(np.prod(1 + gg["ret"].dropna().values)) - 1
        return out

    ls_by_year = {}
    if not ls_series.empty:
        lstmp = ls_series.copy()
        lstmp["year"] = pd.to_datetime(lstmp["date"]).dt.year
        ls_by_year = _year_cum(lstmp)

    # 多头组逐年收益(跟随 direction 选高/低分位组)
    long_by_year = {}
    if not group_returns.empty and long_group is not None:
        gr = group_returns.copy()
        gr["year"] = pd.to_datetime(gr["date"]).dt.year
        long_by_year = _year_cum(gr[gr["group"] == long_group])

    for y, gg in ic_series.groupby("year"):
        yic = gg[base_ic].dropna()
        yearly_rows.append({
            "year": int(y),
            "ic": yic.mean(),
            "icir": (yic.mean() / yic.std() * np.sqrt(n_per_year)
                     if yic.std() > 0 else np.nan),
            "ic_win_rate": float((yic > 0).mean()) if len(yic) else np.nan,
            "ls_return": ls_by_year.get(y, np.nan),
            "long_return": long_by_year.get(y, np.nan),
            "n_days": int(len(yic)),
        })
    yearly = pd.DataFrame(yearly_rows).sort_values("year").reset_index(drop=True)
    return metrics, yearly, ls_series


# ==============================================================================
# 主入口
# ==============================================================================
def analyze(factor_df, price_df, status_df, periods=(1, 5, 10, 20),
            n_groups=10, ic_method="rank", base_period=None,
            exclude_suspended=True, exclude_st=True, exclude_limit=True,
            winsorize=True, standardize=True, direction=None):
    """
    因子分析主入口(纯函数)。喂三张表出四张表。

    参数:
        factor_df: date / instrument / value  (用户 SQL 结果)
        price_df:  date / instrument / open / adjust_factor
        status_df: date / instrument / suspended / st_status / price_limit_status
        periods:   未来收益周期, 默认 (1,5,10,20)
        n_groups:  分组数
        ic_method: 'rank' 或 'normal'
        base_period: 分组/多空/汇总用哪个周期, 默认取 periods 第一个

    返回 dict:
        ic_series: 逐日 IC 时序
        groups:    逐日逐组收益
        group_summary: 各组年化收益/净值
        ls_series: 多空逐日收益
        yearly:    年度拆解
        metrics:   全区间标量指标
    """
    periods = list(periods)
    if base_period is None:
        base_period = periods[0]

    # 2. 可交易 mask(先算, 供未来收益按可交易序列 shift)
    mask = build_tradable_mask(status_df, exclude_suspended, exclude_st, exclude_limit)

    # 1. 未来收益(传入 mask, 在可交易序列上算, 与 SQL 版对齐)
    fwd = compute_forward_returns(price_df, periods, tradable_mask=mask)

    # 对齐: 因子值 + 未来收益(fwd 已仅含可交易行)
    f = factor_df[["date", "instrument", "value"]].copy()
    f["date"] = pd.to_datetime(f["date"])
    panel = f.merge(fwd, on=["date", "instrument"], how="inner")
    panel = panel.dropna(subset=["value"])

    # 3. 横截面预处理(逐日 zscore 因子值)
    panel["value"] = (panel.groupby("date")["value"]
                      .transform(lambda s: preprocess_cross_section(
                          s, winsorize, standardize)))

    # 4. IC
    ic_series = compute_ic_series(panel, periods, ic_method)

    # 5. 分组
    group_returns, group_summary, ls_series = compute_groups(
        panel, base_period, n_groups)

    # 6. 汇总(ls_series 按 direction 重构后返回)
    metrics, yearly, ls_series = summarize(ic_series, group_returns, group_summary,
                                           ls_series, periods, base_period, direction)

    # 覆盖度: 有因子值的可交易股票数 / 全体可交易股票数, 逐日平均
    #   分母 = 每日可交易股票(mask=True)总数; 分子 = 其中有因子值的
    tradable = mask[mask["tradable"]]
    denom = tradable.groupby("date")["instrument"].nunique()
    numer = panel.groupby("date")["instrument"].nunique()
    cov = (numer / denom.reindex(numer.index)).replace([np.inf], np.nan)
    metrics["coverage"] = float(cov.mean()) if len(cov) else np.nan

    return {
        "ic_series": ic_series,
        "groups": group_returns,
        "group_summary": group_summary,
        "ls_series": ls_series,
        "yearly": yearly,
        "metrics": metrics,
        "params": {"periods": periods, "n_groups": n_groups,
                   "ic_method": ic_method, "base_period": base_period},
    }


# ==============================================================================
# SQL-first 收尾: 从 SQL 出的分组明细 -> group_returns / summary / ls_series
# ==============================================================================
def groups_from_detail(detail, base_period, n_groups):
    """
    输入 engine_sql.build_groups_sql 的结果明细(已是不重叠调仓期 + 已分组):
        detail[date, grp, instrument, ret]
    产出与 compute_groups 完全一致的三张表(含换手率)。

    SQL 已完成: 不重叠采样、NTILE 分组、对齐收益。
    这里 pandas 只做 SQL 啃不动的: 逐组平均收益 + 相邻期成分集合差异(换手) + 年化。
    """
    if detail is None or detail.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    detail = detail.copy()
    detail["date"] = pd.to_datetime(detail["date"])
    detail["grp"] = detail["grp"].astype(int)

    # 逐调仓期逐组平均收益
    gr = (detail.groupby(["date", "grp"])["ret"].mean()
          .reset_index().rename(columns={"grp": "group"}))
    gr = gr.sort_values(["date", "group"]).reset_index(drop=True)

    # 换手: 每组相邻调仓期成分股集合差异
    turnover_acc = {gi: [] for gi in range(n_groups)}
    prev_members = {}
    for date in sorted(detail["date"].unique()):
        day = detail[detail["date"] == date]
        for gi, gg in day.groupby("grp"):
            gi = int(gi)
            cur = set(gg["instrument"])
            if gi in prev_members and prev_members[gi]:
                old = prev_members[gi]
                turnover_acc[gi].append(len(old - cur) / len(old))
            prev_members[gi] = cur

    n_rebalance = gr["date"].nunique()
    hold_days = max(n_rebalance * base_period, 1)

    summ = []
    for gi, gg in gr.groupby("group"):
        r = gg["ret"].values
        nav_end = float(np.prod(1 + r))
        ann = nav_end ** (TRADING_DAYS / hold_days) - 1 if nav_end > 0 else -1.0
        tvals = turnover_acc.get(int(gi), [])
        turnover = float(np.mean(tvals)) if tvals else np.nan
        summ.append({"group": int(gi), "ann_return": ann, "nav_end": nav_end,
                     "mean_ret": gg["ret"].mean(), "turnover": turnover})
    summary = pd.DataFrame(summ).sort_values("group").reset_index(drop=True)

    piv = gr.pivot(index="date", columns="group", values="ret")
    hi, lo = piv.columns.max(), piv.columns.min()
    ls_series = pd.DataFrame({"date": piv.index,
                              "ret": (piv[hi] - piv[lo]).values})
    return gr, summary, ls_series


# ==============================================================================
# 因子有效时限: 滞后 IC 衰减曲线 + 派生时限标量 + 多空持有期扫描
# ==============================================================================
def build_decay_curve(ic_lag_df, lags):
    """
    把逐日滞后 IC(ic_lag_{k}) 汇总成"每个 lag 一行"的衰减曲线。
    输入 ic_lag_df: build_lagged_ic_sql 的结果, 列 date/n/ic_lag_1.../ic_lag_K。
    输出 DataFrame[lag, ic_mean, ic_std, t_stat, ic_ir, n_days]。
    t_stat 判断该 lag 的边际 IC 是否显著异于 0。
    """
    rows = []
    for k in lags:
        col = f"ic_lag_{k}"
        if col not in ic_lag_df.columns:
            continue
        s = ic_lag_df[col].dropna()
        if len(s) == 0:
            continue
        mean, std, nobs = float(s.mean()), float(s.std()), int(len(s))
        t_stat = mean / (std / np.sqrt(nobs)) if std > 0 else np.nan
        rows.append({
            "lag": int(k),
            "ic_mean": mean,
            "ic_std": std,
            "t_stat": t_stat,
            "ic_ir": mean / std if std > 0 else np.nan,
            "n_days": nobs,
        })
    return pd.DataFrame(rows)


def derive_horizon(curve, sig_t=2.0):
    """
    从衰减曲线推出"有效时限"标量。曲线以 lag=1 的 IC 定符号(因子主方向),
    统一乘符号后按同向强度衰减来算, 负向因子(反转类)也能正确处理。

    返回 dict:
        ic_lag1       lag1 边际 IC(带原符号)
        half_life     半衰期: 同向 IC 首次跌破 ic0/2 的 lag(线性插值)
        last_sig_lag  显著临界: 同向 t 值最后一次 >= sig_t 的 lag(此后不再显著)
        info80_lag    信息80%: 前 k 个 lag 累计同向正 IC 占比达 80% 的 k
        tau           指数拟合特征时间尺度(天), 拟合失败为 nan
    """
    if curve is None or curve.empty:
        return {}
    curve = curve.sort_values("lag").reset_index(drop=True)
    sign = np.sign(curve.iloc[0]["ic_mean"]) or 1.0
    ic = (curve["ic_mean"] * sign).values      # 主方向强度, 起点为正
    lag = curve["lag"].values.astype(float)
    tstat = (curve["t_stat"] * sign).values
    ic0 = ic[0]

    # 半衰期(线性插值到小数)
    half = np.nan
    target = ic0 / 2.0
    for i in range(1, len(ic)):
        if ic[i] <= target:
            x0, x1, l0, l1 = ic[i - 1], ic[i], lag[i - 1], lag[i]
            half = (l0 + (target - x0) / (x1 - x0) * (l1 - l0)
                    if x1 != x0 else l1)
            break

    # 显著临界 lag
    sig_lags = lag[tstat >= sig_t]
    last_sig = int(sig_lags.max()) if len(sig_lags) else 0

    # 信息 80% 耗尽
    pos = np.clip(ic, 0, None)
    total = pos.sum()
    info80 = np.nan
    if total > 0:
        cum = np.cumsum(pos) / total
        idx = int(np.argmax(cum >= 0.8))
        if cum[idx] >= 0.8:
            info80 = int(lag[idx])

    # 指数拟合 τ: ln(IC) = ln(ic0) - lag/τ, 只用同向为正的点
    tau = np.nan
    fit_mask = ic > 0
    if fit_mask.sum() >= 3:
        slope = np.polyfit(lag[fit_mask], np.log(ic[fit_mask]), 1)[0]
        if slope < 0:
            tau = -1.0 / slope

    return {
        "ic_lag1": float(ic0 * sign),
        "half_life": float(half) if half == half else np.nan,
        "last_sig_lag": last_sig,
        "info80_lag": int(info80) if info80 == info80 else np.nan,
        "tau": float(tau) if tau == tau else np.nan,
    }


def analyze_from_sql(db, user_sql, periods=(1, 5, 10, 20), n_groups=10,
                     ic_method="rank", base_period=None,
                     exclude_suspended=True, exclude_st=True, exclude_limit=True,
                     winsorize=True, standardize=True, direction=None,
                     decay_lags=tuple(range(1, 21)),
                     with_horizon=True):
    """
    SQL-first 主入口。把用户因子 SQL 下推 DuckDB 算 IC/分组/覆盖度,
    pandas 只收尾算换手和汇总。返回与 analyze() 完全一致的六键 dict。

    参数:
        db:        已打开的 xxydb 连接
        user_sql:  用户因子 SQL, 须返回 date/instrument/value 三列
        其余同 analyze()
    """
    from . import engine_sql as es
    periods = list(periods)
    if base_period is None:
        base_period = periods[0]

    # 1. IC 时序(SQL)
    ic_sql = es.build_ic_sql(user_sql, periods, ic_method, exclude_suspended,
                             exclude_st, exclude_limit, winsorize, standardize)
    ic_series = db.query(ic_sql).df()
    ic_series["date"] = pd.to_datetime(ic_series["date"])

    # 2. 分组明细(SQL) -> pandas 收尾
    g_sql = es.build_groups_sql(user_sql, base_period, n_groups, exclude_suspended,
                                exclude_st, exclude_limit, winsorize, standardize)
    detail = db.query(g_sql).df()
    group_returns, group_summary, ls_series = groups_from_detail(
        detail, base_period, n_groups)

    # 3. 汇总(ls_series 按 direction 重构后返回)
    metrics, yearly, ls_series = summarize(ic_series, group_returns, group_summary,
                                           ls_series, periods, base_period, direction)

    # 4. 覆盖度(SQL)
    cov_sql = es.build_coverage_sql(user_sql, exclude_suspended, exclude_st,
                                    exclude_limit)
    cov = db.query(cov_sql).df()
    metrics["coverage"] = float(cov["coverage"].mean()) if len(cov) else np.nan

    # 5. 因子有效时限(可选, 每日重跑要背这块耗时, 故可关)
    decay_curve = pd.DataFrame()
    if with_horizon:
        # 滞后 IC 衰减曲线(SQL) -> 汇总 -> 派生半衰期等标量。
        # 衰减曲线只看形状/拐点, 固定用 Pearson(normal): 与 Spearman 衰减形态几乎一致,
        # 但省掉每个 lag 两个 RANK() 排序窗口(20-lag 下 rank 约 43s, normal 约 8s)。
        decay_lags = list(decay_lags)
        lag_sql = es.build_lagged_ic_sql(
            user_sql, decay_lags, "normal", exclude_suspended, exclude_st,
            exclude_limit, winsorize, standardize)
        ic_lag_df = db.query(lag_sql).df()
        decay_curve = build_decay_curve(ic_lag_df, decay_lags)
        horizon = derive_horizon(decay_curve)
        # 时限标量并入 metrics(前端 KPI 直接读)
        metrics["half_life"] = horizon.get("half_life", np.nan)
        metrics["last_sig_lag"] = horizon.get("last_sig_lag", np.nan)
        metrics["info80_lag"] = horizon.get("info80_lag", np.nan)
        metrics["decay_tau"] = horizon.get("tau", np.nan)

    return {
        "ic_series": ic_series,
        "groups": group_returns,
        "group_summary": group_summary,
        "ls_series": ls_series,
        "yearly": yearly,
        "metrics": metrics,
        "decay_curve": decay_curve,
        "params": {"periods": periods, "n_groups": n_groups,
                   "ic_method": ic_method, "base_period": base_period,
                   "decay_lags": list(decay_lags)},
    }
