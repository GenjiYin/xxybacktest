# 模拟交易系统 — 每日重跑回测方案

**核心思路**：不自己实现撮合/结算，每天对每个账户从 `start_date` 到今天重跑一次完整回测，直接用回测引擎的结果存库。

---

## 技术栈约定

- **数据存储**：xxydb（Parquet + DuckDB）
- **定时任务**：Plombery
- **回测引擎**：现有 `run_backtest`，全量复用
- **测试代码**：必须放在 `tests/` 目录
- **运行环境**：`conda activate vnpy`

---

## 工作面板

### ✅ 阶段一：改造回测引擎，支持无 UI 模式

**目标**：让 `run_backtest` 可以在非 Notebook 环境静默运行，不弹图、不调 `itables`。

**背景**：当前 `backtest.py` 末尾无条件调用了 `show()`（itables）和 `Performance.plot()`，在定时任务环境会报错或卡住。

**工作内容**：

修改 `xxybacktest/backtest.py`：
- `plot=True` 时才调用 `Performance.plot(context)` 和 `show()`（已有 `plot` 参数，只需把 `show()` 也纳入条件）
- `plot=False` 时静默返回 context，不产生任何 UI 副作用

```python
# 修改前（末尾无条件执行）
show(context.pos, ...)
show(context.order, ...)

# 修改后
if plot:
    Performance.plot(context)
    show(context.pos, ...)
    show(context.order, ...)
```

**验收**：`run_backtest(..., plot=False)` 在普通 Python 脚本中正常返回 context，无任何报错。

---

### ✅ 阶段二：设计账户表并实现 submit() 接口

**前置**：阶段一完成（确保回测可静默运行）

**目标**：用一行代码把策略注册为模拟交易账户。

**数据库表设计**（只需一张表）：

```
simulation_accounts（不分区）
  account_id      string    账户唯一ID（sim_YYYYMMDD_HHMMSS_XXX）
  name            string    账户名称
  initialize_code string    initialize 函数源码
  handle_data_code string   handle_data 函数源码
  initial_cash    double    初始资金
  start_date      string    策略开始日期（YYYY-MM-DD），即提交当天
  status          string    running / paused / stopped
  asset_type      string    stock / fund，默认 stock
  benchmark       string    基准指数，默认 000001.SH
  created_at      datetime  创建时间
```

**文件**：`xxybacktest/simulation/submitter.py`

```python
from xxybacktest.simulation import submit, pause, resume, delete

# 用法示例
account_id = submit(
    name="双均线策略",
    initialize=initialize,
    handle_data=handle_data,
    capital=100000,
    start_date="2025-01-01",  # 可选，默认今天
)
```

**实现要点**：
- 用 `inspect.getsource()` 提取函数源码存库
- `start_date` 默认为今天（提交即开始）
- 同时实现 `pause(account_id)` / `resume(account_id)` / `delete(account_id)`

**验收**：调用 `submit()` 后，xxydb 中 `simulation_accounts` 表有对应记录。

---

### ✅ 阶段三：实现每日重跑引擎

**前置**：阶段一、二完成

**目标**：每天对所有 `status=running` 的账户，从 `start_date` 到今天重跑回测，把结果存库。

**文件**：`xxybacktest/simulation/runner.py`

**核心流程**：

```python
def run_all(end_date=None):
    """对所有运行中账户执行回测并存库"""
    if end_date is None:
        end_date = today()

    accounts = load_running_accounts()  # 从 simulation_accounts 查 status=running

    for account in accounts:
        # 1. 从源码重建函数
        initialize = load_func(account.initialize_code)
        handle_data = load_func(account.handle_data_code)

        # 2. 重跑完整回测
        context = run_backtest(
            initialize=initialize,
            handle_data=handle_data,
            start_date=account.start_date,
            end_date=end_date,
            capital=account.initial_cash,
            asset_type=account.asset_type,
            benchmark=account.benchmark,
            plot=False,  # 静默模式
        )

        # 3. 提取结果存库（全量覆盖）
        save_results(account.account_id, context)
```

**存库内容**（从 context 直接提取，不重复计算）：

| 存储目标 | 数据来源 | 说明 |
|---------|---------|------|
| `simulation_daily_values` | `context.performance.returns` + `context.portfolio` | 每日净值、收益率 |
| `simulation_positions` | `context.performance.position_snapshots` | 每日持仓快照 |
| `simulation_orders` | `context.order`（DataFrame） | 全部成交订单 |

**存库策略**：每次全量覆盖（`rewrite=True`），因为是重跑，历史数据也可能因数据修正而变化。

**验收**：手动调用 `run_all()` 后，三张表有数据，净值曲线与直接跑回测结果一致。

---

### 阶段四：接入 Plombery 定时任务

**前置**：阶段三完成

**目标**：每天定时自动触发重跑，并在 Plombery Web UI 中可查看日志和结果。

**文件**：`xxybacktest/simulation/pipeline.py`

**Pipeline 设计**：

```
Pipeline: 每日模拟交易更新
  Task 1: update_market_data   → 执行 data_renew.py 更新行情
  Task 2: run_simulation       → 对所有账户重跑回测并存库
```

```python
@task
async def update_market_data():
    """执行 data_renew.py，失败则阻断后续任务"""
    ...

@task
async def run_simulation():
    """重跑所有 running 账户的回测"""
    from xxybacktest.simulation.runner import run_all
    results = run_all()
    return {"processed": len(results), "details": results}

register_pipeline(
    id="daily_simulation",
    name="每日模拟交易更新",
    tasks=[update_market_data, run_simulation],
    triggers=[
        Trigger(
            id="daily_22",
            name="每天22:00",
            schedule=CronTrigger(hour=22, minute=0, timezone="Asia/Shanghai"),
        )
    ],
)
```

**启动入口**：`run_simulation.py`（项目根目录）

```bash
conda activate vnpy
python run_simulation.py
# 访问 http://localhost:8000 查看任务面板
```

**验收**：
- Plombery UI 可看到 Pipeline 和两个 Task
- 手动点击 Run 可触发，Data 标签显示处理账户数
- Task 1 失败时 Task 2 不执行

---

### 阶段五：Flask 前端展示

**前置**：阶段三完成（有数据可展示）

**目标**：简洁的 Web 页面，展示所有模拟账户的净值曲线和持仓情况。

**目录结构**：

```
web/
├── app.py
├── routes/
│   ├── dashboard.py   # 账户列表 + 汇总统计
│   ├── account.py     # 单账户详情（净值曲线 + 持仓 + 订单）
│   └── api.py         # JSON API，供前端 AJAX 调用
└── templates/
    ├── base.html
    ├── dashboard.html  # 账户列表，按收益率排序
    └── account.html    # 单账户详情页
```

**页面功能**：

`dashboard.html`（账户列表）：
- 所有账户卡片，显示：名称、累计收益率、最大回撤、状态
- 按累计收益率排序
- 点击进入详情页

`account.html`（账户详情）：
- ECharts 净值曲线（策略 vs 基准）
- 当前持仓表格
- 最近 30 条成交记录
- 绩效指标卡片（夏普、最大回撤等）

**API 接口**：

```
GET /api/accounts                    # 账户列表（含最新净值）
GET /api/accounts/<id>/nav           # 净值曲线数据
GET /api/accounts/<id>/positions     # 当前持仓
GET /api/accounts/<id>/orders        # 成交记录
GET /api/accounts/<id>/indicators    # 绩效指标
POST /api/accounts/<id>/pause        # 暂停
POST /api/accounts/<id>/resume       # 恢复
DELETE /api/accounts/<id>            # 删除
```

**验收**：浏览器打开可看到账户列表和净值曲线，数据与数据库一致。

---

### 阶段六：增量回测模式（性能优化）

**前置**：阶段三完成

**背景**：当前每日重跑会从 `start_date` 到今天重放所有历史交易日的事件循环。账户存续越长，每天的跑批耗时就越长（线性增长）。经分析，瓶颈在于 `handle_bar` 被调用的总次数，而非 `init` 中的取数 SQL。

**目标**：每天只处理今天这 1 个交易日，无论账户跑了多久，每日耗时恒定。

**核心思路：Checkpoint 机制**

每次回测结束后，将当天的完整状态序列化存盘（Checkpoint）。第二天启动时加载 Checkpoint，跳过历史，只运行今天 1 天的事件。

```
现在：
  start_date ──────────────────────── today
  [D1][D2][D3]...[D499][D500][D501]   ← 每天全部重跑

优化后：
  加载 Checkpoint（D500 结束时的状态）
                              [D501]   ← 只跑今天
```

**需要持久化的 Checkpoint 内容**：

| 字段 | 内容 | 格式 |
|------|------|------|
| `portfolio` | cash、positions（amount/cost_basis等） | JSON |
| `performance.returns` | 历史每日收益率序列 | JSON |
| `performance.position_snapshots` | 历史持仓快照 | Parquet |
| `performance.position_ratio` | 历史仓位比例序列 | JSON |
| `logs.order_list` | 历史全部订单 | Parquet |
| `data.dividend` | 待发放分红缓存 | JSON |
| `context.g` | 用户自定义变量（必须 JSON 可序列化） | JSON |
| `last_date` | 最后处理的交易日 | JSON |
| `code_hash` | initialize/handle_data 源码的哈希 | JSON |

**不需要持久化**（每次重新生成）：
- `Data._daily_cache`：从 xxydb 重新加载
- `context.data.calendar`：从 DB 重新查询
- `event_list`：重新生成
- `context.df` 等用户在 `init` 中计算的数据：重新执行 `initialize(context)`

**Checkpoint 存储路径**：
```
data/simulation_results/checkpoints/{account_id}/checkpoint.json
data/simulation_results/checkpoints/{account_id}/snapshots.parquet
data/simulation_results/checkpoints/{account_id}/orders.parquet
```

**文件改动**：

新增 `xxybacktest/simulation/state.py`：
```python
def save_checkpoint(context, account_id, data_path, code_hash): ...
def load_checkpoint(account_id, data_path): ...  # 返回 dict 或 None
def apply_checkpoint(context, checkpoint): ...   # 将 checkpoint 注入 context
```

修改 `xxybacktest/backtest.py`：
```python
def run_backtest(
    initialize, handle_data,
    start_date, end_date,
    ...,
    resume_state=None,   # ← 新增参数，传入 checkpoint dict
):
    # resume_state 不为 None 时：
    # 1. 正常执行 initialize(context)（重建 context.df 等数据）
    # 2. 用 resume_state 覆盖 portfolio/performance/orders/g 状态
    # 3. 将 start_date 推进到 last_date 的下一个交易日
    # 4. 只处理新的事件（从 last_date+1 到 end_date）
```

修改 `xxybacktest/simulation/runner.py`：
```python
def run_single(account_id, end_date, data_path):
    checkpoint = load_checkpoint(account_id, data_path)

    # 代码变更检测：源码哈希不一致时强制全量
    code_hash = hash(initialize_code + handle_data_code)
    if checkpoint and checkpoint['code_hash'] != code_hash:
        checkpoint = None  # 策略改了，全量重跑

    context = run_backtest(
        ...,
        resume_state=checkpoint,  # ← 有则增量，无则全量
    )

    save_checkpoint(context, account_id, data_path, code_hash)
    _save_results(account_id, context, data_path)
```

**降级策略**（保证安全）：
- Checkpoint 不存在 → 全量回测（同现在）
- Checkpoint 损坏或读取异常 → 全量回测 + 警告日志
- 策略源码变更（code_hash 不匹配）→ 全量回测 + 删除旧 Checkpoint
- `context.g` 含不可序列化对象 → 抛出明确错误，提示用户

**用户侧限制**：
- `context.g` 中存放的变量必须是 JSON 可序列化类型（数字、字符串、列表、字典）
- 不可存放 sklearn 模型、DataFrame、自定义对象等
- 违反此约束时，`save_checkpoint` 会抛出带有明确提示的异常

**性能对比**：

| 场景 | 优化前 | 优化后 |
|------|--------|--------|
| 账户运行 1 年（250天） | 跑 250 天 | 跑 1 天 |
| 账户运行 3 年（750天） | 跑 750 天 | 跑 1 天 |
| 10 个账户 × 2 年 | 5000 天事件循环 | 10 天事件循环 |

**验收**：
- 第一次运行：全量回测，结果与现有一致，Checkpoint 文件生成
- 第二次运行：只处理新增交易日，净值/持仓/订单结果与全量重跑完全一致
- 策略源码修改后重新 submit：自动触发全量重跑

---

## 文件结构总览

```
xxybacktest/
├── backtest.py                    # [改] plot=False 时跳过 show()；新增 resume_state 参数
└── simulation/
    ├── __init__.py                # 导出 submit/pause/resume/delete
    ├── submitter.py               # submit() 接口 + 账户管理
    ├── runner.py                  # [改] run_all() 重跑引擎，支持增量模式
    ├── pipeline.py                # Plombery Pipeline 定义
    └── state.py                   # [新] Checkpoint 序列化/反序列化

web/
├── app.py
├── routes/
└── templates/

run_simulation.py                  # 启动入口（Plombery + Flask）

tests/
├── test_submitter.py
├── test_runner.py
├── test_pipeline.py
└── test_state.py                  # [新] Checkpoint 机制测试
```

---

## 各阶段依赖关系

```
阶段一（改造回测引擎）
    │
    └─► 阶段二（submit接口）
            │
            └─► 阶段三（重跑引擎）
                    │
                    ├─► 阶段四（Plombery定时任务）
                    │
                    ├─► 阶段五（Flask前端）
                    │
                    └─► 阶段六（增量回测模式）
```

---

## 注意事项

- 运行前必须 `conda activate vnpy`
- `data_renew.py` 由用户自行维护，Pipeline 只负责执行它
- 所有测试代码放 `tests/` 目录
- 重跑策略：每次全量覆盖，不做增量（简单可靠）；账户多时可启用阶段六的增量模式
- 阶段六启用后，`context.g` 中的变量必须是 JSON 可序列化类型
- 策略运行时间随账户存续时间线性增长，100个账户×1年数据约需几分钟，可接受；启用增量模式后与账户存续时间无关
