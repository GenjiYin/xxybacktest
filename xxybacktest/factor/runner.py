"""
================================================================================
runner —— 因子分析调度(单因子 + 并行全量)
================================================================================
把各模块串起来:
    submitter(取因子定义 meta) → engine(SQL 下推计算) → store(落盘)

    run_single(factor_id): 跑一个因子的完整流程, 落盘并回填 meta 状态
    run_all():             对所有已登记因子并行重跑(前端"每日更新"的入口)

并行安全性: 每个 run_single 在子进程里自开 xxydb 连接(内存 DuckDB 无文件锁),
每个因子写自己的独立目录(store 覆盖写), 天然无竞争。照搬 simulation 的
ProcessPoolExecutor 模式。

Windows 注意: spawn 模式下, 调 run_all 的入口脚本须在 if __name__=='__main__' 保护下。
================================================================================
"""
import os
from concurrent.futures import ProcessPoolExecutor, as_completed

from . import store
from .engine import analyze_from_sql
from .result import FactorResult
from .submitter import list_factors, get_factor, update_factor


def run_single(factor_id, data_path="./data"):
    """
    跑一个因子的完整流程: 取定义 → SQL 下推计算 → 落盘 → 回填 meta 状态。

    返回 dict: {factor_id, status: 'success'/'error', reason?}
    与即时接口 analyze_factor 共享同一 engine(analyze_from_sql), 口径必然一致。
    """
    meta = get_factor(factor_id, data_path)
    if meta is None:
        return {"factor_id": factor_id, "status": "error", "reason": "因子不存在"}

    from xxydb import xxydb
    db = xxydb(path=data_path)
    try:
        output = analyze_from_sql(
            db, meta["sql"],
            periods=meta.get("periods", [1, 5, 10, 20]),
            n_groups=meta.get("n_groups", 10),
            ic_method=meta.get("ic_method", "rank"),
            base_period=meta.get("base_period"),
            exclude_suspended=meta.get("exclude_suspended", True),
            exclude_st=meta.get("exclude_st", True),
            exclude_limit=meta.get("exclude_limit", True),
            winsorize=meta.get("winsorize", True),
            standardize=meta.get("standardize", True),
            # 用户指定的 direction 传进引擎, 让多空/多头组一次算对(不再事后覆盖)
            direction=meta.get("direction"),
            # 定时任务落盘算因子有效时限(IC衰减曲线), 供详情页展示
            with_horizon=True,
        )
        res = FactorResult(output, name=meta.get("name"))

        # 落盘(结果 + 更新后的 meta)
        meta_out = dict(meta)
        meta_out["status"] = "ok"
        meta_out["last_error"] = None
        store.save_factor_result(factor_id, res.to_dict(), meta=meta_out,
                                 data_path=data_path)
        return {"factor_id": factor_id, "status": "success",
                "ic_mean": res.metrics.get("ic_mean"),
                "icir": res.metrics.get("icir")}
    except Exception as e:
        # 回填错误状态, 不删旧结果(保留上次成功的数据)
        update_factor(factor_id, data_path, status="error", last_error=str(e))
        return {"factor_id": factor_id, "status": "error", "reason": str(e)}
    finally:
        db.close()


def run_all(data_path="./data", max_workers=None):
    """
    对所有已登记因子并行重跑。前端"每日更新"的入口(定时任务调它)。

    参数:
        data_path:   数据根路径
        max_workers: 并行进程数, 默认 min(因子数, CPU核心数)

    返回:
        list[dict]: 每个因子的执行结果
    """
    factors = list_factors(data_path)
    if not factors:
        print("[提示] 没有已登记的因子")
        return []

    ids = [m["factor_id"] for m in factors]
    print(f"\n{'='*60}")
    print(f"[因子分析全量重跑] 共 {len(ids)} 个因子, 开始并行执行")
    print(f"{'='*60}")

    if max_workers is None:
        max_workers = min(len(ids), os.cpu_count() or 4)

    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        future_to_id = {
            pool.submit(run_single, fid, data_path): fid for fid in ids
        }
        for future in as_completed(future_to_id):
            fid = future_to_id[future]
            try:
                result = future.result()
            except Exception as e:
                print(f"[错误] {fid} 执行异常: {e}")
                result = {"factor_id": fid, "status": "error", "reason": str(e)}
            tag = "✓" if result["status"] == "success" else "✗"
            print(f"  [{tag}] {fid}  {result.get('reason', '')}")
            results.append(result)

    ok = sum(1 for r in results if r["status"] == "success")
    err = sum(1 for r in results if r["status"] == "error")
    print(f"\n{'='*60}")
    print(f"[全量重跑完成] 成功: {ok}, 失败: {err}")
    print(f"{'='*60}")
    return results
