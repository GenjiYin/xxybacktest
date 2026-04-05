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

### ✅ 阶段四：接入 Plombery 定时任务

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

### ✅ 阶段五：Flask 前端展示

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

## 文件结构总览

```
xxybacktest/
├── backtest.py                    # [改] plot=False 时跳过 show()
└── simulation/
    ├── __init__.py                # 导出 submit/pause/resume/delete
    ├── submitter.py               # submit() 接口 + 账户管理
    ├── runner.py                  # run_all() 重跑引擎
    └── pipeline.py                # Plombery Pipeline 定义

web/
├── app.py
├── routes/
└── templates/

run_simulation.py                  # 启动入口（Plombery + Flask）

tests/
├── test_submitter.py
├── test_runner.py
└── test_pipeline.py
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
                    └─► 阶段五（Flask前端）
```

---

## 注意事项

- 运行前必须 `conda activate vnpy`
- `data_renew.py` 由用户自行维护，Pipeline 只负责执行它
- 所有测试代码放 `tests/` 目录
- 重跑策略：每次全量覆盖，不做增量（简单可靠）
- 策略运行时间随账户存续时间线性增长，100个账户×1年数据约需几分钟，可接受
