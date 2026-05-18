"""
live/utils.py — 实盘辅助工具

提供：
  - is_trading_day：查 trading_days 表判断是否为交易日
  - _load_schedule / _update_schedule：live_schedule.json 读写
  - _load_strategy_state / _save_strategy_state：策略状态持久化
"""

import json
import os
from datetime import date, datetime


# ---------------------------------------------------------------------------
# 交易日判断
# ---------------------------------------------------------------------------

def is_trading_day(date_str: str, data_path: str = "./data") -> bool:
    """
    判断指定日期是否为 A 股交易日。

    参数:
        date_str:  日期字符串，格式 'YYYY-MM-DD'
        data_path: 数据目录（含 xxydb 数据库）

    返回:
        True — 交易日；False — 非交易日（周末/节假日）
    """
    from xxydb import xxydb

    db = xxydb(path=data_path)
    try:
        df = db.query(f"""
            SELECT 1 FROM trading_days
            WHERE market_code = 'CN'
              AND date = '{date_str}'
        """).df()
        return not df.empty
    finally:
        db.close()


# ---------------------------------------------------------------------------
# live_schedule.json 读写
# ---------------------------------------------------------------------------

def _live_dir(data_path: str) -> str:
    """返回实盘根目录：data/live/"""
    return os.path.join(data_path, "live")


def _schedule_path(data_path: str) -> str:
    """返回 live_schedule.json 的完整路径：data/live/live_schedule.json"""
    return os.path.join(_live_dir(data_path), "live_schedule.json")


def _load_schedule(account_id: str, data_path: str) -> dict:
    """
    读取 live_schedule.json，返回指定账户的调度记录。

    若文件不存在或账户不在其中，返回空 dict。
    """
    path = _schedule_path(data_path)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get(account_id, {})


def _update_schedule(account_id: str, updates: dict, data_path: str) -> None:
    """
    更新 live_schedule.json 中指定账户的字段。

    updates 中的键值会合并（浅合并）到现有记录中。
    文件不存在时自动创建。
    """
    path = _schedule_path(data_path)
    os.makedirs(_live_dir(data_path), exist_ok=True)

    # 读取现有内容
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    # 合并更新
    if account_id not in data:
        data[account_id] = {}
    data[account_id].update(updates)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 策略状态持久化
# ---------------------------------------------------------------------------

def _load_strategy_state(account_id: str, data_path: str) -> dict:
    """
    从 live_schedule.json 读取上次持久化的策略状态。

    返回 dict（首次运行时返回空 dict）。
    """
    record = _load_schedule(account_id, data_path)
    return record.get("strategy_state", {})


def _save_strategy_state(account_id: str, state: dict, data_path: str) -> None:
    """
    将策略状态（context.g 的内容）序列化后写入 live_schedule.json。

    自动处理 numpy/pandas 等不可 JSON 序列化的类型：
      - np.ndarray        → list
      - np.integer        → int
      - np.floating       → float
      - np.bool_          → bool
      - datetime/date     → ISO 字符串
      - 其他不支持的类型  → str()
    """
    serialized = _serialize_state(state)
    _update_schedule(account_id, {"strategy_state": serialized}, data_path)


def _serialize_state(obj):
    """
    递归序列化对象，将不可 JSON 序列化的类型转换为基础类型。
    """
    # dict
    if isinstance(obj, dict):
        return {str(k): _serialize_state(v) for k, v in obj.items()}

    # list / tuple
    if isinstance(obj, (list, tuple)):
        return [_serialize_state(item) for item in obj]

    # 基础类型直接返回
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj

    # datetime / date
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()

    # numpy 类型（可选依赖，运行时检测）
    try:
        import numpy as np
        if isinstance(obj, np.ndarray):
            return _serialize_state(obj.tolist())
        if isinstance(obj, np.integer):
            return int(obj.item())
        if isinstance(obj, np.floating):
            return float(obj.item())
        if isinstance(obj, np.bool_):
            return bool(obj.item())
    except ImportError:
        pass

    # pandas Series / DataFrame（转为 dict/list）
    try:
        import pandas as pd
        if isinstance(obj, pd.Series):
            return _serialize_state(obj.to_dict())
        if isinstance(obj, pd.DataFrame):
            return _serialize_state(obj.to_dict(orient="list"))
    except ImportError:
        pass

    # 兜底：转字符串
    return str(obj)
