"""Flask 任务管理路由"""
import os

from flask import Blueprint, jsonify, render_template

from xxybacktest.simulation.scheduler import get_all_jobs, get_task_history, remove_job, trigger_job
from xxybacktest.simulation.task_store import remove_task

tasks_bp = Blueprint("tasks", __name__)

BUILTIN_TASK_ID = "builtin_run_simulation"


def _data_path() -> str:
    return os.environ.get("XXY_DATA_PATH", "./data")


@tasks_bp.route("/tasks")
def tasks_page():
    return render_template("tasks.html")


@tasks_bp.route("/tasks/log/<task_id>")
def task_log_page(task_id):
    """日志详情页：左侧时间标签 + 右侧日志内容"""
    return render_template("log.html", task_id=task_id)


@tasks_bp.route("/tasks/api/list")
def tasks_api_list():
    jobs = get_all_jobs(_data_path())
    for job in jobs:
        job["is_builtin"] = job["task_id"] == BUILTIN_TASK_ID
    return jsonify(jobs)


@tasks_bp.route("/tasks/api/trigger/<task_id>", methods=["POST"])
def tasks_api_trigger(task_id):
    try:
        trigger_job(task_id, _data_path())
        return jsonify({"success": True, "message": "已触发"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@tasks_bp.route("/tasks/api/delete/<task_id>", methods=["POST"])
def tasks_api_delete(task_id):
    if task_id == BUILTIN_TASK_ID:
        return jsonify({"success": False, "error": "内置任务不能删除"}), 400

    # ── 实盘任务：live_{account_id} ──
    if task_id.startswith("live_"):
        try:
            remove_job(task_id)
            # 清理日志文件
            log_dir = os.path.join(_data_path(), "simulation_results", "task_logs")
            for ext in [".log", ".status"]:
                log_file = os.path.join(log_dir, f"{task_id}{ext}")
                if os.path.exists(log_file):
                    os.remove(log_file)
            history_dir = os.path.join(log_dir, "history", task_id)
            if os.path.exists(history_dir):
                import shutil
                shutil.rmtree(history_dir)
            return jsonify({"success": True, "message": "实盘任务已停止，对应账户未删除"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ── 用户脚本任务 ──
    try:
        ok = remove_task(task_id, _data_path())
        if ok:
            return jsonify({"success": True, "message": "已删除"})
        return jsonify({"success": False, "error": "任务不存在"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@tasks_bp.route("/tasks/api/log/<task_id>")
def tasks_api_log(task_id):
    log_dir = os.path.join(_data_path(), "simulation_results", "task_logs")
    log_path = os.path.join(log_dir, f"{task_id}.log")

    content = ""
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            content = "[读取日志失败]"

    # 同时读取状态文件
    status = {"status": "-", "executed_at": "-"}
    status_path = os.path.join(log_dir, f"{task_id}.status")
    if os.path.exists(status_path):
        try:
            import json
            with open(status_path, "r", encoding="utf-8") as f:
                status = json.load(f)
        except Exception:
            pass

    return jsonify({
        "task_id": task_id,
        "content": content,
        "status": status.get("status", "-"),
        "executed_at": status.get("executed_at", "-"),
    })


@tasks_bp.route("/tasks/api/history/<task_id>")
def tasks_api_history(task_id):
    """返回任务的历史运行记录列表。"""
    try:
        history = get_task_history(task_id, _data_path())
        return jsonify({"success": True, "history": history})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@tasks_bp.route("/tasks/api/reregister-all", methods=["POST"])
def tasks_api_reregister_all():
    """重新注册所有内置任务（改完代码后调用，无需重启服务）。"""
    try:
        from xxybacktest.simulation.main import _register_builtin_jobs, _register_live_jobs
        time_str = os.environ.get("XXY_TRIGGER_TIME", "22:00")
        _register_builtin_jobs(_data_path(), time_str)
        _register_live_jobs(_data_path())
        return jsonify({"success": True, "message": "所有内置任务已重新注册，新代码将生效"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
