# 并行化改造方案：每账户独立存储 + ProcessPoolExecutor

## 背景

当前 `run_all()` 串行执行，账户越多耗时越长。根本原因是 `_save_results`
使用了"读全表→过滤→合并→覆盖写"的模式，多进程并行时必然丢数据。

xxydb 使用内存 DuckDB（无文件锁），行情数据多进程读取没有问题。
唯一需要解决的就是**结果写入的竞争问题**。

---

## 核心思路

将模拟结果从**所有账户共享一张表**改为**每账户独立文件**：

```
改造前：
data/simulation_results/
  simulation_daily_values/data.parquet   ← 所有账户混在一起
  simulation_positions/data.parquet
  simulation_orders/data.parquet

改造后：
data/simulation_results/
  accounts/
    sim_001/
      daily_values.parquet               ← 只属于 sim_001
      positions.parquet
      orders.parquet
    sim_002/
      daily_values.parquet
      ...
```

写入时直接覆盖自己的文件，不读其他账户数据，天然无冲突。

---

## 改造步骤

### 步骤一：修改 `_save_results`（核心改动）

**文件**：`xxybacktest/simulation/runner.py`

**改动位置**：`_save_results` 函数，约第 71~191 行

**改动内容**：去掉 xxydb 依赖，改为直接写 Parquet 文件。

```python
# ====== 改造前（有竞争的写法）======
def _save_results(account_id: str, context, data_path: str):
    sim_path = os.path.join(data_path, "simulation_results")
    db = get_db(sim_path)
    try:
        # 1. 保存每日净值
        ...
        # 先删除该账户的旧数据（竞争点在这里！）
        try:
            old_df = db.query(f"SELECT * FROM {DAILY_VALUES_TABLE}").df()
            old_df = old_df[old_df['account_id'] != account_id]
            df_nav = pd.concat([old_df, df_nav], ignore_index=True)
        except Exception:
            pass
        db.write_data(df_nav, id=DAILY_VALUES_TABLE, ..., rewrite=True)

        # 2. 保存持仓（同样模式）...
        # 3. 保存订单（同样模式）...
    finally:
        close_db(sim_path)


# ====== 改造后（无竞争的写法）======
def _save_results(account_id: str, context, data_path: str):
    # 每个账户写自己的独立目录
    account_dir = os.path.join(data_path, "simulation_results", "accounts", account_id)
    os.makedirs(account_dir, exist_ok=True)

    # 1. 保存每日净值（构建 df_nav 的逻辑不变，只改最后的写入方式）
    ...
    if nav_records:
        df_nav = pd.DataFrame(nav_records)
        df_nav.to_parquet(os.path.join(account_dir, "daily_values.parquet"), index=False)

    # 2. 保存持仓快照
    ...
    if not df_pos.empty:
        df_pos.to_parquet(os.path.join(account_dir, "positions.parquet"), index=False)

    # 3. 保存订单
    ...
    if not df_orders.empty:
        df_orders.to_parquet(os.path.join(account_dir, "orders.parquet"), index=False)
```

注意：构建 DataFrame 的逻辑（for 循环、字段重命名、列选择等）**完全不变**，
只删掉中间那段"读旧数据 + concat"，以及把最后的 `db.write_data(...)` 换成 `df.to_parquet(...)`。

---

### 步骤二：修改三个查询函数

**文件**：`xxybacktest/simulation/runner.py`

**改动位置**：`get_account_nav`、`get_account_positions`、`get_account_orders`，约第 335~435 行

```python
# ====== 改造前 ======
def get_account_nav(account_id: str, data_path: str = "./data") -> pd.DataFrame:
    sim_path = os.path.join(data_path, "simulation_results")
    db = get_db(sim_path)
    try:
        try:
            df = db.query(f"""
                SELECT date, nav, daily_return
                FROM {DAILY_VALUES_TABLE}
                WHERE account_id = '{account_id}'
                ORDER BY date
            """).df()
            return df
        except Exception:
            return pd.DataFrame(columns=['date', 'nav', 'daily_return'])
    finally:
        close_db(sim_path)


# ====== 改造后 ======
def get_account_nav(account_id: str, data_path: str = "./data") -> pd.DataFrame:
    path = os.path.join(data_path, "simulation_results", "accounts", account_id, "daily_values.parquet")
    if not os.path.exists(path):
        return pd.DataFrame(columns=['date', 'nav', 'daily_return'])
    df = pd.read_parquet(path)
    return df.sort_values('date').reset_index(drop=True)
```

```python
# get_account_positions 改造后
def get_account_positions(account_id: str, date: Optional[str] = None, data_path: str = "./data") -> pd.DataFrame:
    path = os.path.join(data_path, "simulation_results", "accounts", account_id, "positions.parquet")
    cols = ['date', 'instrument', 'name', 'volume', 'ratio', 'cum_profit', 'cum_return', 'close_price', 'avg_cost']
    if not os.path.exists(path):
        return pd.DataFrame(columns=cols)
    df = pd.read_parquet(path)
    if date:
        df = df[df['date'] == date]
    else:
        # 取最新日期的持仓
        if not df.empty:
            latest_date = df['date'].max()
            df = df[df['date'] == latest_date]
    return df.sort_values('ratio', ascending=False).reset_index(drop=True)
```

```python
# get_account_orders 改造后
def get_account_orders(account_id: str, limit: int = 100, data_path: str = "./data") -> pd.DataFrame:
    path = os.path.join(data_path, "simulation_results", "accounts", account_id, "orders.parquet")
    cols = ['date', 'instrument', 'name', 'volume', 'side', 'status', 'cost']
    if not os.path.exists(path):
        return pd.DataFrame(columns=cols)
    df = pd.read_parquet(path)
    return df.sort_values('date', ascending=False).head(limit).reset_index(drop=True)
```

---

### 步骤三：`run_all` 改为并行执行

**文件**：`xxybacktest/simulation/runner.py`

**改动位置**：`run_all` 函数，约第 289~332 行

```python
# ====== 改造后 ======
import os
from concurrent.futures import ProcessPoolExecutor, as_completed

def run_all(end_date: Optional[str] = None, data_path: str = "./data") -> list:
    from .submitter import list_accounts

    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"[每日模拟交易重跑] 目标日期: {end_date}")
    print(f"{'='*60}")

    accounts = list_accounts(status='running', data_path=data_path)
    if not accounts:
        print("[提示] 没有运行中的账户")
        return []

    print(f"[信息] 共 {len(accounts)} 个运行中账户，开始并行执行")

    # max_workers 默认用 CPU 核心数，也可以写死为 4
    max_workers = min(len(accounts), os.cpu_count() or 4)

    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        future_to_id = {
            pool.submit(run_single, acc['account_id'], end_date, data_path): acc['account_id']
            for acc in accounts
        }
        for future in as_completed(future_to_id):
            account_id = future_to_id[future]
            try:
                result = future.result()
            except Exception as e:
                print(f"[错误] {account_id} 执行异常: {e}")
                result = {'account_id': account_id, 'status': 'error', 'reason': str(e)}
            results.append(result)

    success_count = sum(1 for r in results if r['status'] == 'success')
    error_count   = sum(1 for r in results if r['status'] == 'error')
    skip_count    = sum(1 for r in results if r['status'] == 'skipped')

    print(f"\n{'='*60}")
    print(f"[每日重跑完成] 成功: {success_count}, 失败: {error_count}, 跳过: {skip_count}")
    print(f"{'='*60}")
    return results
```

**注意（Windows 特有）**：Windows 的 multiprocessing 使用 spawn 模式，
调用 `run_all()` 的入口脚本（`run_simulation.py` 或 `pipeline.py`）
必须在 `if __name__ == '__main__':` 保护下调用，否则子进程会递归启动报错。

`pipeline.py` 中的 `run_simulation` task 里调用 `run_all()` 不在主模块，
一般没问题。但如果直接在 `run_simulation.py` 里调用 `run_all()`，需要确认有保护块。

---

### 步骤四：清理 `db_utils.py` 的调用（可选）

`_save_results` 改完后，runner.py 不再需要 `get_db` / `close_db`。
可以删掉 runner.py 顶部的相关 import：

```python
# 删掉这行
from .db_utils import close_db, get_db

# 删掉这些常量（不再使用）
DAILY_VALUES_TABLE = "simulation_daily_values"
POSITIONS_TABLE = "simulation_positions"
ORDERS_TABLE = "simulation_orders"
```

`db_utils.py` 本身保留（`submitter.py` 还在用）。

---

### 步骤五：旧数据迁移

现有数据存在 `data/simulation_results/simulation_daily_values/data.parquet` 等共享文件中，
改完代码后无法被新的查询函数读到。有两种处理方式：

**方式 A（推荐）：写迁移脚本**

新建 `scripts/migrate_sim_results.py`：

```python
"""
一次性迁移脚本：将旧格式（共享表）拆分为新格式（每账户独立文件）
运行一次即可，之后删除即可。
"""
import os
import pandas as pd
from xxydb import xxydb

DATA_PATH = "./data"
SIM_PATH  = os.path.join(DATA_PATH, "simulation_results")

db = xxydb(path=SIM_PATH)

for table, filename in [
    ("simulation_daily_values", "daily_values.parquet"),
    ("simulation_positions",    "positions.parquet"),
    ("simulation_orders",       "orders.parquet"),
]:
    try:
        df = db.query(f"SELECT * FROM {table}").df()
    except Exception:
        print(f"[跳过] 表 {table} 不存在")
        continue

    for account_id, group in df.groupby('account_id'):
        account_dir = os.path.join(SIM_PATH, "accounts", account_id)
        os.makedirs(account_dir, exist_ok=True)
        out_path = os.path.join(account_dir, filename)
        group.drop(columns=['account_id'], errors='ignore').assign(account_id=account_id).to_parquet(out_path, index=False)
        print(f"[迁移] {account_id}/{filename}  {len(group)} 行")

db.close()
print("迁移完成")
```

**方式 B（最简单）**：让所有账户重跑一次

如果账户数量少、回测区间短，直接跑 `run_all()` 即可，新文件自动生成。

---

## 改动文件汇总

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `xxybacktest/simulation/runner.py` | 核心修改 | `_save_results`、三个查询函数、`run_all` |
| `xxybacktest/simulation/db_utils.py` | 无需改动 | submitter.py 还在用 |
| `xxybacktest/web/routes/*.py` | 无需改动 | 调用的是 runner.py 的函数，接口不变 |
| `scripts/migrate_sim_results.py` | 新建（可选）| 一次性迁移旧数据 |

**web 层完全不受影响**：`account.py`、`api.py`、`dashboard.py` 都是调用
`get_account_nav` / `get_account_positions` / `get_account_orders`，
这三个函数的签名和返回值不变，只是内部改了读取方式。

---

## 执行顺序建议

1. 先做步骤一 + 步骤二（存储格式改造），用单账户测试 `run_single` 是否正常
2. 做步骤五（迁移旧数据，或重跑），确认 Web UI 数据正常显示
3. 再做步骤三（改 `run_all` 为并行），多账户测试并行执行
4. 最后做步骤四（清理 import）

---

## 风险点

1. **Windows spawn 模式**：`ProcessPoolExecutor` 在 Windows 下每次启动子进程都会重新 import 所有模块，
   比 Linux fork 慢，但功能正常。如果账户数很少（< 4），并行收益可能不明显。

2. **子进程中的 print 输出**：并行时各账户的日志会交错输出，视觉上比较乱。
   可以考虑之后用 logging 模块替代 print，每个账户写到独立日志文件。
   当前阶段不强制处理，功能优先。

3. **`run_single` 内的 import**：函数内有 `from .submitter import get_account`，
   这在子进程中会重新 import，需要确认 submitter.py 在子进程环境下可正常加载。
   通常没问题，因为没有全局副作用。
