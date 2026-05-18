"""
task_store.py 功能测试

覆盖：schedule_task、load_tasks、remove_task、参数校验。
"""
import os
import shutil
import tempfile

from xxybacktest.simulation.task_store import (
    schedule_task,
    load_tasks,
    remove_task,
    _time_to_cron,
    _validate_cron,
)


def _make_temp_script(suffix=".py"):
    """创建临时脚本文件并返回绝对路径"""
    fd, path = tempfile.mkstemp(suffix=suffix, text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("print('hello')\n")
    return path


def test_time_to_cron():
    assert _time_to_cron("17:30") == "30 17 * * *"
    assert _time_to_cron("22:00") == "0 22 * * *"
    assert _time_to_cron("9:05") == "5 9 * * *"


def test_time_to_cron_invalid():
    try:
        _time_to_cron("25:00")
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_validate_cron_ok():
    _validate_cron("30 17 * * *")
    _validate_cron("0 10 1 1,4,7,10 *")


def test_validate_cron_invalid():
    try:
        _validate_cron("* *")
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_schedule_and_load_by_time():
    script = _make_temp_script()
    data_dir = "./data"
    try:
        tid = schedule_task(
            name="数据更新",
            script=script,
            time="10:00",
            data_path=data_dir,
        )
        assert tid.startswith("task_")

        tasks = load_tasks(data_dir)
        assert any(t["task_id"] == tid for t in tasks)

        task = next(t for t in tasks if t["task_id"] == tid)
        assert task["name"] == "数据更新"
        assert task["cron"] == "0 10 * * *"
        assert task["script"] == os.path.abspath(script)
    finally:
        remove_task(tid, data_dir)
        os.remove(script)


def test_schedule_and_load_by_cron():
    script = _make_temp_script()
    data_dir = "./data"
    try:
        tid = schedule_task(
            name="季报数据",
            script=script,
            cron="0 10 1 1,4,7,10 *",
            data_path=data_dir,
        )
        tasks = load_tasks(data_dir)
        assert any(t["task_id"] == tid for t in tasks)

        task = next(t for t in tasks if t["task_id"] == tid)
        assert task["cron"] == "0 10 1 1,4,7,10 *"
    finally:
        remove_task(tid, data_dir)
        os.remove(script)


def test_remove_task():
    script = _make_temp_script()
    data_dir = "./data"
    try:
        tid = schedule_task(name="临时任务", script=script, time="12:00", data_path=data_dir)
        assert remove_task(tid, data_dir) is True

        tasks = load_tasks(data_dir)
        assert not any(t["task_id"] == tid for t in tasks)

        # 重复删除返回 False
        assert remove_task(tid, data_dir) is False
    finally:
        os.remove(script)


def test_schedule_missing_script():
    data_dir = "./data"
    try:
        schedule_task(name="错误", script="/不存在的脚本.py", time="10:00", data_path=data_dir)
        assert False, "应抛出 FileNotFoundError"
    except FileNotFoundError:
        pass


def test_schedule_no_time_or_cron():
    script = _make_temp_script()
    data_dir = "./data"
    try:
        schedule_task(name="错误", script=script, data_path=data_dir)
        assert False, "应抛出 ValueError"
    except ValueError:
        pass
    finally:
        os.remove(script)


def test_schedule_both_time_and_cron():
    script = _make_temp_script()
    data_dir = "./data"
    try:
        schedule_task(name="错误", script=script, time="10:00", cron="0 10 * * *", data_path=data_dir)
        assert False, "应抛出 ValueError"
    except ValueError:
        pass
    finally:
        os.remove(script)


if __name__ == "__main__":
    test_time_to_cron()
    test_time_to_cron_invalid()
    test_validate_cron_ok()
    test_validate_cron_invalid()
    test_schedule_and_load_by_time()
    test_schedule_and_load_by_cron()
    test_remove_task()
    test_schedule_missing_script()
    test_schedule_no_time_or_cron()
    test_schedule_both_time_and_cron()
    print("所有测试通过")
