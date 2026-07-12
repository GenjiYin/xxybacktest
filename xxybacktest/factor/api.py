"""
================================================================================
api —— 即时分析接口(notebook 门面)
================================================================================
engine 的薄门面。用户传一条因子 SQL, 一行拿到可画图的 FactorResult。
不落盘、不登记, 一次性。用于探索、调参、试因子。

    from xxybacktest.factor import analyze_factor
    res = analyze_factor(
        sql="SELECT date, instrument, close/pre_close-1 AS value FROM daily_bar",
        data_path=r"D:\\Desktop\\最新回测框架\\data",
    )
    res.summary()
    res.plot()

生产侧的 submit_factor / run_all(每日落盘更新前端)复用同一个 engine,口径一致。
================================================================================
"""
from .engine import analyze_from_sql
from .result import FactorResult

# 因子 SQL 必须返回的列
REQUIRED_COLS = {"date", "instrument", "value"}


def _validate_sql_result(db, sql):
    """执行前轻量校验: 跑一条 LIMIT 1 确认返回了 date/instrument/value 三列。"""
    probe = f"SELECT * FROM ({sql}) _probe LIMIT 1"
    try:
        df = db.query(probe).df()
    except Exception as e:
        raise ValueError(f"因子 SQL 执行失败: {e}")
    cols = set(df.columns)
    missing = REQUIRED_COLS - cols
    if missing:
        raise ValueError(
            f"因子 SQL 必须返回 date/instrument/value 三列, 缺少: {missing}。"
            f"实际返回: {sorted(cols)}")


def analyze_factor(sql, data_path="./data", name=None,
                   periods=(1, 5, 10, 20), n_groups=10, ic_method="rank",
                   base_period=None, exclude_suspended=True, exclude_st=True,
                   exclude_limit=True, winsorize=True, standardize=True,
                   direction=None, db=None, with_horizon=False):
    """
    即时分析一个因子, 返回 FactorResult(可 .summary() / .plot())。

    参数:
        sql:        因子 SQL, 必须返回 date / instrument / value 三列。
                    股票池/中性化由用户在此 SQL 内自理。
        data_path:  xxydb 数据路径(db 未传时用它自开连接)
        name:       因子名称(展示用)
        periods:    未来收益周期, 默认 (1,5,10,20)
        n_groups:   分组数, 默认 10
        ic_method:  'rank'(Spearman) 或 'normal'(Pearson)
        base_period: 分组/多空/汇总用哪个周期, 默认 periods[0]
        exclude_*:  可交易过滤开关(停牌/ST/涨跌停), 默认全开
        winsorize/standardize: 截面预处理开关, 默认全开
        db:         可选, 传入已开的 xxydb 连接直接复用(此时不负责关闭)
        with_horizon: 是否算因子有效时限(IC衰减曲线+半衰期等标量)。默认 False,
                    即时试因子/调参不算它, 秒回; 需要看时限时手动传 True。
                    定时任务(run_single)另行开启, 落盘供详情页展示。

    返回:
        FactorResult
    """
    own_db = False
    if db is None:
        from xxydb import xxydb
        db = xxydb(path=data_path)
        own_db = True
    try:
        _validate_sql_result(db, sql)
        output = analyze_from_sql(
            db, sql, periods=periods, n_groups=n_groups, ic_method=ic_method,
            base_period=base_period, exclude_suspended=exclude_suspended,
            exclude_st=exclude_st, exclude_limit=exclude_limit,
            winsorize=winsorize, standardize=standardize, direction=direction,
            with_horizon=with_horizon)
        return FactorResult(output, name=name)
    finally:
        if own_db:
            db.close()
