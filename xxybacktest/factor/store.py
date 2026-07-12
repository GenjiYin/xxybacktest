"""
================================================================================
store —— 因子分析结果的存储层(每因子独立目录, 覆盖写, 无竞争)
================================================================================
照搬 simulation 的"每账户独立目录"思路: 每个因子写自己的目录, 每天全量重跑
直接覆盖自己的文件, 不读其他因子数据, 天然无并发冲突, 可安全多进程并行。

目录结构:
    data/factor_analysis/factors/<factor_id>/
        meta.json          因子定义(name/sql/category/direction/params/updated_at...)
        metrics.json       全区间标量绩效(列表页读这个)
        ic_series.parquet  逐日 IC 时序(详情页累计IC曲线)
        yearly.parquet     年度拆解(详情页年度表)
        groups.parquet     逐调仓期逐组收益(详情页净值曲线)
        group_summary.parquet  各组年化/换手(详情页分组柱状)
        ls_series.parquet  多空逐期收益(详情页多空曲线)

读取函数供 web 层调用, 签名稳定。
================================================================================
"""
import os
import json
import pandas as pd

FACTOR_ROOT = "factor_analysis"  # data_path 下的因子分析根目录


# ==============================================================================
# 路径
# ==============================================================================
def factor_dir(factor_id, data_path="./data"):
    """某因子的独立目录(不存在则创建)。"""
    d = os.path.join(data_path, FACTOR_ROOT, "factors", factor_id)
    os.makedirs(d, exist_ok=True)
    return d


def _factors_base(data_path="./data"):
    return os.path.join(data_path, FACTOR_ROOT, "factors")


# ==============================================================================
# 保存(run_single 落盘时调用)
# ==============================================================================
def save_factor_result(factor_id, result_dict, meta=None, data_path="./data"):
    """
    把 FactorResult.to_dict() 的结果写入该因子独立目录。覆盖写。

    参数:
        factor_id:   因子 ID
        result_dict: FactorResult.to_dict() 的返回(含 metrics + 各序列)
        meta:        因子定义 dict(name/sql/category/...), 与结果一起存 meta.json;
                     None 则不动已有 meta.json
        data_path:   数据根路径
    """
    d = factor_dir(factor_id, data_path)

    # 1. metrics(小, JSON)
    with open(os.path.join(d, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(result_dict.get("metrics", {}), f, ensure_ascii=False, indent=2)

    # 2. 各序列(parquet)。用 records -> DataFrame 落盘
    for key, filename in [
        ("ic_series", "ic_series.parquet"),
        ("yearly", "yearly.parquet"),
        ("groups", "groups.parquet"),
        ("group_summary", "group_summary.parquet"),
        ("ls_series", "ls_series.parquet"),
        ("decay_curve", "decay_curve.parquet"),
    ]:
        records = result_dict.get(key, [])
        df = pd.DataFrame(records)
        df.to_parquet(os.path.join(d, filename), index=False)

    # 3. meta(可选)
    if meta is not None:
        meta = dict(meta)
        meta["updated_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)


# ==============================================================================
# 读取(web 层调用)
# ==============================================================================
def _read_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_parquet(path, cols=None):
    if not os.path.exists(path):
        return pd.DataFrame(columns=cols or [])
    return pd.read_parquet(path)


def _clean_nan(obj):
    """递归把 float NaN/Inf 替换为 None, 使输出为合法 JSON(浏览器 JSON.parse 不接受 NaN)。"""
    import math
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nan(v) for v in obj]
    return obj


def load_meta(factor_id, data_path="./data"):
    """读因子定义。不存在返回 None。"""
    path = os.path.join(_factors_base(data_path), factor_id, "meta.json")
    return _read_json(path, None)


def load_metrics(factor_id, data_path="./data"):
    """读全区间绩效指标。不存在返回 {}。"""
    path = os.path.join(_factors_base(data_path), factor_id, "metrics.json")
    return _read_json(path, {})


def load_ic_series(factor_id, data_path="./data"):
    return _read_parquet(os.path.join(_factors_base(data_path), factor_id,
                                      "ic_series.parquet"))


def load_yearly(factor_id, data_path="./data"):
    return _read_parquet(os.path.join(_factors_base(data_path), factor_id,
                                      "yearly.parquet"))


def load_groups(factor_id, data_path="./data"):
    return _read_parquet(os.path.join(_factors_base(data_path), factor_id,
                                      "groups.parquet"))


def load_group_summary(factor_id, data_path="./data"):
    return _read_parquet(os.path.join(_factors_base(data_path), factor_id,
                                      "group_summary.parquet"))


def load_ls_series(factor_id, data_path="./data"):
    return _read_parquet(os.path.join(_factors_base(data_path), factor_id,
                                      "ls_series.parquet"))


def load_detail(factor_id, data_path="./data"):
    """详情页一次性打包: meta + metrics + 各序列(records 形式, JSON 友好)。"""
    base = os.path.join(_factors_base(data_path), factor_id)
    if not os.path.exists(base):
        return None

    def _recs(fn):
        df = _read_parquet(os.path.join(base, fn))
        # 注意: df.where(notna, None) 在 float 列会把 None 又转回 NaN,
        # 必须在 to_dict 之后于原生 dict 层清洗, 否则输出非法 JSON(NaN)导致
        # 浏览器 JSON.parse 失败。
        return _clean_nan(df.to_dict("records"))

    return {
        "factor_id": factor_id,
        "meta": load_meta(factor_id, data_path),
        "metrics": _clean_nan(load_metrics(factor_id, data_path)),
        "ic_series": _recs("ic_series.parquet"),
        "yearly": _recs("yearly.parquet"),
        "groups": _recs("groups.parquet"),
        "group_summary": _recs("group_summary.parquet"),
        "ls_series": _recs("ls_series.parquet"),
        "decay_curve": _recs("decay_curve.parquet"),
    }


def list_factor_metrics(data_path="./data"):
    """
    扫所有因子目录, 拼成列表页大表。每行 = 一个因子的 meta + metrics 合并。
    返回 list[dict], 供列表页直接渲染 / 排序 / 筛选。
    """
    base = _factors_base(data_path)
    if not os.path.exists(base):
        return []
    rows = []
    for factor_id in sorted(os.listdir(base)):
        d = os.path.join(base, factor_id)
        if not os.path.isdir(d):
            continue
        meta = load_meta(factor_id, data_path) or {}
        metrics = load_metrics(factor_id, data_path) or {}
        row = {"factor_id": factor_id}
        # metrics 里的绩效字段先铺底(含自动判定的 direction)
        row.update(metrics)
        # meta 里的展示/状态字段覆盖在上(status、用户指定的 direction 等以 meta 为准)
        for k in ("name", "category", "direction", "description",
                  "status", "created_at", "updated_at"):
            if k in meta and meta[k] is not None:
                row[k] = meta[k]
        rows.append(row)
    return _clean_nan(rows)


def delete_factor_result(factor_id, data_path="./data"):
    """删除某因子的整个结果目录。返回是否删除成功。"""
    import shutil
    d = os.path.join(_factors_base(data_path), factor_id)
    if os.path.exists(d):
        shutil.rmtree(d)
        return True
    return False
