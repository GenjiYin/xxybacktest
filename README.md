# xxybacktest

A 股量化回测框架，支持日频策略回测，内置交易规则引擎、分红除权处理、绩效分析与可视化。

## 安装

```bash
pip install -e .
```

## 快速开始

```python
from xxybacktest import run_backtest, order_target_percent, OrderCost, FixedSlippage

def initialize(context):
    context.universe = ["000001.SZ", "600519.SH"]
    context.run_daily(handle_data, "9:30")

def handle_data(context):
    for code in context.universe:
        order_target_percent(code, 0.5, context)

result = run_backtest(
    initialize=initialize,
    handle_data=None,
    start_date="2023-01-01",
    end_date="2023-12-31",
    capital=1000000,
    data_path="./data",          # 你的数据目录路径
    benchmark="000001.SH",
    plot=True,                   # 在 Notebook 中展示回测曲线
)

# 查看下单记录
print(result.order)

# 查看每日持仓明细
print(result.pos)

# 查看绩效指标
print(result.performance.indicators)
```

## run_backtest 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `initialize` | callable | 必填 | 初始化函数，签名 `func(context)` |
| `handle_data` | callable / None | 必填 | 策略函数，签名 `func(context)`；若为 None 需在 initialize 中用 `run_daily` 自行注册 |
| `start_date` | str | 必填 | 回测起始日 `'YYYY-MM-DD'` |
| `end_date` | str | 必填 | 回测结束日 `'YYYY-MM-DD'` |
| `capital` | float | 1000000 | 初始资金 |
| `data_path` | str | `'./data'` | 数据目录路径（见下方数据配置） |
| `order_cost` | OrderCost | None | 费率配置 |
| `slippage` | Slippage | None | 滑点配置（`FixedSlippage` 或 `PriceRelatedSlippage`） |
| `benchmark` | str | `'000001.SH'` | 基准指数代码 |
| `rule_list` | str | 全部规则 | 逗号分隔的规则链 |
| `plot` | bool | True | 是否展示回测曲线与绩效表 |

## 返回结果

`run_backtest` 返回 `context` 对象，主要属性：

| 属性 | 说明 |
|------|------|
| `result.order` | DataFrame — 全部下单记录（date, instrument, volume, side, status, cost） |
| `result.pos` | DataFrame — 每日持仓快照（date, instrument, volume, ratio, return, close, avg_cost） |
| `result.performance.indicators` | dict — 绩效指标（sharpe, max_drawdown, alpha, beta 等） |
| `result.portfolio` | 最终资金与持仓状态 |

## 下单函数

在策略函数中可使用以下下单接口（需先 import）：

```python
from xxybacktest import order, order_value, order_target_value, order_target_percent, inout_cash
```

| 函数 | 说明 |
|------|------|
| `order(code, amount, context)` | 按数量下单，正数买入，负数卖出 |
| `order_value(code, value, context)` | 按金额下单 |
| `order_target_value(code, value, context)` | 调仓至目标市值 |
| `order_target_percent(code, percent, context)` | 按总资产百分比调仓 |
| `inout_cash(amount, context)` | 出入金 |

## 费率与滑点

```python
from xxybacktest import OrderCost, FixedSlippage, PriceRelatedSlippage

cost = OrderCost(
    open_tax=0,            # 买入税费（A股为0）
    close_tax=0.001,       # 卖出印花税（千分之一）
    open_commission=0.0003,  # 买入佣金（万三）
    close_commission=0.0003, # 卖出佣金（万三）
    min_commission=5,        # 单笔最低佣金（5元）
)

slip = FixedSlippage(0.02)            # 每股固定滑点 0.02 元
# 或
slip = PriceRelatedSlippage(0.002)    # 按比例滑点 千分之二
```

## 数据配置

xxybacktest 不内置数据，用户需自行准备数据并通过 `data_path` 参数指定数据目录。数据使用 [xxydb](https://pypi.org/project/xxydb/) 格式存储（Parquet 分区 + DuckDB 查询）。

### 数据目录结构

```
data/
├── tables_config.json          # 表结构配置文件
├── trading_days/
│   └── data.parquet            # 交易日历
├── daily_bar/
│   ├── year=2019/data.parquet  # 日线行情（按年分区）
│   ├── year=2020/data.parquet
│   └── ...
├── stock_status/
│   ├── year=2019/data.parquet  # 股票状态（按年分区）
│   └── ...
├── index_bar/
│   ├── year=2019/data.parquet  # 指数行情（按年分区）
│   └── ...
└── dividend/
    └── data.parquet            # 分红送股数据
```

### 各表字段说明

#### 1. trading_days（交易日历）

| 字段 | 类型 | 说明 |
|------|------|------|
| `date` | datetime | 交易日期 |
| `market_code` | str | 市场标识，`'CN'` 为 A 股 |

#### 2. daily_bar（日线行情）

按年分区（`year=YYYY`），每个分区一个 `data.parquet` 文件。

| 字段 | 类型 | 说明 |
|------|------|------|
| `instrument` | str | 证券代码，如 `'000001.SZ'` |
| `name` | str | 证券简称 |
| `date` | datetime | 日期 |
| `open` | float | 开盘价 |
| `high` | float | 最高价 |
| `low` | float | 最低价 |
| `close` | float | 收盘价 |
| `pre_close` | float | 昨收盘价 |
| `volume` | int | 成交量（股） |
| `amount` | float | 成交额（元） |
| `change_ratio` | float | 涨跌幅（小数，如 0.05 表示 5%） |
| `upper_limit` | float | 涨停价 |
| `lower_limit` | float | 跌停价 |
| `turn` | float | 换手率 |
| `adjust_factor` | float | 累积后复权因子 |
| `deal_number` | int | 成交笔数 |

#### 3. stock_status（股票状态）

按年分区，与 daily_bar 对应。

| 字段 | 类型 | 说明 |
|------|------|------|
| `instrument` | str | 证券代码 |
| `date` | datetime | 日期 |
| `suspended` | int8 | 停牌标记（0=正常, 1=停牌） |
| `st_status` | int8 | ST 标记（0=正常, 1=ST, 2=*ST） |
| `price_limit_status` | int8 | 涨跌停状态（1=跌停, 2=非涨跌停, 3=涨停） |
| `exdr` | int8 | 除权除息标记（0=非除权除息日, 1=除权除息日） |
| `is_risk_warning` | int8 | 风险警示标志（0=正常, 1=风险警示） |

#### 4. index_bar（指数行情）

按年分区。用于基准收益率计算。

| 字段 | 类型 | 说明 |
|------|------|------|
| `instrument` | str | 指数代码，如 `'000001.SH'` |
| `name` | str | 指数简称 |
| `date` | datetime | 日期 |
| `open` | float | 开盘价 |
| `high` | float | 最高价 |
| `low` | float | 最低价 |
| `close` | float | 收盘价 |
| `pre_close` | float | 昨收盘价 |
| `volume` | int | 成交量 |
| `amount` | float | 成交额 |
| `change_ratio` | float | 涨跌幅（小数） |

#### 5. dividend（分红送股）

不分区，单个 `data.parquet` 文件。

| 字段 | 类型 | 说明 |
|------|------|------|
| `instrument` | str | 证券代码 |
| `date` | datetime | 日期 |
| `register_date` | datetime | 股权登记日 |
| `ex_date` | datetime | 除权除息日 |
| `bonus_rate` | float | 每股送股比例 |
| `conversed_rate` | float | 每股转增比例 |
| `cash_before_tax` | float | 每股派现（税前） |
| `cash_after_tax` | float | 每股派现（税后） |

### tables_config.json

数据目录下必须包含 `tables_config.json` 配置文件，定义各表的分区方式和字段 schema。xxydb 根据此文件自动建立 DuckDB 视图。格式示例见项目自带的 `data/tables_config.json`。

## 依赖

- Python >= 3.8
- pandas >= 1.5
- numpy >= 1.21
- matplotlib >= 3.5
- empyrical-reloaded >= 0.5
- xxydb >= 0.1
