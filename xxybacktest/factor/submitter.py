"""
================================================================================
submitter —— 因子的提交与元数据管理
================================================================================
因子的"账户管理": 提交(登记)、列出、查看、更新、删除。

设计选择: 因子定义直接存在每因子目录的 meta.json(与 store 一致), 不额外建 xxydb 表。
  - submit_factor: 生成 factor_id, 校验 SQL, 写 meta.json(status=registered, 未跑)
  - run_single(runner.py) 跑完后回填 metrics/序列, 并更新 meta 的 status/updated_at
  - list/get 扫目录读 meta, delete 删目录

meta.json 字段:
    factor_id, name, category, sql, description, direction(用户指定或None),
    periods, n_groups, ic_method, base_period, 过滤开关, winsorize, standardize,
    status(registered/ok/error), created_at, updated_at, last_error
================================================================================
"""
import os
import json
import uuid
from datetime import datetime

from . import store


def _generate_factor_id() -> str:
    """生成因子 ID: fac_YYYYMMDD_HHMMSS_XXXXXX"""
    now = datetime.now()
    return f"fac_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def _validate_sql(sql, data_path):
    """轻量校验因子 SQL: 能执行且返回 date/instrument/value 三列。"""
    from xxydb import xxydb
    db = xxydb(path=data_path)
    try:
        probe = f"SELECT * FROM ({sql}) _probe LIMIT 1"
        try:
            df = db.query(probe).df()
        except Exception as e:
            raise ValueError(f"因子 SQL 执行失败: {e}")
        missing = {"date", "instrument", "value"} - set(df.columns)
        if missing:
            raise ValueError(
                f"因子 SQL 必须返回 date/instrument/value 三列, 缺少: {missing}")
    finally:
        db.close()


def submit_factor(name, sql, category, data_path="./data",
                  periods=(1, 5, 10, 20), n_groups=10, ic_method="rank",
                  base_period=None, exclude_suspended=True, exclude_st=True,
                  exclude_limit=True, winsorize=True, standardize=True,
                  description=None, direction=None, run_now=False,
                  validate=True):
    """
    提交(登记)一个因子, 纳入每日监控看板。返回 factor_id。

    参数:
        name/sql/category: 必填。sql 须返回 date/instrument/value 三列。
        run_now:  提交后是否立即算一次(默认 False, 等 run_all 定时重跑)
        validate: 是否在提交前校验 SQL(默认 True)
        其余同 analyze_factor(计算参数存进 meta, run_single 时读取)

    返回:
        factor_id
    """
    if validate:
        _validate_sql(sql, data_path)

    factor_id = _generate_factor_id()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta = {
        "factor_id": factor_id,
        "name": name,
        "category": category,
        "sql": sql,
        "description": description,
        "direction": direction,
        "periods": list(periods),
        "n_groups": n_groups,
        "ic_method": ic_method,
        "base_period": base_period if base_period is not None else list(periods)[0],
        "exclude_suspended": exclude_suspended,
        "exclude_st": exclude_st,
        "exclude_limit": exclude_limit,
        "winsorize": winsorize,
        "standardize": standardize,
        "status": "registered",
        "created_at": now,
        "updated_at": now,
        "last_error": None,
    }
    # 写 meta.json(建目录)
    d = store.factor_dir(factor_id, data_path)
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    if run_now:
        from .runner import run_single
        run_single(factor_id, data_path=data_path)

    return factor_id


def list_factors(data_path="./data", status=None):
    """列出所有因子的 meta(可按 status 过滤)。返回 list[dict]。"""
    base = os.path.join(data_path, store.FACTOR_ROOT, "factors")
    if not os.path.exists(base):
        return []
    out = []
    for factor_id in sorted(os.listdir(base)):
        if not os.path.isdir(os.path.join(base, factor_id)):
            continue
        meta = store.load_meta(factor_id, data_path)
        if meta is None:
            continue
        if status is not None and meta.get("status") != status:
            continue
        out.append(meta)
    return out


def get_factor(factor_id, data_path="./data"):
    """读单个因子定义。不存在返回 None。"""
    return store.load_meta(factor_id, data_path)


def update_factor(factor_id, data_path="./data", **fields):
    """
    更新因子定义的部分字段(如改 name/category/sql/params)。
    改了 sql/计算参数后需重跑才生效。返回更新后的 meta, 不存在返回 None。
    """
    meta = store.load_meta(factor_id, data_path)
    if meta is None:
        return None
    allowed = {"name", "category", "sql", "description", "direction",
               "periods", "n_groups", "ic_method", "base_period",
               "exclude_suspended", "exclude_st", "exclude_limit",
               "winsorize", "standardize", "status", "last_error"}
    for k, v in fields.items():
        if k in allowed:
            meta[k] = v
    meta["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    d = store.factor_dir(factor_id, data_path)
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def delete_factor(factor_id, data_path="./data"):
    """删除因子(整个目录)。返回是否成功。"""
    return store.delete_factor_result(factor_id, data_path)
