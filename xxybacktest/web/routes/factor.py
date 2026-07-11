"""因子分析页面与 API 路由 - 连接真实数据

页面:
    GET /factors            列表页(所有因子绩效)
    GET /factors/<id>       详情页(年度IC/分组收益/曲线)
API(AJAX):
    GET  /api/factors       所有因子绩效 JSON(列表页数据)
    GET  /api/factors/<id>  单因子详情 JSON(年度/分组/曲线)
    POST /api/factors       提交新因子
    POST /api/factors/<id>/run    立即重跑单个因子
    POST /api/factors/run_all      全量重跑
    DELETE /api/factors/<id>       删除因子
"""
import os
from flask import Blueprint, render_template, jsonify, request, abort

from xxybacktest.factor import store
from xxybacktest.factor.submitter import (submit_factor, get_factor,
                                          delete_factor, list_factors)

factor_bp = Blueprint('factor', __name__)

DEFAULT_DATA_PATH = os.environ.get('XXY_DATA_PATH', './data')


# ==============================================================================
# 页面
# ==============================================================================
@factor_bp.route('/factors')
def factor_list():
    """因子列表页。"""
    return render_template('factor_list.html')


@factor_bp.route('/factors/<factor_id>')
def factor_detail(factor_id):
    """因子详情页。"""
    meta = get_factor(factor_id, data_path=DEFAULT_DATA_PATH)
    if meta is None:
        abort(404)
    return render_template('factor_detail.html', factor_id=factor_id,
                           factor_name=meta.get('name', factor_id))


# ==============================================================================
# API
# ==============================================================================
@factor_bp.route('/api/factors')
def api_factor_list():
    """所有因子绩效汇总(列表页表格数据)。"""
    rows = store.list_factor_metrics(data_path=DEFAULT_DATA_PATH)
    return jsonify({"factors": rows, "count": len(rows)})


@factor_bp.route('/api/factors/<factor_id>')
def api_factor_detail(factor_id):
    """单因子详情(年度/分组/曲线)。"""
    detail = store.load_detail(factor_id, data_path=DEFAULT_DATA_PATH)
    if detail is None:
        return jsonify({"error": "因子不存在"}), 404
    return jsonify(detail)


@factor_bp.route('/api/factors', methods=['POST'])
def api_submit_factor():
    """提交新因子。body: {name, sql, category, ...可选参数, run_now}"""
    data = request.get_json(force=True) or {}
    required = ("name", "sql", "category")
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"缺少必填字段: {missing}"}), 400
    try:
        fid = submit_factor(
            name=data["name"], sql=data["sql"], category=data["category"],
            data_path=DEFAULT_DATA_PATH,
            periods=data.get("periods", [1, 5, 10, 20]),
            n_groups=data.get("n_groups", 10),
            ic_method=data.get("ic_method", "rank"),
            base_period=data.get("base_period"),
            description=data.get("description"),
            direction=data.get("direction"),
            run_now=data.get("run_now", False),
        )
        return jsonify({"factor_id": fid, "status": "ok"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@factor_bp.route('/api/factors/<factor_id>/run', methods=['POST'])
def api_run_factor(factor_id):
    """立即重跑单个因子。"""
    from xxybacktest.factor.runner import run_single
    if get_factor(factor_id, DEFAULT_DATA_PATH) is None:
        return jsonify({"error": "因子不存在"}), 404
    result = run_single(factor_id, data_path=DEFAULT_DATA_PATH)
    code = 200 if result["status"] == "success" else 500
    return jsonify(result), code


@factor_bp.route('/api/factors/run_all', methods=['POST'])
def api_run_all():
    """全量重跑所有因子(串行, 避免 web 进程内 fork 子进程的复杂度)。"""
    from xxybacktest.factor.runner import run_single
    ids = [m["factor_id"] for m in list_factors(DEFAULT_DATA_PATH)]
    results = [run_single(fid, DEFAULT_DATA_PATH) for fid in ids]
    ok = sum(1 for r in results if r["status"] == "success")
    return jsonify({"total": len(results), "success": ok, "results": results})


@factor_bp.route('/api/factors/<factor_id>', methods=['DELETE'])
def api_delete_factor(factor_id):
    """删除因子。"""
    ok = delete_factor(factor_id, data_path=DEFAULT_DATA_PATH)
    if not ok:
        return jsonify({"error": "因子不存在"}), 404
    return jsonify({"status": "deleted", "factor_id": factor_id})
