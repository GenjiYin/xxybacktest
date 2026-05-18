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

## P4 — 实盘版交易函数（live/trading.py）

- [ ] 实现 `_refresh_portfolio`：下单后从 QMT 重新拉取资金和持仓，更新 context.portfolio
- [ ] 实现 `order_target_percent`：目标仓位 → 差值 → 下单 → 刷新 portfolio → 返回 Order
- [ ] 实现 `order_target_value`：目标市值版本
- [ ] 实现 `order_value`：按金额下单
- [ ] 实现 `order`：按差量下单（正数买，负数卖）
- [ ] 实现 `order_buy`：直接买入指定数量
- [ ] 实现 `order_sell`：直接卖出指定数量
- [ ] 实现 `inout_cash`：记录 warning 并跳过（实盘不支持）
- [ ] 所有函数下单后等待 0.5 秒防爆单
- [ ] 构造 Order 对象记录到 context.logs.order_list（status=1 提交成功，-1 失败）

> **后续优化 — 自动先卖后买**
>
> 当前实现：`order_*` 被调用时立即向 QMT 下单，策略需自己保证先卖后买顺序。
>
> 优化方案：`order_*` 调用时只将订单意图写入 `ctx._pending_orders` 队列，
> handle_data 全部执行完后，runner.py 统一按"卖单优先"顺序批量提交，用户无需关心顺序。
>
> 待确认：买单 volume 的计算时机（收集时算好 vs 卖单执行后重新算），
> 月度调仓场景下收集时算好（方式 A）已足够，资金偏差极小。

---

## P5 — 结果持久化（live/recorder.py）

- [ ] 实现 `_save_live_results`
  - [ ] daily_values.parquet：每天追加一行（date / nav / daily_return），列结构与模拟交易一致
  - [ ] positions.parquet：每次覆盖写入当前持仓（date / instrument / name / volume / ratio / cum_profit / cum_return / close_price / avg_cost）
  - [ ] orders.parquet：有订单时追加（date / instrument / name / volume / side / status / cost）
- [ ] nav 计算：`total_asset / initial_cash`
- [ ] daily_return 计算：读取上一条 nav 记录做差，首次运行为 0
- [ ] 编写测试 `tests/test_live_recorder.py`
  - [ ] 首次运行生成三个 parquet 文件
  - [ ] 二次运行 daily_values 追加，positions 覆盖，orders 追加
  - [ ] 列名与 simulation/runner.py 的 _save_results 完全一致

---

## P6 — 实盘调仓入口（live/runner.py）

- [ ] 实现 `run_live`
  - [ ] 加载账户配置，校验 account_type == 'live'
  - [ ] 调用 `is_trading_day` 判断，非交易日返回 skipped
  - [ ] 连接 QMT（QMTTrader），失败返回 error
  - [ ] 调用 `_load_strategy_state` 加载上次状态
  - [ ] 调用 `create_live_context` 构建 context
  - [ ] 用 lambda 将交易函数绑定到 context（与 backtest.py 方式完全一致）
  - [ ] 绑定 `context.run_daily`：收集回调到列表
  - [ ] 绑定 `context.history`：复用 Data 类（行情数据本地读取）
  - [ ] 执行 `initialize(ctx)`
  - [ ] 执行所有 daily_callbacks
  - [ ] 调用 `_save_live_results` 保存结果
  - [ ] 调用 `_save_strategy_state` 持久化 context.g
  - [ ] 防并发：检查同一账户任务是否仍在运行，是则跳过
  - [ ] 全程 try/except，异常返回 error 不向上抛出
- [ ] 编写测试 `tests/test_live_runner.py`
  - [ ] 非交易日返回 skipped
  - [ ] 策略执行后 context.g 被持久化
  - [ ] 执行后 parquet 文件存在

---

## P7 — 扩展账户提交（simulation/submitter.py）

- [ ] `submit()` 新增参数：`account_type`、`live_account_id`、`qmt_path`、`trigger_cron`、`execution_mode`、`rebalance_interval`
- [ ] `account_type='live'` 时：连接 QMT 读取 `total_asset`，写入 `initial_cash`，断开连接
- [ ] 账户 ID 生成：实盘账户以 `live_` 开头（区别于模拟的 `sim_`）
- [ ] 现有模拟账户调用不受影响（新参数均有默认值）
- [ ] 编写测试（可 mock QMTTrader）

---

## P8 — 注册实盘调度 job（simulation/main.py）

- [ ] 启动时读取所有 `account_type='live'` 且 `status='running'` 的账户
- [ ] 为每个实盘账户注册独立 cron job：`add_func_job(task_id=f"live_{account_id}", ...)`
- [ ] job ID 前缀固定为 `live_`，与内置任务区分
- [ ] 触发时间由账户的 `trigger_cron` 字段决定，默认 `30 9 * * *`
- [ ] 验证：Web 定时任务页面显示实盘 job，到点自动触发

---

## P9 — 集成测试

- [ ] 提交一个真实实盘账户，确认 `initial_cash` 自动写入
- [ ] 手动触发 `run_live`，确认策略执行、QMT 委托产生
- [ ] 检查三个 parquet 文件内容正确
- [ ] 打开 Web，确认净值曲线、持仓、订单与 QMT 界面一致
- [ ] 等待定时任务自动触发，确认全流程无人工干预正常运行
