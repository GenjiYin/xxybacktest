# 实盘改造任务面板

技术方案详见 `LIVE_TECH_SPEC.md`。本文档只跟踪任务状态，每完成一项在 `[ ]` 改为 `[x]`。

---

## 开发约定

| 项目 | 值 |
|------|----|
| 真实数据路径 | `D:\Desktop\最新回测框架\data` |
| QMT 路径 | `D:\国金证券QMT交易端\userdata_mini` |
| QMT 账号 | `8881686799` |
| 所有 live 测试文件 | 使用上述真实路径，不使用 `./data` |
| 实盘专属目录 | `data/live/`（与 `simulation_results/` 平级） |
| 调度状态文件 | `data/live/live_schedule.json` |
| 实盘账户结果 | `data/live/accounts/{account_id}/` |

---

## P0 — 包骨架

- [x] 新建 `xxybacktest/live/__init__.py`

---

## P1 — QMT 交易通道（live/trader.py）

- [x] 实现 `QMTTrader.__init__`：连接 QMT，失败自动重试（5次 × 3秒）
- [x] 实现 `QMTTrader.is_connected`
- [x] 实现 `QMTTrader.disconnect`
- [x] 实现 `QMTTrader.get_portfolio`：返回 cash / frozen_cash / market_value / total_asset
- [x] 实现 `QMTTrader.get_positions`：返回持仓 dict，过滤 volume=0，market_value 自行计算
- [x] 实现 `QMTTrader.get_price`：通过 xtdata.get_full_tick 取最新价，停牌返回 None
- [x] 实现 `QMTTrader.order_stock`：原始下单，参数校验，返回 submitted / error
- [x] 编写真实环境测试 `tests/test_live_trader.py`

---

## P2 — 实盘上下文构建（live/context.py）

- [x] 实现 `create_live_context`：从 QMT 读取资金和持仓，构建与回测兼容的 context
- [x] portfolio 字段映射：cash / total_value / positions_value / starting_cash
- [x] 持仓转换为 Position 对象，字段与回测一致
- [x] trade / data 字段从账户配置填充
- [x] strategy_state 恢复到 context.g
- [x] 挂载 `ctx._trader`，供 trading.py 内部调用
- [x] 编写真实环境测试 `tests/test_live_context.py`

---

## P3 — 辅助工具（live/utils.py）

- [x] 实现 `is_trading_day`：查 xxydb trading_days 表
- [x] 实现 `_load_schedule`：读取 live_schedule.json 中指定账户的记录
- [x] 实现 `_update_schedule`：更新 live_schedule.json
- [x] 实现 `_load_strategy_state`：从 live_schedule.json 读取 strategy_state
- [x] 实现 `_save_strategy_state`：序列化 context.g 写入 live_schedule.json
  - [x] 处理 numpy/pandas 不可序列化类型（ndarray → tolist，integer/floating → .item()）
- [x] 编写测试 `tests/test_live_utils.py`
  - [x] is_trading_day：交易日返回 True，周末/节假日返回 False
  - [x] strategy_state 写入后读取内容一致
  - [x] numpy 类型序列化不报错

---

## P4 — 实盘版交易函数

### P4.1 trader.py 补充单股持仓查询
- [x] 实现 `QMTTrader.get_position(code)`：查询单只股票持仓，无持仓返回 None

### P4.2 live/trading.py — 实时刷新接口
- [x] 实现 `get_portfolio(context)`：从 QMT 拉取最新资金，同步到 `context.portfolio`，返回 dict
- [x] 实现 `get_account_positions(context)`：从 QMT 拉取全部持仓，同步到 `context.portfolio.positions`，返回 dict
- [x] 实现 `_refresh_portfolio(context)`：同时调用上述两个函数，统一刷新（handle_data 结束后由 runner.py 调用）

### P4.3 live/trading.py — 交易函数（内部实时查 QMT，不自动刷新 context）
- [x] 实现 `order_target_percent`：实时查总资产 + 实时查该股持仓 → 算差值 → 下单 → sleep 0.5s → 记录 Order
- [x] 实现 `order_target_value`：同上，目标市值版本
- [x] 实现 `order_value`：按金额下单
- [x] 实现 `order`：按差量下单（正数买，负数卖）
- [x] 实现 `order_buy`：直接买入指定数量
- [x] 实现 `order_sell`：直接卖出指定数量
- [x] 实现 `inout_cash`：记录 warning 并跳过（实盘不支持）
- [x] 所有函数构造 Order 对象记录到 `context.logs.order_list`（status=1 提交成功，-1 失败）

### P4.4 live/runner.py — 绑定更新
- [x] `run_live` 中绑定 `get_portfolio` / `get_account_positions` 到 context
- [x] `handle_data` 执行完后统一调用 `_refresh_portfolio(ctx)`，再进入 `_save_live_results`

> **说明：为什么交易函数内部不自动刷新？**
>
> 交易函数内部通过 `trader.get_position()` / `trader.get_portfolio()` 实时查 QMT 下单，
> 但**不修改 `context.portfolio`**。handle_data 执行期间 portfolio 保持快照状态，
> 避免连续调仓时 context 状态波动影响策略逻辑。
> handle_data 全部执行完后，runner.py 统一调用 `_refresh_portfolio` 一次。
>
> 策略如需 handle_data 中间查看最新持仓/资金，显式调用 `context.get_account_positions()` 即可。

---

## P5 — 结果持久化（live/recorder.py）

- [x] 实现 `_save_live_results`
  - [x] daily_values.parquet：每天追加一行（date / nav / daily_return），列结构与模拟交易一致
  - [x] positions.parquet：每次覆盖写入当前持仓（date / instrument / name / volume / ratio / cum_profit / cum_return / close_price / avg_cost）
  - [x] orders.parquet：有订单时追加（date / instrument / name / volume / side / status / price / cost）
- [x] nav 计算：`total_asset / initial_cash`
- [x] daily_return 计算：读取上一条 nav 记录做差，首次运行为 0
- [x] 编写测试 `tests/test_live_recorder.py`
  - [x] 首次运行生成三个 parquet 文件
  - [x] 二次运行 daily_values 追加，positions 覆盖，orders 追加
  - [x] 列名与 simulation/runner.py 的 _save_results 完全一致

---

## P6 — 实盘调仓入口（live/runner.py）

- [x] 实现 `run_live`
  - [x] 加载账户配置，校验 account_type == 'live'
  - [x] 调用 `is_trading_day` 判断，非交易日返回 skipped
  - [x] 连接 QMT（QMTTrader），失败返回 error
  - [x] 调用 `_load_strategy_state` 加载上次状态
  - [x] 调用 `create_live_context` 构建 context
  - [x] 用 lambda 将交易函数绑定到 context（与 backtest.py 方式完全一致）
  - [x] 绑定 `context.run_daily`：收集回调到列表
  - [x] 绑定 `context.history`：复用 Data 类（行情数据本地读取）
  - [x] 执行 `initialize(ctx)`
  - [x] 执行所有 daily_callbacks
  - [x] 调用 `_save_live_results` 保存结果
  - [x] 调用 `_save_strategy_state` 持久化 context.g
  - [x] 防并发：检查同一账户任务是否仍在运行，是则跳过
  - [x] 全程 try/except，异常返回 error 不向上抛出
- [x] 编写测试 `tests/test_live_runner.py`
  - [x] 非交易日返回 skipped
  - [x] 策略执行后 context.g 被持久化
  - [x] 执行后 parquet 文件存在

---

## P7 — 扩展账户提交（simulation/submitter.py）

- [x] `submit()` 新增参数：`account_type`、`live_account_id`、`qmt_path`、`trigger_cron`、`execution_mode`、`rebalance_interval`
- [x] `account_type='live'` 时：连接 QMT 读取 `total_asset`，写入 `initial_cash`，断开连接
- [x] 账户 ID 生成：实盘账户以 `live_` 开头（区别于模拟的 `sim_`）
- [x] 现有模拟账户调用不受影响（新参数均有默认值）
- [x] 编写测试（可 mock QMTTrader）

---

## P8 — 注册实盘调度 job（simulation/main.py）

- [x] 启动时读取所有 `account_type='live'` 且 `status='running'` 的账户
- [x] 为每个实盘账户注册独立 cron job：`add_func_job(task_id=f"live_{account_id}", ...)`
- [x] job ID 前缀固定为 `live_`，与内置任务区分
- [x] 触发时间由账户的 `trigger_cron` 字段决定，默认 `30 9 * * *`
- [x] 验证：Web 定时任务页面显示实盘 job，到点自动触发

---

## P9 — 集成测试

- [ ] 提交一个真实实盘账户，确认 `initial_cash` 自动写入
- [ ] 手动触发 `run_live`，确认策略执行、QMT 委托产生
- [ ] 检查三个 parquet 文件内容正确
- [ ] 打开 Web，确认净值曲线、持仓、订单与 QMT 界面一致
- [ ] 等待定时任务自动触发，确认全流程无人工干预正常运行

---

## P10 — 使用文档

- [ ] 编写实盘模块使用说明文档（README 或 docs）
  - [ ] 实盘账户注册流程（Web 端 vs API）
  - [ ] 策略代码规范（`initialize` + `handle_data`，与回测完全一致）
  - [ ] QMT 登录脚本的编写与定时配置
  - [ ] 调仓周期控制（`periodic` vs `daily` 模式）
  - [ ] Web 端查看实盘净值/持仓/订单
  - [ ] **修改已有账户策略代码（`update_account`）**
    - [ ] Python 脚本用法：`update_account(account_id, initialize=new_init)`
    - [ ] Web API 用法：`PUT /accounts/{account_id}` 传 `initialize_code` 字符串
    - [ ] **关键说明**：策略代码修改后，下次定时任务触发时自动生效，无需重启 xxy-sim
    - [ ] `trigger_cron` 修改后，如果 xxy-sim 已运行则自动热更新，无需重启
- [ ] **⚠️ 特别标注：当前仅支持 A 股股票和基金（ETF/LOF），不支持可转债**
  - [ ] 原因说明：股数取整为 100 的倍数（A 股/ETF 1 手 = 100 股），可转债为 10 张/手
  - [ ] 如需支持可转债，需修改 `live/trading.py` 中 `_round_volume` 逻辑，按代码前缀区分
- [ ] 风险提示文档
  - [ ] 市价单成交价格可能与预期有偏差（五档即成剩撤）
  - [ ] 策略需自行保证"先卖后买"顺序，系统不做批量排序
  - [ ] `execution_mode='daily'` 下系统不做调仓周期拦截，策略需自行控制
