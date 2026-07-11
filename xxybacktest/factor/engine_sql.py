"""
================================================================================
engine_sql —— SQL-first 计算下推(深度绑定 xxydb / DuckDB)
================================================================================
因子分析以快为主。把用户的因子 SQL 当作子查询(CTE)塞进来, 外层拼接
"未来收益 + 可交易过滤 + 截面标准化 + rank + 分组" 的 SQL, 一次性在 DuckDB
里跑完绝大部分计算, .df() 出来已是接近成品的小结果。换手率这类"相邻期成分
集合差异"SQL 啃不动的, 留给 engine.py 的 pandas 段收尾。

对外提供两个拼接函数, 各返回一条可直接 db.query() 的 SQL:
  build_ic_sql        -> 逐日各周期 IC + 每日样本数 + 覆盖度分子
  build_groups_sql    -> 不重叠调仓期的逐组收益 + 每组成分明细(供 pandas 算换手)

设计要点:
  - 用户 SQL 只需返回 date / instrument / value 三列(见建设方案约定)
  - 收益口径: 次日开盘后复权  (open*adj)(T+1+N)/(open*adj)(T+1)-1
  - 过滤口径: suspended=0 AND st_status=0 AND price_limit_status=2
  - 预处理:   截面 zscore(去极值默认用分位裁剪, 比 MAD 更 SQL 友好)
================================================================================
"""


def _tradable_where(exclude_suspended, exclude_st, exclude_limit):
    """拼接可交易过滤条件(作用在 join 了 stock_status 的行上)。"""
    conds = []
    if exclude_suspended:
        conds.append("s.suspended = 0")
    if exclude_st:
        conds.append("s.st_status = 0")
    if exclude_limit:
        conds.append("s.price_limit_status = 2")
    return (" AND " + " AND ".join(conds)) if conds else ""


def _forward_return_selects(periods):
    """为每个周期生成 未来收益列: (open*adj)(T+1+N)/(open*adj)(T+1)-1。

    buy = LEAD(adj_open, 1), sell_N = LEAD(adj_open, 1+N), fwd_N = sell_N/buy - 1
    """
    lines = []
    for n in periods:
        lines.append(
            f"        LEAD(d.open * d.adjust_factor, {1 + n}) "
            f"OVER w / NULLIF(LEAD(d.open * d.adjust_factor, 1) OVER w, 0) - 1 "
            f"AS fwd_ret_{n}"
        )
    return ",\n".join(lines)


def _base_cte(user_sql, periods, winsorize, standardize,
              exclude_suspended, exclude_st, exclude_limit,
              winsor_q=0.01):
    """
    构建公共前置 CTE:
      uf      = 用户因子 SQL (原样)
      aligned = uf JOIN daily_bar + stock_status, 算未来收益 + 过滤
      prep    = 截面去极值(分位裁剪) + zscore 标准化后的因子值
    返回 (cte_sql, 最终可用表名 'prep', 收益列名列表)
    """
    where = _tradable_where(exclude_suspended, exclude_st, exclude_limit)
    fwd_selects = _forward_return_selects(periods)

    fwd_cols = [f"fwd_ret_{n}" for n in periods]
    fwd_col_list = ", ".join(fwd_cols)

    # 预处理分两步(DuckDB 不允许窗口函数嵌套, 故 winsorize 与 zscore 各占一个 CTE)
    # 第一步 winsor: 截面分位裁剪去极值
    if winsorize:
        winsor_val = (
            f"LEAST(GREATEST(a.value, "
            f"quantile_cont(a.value, {winsor_q}) OVER (PARTITION BY a.date)), "
            f"quantile_cont(a.value, {1 - winsor_q}) OVER (PARTITION BY a.date))"
        )
    else:
        winsor_val = "a.value"

    # 第二步 zscore: 在 winsor 结果上做截面标准化
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
{fwd_selects}
    FROM uf
    JOIN daily_bar d
      ON uf.instrument = d.instrument AND uf.date = d.date
    JOIN stock_status s
      ON uf.instrument = s.instrument AND uf.date = s.date
    WHERE uf.value IS NOT NULL{where}
    WINDOW w AS (PARTITION BY uf.instrument ORDER BY d.date)
),
winsor AS (
    SELECT a.date, a.instrument,
           {winsor_val} AS value,
           {fwd_col_list}
    FROM aligned a
),
prep AS (
    SELECT w.date, w.instrument,
           {value_final} AS value,
           {fwd_col_list}
    FROM winsor w
)"""
    return cte, fwd_cols


def build_ic_sql(user_sql, periods, ic_method="rank",
                 exclude_suspended=True, exclude_st=True, exclude_limit=True,
                 winsorize=True, standardize=True):
    """
    生成逐日 IC 的 SQL。返回列: date, ic_{N}..., n

    rank IC: 截面对 value 和 fwd_ret 分别 RANK, 再 corr
    normal IC: 直接 corr(value, fwd_ret)
    每个周期一列 ic_{N}。n = 该截面日参与样本数(以 base_period 无关, 取有 value 行)。
    """
    cte, fwd_cols = _base_cte(user_sql, periods, winsorize, standardize,
                              exclude_suspended, exclude_st, exclude_limit)

    if ic_method == "rank":
        # 每个周期在截面内对 value、fwd_ret 排秩
        rank_selects = ["date", "value"]
        for n in periods:
            rank_selects.append(
                f"RANK() OVER (PARTITION BY date ORDER BY fwd_ret_{n}) AS rr_{n}")
            rank_selects.append(
                f"CASE WHEN fwd_ret_{n} IS NOT NULL "
                f"THEN RANK() OVER (PARTITION BY date ORDER BY value) END AS rv_{n}")
        ranked = "SELECT " + ", ".join(rank_selects) + " FROM prep"
        ic_selects = ["date", "count(*) AS n"]
        for n in periods:
            ic_selects.append(f"corr(rv_{n}, rr_{n}) AS ic_{n}")
        final = (f"{cte},\nranked AS (\n{ranked}\n)\n"
                 f"SELECT {', '.join(ic_selects)} FROM ranked "
                 f"GROUP BY date ORDER BY date")
    else:
        ic_selects = ["date", "count(*) AS n"]
        for n in periods:
            ic_selects.append(f"corr(value, fwd_ret_{n}) AS ic_{n}")
        final = (f"{cte}\n"
                 f"SELECT {', '.join(ic_selects)} FROM prep "
                 f"GROUP BY date ORDER BY date")
    return final


def build_groups_sql(user_sql, base_period, n_groups=10,
                     exclude_suspended=True, exclude_st=True, exclude_limit=True,
                     winsorize=True, standardize=True):
    """
    生成不重叠调仓期的逐组收益 + 成分明细 SQL。返回列:
        date, grp, instrument, ret   (每行 = 某调仓期某组的一只成分股及其收益)

    pandas 段拿到后:
        - groupby(date,grp).ret.mean()  -> 逐组收益
        - 相邻期 grp 的 instrument 集合差异 -> 换手
    不重叠采样: 对 prep 里出现的交易日 dense_rank, 每隔 base_period 取一期。
    """
    cte, _ = _base_cte(user_sql, [base_period], winsorize, standardize,
                       exclude_suspended, exclude_st, exclude_limit)
    col = f"fwd_ret_{base_period}"

    final = f"""{cte},
dates AS (
    SELECT date, dense_rank() OVER (ORDER BY date) - 1 AS dnum
    FROM (SELECT DISTINCT date FROM prep)
),
sampled AS (
    SELECT p.date, p.instrument, p.value, p.{col} AS ret
    FROM prep p
    JOIN dates dt ON p.date = dt.date
    WHERE dt.dnum % {base_period} = 0
      AND p.value IS NOT NULL AND p.{col} IS NOT NULL
),
grouped AS (
    SELECT date, instrument, ret,
           -- 加 instrument 次级排序, 使并列 value 的分组与 pandas 端 tie-break 一致
           NTILE({n_groups}) OVER (PARTITION BY date ORDER BY value, instrument) - 1 AS grp
    FROM sampled
)
SELECT date, grp, instrument, ret FROM grouped ORDER BY date, grp"""
    return final


def build_coverage_sql(user_sql, exclude_suspended=True, exclude_st=True,
                       exclude_limit=True):
    """
    覆盖度 SQL: 逐日 (有因子值的可交易股票数) / (全体可交易股票数)。
    分母 = 当日所有满足过滤的股票; 分子 = 其中出现在用户因子结果里且 value 非空。
    返回列: date, coverage
    """
    # 过滤条件(去掉前导 ' AND ', 用于 WHERE)
    where = _tradable_where(exclude_suspended, exclude_st, exclude_limit)
    where_clause = ("WHERE " + where[len(" AND "):]) if where else ""
    return f"""
WITH uf AS (
{user_sql}
),
fdates AS (              -- 只在因子实际覆盖的交易日上算覆盖度
    SELECT DISTINCT date FROM uf
),
tradable AS (            -- 分母: 这些日期上全体可交易股票
    SELECT s.date, s.instrument
    FROM stock_status s
    JOIN fdates f ON f.date = s.date
    {where_clause}
),
have AS (                -- 分子: 其中有因子值的
    SELECT DISTINCT t.date, t.instrument
    FROM tradable t
    JOIN uf ON uf.date = t.date AND uf.instrument = t.instrument
    WHERE uf.value IS NOT NULL
)
SELECT t.date,
       count(DISTINCT h.instrument) * 1.0 / NULLIF(count(DISTINCT t.instrument), 0) AS coverage
FROM tradable t
LEFT JOIN have h ON h.date = t.date AND h.instrument = t.instrument
GROUP BY t.date ORDER BY t.date"""

