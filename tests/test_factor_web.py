"""
阶段5 · Web 后端路由测试(Flask test client)

走完整 HTTP 流程: 提交 → 列表API → 重跑 → 详情API → 页面渲染 → 删除。
需真实 db(提交校验SQL + 重跑计算), 无则 skip。用完删除, 不污染真实目录。
"""
import os
import json
import pytest

DATA_PATH = os.environ.get("XXY_DATA_PATH", r"D:\Desktop\最新回测框架\data")
pytestmark = pytest.mark.skipif(not os.path.exists(DATA_PATH), reason="无真实数据库")


@pytest.fixture(scope="module")
def client():
    # 确保 web 层用的路径与测试一致
    os.environ["XXY_DATA_PATH"] = DATA_PATH
    from xxybacktest.web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_full_web_flow(client):
    # 1. 提交因子
    resp = client.post("/api/factors", json={
        "name": "web测试因子", "category": "反转",
        "sql": "SELECT date, instrument, close/pre_close-1 AS value "
               "FROM daily_bar WHERE date >= '2025-06-01'",
        "run_now": True,   # 提交即算
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    fid = resp.get_json()["factor_id"]

    try:
        # 2. 列表 API 应含该因子, 带绩效字段
        resp = client.get("/api/factors")
        assert resp.status_code == 200
        data = resp.get_json()
        row = next(x for x in data["factors"] if x["factor_id"] == fid)
        assert "ic_mean" in row and row["status"] == "ok"
        assert row["name"] == "web测试因子"

        # 3. 详情 API 结构完整
        resp = client.get(f"/api/factors/{fid}")
        assert resp.status_code == 200
        detail = resp.get_json()
        assert len(detail["ic_series"]) > 0
        assert len(detail["group_summary"]) > 0
        assert len(detail["yearly"]) > 0

        # 回归: 响应必须是合法 JSON, 不含 NaN(否则浏览器 JSON.parse 失败, 详情页卡"加载中")
        raw = resp.get_data(as_text=True)
        assert "NaN" not in raw, "响应含 NaN, 浏览器无法解析"
        import json
        json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(
            ValueError(f"非法JSON常量: {x}")))

        # 4. 列表页 + 详情页能渲染(占位模板也应 200)
        assert client.get("/factors").status_code == 200
        assert client.get(f"/factors/{fid}").status_code == 200

        # 5. 手动重跑单因子
        resp = client.post(f"/api/factors/{fid}/run")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    finally:
        # 6. 删除
        resp = client.delete(f"/api/factors/{fid}")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "deleted"

    # 删除后详情 404
    assert client.get(f"/api/factors/{fid}").status_code == 404
    assert client.get(f"/factors/{fid}").status_code == 404


def test_submit_missing_field(client):
    """缺 sql 应 400。"""
    resp = client.post("/api/factors", json={"name": "x", "category": "y"})
    assert resp.status_code == 400
    assert "缺少" in resp.get_json()["error"]


def test_submit_bad_sql(client):
    """SQL 不返回 value 列应 400。"""
    resp = client.post("/api/factors", json={
        "name": "bad", "category": "测试",
        "sql": "SELECT date, instrument FROM daily_bar WHERE date>='2025-06-01'",
    })
    assert resp.status_code == 400
    assert "value" in resp.get_json()["error"]


def test_detail_not_found(client):
    assert client.get("/api/factors/fac_不存在").status_code == 404


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
