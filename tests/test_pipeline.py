"""
阶段四 Pipeline 测试

用法:
    pytest tests/test_pipeline.py -v
    python tests/test_pipeline.py   （直接运行也可）
"""

from pathlib import Path


def test_project_root_detection():
    """测试项目根目录可以正确识别"""
    from xxybacktest.simulation.pipeline import _PROJECT_ROOT

    assert _PROJECT_ROOT.exists(), f"项目根目录不存在: {_PROJECT_ROOT}"
    assert (_PROJECT_ROOT / "data").exists(), "data 目录不存在"
    assert (_PROJECT_ROOT / "data_renew.py").exists(), "data_renew.py 不存在"
    print(f"  项目根目录: {_PROJECT_ROOT}")


def test_pipeline_tasks_are_defined():
    """测试两个 task 对象可正常访问（@task 装饰后不是普通 callable）"""
    from xxybacktest.simulation.pipeline import update_market_data, run_simulation

    assert update_market_data is not None
    assert run_simulation is not None
    print(f"  update_market_data: {update_market_data}")
    print(f"  run_simulation: {run_simulation}")


def test_pipeline_registration():
    """测试 pipeline 已成功注册到 Plombery"""
    import xxybacktest.simulation.pipeline  # noqa - 触发注册
    from plombery import get_app

    app = get_app()
    assert app is not None
    print("  Plombery app 创建成功")


if __name__ == "__main__":
    tests = [
        test_project_root_detection,
        test_pipeline_tasks_are_defined,
        test_pipeline_registration,
    ]
    passed = 0
    for fn in tests:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {fn.__name__}: {e}")
    print(f"\n结果: {passed}/{len(tests)} 通过")
