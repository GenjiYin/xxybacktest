# xxybacktest

量化回测+模拟交易+实盘交易一体化框架，目前支持日频策略回测，内置交易规则引擎、分红除权处理、绩效分析与可视化，实盘通过 QMT 对接真实账户自动下单。（期货期权可转债正在规划中，先把版图拼起来, 再谈高频）

## 安装

```bash
pip install -e .
```

## 快速开始

### 股票回测示例

```python
from xxybacktest import run_backtest, OrderCost, FixedSlippage

def initialize(context):
    context.universe = ["000001.SZ", "600519.SH"]
    context.run_daily(handle_data, "9:30")

def handle_data(context):
    for code in context.universe:
        context.order_target_percent(code, 0.5)

result = run_backtest(
    initialize=initialize,
    handle_data=None,
    start_date="2023-01-01",
    end_date="2023-12-31",
    capital=1000000,
    data_path="./data",          # 你的数据目录路径
    benchmark="000001.SH",
    asset_type="stock",          # 资产类型：stock (股票) 或 fund (场内基金)
    plot=True,                   # 在 Notebook 中展示回测曲线
)

# 查看下单记录
print(result.order)

# 查看每日持仓明细
print(result.pos)

# 查看绩效指标
print(result.performance.indicators)
```

### 场内基金回测示例

```python
from xxybacktest import run_backtest

def initialize(context):
    context.universe = ["510300.SH"]  # 沪深300ETF
    context.first_day = True

def handle_data(context):
    if context.first_day:
        # 首日买入10000份ETF并持有
        context.order_target_value("510300.SH", 10000)
        context.first_day = False

result = run_backtest(
    initialize=initialize,
    handle_data=None,
    start_date="2023-01-01",
    end_date="2023-12-31",
    capital=100000,
    data_path="./data",
    asset_type="fund",           # 指定为基金回测
    plot=True,
)

print(f"资产类型: {result.trade.asset_type}")
print(f"卖出印花税率: {result.account.close_tax}")  # 基金默认为0（无印花税）
print(f"最终总资产: {result.portfolio.total_value:.2f}")
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
| `asset_type` | str | `'stock'` | **资产类型**：`'stock'` (A股) 或 `'fund'` (场内基金ETF/LOF) |
| `plot` | bool | True | 是否展示回测曲线与绩效表 |

**注意**：`asset_type` 参数决定回测模式，影响数据表选择、规则链和默认费率。股票模式下使用 `daily_bar` + `stock_status` 表，基金模式下使用 `daily_fund` 表。

## 返回结果

`run_backtest` 返回 `context` 对象，主要属性：

| 属性 | 说明 |
|------|------|
| `result.order` | DataFrame — 全部下单记录（date, instrument, volume, side, status, cost） |
| `result.pos` | DataFrame — 每日持仓快照（date, instrument, volume, ratio, return, close, avg_cost） |
| `result.performance.indicators` | dict — 绩效指标（sharpe, max_drawdown, alpha, beta 等） |
| `result.portfolio` | 最终资金与持仓状态 |

## 下单函数

下单函数已绑定到 context 上，无需手动导入，也无需传入 context 参数：

```python
def handle_data(context):
    context.order_buy('000001.SZ', 100)
    context.order_sell('000001.SZ', 100)
    context.order_value('000001.SZ', 50000)
    context.order_target_value('000001.SZ', 100000)
    context.order_target_percent('000001.SZ', 0.1)
    context.inout_cash(50000)
```

| 函数 | 说明 |
|------|------|
| `context.order_buy(code, amount)` | 买入指定数量 |
| `context.order_sell(code, amount)` | 卖出指定数量 |
| `context.order_value(code, value)` | 按金额下单，正数买入，负数卖出 |
| `context.order_target_value(code, value)` | 调仓至目标市值 |
| `context.order_target_percent(code, percent)` | 按总资产百分比调仓 |
| `context.inout_cash(amount)` | 出入金，正数入金，负数出金 |

`order(code, amount, context)` 由于与回测结果 `result.order` (DataFrame) 同名，仍需通过导入使用：

```python
from xxybacktest import order
order('000001.SZ', 100, context)   # 正数买入，负数卖出
```

## 历史行情

在策略函数中通过 `context.history` 获取历史K线数据，返回 `{instrument: np.recarray}`，支持属性访问：

```python
def handle_data(context):
    # 获取最近 20 根K线的收盘价（fields 默认为 ['close']）
    his = context.history(['000001.SZ', '600519.SH'], bar_count=20)
    ma20 = his['000001.SZ'].close.mean()

    # 获取多个字段
    his = context.history(['000001.SZ'], fields=['close', 'volume', 'high'], bar_count=10)
    his['000001.SZ'].close    # float64 数组
    his['000001.SZ'].volume   # int64 数组
    his['000001.SZ'].date     # 日期字符串数组（自动包含）
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `instruments` | List[str] | 必填 | 股票代码列表 |
| `fields` | List[str] | `['close']` | K线字段：open, high, low, close, pre_close, volume, amount, vwap |
| `bar_count` | int | 1 | 回溯K线数量（含当日） |

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

result = run_backtest(
    ..., 
    order_cost=cost, 
    slippage=slip
)
```

## 数据配置

xxybacktest 不内置数据，用户需自行准备数据并通过 `data_path` 参数指定数据目录。数据使用 [xxydb](https://pypi.org/project/xxydb/) 格式存储（Parquet 分区 + DuckDB 查询）。

### 数据目录结构

**股票回测数据目录**：

```
data/
├── tables_config.json          # 表结构配置文件
├── trading_days/
│   └── data.parquet            # 交易日历
├── daily_bar/                  # 股票日线行情
│   ├── year=2019/data.parquet  # 按年分区
│   ├── year=2020/data.parquet
│   └── ...
├── stock_status/               # 股票状态
│   ├── year=2019/data.parquet
│   └── ...
├── index_bar/                  # 指数行情
│   ├── year=2019/data.parquet
│   └── ...
└── dividend/                   # 分红送股数据
    └── data.parquet
```

**场内基金回测数据目录**（新增）：

```
data/
├── tables_config.json          # 需包含基金表配置
├── trading_days/               # 复用股票交易日历
│   └── data.parquet
├── daily_fund/                 # 基金日线行情（新增）
│   ├── year=2019/data.parquet  # 按年分区
│   ├── year=2020/data.parquet
│   └── ...
├── fund_dividend/              # 基金分红数据（新增）
│   └── data.parquet
├── fund_split/                 # 基金拆分/合并（新增）
│   └── data.parquet
└── index_bar/                  # 复用指数行情
    └── ...
```

**注意**：基金与股票数据可以并存于同一 `data` 目录，运行时通过 `asset_type` 参数自动选择对应数据表。

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

**基金数据表配置示例**：

```json
{
  "daily_fund": {
    "partition_by": "year",
    "schema": {
      "instrument": "VARCHAR",
      "name": "VARCHAR",
      "date": "TIMESTAMP",
      "open": "DOUBLE",
      "high": "DOUBLE",
      "low": "DOUBLE",
      "close": "DOUBLE",
      "pre_close": "DOUBLE",
      "volume": "BIGINT",
      "amount": "DOUBLE",
      "upper_limit": "DOUBLE",
      "lower_limit": "DOUBLE",
      "change_ratio": "DOUBLE",
      "turn": "DOUBLE",
      "adjust_factor": "DOUBLE",
      "deal_number": "INTEGER",
      "iopv": "DOUBLE"
    }
  },
  "fund_dividend": {
    "partition_by": null,
    "schema": {
      "instrument": "VARCHAR",
      "name": "VARCHAR",
      "date": "TIMESTAMP",
      "register_date": "TIMESTAMP",
      "cash_dividend": "DOUBLE",
      "dividend_distribution_date": "TIMESTAMP",
      "fund_type": "VARCHAR"
    }
  },
  "fund_split": {
    "partition_by": null,
    "schema": {
      "instrument": "VARCHAR",
      "name": "VARCHAR",
      "date": "TIMESTAMP",
      "split_type": "DOUBLE",
      "split_conversion": "DOUBLE",
      "fund_type": "VARCHAR"
    }
  }
}
```

## 股票 vs 场内基金差异说明

xxybacktest 支持 A股股票 和 场内基金（ETF/LOF）两种资产类型，通过 `asset_type` 参数切换。主要差异如下：

| 对比维度 | A股股票 (`asset_type="stock"`) | 场内基金 (`asset_type="fund"`) | 说明 |
|---------|------------------------------|------------------------------|------|
| **行情表** | `daily_bar` + `stock_status` | `daily_fund` | 基金无需股票状态表 |
| **停牌判断** | `stock_status.suspended` | `volume=0` 推断 | 基金从成交量判断 |
| **ST状态** | 有ST/*ST概念 | 无ST概念 | 基金不受ST影响 |
| **分红** | 现金+送股+转增 | 仅现金分红 | 基金只有现金分红 |
| **拆分/折算** | 不适用 | 支持拆分/合并 | 基金特有机制 |
| **印花税** | 卖出 0.1% | **无** | 基金交易免征印花税 |
| **规则链** | 含 `rule_delist` | **不含** `rule_delist` | 基金无退市概念 |
| **最小单位** | 100股 | 100份 | 与股票一致 |
| **交易制度** | T+1 | T+1 | 相同 |
| **涨跌停** | 10%/20% | 10% | ETF有涨跌停限制 |

### 费率差异示例

股票默认费率（卖出印花税千分之一）：

```python
# 股票默认费率
context.account.close_tax = 0.001       # 卖出印花税
context.account.open_commission = 0.0003  # 买入佣金万三
context.account.close_commission = 0.0003 # 卖出佣金万三
```

基金默认费率（**无印花税**，仅佣金）：

```python
# 基金默认费率（asset_type="fund" 时自动设置）
context.account.close_tax = 0             # 无印花税
context.account.open_commission = 0.0003  # 买入佣金万三
context.account.close_commission = 0.0003 # 卖出佣金万三
```

### 基金拆分/合并处理

基金支持拆分（如 1:4）和合并（如 4:1），框架自动处理：

- **拆分日**：价格不变，次日开盘价格调整为拆分前价格的 1/4，持仓份额变为 4 倍
- **合并日**：价格不变，次日开盘价格调整为合并前价格的 4 倍，持仓份额变为 1/4
- **总值不变**：拆分/合并前后持仓总市值保持不变，净值曲线平滑

示例：持有纳指 ETF (159941.SZ) 经历 1:4 拆分

```python
def initialize(context):
    context.universe = ["159941.SZ"]
    context.first_day = True

def handle_data(context):
    if context.first_day:
        # 在拆分前买入
        context.order_target_value("159941.SZ", 10000)
        context.first_day = False

result = run_backtest(
    initialize=initialize,
    handle_data=handle_data,
    start_date="2022-06-01",   # 拆分基准日 2022-07-04
    end_date="2022-07-10",
    asset_type="fund",
    plot=True,
)

# 回测结果：
# - 2022-07-04: 持有 1000 份，收盘价 2.384 元
# - 2022-07-05: 自动调整为 4000 份，开盘价 0.596 元（=2.384/4）
# - 持仓总值保持不变：1000 × 2.384 ≈ 4000 × 0.596
```

## 依赖

- Python >= 3.8
- pandas >= 1.5
- numpy >= 1.21
- matplotlib >= 3.5
- empyrical-reloaded >= 0.5
- xxydb >= 0.1
- itables>=1.0

---

# 模拟交易系统使用指南

模拟交易系统支持将你的策略提交为**模拟交易账户**，系统每天自动重跑回测并生成交易信号，可通过 Web 界面查看净值曲线、持仓和计划交易（信号跟单）。

## 系统架构

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   策略提交   │────▶│  每日重跑   │────▶│  Web 展示   │
│  submit()   │     │  run_all()  │     │  Flask UI   │
└─────────────┘     └─────────────┘     └─────────────┘
        │
        ├──────────────────────────────┐
        │                              │
        ▼                              ▼
┌───────────────┐            ┌───────────────┐
│   模拟账户     │            │   实盘账户     │
│  sim_xxx      │            │  live_xxx     │
│  APScheduler  │            │  APScheduler  │
│  每天 22:00   │            │  trigger_cron │
└───────────────┘            └───────┬───────┘
                                     │
                                     ▼
                              ┌───────────────┐
                              │  QMTTrader    │
                              │  xtquant      │
                              │  真实委托      │
                              └───────────────┘
```

## 快速开始

### 1. 提交策略

```python
from xxybacktest.simulation import submit

def initialize(context):
    context.universe = ["000001.SZ", "600519.SH"]
    context.run_daily(handle_data, "9:30")

def handle_data(context):
    for code in context.universe:
        context.order_target_percent(code, 0.5)

# 提交策略为模拟账户
account_id = submit(
    name="双均线策略",
    initialize=initialize,
    handle_data=handle_data,
    capital=100000,
    start_date="2025-01-01",  # 可选，默认今天
    asset_type="stock",       # 可选，默认 stock
    benchmark="000001.SH",    # 可选，默认 000001.SH
)

print(f"账户已创建: {account_id}")
```

#### 注册实盘账户（对接 QMT）

```python
from xxybacktest.simulation import submit

# 实盘策略代码与回测完全一致，无需修改
def initialize(context):
    context.g.setdefault("target_pct", 0.05)
    context.g.setdefault("run_count", 0)

def handle_data(context):
    context.g["run_count"] += 1
    context.order_target_percent("600519.SH", context.g["target_pct"])

# 提交为实盘账户
account_id = submit(
    name="茅台实盘策略",
    initialize=initialize,
    handle_data=handle_data,
    account_type="live",                         # 指定为实盘
    live_account_id="8881686799",                # QMT 资金账号
    qmt_path=r"D:\\国金证券QMT交易端\\userdata_mini",
    trigger_cron="30 9 * * *",                   # 每天 9:30 触发调仓
    asset_type="stock",
    data_path="./data",
)

print(f"实盘账户已创建: {account_id}")
```

**注意**：实盘注册时会自动连接 QMT 读取总资产作为 `initial_cash`，你传入的 `capital` 会被覆盖。策略代码中不要引用外部全局变量（实盘用 `exec()` 加载源码，外部变量不可见）。

### 2. 准备数据更新脚本

自行编写一个数据更新脚本（名称和路径随意），在其中实现行情数据的拉取与入库逻辑。系统每天定时会自动调用它。

```python
# 示例：my_data_renew.py（路径随意）
# 在这里编写你的行情数据更新逻辑
print("正在更新行情数据...")
# ... 你的数据更新代码 ...
print("更新完成")
```

### 3. 启动服务

```bash
# 安装完成后，可在任意目录使用 xxy-sim 命令
xxy-sim --data /path/to/your/data --data-renew /path/to/my_data_renew.py --time 22:00:00

# 也可以直接运行脚本（效果相同）
python run_simulation.py --data /path/to/your/data --data-renew /path/to/my_data_renew.py --time 22:00:00
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--data` | 行情数据目录路径 | `./data` |
| `--data-renew` | 数据更新脚本路径 | `./data_renew.py` |
| `--time` | 每日触发时间，格式 `HH:MM:SS` | `22:00:00` |

访问：
- **Web 界面**: http://localhost:5000
- **任务面板**: http://localhost:8000

### 3. 查看结果

1. 打开 http://localhost:5000 查看所有账户列表
2. 点击账户卡片进入详情页
3. 查看净值曲线、持仓、历史成交和计划交易（信号）

## 核心概念

### 计划交易（信号跟单）

系统每天运行回测后，会提取**最新一天的所有订单**（买入+卖出）作为"计划交易"，方便你跟单操作：

- 在账户详情页顶部以紫色卡片形式展示
- 显示交易日期、代码、名称、方向、数量
- 这是散户投资者最常用的功能：获取当天的交易信号进行跟单

### 数据流转

**模拟账户**：
```
Day 1: submit() 提交策略 ──▶ 创建 sim_xxx 账户，状态 running
       │
Day N: APScheduler 每天 22:00 触发
       │
       ├─▶ Task 1: 更新行情数据 (data_renew.py)
       │
       └─▶ Task 2: 重跑所有 running 模拟账户的回测
               │
               ├─▶ 从 start_date 到 today 完整回测
               ├─▶ 保存净值、持仓、订单（每账户独立 Parquet）
               └─▶ 生成最新一天的交易信号
```

**实盘账户**：
```
Day 1: submit(account_type="live") ──▶ 创建 live_xxx 账户，自动注册 APScheduler job
       │
Day N: APScheduler 按 trigger_cron 触发
       │
       └─▶ run_live(account_id)
               │
               ├─▶ 连接 QMT，读取持仓和总资产
               ├─▶ 从数据库加载最新策略源码
               ├─▶ 执行 initialize（首次）+ handle_data
               ├─▶ 下单函数直接发往 QMT（真实委托）
               ├─▶ 保存结果到 data/live/accounts/live_xxx/
               └─▶ 持久化 context.g 到 live_schedule.json
```

## API 参考

### submit() - 提交策略

```python
from xxybacktest.simulation import submit

account_id = submit(
    name="策略名称",            # 必填：账户显示名称
    initialize=initialize,     # 必填：初始化函数
    handle_data=handle_data,   # 可选：策略函数
    capital=100000,            # 可选：初始资金，默认 10万
    start_date="2025-01-01",   # 可选：开始日期，默认今天
    asset_type="stock",        # 可选：stock/fund，默认 stock
    benchmark="000001.SH",     # 可选：基准指数，默认 000001.SH
    run_now=True,              # 可选：注册后立即运行回测（仅模拟账户）
    # --- 实盘专属参数 ---
    account_type="sim",        # 可选：'sim' 模拟 / 'live' 实盘
    live_account_id=None,      # 实盘必填：QMT 资金账号
    qmt_path=None,             # 实盘必填：QMT 客户端安装目录
    trigger_cron="30 9 * * *", # 可选：实盘定时触发 cron，默认 9:30
    execution_mode="daily",    # 可选：'daily' 每日 / 'periodic' 按周期
    rebalance_interval=1,      # 可选：调仓周期天数（periodic 模式生效）
)
```

**返回值**: `account_id` (str) - 账户唯一标识，格式 `sim_YYYYMMDD_HHMMSS_XXX`（模拟）或 `live_YYYYMMDD_HHMMSS_XXX`（实盘）

### pause() / resume() / delete() / update_account() - 账户管理

```python
from xxybacktest.simulation import pause, resume, delete, update_account, list_accounts

# 暂停账户（停止每日重跑/调仓，数据保留）
pause(account_id)

# 恢复账户
resume(account_id)

# 删除账户（数据彻底删除，不可恢复。实盘会同步清理 APScheduler job 和 live_schedule.json）
delete(account_id)

# 修改策略或配置（热更新，无需重启服务）
update_account(
    account_id,
    initialize_code="def initialize(ctx):\n    ctx.g['target'] = 0.05",
    trigger_cron="0 10 * * *",  # 改为 10:00 触发
)

# 查看所有账户（含模拟+实盘）
accounts = list_accounts()
for acc in accounts:
    print(f"{acc['account_id']}: {acc['name']} ({acc['status']})")
```

### 手动触发重跑（调试）

```python
from xxybacktest.simulation.runner import run_all

# 手动触发所有 running 账户的重跑
results = run_all()

# 查看结果
for account_id, result in results.items():
    print(f"{account_id}: {result['days']} 天, 最终净值 {result['final_nav']:.4f}")
```

## Web 界面功能

### 账户列表页 (Dashboard)

- **汇总统计**: 总账户数、运行中数量、所有策略累计收益率之和
- **账户卡片**: 显示名称、累计收益率、最大回撤、状态、迷你净值曲线
- **实盘标识**: 实盘账户卡片带红色"实盘"标签和红色左边框，与模拟账户区分
- **排序**: 支持按收益率、最大回撤、创建时间排序

### 账户详情页 (Account Detail)

- **绩效指标**: 累计收益率、年化收益率、最大回撤、夏普比率、当前净值
- **净值曲线**: ECharts 图表，策略净值 vs 基准净值
- **计划交易**: 紫色高亮卡片，显示最新一天的所有交易信号
- **当前持仓**: 代码、名称、数量、成本价、市值、占比、累计收益
- **历史成交**: 分页显示（每页10条），支持翻页

### API 端点

```
GET  /                    账户列表页面
GET  /account/<id>        账户详情页面
GET  /api/accounts        账户列表 JSON
GET  /api/accounts/<id>/nav           净值曲线数据
GET  /api/accounts/<id>/positions     当前持仓数据
GET  /api/accounts/<id>/orders        成交记录数据
POST /api/accounts/<id>/pause         暂停账户
POST /api/accounts/<id>/resume        恢复账户
DELETE /api/accounts/<id>             删除账户
PUT  /api/accounts/<id>               更新账户配置/策略代码（热更新）
```

## 数据存储

### 模拟交易数据

模拟账户结果存储在 `./data/simulation_results/` 目录（每账户独立文件，支持并行）：

```
data/
├── simulation_results/
│   ├── simulation_accounts.parquet       # 账户配置表
│   └── accounts/
│       ├── sim_20250101_120000_xxx/
│       │   ├── daily_values.parquet      # 每日净值
│       │   ├── positions.parquet         # 每日持仓快照
│       │   └── orders.parquet            # 全部订单
│       └── ...
```

### 实盘交易数据

实盘账户结果存储在 `./data/live/` 目录：

```
data/
├── live/
│   ├── live_schedule.json                # 实盘调度配置 + 策略状态持久化
│   └── accounts/
│       ├── live_20250101_120000_xxx/
│       │   ├── daily_values.parquet      # 每日净值
│       │   ├── positions.parquet         # 每日持仓快照
│       │   └── orders.parquet            # 全部订单
│       └── ...
```

**注意**: 数据使用 Parquet 格式存储，可直接用 pandas 读取：

```python
import pandas as pd

# 读取模拟账户净值（每账户独立文件）
nav = pd.read_parquet("data/simulation_results/accounts/sim_xxx/daily_values.parquet")

# 读取实盘账户持仓
positions = pd.read_parquet("data/live/accounts/live_xxx/positions.parquet")
```

## 部署指南

### 环境准备

```bash
# 1. 安装 Python 3.8+
# 2. 克隆代码并安装依赖
git clone <your-repo>
cd xxybacktest
pip install -e .
```

### 启动服务

```bash
conda activate vnpy

# 指定数据目录、更新脚本路径和触发时间
xxy-sim \
  --data /path/to/your/data \
  --data-renew /path/to/your_data_renew.py \
  --time 22:00:00
```

服务启动后会输出：
```
==================================================
模拟交易系统已启动
==================================================
数据目录:     /path/to/your/data
更新脚本:     /path/to/your_data_renew.py
每日触发时间: 22:00:00
--------------------------------------------------
Web 界面: http://localhost:5000
任务面板: http://localhost:8000
==================================================
```

### 生产环境部署

使用 Gunicorn 启动 Flask（多进程模式）：

```bash
gunicorn -w 4 -b 0.0.0.0:5000 "xxybacktest.web.app:create_app()"
```

或使用 nohup 后台运行：

```bash
nohup xxy-sim --data /path/to/data --data-renew /path/to/script.py > simulation.log 2>&1 &
```

### 定时任务说明

系统每天在 `--time` 指定的时间自动执行：
1. 运行 `--data-renew` 指定的脚本更新行情数据
2. 重跑所有 running 账户的回测

## 注意事项

1. **数据依赖**: 模拟交易和实盘均依赖本地行情数据，通过 `--data` 参数指定数据目录路径
2. **状态管理**: 只有 `status=running` 的账户会被每日重跑/调仓
3. **全量重跑**: 当前实现每天从 `start_date` 到当天完整重跑（阶段六将支持增量）
4. **策略热更新**: 调用 `update_account()` 修改策略代码或 cron 后，下次定时触发自动生效，无需重启服务，无需删除重建
5. **实盘全局变量**: 实盘策略用 `exec()` 在独立模块加载源码，外部全局变量不可见。所有配置应在函数内部硬编码，或通过 `context.g` 持久化
6. **性能预估**: 账户数量 × 历史天数 = 每日处理的事件数。模拟账户使用 `ProcessPoolExecutor` 并行执行，实盘账户通过 APScheduler 独立调度