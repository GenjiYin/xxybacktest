# 实盘交易技术方案（修订版）

## 一、现状与目标

### 1.1 现状

当前系统已完成回测核心 + 模拟交易 + Web 展示的全链路闭环：

| 层级 | 模块 | 状态 |
|------|------|------|
| 数据层 | `xxydb` (DuckDB) + `Data` 类 | 已投产 |
| 回测核心 | `backtest.py`, `context.py`, `trading.py`, `rules.py` | 已投产 |
| 模拟交易 | `simulation/submitter.py`, `runner.py`, `scheduler.py` | 已投产，并行化改造完成 |
| 存储 | 每账户独立 Parquet (`accounts/{id}/*.parquet`) | 已投产 |
| Web | Flask + `api.py` / `account.py` / `dashboard.py` | 已投产 |

### 1.2 目标

在不破坏现有回测/模拟链路的前提下，新增 **QMT 实盘交易** 能力，满足：

1. **策略零改动**：同一套 `initialize` + `handle_data` 源码，回测与实盘共用
2. **每天执行策略**：`run_live` 每天触发一次，策略内部自己决定是否下单
3. **独立触发时间**：每个实盘账户可独立设置每天触发时间（默认 9:30）
4. **状态自动持久化**：`context.g` 跨运行自动保存/恢复，策略无需额外处理
5. **Web 无感知**：实盘账户的数据格式与模拟账户完全一致，现有页面直接兼容
6. **调度可复用**：复用现有的 APScheduler 封装，每个实盘账户一个独立 cron job
7. **登录解耦**：QMT 客户端登录由用户自定义脚本负责，实盘模块只假设 QMT 已就绪

---

## 二、总体架构

```
                    Web 层（Flask）
    ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
    │ dashboard│  │ account  │   api    │   tasks  │
    └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘
         │             │             │             │
         └─────────────┴──────┬──────┴─────────────┘
                              │
                    {simulation_results,live}/accounts/{id}/*.parquet

                              │
    ┌─────────────────────────┼─────────────────────────────────┐
    │                    业务层 │                                 │
    │  ┌─────────────────────────┐  ┌─────────────────────────┐  │
    │  │      模拟交易            │  │        实盘              │  │
    │  │  submitter.py           │  │  trader.py              │  │
    │  │  runner.py              │  │  context.py             │  │
    │  │  scheduler.py           │  │  trading.py             │  │
    │  │  task_store.py          │  │  runner.py              │  │
    │  │  main.py                │  │  recorder.py            │  │
    │  └─────────────────────────┘  └─────────────────────────┘  │
    │                              │                              │
    │  ┌───────────────────────────┴───────────────────────────┐  │
    │  │              回测核心（复用）                             │  │
    │  │  context.py  create_context() / DictObj                  │  │
    │  │  objects.py  Position / Order / OrderCost                │  │
    │  │  trading.py  order_buy / order_target_percent（回测版）  │  │
    │  │  data.py     Data 类（行情/日历/分红）                  │  │
    │  └─────────────────────────────────────────────────────────┘  │
    └───────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │   QMT 客户端       │
                    │  (XtQuantTrader)  │
                    └───────────────────┘
```

---

## 三、模块设计

### 3.1 live/trader.py ✅ —— QMT 交易通道

职责：唯一与 QMT API 打交道的模块，对外屏蔽 `xtquant` 细节。

```python
class QMTTrader:
    def __init__(self, qmt_path: str, account_id: str, retry: int = 5, interval: int = 3):
        """
        连接 QMT，失败自动重试。
        qmt_path: QMT 客户端安装目录（含 XtQuantClient）
        account_id: QMT 资金账号
        """

    def is_connected(self) -> bool:
        """检查连接状态"""

    def get_portfolio(self) -> dict:
        """
        返回资金概况：
        {
            'cash': float,           # 可用资金
            'frozen_cash': float,    # 冻结资金
            'market_value': float,   # 持仓市值
            'total_asset': float,    # 总资产
        }
        """

    def get_position(self, code: str) -> dict | None:
        """
        查询单只股票持仓，无持仓时返回 None。
        用于 trading.py 中交易函数实时对比当前持仓与目标持仓。

        返回:
            {
                'volume': int,
                'can_sell_volume': int,
                'cost_price': float,
                'last_price': float,
                'market_value': float,
            }
        """

    def get_positions(self) -> dict:
        """
        返回全部当前持仓（过滤 volume=0）：
        {
            '000001.SZ': {
                'volume': int,
                'can_sell_volume': int,
                'cost_price': float,
                'last_price': float,
                'market_value': float,
            },
            ...
        }
        """

    def get_price(self, code: str) -> float | None:
        """通过 xtdata.get_full_tick 取最新价，停牌返回 None"""

    def order_stock(self, code: str, volume: int, direction: str,
                    price_type: str = 'MARKET', price: float = 0.0) -> dict:
        """
        原始下单接口。
        direction: 'BUY' | 'SELL'
        price_type: 'MARKET' | 'FIX' 等
        返回: {'status': 'submitted'|'error', 'order_id': str|None, 'msg': str}
        """
```

**关键约束**：
- `xtquant` 为本地安装包，不在 `pyproject.toml` 中声明依赖，运行期 `try/except ImportError` 提示用户安装
- 连接失败重试 5 次 x 3 秒，仍失败则抛出 `QMTConnectionError`
- **`order_stock` 是底层接口，由 `live/trading.py` 直接调用**
- **策略自己保证"先卖后买"的顺序，系统不做批量排序**

---

### 3.2 live/context.py ✅ —— 实盘上下文构建

职责：从 QMT 读取真实数据，构建与回测完全兼容的 `context` 对象。

```python
def create_live_context(account: dict, trader: QMTTrader,
                        strategy_state: dict = None) -> DictObj:
    """
    account: submitter.get_account() 返回的 dict
    trader: 已连接的 QMTTrader 实例
    strategy_state: 上次持久化的策略状态（即 context.g 的内容）

    返回: 与 run_backtest 返回的 context 结构一致的 DictObj
    """
```

**构建逻辑**：

| context 字段 | 数据来源 |
|-------------|---------|
| `portfolio.cash` | `trader.get_portfolio()['cash']` |
| `portfolio.total_value` | `trader.get_portfolio()['total_asset']` |
| `portfolio.positions_value` | `trader.get_portfolio()['market_value']` |
| `portfolio.starting_cash` | `account['initial_cash']`（用于净值归一化） |
| `portfolio.positions` | `trader.get_positions()` -> 遍历构建 `Position` 对象 |
| `current_dt` | `datetime.now()` |
| `trade.asset_type` | `account.get('asset_type', 'stock')` |
| `account.*` | 默认费率配置（保留字段兼容性） |
| `data.data_path` | `account.get('data_path', './data')` |
| `g` | `strategy_state`（上次持久化的策略状态） |
| `logs.order_list` | `[]`（由 trading.py 实盘版填充） |
| `performance.*` | 初始化为空结构 |

**Position 对象构建**：

```python
for code, pos in trader.get_positions().items():
    p = Position(
        code=code,
        amount=pos['volume'],
        enable_amount=pos['can_sell_volume'],
        last_sale_price=pos['last_price'],
    )
    p.cost_basis = pos['cost_price']
    p.total_cost = pos['volume'] * pos['cost_price']
    p.total_value = pos['volume'] * pos['last_price']
    ctx.portfolio.positions[code] = p
```

**关键设计**：
- 在 context 上挂载 `ctx._trader = trader`，供 `live/trading.py` 内部调用
- `ctx.g` 初始化为 `strategy_state`，策略可以像回测一样读写 `context.g['xxx']`

---

### 3.3 live/trading.py —— 实盘版交易函数

职责：提供与回测 `trading.py` 完全一致的调用方式，策略代码无需任何修改。

与回测一样，所有交易函数通过 `live/runner.py` 用 lambda 绑定到 context 上，
策略只调用 `context.order_target_percent(code, pct)`，不直接 import 本模块。

**核心设计：持仓/资金始终以 QMT 为准，交易函数实时查询 QMT，不依赖 context 快照。**


#### 3.3.1 实时刷新接口（策略可直接调用）

```python
def get_portfolio(context) -> dict:
    """
    从 QMT 实时拉取资金概况，同步到 context.portfolio，并返回 dict。
    策略可直接调用 context.get_portfolio() 获取最新资金。
    """

def get_account_positions(context) -> dict:
    """
    从 QMT 实时拉取全部持仓，同步到 context.portfolio.positions，并返回 dict。
    策略可直接调用 context.get_account_positions() 获取最新持仓。
    """

def _refresh_portfolio(context):
    """
    同时调用 get_portfolio + get_account_positions，刷新整个 context.portfolio。
    runner.py 在 handle_data 执行完后统一调用一次。
    """
```

**刷新后 context.portfolio 状态**：

| 字段 | 数据来源 | 说明 |
|------|---------|------|
| `cash` | `trader.get_portfolio()['cash']` | 可用资金 |
| `total_value` | `trader.get_portfolio()['total_asset']` | 总资产 |
| `positions_value` | `trader.get_portfolio()['market_value']` | 持仓市值 |
| `positions` | `trader.get_positions()` → Position 对象 | 全部持仓，volume=0 的已过滤 |

**注意**：交易函数内部**不自动调用** `_refresh_portfolio`，以免 handle_data 执行期间 QMT 状态波动导致策略逻辑不一致。策略如需最新持仓/资金，显式调用 `context.get_account_positions()` / `context.get_portfolio()`。


#### 3.3.2 交易函数（内部实时查 QMT）

```python
def order_target_percent(security: str, percent: float, context) -> Order | None:
    """
    实盘版实现：
    1. 从 context._trader 取 QMTTrader
    2. 用 trader.get_portfolio()['total_asset'] 取实时总资产
    3. 用 trader.get_price() 取最新价，计算目标股数（100股取整）
    4. 用 trader.get_position() 取该股票实时持仓，算差值
    5. 差值 > 0 → trader.order_stock(BUY)；差值 < 0 → trader.order_stock(SELL)
    6. 等待 0.5 秒防爆单
    7. 构造 Order 对象记录到 context.logs.order_list
    8. **不刷新 context.portfolio**（由 runner.py 在 handle_data 结束后统一刷新）
    9. 返回 Order 对象
    """

def order(security: str, amount: int, context) -> Order | None:
    """按差量下单。amount > 0 买，amount < 0 卖。"""

def order_value(security: str, value: float, context) -> Order | None:
    """按金额下单。正数买入，负数卖出。"""

def order_target_value(security: str, value: float, context) -> Order | None:
    """调仓至目标市值。0 表示清仓。"""

def order_buy(security: str, amount: int, context) -> Order | None:
    """直接买入指定数量。"""

def order_sell(security: str, amount: int, context) -> Order | None:
    """直接卖出指定数量。"""

def inout_cash(cash_amount: float, context):
    """实盘不支持出入金，调用时记录 warning 并跳过。"""
```


#### 3.3.3 runner.py 中的绑定方式

```python
from .trading import (
    order_buy as _order_buy,
    order_sell as _order_sell,
    order_value as _order_value,
    order_target_value as _order_target_value,
    order_target_percent as _order_target_percent,
    inout_cash as _inout_cash,
    get_portfolio as _get_portfolio,
    get_account_positions as _get_account_positions,
)

context.order_buy            = lambda code, amount:     _order_buy(code, amount, context)
context.order_sell           = lambda code, amount:     _order_sell(code, amount, context)
context.order_value          = lambda security, value:  _order_value(security, value, context)
context.order_target_value   = lambda security, value:  _order_target_value(security, value, context)
context.order_target_percent = lambda security, pct:    _order_target_percent(security, pct, context)
context.inout_cash           = lambda cash_amount:      _inout_cash(cash_amount, context)
context.get_portfolio        = lambda:                  _get_portfolio(context)
context.get_account_positions = lambda:                 _get_account_positions(context)
```

---

### 3.4 live/runner.py —— 实盘调仓入口

```python
def run_live(account_id: str, data_path: str = "./data") -> dict:
    """
    执行一次实盘任务（每天触发一次）。
    initialize + handle_data 每天各执行一次。

    返回:
        {
            'account_id': str,
            'status': 'success' | 'skipped' | 'error',
            'reason': str,
            'orders': int,
        }
    """
```

**执行流程**：

```
1. 加载账户配置 (submitter.get_account)
   校验 account_type == 'live'

2. 检查交易日
   查 trading_days 表
   非交易日 -> 返回 skipped

3. 连接 QMT
   QMTTrader(qmt_path, live_account_id)
   失败重试 5 次，仍失败 -> 返回 error

4. 加载上次持久化状态
   从 live_schedule.json 读取 strategy_state

5. 构建实盘上下文
   create_live_context(account, trader, strategy_state)
   将交易函数绑定到 context（同 backtest.py 方式）

6. 加载策略并执行 initialize
   _load_func(account['initialize_code']) -> initialize(ctx)
   收集 run_daily 注册的回调
   initialize 里可读写 context.g（已恢复上次状态）

7. 执行策略回调（handle_data / run_daily 注册函数）
   for func in daily_callbacks:
       func(ctx)
   策略内部自己判断是否下单、下什么单
   策略可显式调用 context.get_portfolio() / get_account_positions() 获取实时数据

8. 刷新 portfolio（handle_data 结束后统一执行一次）
   调用 _refresh_portfolio(ctx)，从 QMT 拉取最新资金和持仓更新 context
   后续 recorder.py 保存结果时使用刷新后的 context

9. 保存结果
   _save_live_results(account_id, ctx, data_path, trader)

10. 保存策略状态（关键！）
    将 ctx.g 序列化，更新到 live_schedule.json

11. 返回结果
```

**防并发设计**：
- `scheduler.py` 的 `add_func_job` 已设 `max_instances=1`
- `run_live` 开头额外检查 `is_job_running(f"live_{account_id}")`，若任务仍在执行则直接跳过

---

### 3.5 live/recorder.py —— 结果持久化

职责：将实盘执行结果写入与模拟交易完全一致的 Parquet 文件。

```python
def _save_live_results(account_id: str, context, data_path: str, trader: QMTTrader):
    """
    存储路径: data/live/accounts/{account_id}/
      - daily_values.parquet   # 每日总资产快照（每天追加）
      - positions.parquet      # 每日收盘后持仓（每天覆盖）
      - orders.parquet         # 本次订单流水（有单时追加）

    列结构与 simulation/runner.py 的 _save_results 完全一致，
    确保 Web 层无感知。
    """
```

**daily_values 追加逻辑**：

实盘每天记录一次净值：

```python
total_asset = trader.get_portfolio()['total_asset']
initial_cash = account['initial_cash']
nav = total_asset / initial_cash if initial_cash > 0 else 1.0

# daily_return = (today_nav / yesterday_nav) - 1
# 首次运行时 yest_nav = 1.0
```

**positions 刷新逻辑**：

每天从 QMT 拉取最新持仓，覆盖写入：

```python
for code, pos in trader.get_positions().items():
    ratio = pos['market_value'] / total_asset if total_asset > 0 else 0
    cum_return = (pos['last_price'] / pos['cost_price'] - 1
                  if pos['cost_price'] > 0 else 0)
    # 写入 ...
```

**注意**：实盘持仓的 `cum_return` 用当前价相对成本价的浮盈表示，回测的 `cum_return` 是基于建仓以来的累计收益，两者含义不同但格式一致。

---

### 3.6 live/utils.py —— 辅助工具

```python
def is_trading_day(date_str: str, data_path: str = "./data") -> bool:
    """查 trading_days 表判断是否为交易日"""

def _load_schedule(account_id: str, data_path: str) -> dict:
    """读取 live_schedule.json，返回该账户的调度记录"""

def _update_schedule(account_id: str, updates: dict, data_path: str):
    """更新 live_schedule.json"""

def _load_strategy_state(account_id: str, data_path: str) -> dict:
    """读取上次持久化的 strategy_state"""

def _save_strategy_state(account_id: str, state: dict, data_path: str):
    """序列化保存 strategy_state 到 live_schedule.json"""
    # 处理 numpy/pandas 等不可 JSON 序列化的类型
```

**live_schedule.json 格式**：

```json
{
  "live_001": {
    "last_run_date": "2026-05-15",
    "rebalance_count": 5,
    "strategy_state": {
      "counter": 3,
      "last_weights": {"000001.SZ": 0.2}
    }
  }
}
```

---

## 四、与现有系统的整合点

### 4.1 账户管理（simulation/submitter.py）

账户表 `simulation_accounts` 新增字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `account_type` | str | `'simulation'` / `'live'` |
| `execution_mode` | str | `'periodic'` / `'daily'`，默认 `'periodic'` |
| `trigger_cron` | str | 每日触发时间，如 `"30 9 * * *"`（默认 9:30） |
| `live_account_id` | str | QMT 资金账号 |
| `qmt_path` | str | QMT 客户端路径 |
| `rebalance_interval` | int | 调仓周期（天），默认 30，`daily` 模式下可忽略 |
| `initial_cash` | float | 净值归一化基准资金，**提交时自动从 QMT 读取并锁定，之后只读** |

**兼容性处理**：
- 现有模拟账户的 `account_type` 默认为 `'simulation'`
- `execution_mode` 默认为 `'periodic'`（现有行为不变）
- `submit()` 函数新增参数，不影响现有调用

### 4.2 执行模式对比

| 维度 | `periodic`（周期模式） | `daily`（每日模式） |
|------|----------------------|-------------------|
| `run_live` 触发 | 系统检查调仓周期，没到就跳过 | 每天执行 |
| `initialize` 执行 | 只在调仓日执行 | 每天执行 |
| `handle_data` 执行 | 只在调仓日执行 | 每天执行 |
| 调仓判断 | 系统控制 | 策略自己控制 |
| 净值记录 | 调仓日记一次 | 每天追加 |
| 持仓记录 | 调仓日更新 | 每天从 QMT 刷新 |
| `context.g` 持久化 | 调仓日保存 | 每天保存 |
| 适用策略 | 固定周期再平衡 | 信号驱动型 |

### 4.3 定时调度（simulation/scheduler.py）

每个实盘账户独立注册 cron job：

```python
cron = account.get('trigger_cron', '30 9 * * *')
add_func_job(
    task_id=f"live_{account_id}",
    name=f"实盘-{account['name']}",
    func=lambda: run_live(account_id, data_path),
    cron=cron,
    data_path=data_path,
)
```

**设计要点**：
- 每个实盘账户一个独立 job，支持单独暂停/恢复/删除
- job ID 前缀固定为 `live_`，与内置任务区分
- 触发时间由 `trigger_cron` 字段决定，默认 `30 9 * * *`

### 4.4 Web 展示（零改动）

`api.py`、`account.py` 调用 `get_account_nav` / `get_account_positions` / `get_account_orders`，这三个函数只关心 `accounts/{id}/*.parquet` 是否存在。

实盘账户按同样格式存储后，Web 端完全无感知。

### 4.5 存储路径

模拟交易和实盘结果分开存放，互不干扰：

```
data/
  simulation_results/           ← 模拟交易结果
    accounts/
      sim_20260515_093000_abc123/
        daily_values.parquet
        positions.parquet
        orders.parquet
  live/                         ← 实盘专属目录
    live_schedule.json          ← 所有实盘账户的调度状态 & 策略状态
    accounts/
      live_20260515_094000_def456/
        daily_values.parquet
        positions.parquet
        orders.parquet
```

**路径函数**（`live/utils.py`）：

```python
def _live_dir(data_path):      # → data/live/
def _schedule_path(data_path): # → data/live/live_schedule.json
```

实盘账户的 parquet 文件路径由 `live/recorder.py` 负责构建：
`data/live/accounts/{account_id}/`

---

## 五、关键问题与解决方案

### 5.1 初始资金锁定（initial_cash）

实盘账户的净值曲线需要一个固定基准来归一化（`nav = total_asset / initial_cash`）。

**设计决策**：`initial_cash` 在调用 `submit()` 提交实盘账户的那一刻，自动连接 QMT 读取当前 `total_asset` 并写入账户配置，**之后永远不再更新**。

```
submit() 调用时（account_type='live'）
  → 连接 QMT，读取 trader.get_portfolio()['total_asset']
  → 写入账户配置 initial_cash = total_asset
  → 断开连接

每次 run_live 时
  → create_live_context 读 account['initial_cash']（只读）
  → portfolio.starting_cash = initial_cash
  → recorder.py 计算 nav = total_asset / initial_cash
```

用户**不需要手动填写**初始资金，提交的那一刻资金量即为基准。若需重置净值基准（如追加资金后），删除账户重新提交即可。

---

### 5.2 交易日判断

复用 `xxydb` 的 `trading_days` 表：

```python
def is_trading_day(date_str: str, data_path: str = "./data") -> bool:
    db = xxydb(path=data_path)
    df = db.query(f"""
        SELECT 1 FROM trading_days
        WHERE market_code = 'CN' AND date = '{date_str}'
    """).df()
    db.close()
    return not df.empty
```

### 5.3 策略中的 `run_daily`

回测中 `run_daily` 将回调注册到事件系统，由 `backtest.py` 按日期调度执行。

实盘中 `run_daily` 直接收集回调到一个列表，在 `initialize` 结束后立即执行：

```python
daily_callbacks = []
ctx.run_daily = lambda func, time="9:30": daily_callbacks.append(func)
initialize(ctx)

for func in daily_callbacks:
    func(ctx)
```

这跟回测的"每个交易日执行一次"语义在实盘场景中等价（因为 `run_live` 每天只触发一次）。

**注意**：策略里的 `run_daily(func, "14:50")` 只起注册作用，不控制实际触发时间。实际触发时间由账户的 `trigger_cron` 决定。

### 5.4 Windows spawn 与 xtquant

`XtQuantTrader` 基于本地 COM/IPC，不支持跨进程序列化。实盘任务以**单进程单账户**方式运行，不放在 `ProcessPoolExecutor` 中。

`run_live` 由 APScheduler 在主进程中直接调用，不涉及 multiprocessing。

### 5.5 策略状态持久化

```python
# 运行前加载
create_live_context(account, trader, strategy_state=schedule.get('strategy_state', {}))

# 运行后保存
_save_strategy_state(account_id, ctx.g, data_path)
```

序列化时需处理 numpy/pandas 等不可 JSON 序列化的类型：
- `np.ndarray` -> `tolist()`
- `np.integer/np.floating` -> `.item()`
- 其他不支持的类型 -> `str()` 或跳过

### 5.6 先卖后买

**系统不做批量排序**，`order_target_percent` 被调用时直接下单。

策略代码里需要自己保证顺序：

```python
def strategy(context):
    weights = get_signals()
    
    # 1. 先处理要卖的
    sells = [c for c in weights if weights[c] == 0]
    for code in sells:
        context.order_target_percent(code, 0)
    
    # 2. 再处理要买的
    buys = {c: w for c, w in weights.items() if w > 0}
    for code, w in buys.items():
        context.order_target_percent(code, w)
```

### 5.7 错误隔离

单个实盘账户调仓失败（QMT 连不上、策略异常等）不影响其他账户：
- `scheduler.py` 的每个 job 独立执行
- `run_live` 内 `try/except` 捕获全部异常，返回 `{'status': 'error'}` 而不是抛到调度器

---

## 六、实施步骤

| 阶段 | 任务 | 改动文件 | 验证方式 |
|------|------|---------|---------|
| **P0** ✅ | 搭建 `live/` 包骨架 | `live/__init__.py` | 包可 import |
| **P1** ✅ | 实现 `trader.py`（QMT 连接 + 查询 + 下单） | `live/trader.py` | `test_live_trader.py` 全部通过 |
| **P2** ✅ | 实现 `context.py`（真实数据 → context） | `live/context.py` | `test_live_context.py` 全部通过 |
| **P3** | 实现 `utils.py`（交易日判断 + schedule 读写 + 策略状态序列化） | `live/utils.py` | `is_trading_day` 正确识别交易日；`context.g` 跨运行保持 |
| **P4** | 实现 `trading.py`（实盘版交易函数 + portfolio 刷新） | `live/trading.py` | 单只股票调仓，观察 QMT 委托；连续调仓资金计算正确 |
| **P5** | 实现 `recorder.py`（结果持久化） | `live/recorder.py` | Parquet 文件生成，列结构与模拟交易一致 |
| **P6** | 实现 `runner.py`（实盘调仓入口，绑定交易函数） | `live/runner.py` | 完整跑通一次每日执行，Web 上净值/持仓/订单正常显示 |
| **P7** | 扩展 `submit()` 支持实盘账户（连 QMT 读 initial_cash，生成 `live_` 前缀 ID） | `simulation/submitter.py` | 提交实盘账户后 `initial_cash` 自动写入，账户 ID 以 `live_` 开头 |
| **P8** | 启动时加载实盘账户并注册调度 job | `simulation/main.py` | 定时任务列表显示实盘 job，到点自动触发 |
| **P9** | 集成测试 | 全流程 | Web 上净值/持仓/订单与 QMT 界面一致 |

**说明**：
- 原 SPEC 的 P2（utils.py）和 P3（context.py）顺序对调，先做 context.py 更便于验证整体链路
- 原 P6（策略状态持久化）合并进 P3（utils.py），不单独成阶段
- P7 新增：`submit()` 提交实盘账户时自动连 QMT 读取并锁定 `initial_cash`

---

## 七、接口清单

### 7.1 新增接口

| 接口 | 位置 | 说明 |
|------|------|------|
| `QMTTrader` | `live/trader.py` | QMT 封装类 |
| `create_live_context()` | `live/context.py` | 构建实盘上下文 |
| `order_target_percent()` 等 | `live/trading.py` | 实盘版交易函数（同名） |
| `run_live()` | `live/runner.py` | 实盘任务入口 |
| `_save_live_results()` | `live/recorder.py` | 结果持久化 |
| `is_trading_day()` | `live/utils.py` | 交易日判断 |
| `_load/_save_strategy_state()` | `live/utils.py` | 策略状态持久化 |
| `_load/_update_schedule()` | `live/utils.py` | live_schedule.json 读写 |

### 7.2 修改接口

| 接口 | 位置 | 改动 |
|------|------|------|
| `submit()` | `simulation/submitter.py` | 新增 `account_type`, `execution_mode`, `trigger_cron`, `live_account_id`, `qmt_path` 参数 |
| `list_accounts()` | `simulation/submitter.py` | 自然包含新字段 |
| `main()` | `simulation/main.py` | 启动时加载实盘账户并注册调度 job |

### 7.3 无改动接口

| 接口 | 位置 | 原因 |
|------|------|------|
| `get_account_nav()` | `simulation/runner.py` | 数据格式一致 |
| `get_account_positions()` | `simulation/runner.py` | 数据格式一致 |
| `get_account_orders()` | `simulation/runner.py` | 数据格式一致 |
| 全部 Web 路由 | `web/routes/*.py` | 通过查询函数间接访问 |

---

## 八、风险评估

| 风险 | 等级 | 应对 |
|------|------|------|
| QMT 客户端未启动/未登录 | 高 | runner 重试 5 次后失败，记录状态，不阻塞其他账户 |
| `xtquant` 未安装 | 高 | `trader.py` 顶部 `try/except ImportError`，给出安装提示 |
| 市价单成交价格偏离过大 | 中 | 首期用市价单保证成交，后续可扩展限价单 |
| 策略连续下单资金不足 | 中 | 策略自己保证"先卖后买"，文档明确说明 |
| 策略错误导致每天狂下单 | 中 | `execution_mode='daily'` 下系统不做拦截，策略责任自负 |
| 实盘与回测结果差异大 | 中 | 文档说明差异来源（滑点、停牌、碎股、下单时机） |
| `context.g` 存了不可序列化对象 | 低 | 序列化时转 str 或跳过，文档建议只存基础类型 |
| Windows 下路径/编码问题 | 低 | 统一用 `os.path.join` |
