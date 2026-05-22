# 实盘整合方案（交付视角）

## 一、交付总览

你写完 `initialize` + `handle_data`，注册一次实盘账户，以后每天系统自动完成：**登录 QMT → 读取真实持仓资金 → 执行策略 → 向 QMT 下单 → 记录流水 → Web 展示**。

QMT 登录这件事交给现有的定时任务系统做，实盘代码只管交易。

---

## 二、你需要做的（只有 3 步）

### 第 1 步：写策略（跟你现在写回测一样）

```python
def initialize(context):
    context.run_daily(strategy, "9:30")

def strategy(context):
    # 你的交易逻辑，完全不用改
    weights = get_signals()
    for code, w in weights.items():
        context.order_target_percent(code, w)
```

**关键点**：`context.order_target_percent` 这个函数，回测和实盘都长一个样，你的代码不需要任何 `if 回测 else 实盘` 的判断。

### 第 2 步：在 Web 上注册实盘账户（一次）

提交时选 **实盘模式**，填：
- 账户名称（你自己看着取）
- QMT 资金账号
- QMT 客户端路径
- 调仓周期（默认 30 天）
- 初始资金（用于净值曲线归一化）

注册完你会拿到一个 `live_xxx` 的账户 ID。

### 第 3 步：在 Web 定时任务页面添加登录任务（一次）

用现有的任务系统添加一个脚本任务：
- **名称**：QMT 自动登录
- **脚本路径**：你的 `login_qmt.py`
- **执行时间**：`20 9 * * *`（每天 9:20）

完成。以后每天：
- `9:20` → 系统自动登录 QMT
- `9:30` → 系统读取你账户真实情况，执行策略，真正下单

你在 Web 上看净值、持仓、订单，跟看模拟账户一模一样。

---

## 三、系统内部会自动做什么

### 3.1 每日完整流程

```
9:20 ──→ 你的登录脚本跑完，QMT 客户端已登录
         │
9:30 ──→ 系统触发实盘调仓任务
         │
         ├─→ ① 连接 QMT（失败则重试 5 次，间隔 3 秒，还连不上就报错终止）
         ├─→ ② 读取真实资金、真实持仓，塞进 context
         ├─→ ③ 检查今天是不是交易日（不是就跳过）
         ├─→ ④ 检查调仓周期到了没（没到就跳过）
         ├─→ ⑤ 执行你的 strategy(context)
         │      你的代码里的 order_target_percent 被调用
         │      系统内部：
         │        · 计算当前持仓与目标持仓的差值
         │        · 按 QMT 的市价单下单（买/卖）
         │        · 每次下单后等 0.5 秒（防爆单）
         │        · 记录每一笔订单
         ├─→ ⑥ 重新拉取最新持仓/资金，更新本地记录
         └─→ ⑦ 保存今天的结果到文件
```

### 3.2 净值曲线怎么来的

回测是每天算一次净值，实盘没有"每天虚拟交易"这件事，所以：
- **调仓日**：策略执行完，用 QMT 里的总资产算一次净值
- **非调仓日**：收盘后（或次日开盘前）自动快照一次总资产，追加到净值记录

这样 Web 上的净值曲线是连续的。

### 3.3 持仓和订单怎么展示

- **持仓**：每次调仓后从 QMT 拉取，存入 `positions.parquet`
- **订单**：每次下单立即记录到 `orders.parquet`
- Web 端读取方式和模拟交易完全一样，无需改动

---

## 四、内部模块设计（各层职责）

### 4.1 live/trader.py — QMT 交易通道

只干一件事：**跟 QMT 打交道**。

```python
class QMTTrader:
    def __init__(self, live_account_id, qmt_path):
        """连接 QMT，失败自动重试"""
        self.xt_trader = XtQuantTrader(qmt_path, session_id)
        self.xt_trader.start()
        self._connect_with_retry(retry=5, interval=3)
        self.xt_trader.subscribe(self.acc)

    def get_portfolio(self) -> dict:
        """返回 {cash, frozen_cash, market_value, total_asset}"""

    def get_positions(self) -> dict:
        """返回 {code: {'volume': x, 'cost_price': x, 'last_price': x}}"""

    def get_price(self, code: str) -> float:
        """取最新价（xtdata.get_full_tick）"""

    def order_target_percent(self, code, percent, total_asset) -> dict:
        """
        核心调仓函数。内部逻辑：
        1. 目标市值 = total_asset * percent
        2. 用最新价算目标股数，100 股取整
        3. 查当前持仓，算差值
        4. 差>0 → 买；差<0 → 卖
        5. 调用 order_stock 下市价单
        6. sleep(0.5) 防爆单
        """

    def order_stock(self, code, order_type, volume, price_type, price=0):
        """原始 QMT 下单"""
```

**注意**：这个模块**不包含任何登录逻辑**，只假设 QMT 已经登录好了。

### 4.2 live/context.py — 构建实盘上下文

从 QMT 读取真实数据，转换成回测的 `context` 格式。

```python
def create_live_context(account_config, trader):
    ctx = create_context()  # 复用回测的空 context

    # 同步真实资金
    p = trader.get_portfolio()
    ctx.portfolio.cash = p['可用资金']
    ctx.portfolio.total_value = p['总资产']
    ctx.portfolio.positions_value = p['持仓市值']
    ctx.portfolio.starting_cash = account_config['initial_cash']

    # 同步真实持仓 → Position 对象
    for code, pos in trader.get_positions().items():
        ctx.portfolio.positions[code] = Position(
            code=code,
            amount=pos['volume'],
            enable_amount=pos['volume'],
            last_sale_price=pos['last_price'],
        )
        # 同步成本价
        ctx.portfolio.positions[code].cost_basis = pos['cost_price']
        ctx.portfolio.positions[code].total_cost = pos['volume'] * pos['cost_price']
        ctx.portfolio.positions[code].total_value = pos['volume'] * pos['last_price']

    ctx.current_dt = datetime.now()
    ctx._trader = trader  # 供 trading.py 调用
    return ctx
```

### 4.3 live/trading.py — 实盘版交易函数

API 签名与回测 `trading.py` 完全一致。

```python
def order_target_percent(security, percent, context):
    """
    实盘版：内部调用 QMTTrader.order_target_percent
    返回 Order 对象（兼容回测格式）
    """
    trader = context._trader
    result = trader.order_target_percent(
        security, percent,
        total_asset=context.portfolio.total_value
    )

    # 构造 Order 对象记录到 context.logs
    order_obj = Order(...)
    order_obj.status = 1 if result['status'] == 'filled' else -1
    context.logs.order_list.append(order_obj)

    # 下单后刷新本地持仓/资金（让策略后续调用正确）
    _refresh_portfolio(context, trader)
    return order_obj
```

其他函数同理：
- `order(security, amount, context)` → 按差值直接买/卖
- `order_value(security, value, context)` → 按目标市值调仓
- `order_target_value(security, value, context)` → 同上
- `order_buy / order_sell` → 直接下指定数量的单

### 4.4 live/runner.py — 实盘调仓入口

```python
def run_live(account_id: str, data_path="./data") -> dict:
    """执行一次实盘调仓"""

    # 1. 加载账户配置
    account = get_account(account_id)
    if account['account_type'] != 'live':
        return {'status': 'error', 'reason': '不是实盘账户'}

    # 2. 连接 QMT（失败会重试）
    trader = QMTTrader(
        account['live_account_id'],
        account['qmt_path']
    )

    # 3. 检查交易日
    if not is_trading_day():
        return {'status': 'skipped', 'reason': '非交易日'}

    # 4. 检查调仓周期
    if not _should_rebalance(account):
        return {'status': 'skipped', 'reason': '未到调仓日'}

    # 5. 构建上下文
    ctx = create_live_context(account, trader)

    # 6. 加载策略并执行 initialize
    initialize = _load_func(account['initialize_code'])
    handle_data = _load_func(account['handle_data_code']) if account['handle_data_code'] else None

    daily_callbacks = []
    ctx.run_daily = lambda func, time="9:30": daily_callbacks.append(func)
    initialize(ctx)

    # 7. 执行策略
    for func in daily_callbacks:
        func(ctx)

    # 8. 保存结果
    _save_live_results(account_id, ctx, data_path)

    return {'status': 'success', 'orders': len(ctx.logs.order_list)}
```

### 4.5 live/recorder.py — 结果持久化

存储路径：
```
data/live/accounts/live_001/
  daily_values.parquet   ← 每日总资产快照
  positions.parquet      ← 调仓后持仓
  orders.parquet         ← 订单流水
```

格式与模拟交易完全一致，Web 端直接兼容。

---

## 五、关键问题处理

### 5.1 QMT 连接失败（重试机制）

```
第 1 次连接失败 → 等 3 秒 → 第 2 次
第 2 次连接失败 → 等 3 秒 → 第 3 次
...（最多 5 次）
第 5 次还失败 → 报错终止，记录失败原因，等明天再来
```

**为什么这样设计**：
- 你的登录脚本 9:20 跑，QMT 启动需要时间
- 重试 5 次 × 3 秒 = 15 秒，足够覆盖启动延迟
- 还连不上说明今天登录脚本没跑成功或 QMT 异常，终止是正确选择

### 5.2 调仓周期控制

每个实盘账户独立维护一个 `live_schedule.json`：

```json
{
  "live_001": {"last_rebalance": "2026-04-15"},
  "live_002": {"last_rebalance": "2026-05-10"}
}
```

`run_live` 执行前检查：
- `today - last_rebalance >= rebalance_interval` 才允许调仓
- 调仓成功后更新 `last_rebalance`

### 5.3 交易日判断

复用你的 `is_tradeingday` 逻辑（查 `all_trading_days` 表），非交易日直接跳过，不更新调仓周期。

### 5.4 多次调仓的防护

- `max_instances=1`：同一个实盘账户的调仓任务同一时间只能跑一个
- 任务开始前检查上一次是否还在 running，是则跳过

### 5.5 下单后持仓刷新

策略里可能连续调多只股票：

```python
for code, w in weights.items():
    context.order_target_percent(code, w)  # 每只股票
```

实盘每下一单后，立即从 QMT 拉最新持仓和资金更新到 `context.portfolio`，下一只股票的计算就基于最新的真实情况，不会出现资金不够的错误。

### 5.6 订单记录

QMT 的 `order_stock` 返回的是委托号，不代表成交。实盘记录分两层：

1. **下单时立即记录**：记录下单请求（股票、方向、数量、时间）
2. **盘后补录成交结果**（可选增强）：调仓完成后查询 QMT 的成交回报，补充实际成交价格、数量

第一层已经够用，第二层可以作为后续优化。

---

## 六、与现有系统的整合

### 6.1 账户管理（submitter.py）

账户表新增字段：

| 字段 | 说明 |
|------|------|
| `account_type` | `simulation` / `live` |
| `live_account_id` | QMT 资金账号 |
| `qmt_path` | QMT 客户端路径 |
| `rebalance_interval` | 调仓周期（天） |

Web 上提交账户时根据 `account_type` 显示不同表单。

### 6.2 定时调度（scheduler.py）

为实盘账户独立注册任务：

```python
# 模拟回测任务（已有）
"builtin_run_simulation" @ 22:00

# 实盘调仓任务（新增）
"live_live_001" @ 9:30 → run_live("live_001")
"live_live_002" @ 9:30 → run_live("live_002")
```

每个实盘账户一个独立 job，可以单独暂停/恢复。

### 6.3 Web 展示（无需改动）

Web 层通过 `get_account_nav` / `get_account_positions` / `get_account_orders` 读取账户数据，这些函数自动从 `simulation_results/accounts/{id}/` 或 `live/accounts/{id}/` 查找 Parquet 文件。实盘账户按同样格式存入 `data/live/` 后，Web 端完全无感知，自动兼容。

---

## 七、文件清单

| 文件 | 作用 |
|------|------|
| `xxybacktest/live/__init__.py` | 包入口 |
| `xxybacktest/live/trader.py` | QMT 连接与下单（含重试） |
| `xxybacktest/live/context.py` | 从 QMT 构建兼容的 context |
| `xxybacktest/live/trading.py` | 实盘版 order_* 函数 |
| `xxybacktest/live/runner.py` | 实盘调仓入口 run_live |
| `xxybacktest/live/recorder.py` | 结果持久化 |
| `xxybacktest/simulation/submitter.py` | 改：账户表增加 live 字段 |
| `xxybacktest/simulation/scheduler.py` | 改：注册实盘账户定时任务 |

你的登录脚本不需要改动，作为独立脚本由 scheduler 调用即可。
