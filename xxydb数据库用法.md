# xxydb

轻量 A 股数据库封装，基于 Parquet (Hive 分区) + DuckDB，提供简洁的写入/查询 API。

## 安装

```bash
pip install xxydb

# 如需 AI 自然语言查询功能
pip install xxydb[ai]
```

本地开发安装：

```bash
git clone https://github.com/xxydb/xxydb.git
cd xxydb
pip install -e ".[ai]"
```

## 快速开始

```python
import pandas as pd
from xxydb import xxydb

# 初始化（指定数据存储路径，AI 参数可选）
db = xxydb(path="./my_data")

# 写入数据（按年分区）
df = pd.DataFrame({
    "date": pd.date_range("2024-01-01", periods=100),
    "code": ["000001"] * 100,
    "close": range(100),
})
db.write_data(df, id="daily_bar", date_col="date", partitioning="年",
              unique_together=["date", "code"])

# SQL 查询
result = db.query("SELECT * FROM daily_bar WHERE close > 50").df()
print(result)

# 查看所有表
print(db.tables())

# 删除表
db.delete("daily_bar")

# 关闭连接
db.close()
```

### 上下文管理器

```python
with xxydb(path="./my_data") as db:
    db.write_data(df, id="daily_bar", date_col="date")
    result = db.query("SELECT * FROM daily_bar").df()
# 连接自动关闭
```

## 分区模式

| 参数值 | 目录结构 |
|--------|---------|
| `"年"` | `table/year=2024/data.parquet` |
| `"月"` | `table/year=2024/month=01/data.parquet` |
| `"日"` | `table/year=2024/month=01/day=15/data.parquet` |
| `None` | `table/data.parquet`（不分区） |

## Schema（字段描述）

xxydb 支持为每张表管理字段描述信息，方便记录各列的含义。

### 写入时指定 schema

```python
schema = {
    "date":  {"desc": "交易日期"},
    "code":  {"desc": "股票代码（6位）"},
    "close": {"desc": "日收盘价（元）"},
}
db.write_data(df, id="daily_bar", date_col="date", partitioning="年",
              unique_together=["date", "code"], schema=schema)
```

未提供 `schema` 时，会自动从 DataFrame 推断字段类型（`desc` 留空）。手动传入的 `schema` 会与自动推断结果合并，已有字段的描述会被更新，新字段会追加。

### 单独设置 schema

对已有表补充或修改字段描述，无需重新写入数据：

```python
db.set_schema("daily_bar", {
    "close": {"desc": "日收盘价（前复权，元）"},
})
```

### 查看表结构

`describe()` 返回一个 DataFrame，包含字段名、物理类型、说明、是否主键：

```python
print(db.describe("daily_bar"))
#     字段    物理类型          说明  是否主键
# 0   date  BYTE_ARRAY      交易日期      True
# 1   code  BYTE_ARRAY  股票代码（6位）     True
# 2  close      DOUBLE   日收盘价（元）    False
```

## AI 自然语言查询

安装 `xxydb[ai]` 后，可以用自然语言直接查询数据，AI 会根据表结构自动生成 SQL 并执行。

支持所有兼容 OpenAI 协议的模型服务商（OpenAI、Deepseek、通义千问、Moonshot、Ollama 等）。

### 基本用法

```python
db = xxydb(
    path="./my_data",
    api_key="sk-xxx",
    base_url="https://api.deepseek.com",
    model="deepseek-chat",
)

# 返回 DataFrame
df = db.ask("2024年收盘价最高的前10只股票")

# 只返回 SQL，不执行
sql = db.ask("2024年收盘价最高的前10只股票", return_df=False)
```

### 配置方式

AI 相关参数（`api_key`、`base_url`、`model`）支持两种配置方式：

**方式一：构造函数传参**

```python
db = xxydb("./my_data", api_key="sk-xxx", base_url="https://api.deepseek.com", model="deepseek-chat")
```

**方式二：环境变量**

```bash
export OPENAI_API_KEY=sk-xxx
export OPENAI_BASE_URL=https://api.deepseek.com
```

```python
db = xxydb("./my_data", model="deepseek-chat")
```

`ask()` 调用时也可以临时指定 `model` 覆盖默认值：

```python
df = db.ask("月均成交量排名", model="deepseek-reasoner")
```

### 提高准确率

AI 依赖表的 schema 信息来理解字段含义。字段描述越完善，生成的 SQL 越准确：

```python
db.set_schema("daily_bar", {
    "date":  {"desc": "交易日期"},
    "code":  {"desc": "股票代码（6位）"},
    "close": {"desc": "日收盘价（前复权，元）"},
    "vol":   {"desc": "成交量（手）"},
})

# schema 完善后，AI 能正确理解"成交量"指的是 vol 列
df = db.ask("最近一个月日均成交量最大的股票")
```

## API 参考

### `write_data(data, id, date_col="date", partitioning="年", unique_together=None, rewrite=True, schema=None)`

将 DataFrame 写入存储。

| 参数 | 说明 |
|------|------|
| `data` | 要写入的 DataFrame |
| `id` | 表名 |
| `date_col` | 日期列名，默认 `"date"` |
| `partitioning` | 分区粒度：`"年"` / `"月"` / `"日"` / `None` |
| `unique_together` | 主键列表，指定后自动去重；`None` 不去重 |
| `rewrite` | `True` 保留最新数据（覆盖），`False` 保留旧数据 |
| `schema` | 字段描述字典，如 `{"close": {"desc": "收盘价"}}` |

### `ask(question, *, return_df=True, model=None)`

用自然语言查询数据库（需安装 `xxydb[ai]`）。

| 参数 | 说明 |
|------|------|
| `question` | 自然语言问题 |
| `return_df` | `True` 返回 DataFrame，`False` 返回生成的 SQL 字符串 |
| `model` | 模型名称，不传则使用构造函数中指定的模型 |

### `query(sql)`

执行 SQL 查询，返回 DuckDB 结果对象（调用 `.df()` 转为 DataFrame）。

### `tables()`

返回所有已注册的表名列表。

### `describe(id)`

返回指定表的字段描述 DataFrame（字段、物理类型、说明、是否主键）。

### `set_schema(id, schema)`

为已有表设置或更新字段描述，无需重新写入数据。

### `delete(id)`

删除指定表（数据文件、DuckDB 视图、配置）。

### `close()`

关闭 DuckDB 连接。也可通过 `with` 语句自动管理。

## License

MIT
