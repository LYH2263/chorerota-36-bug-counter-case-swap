"""反提案链路: 选反案 / 选原案 / 反案非法 / 未选案确认。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

# 生成后每格落位: 每天 T1→M1, T2→M2, T3→M3
ORIGINAL = {"a_day": 0, "a_task": 1, "b_day": 1, "b_task": 2}  # M1↔M2
COUNTER = {"a_day": 0, "a_task": 2, "b_day": 1, "b_task": 3}    # M2↔M3


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(app) as cl:
        cl.post("/api/weeks/1/generate", json={"days": 7})
        yield cl


def board_map(cl):
    b = cl.get("/api/weeks/1/board").json()
    return {(a["day"], a["task_id"]): a["member_id"] for a in b["assignments"]}


def request_swap(cl):
    r = cl.post("/api/weeks/1/swaps", json=ORIGINAL)
    assert r.status_code == 200
    return r.json()["id"]


def test_confirm_counter_applies_counter_tuple(client):
    sid = request_swap(client)
    r = client.post(f"/api/swaps/{sid}/counter", json=COUNTER)
    assert r.status_code == 200
    body = r.json()
    assert body["case"] == "counter"
    assert (body["a_member"], body["b_member"]) == (2, 3)  # 反案冻结成员

    r = client.post(f"/api/swaps/{sid}/confirm", json={"case": "counter"})
    assert r.status_code == 200
    body = r.json()  # 回包钉反案
    assert body["selected_case"] == "counter"
    assert (body["a_day"], body["a_task"], body["b_day"], body["b_task"]) == (0, 2, 1, 3)

    grid = board_map(client)  # 看板只反映反案交换: 票面对方成员落格
    assert grid[(0, 2)] == 3
    assert grid[(1, 3)] == 2
    assert grid[(0, 1)] == 1  # 原案两格不得被混用
    assert grid[(1, 2)] == 2

    d = client.get(f"/api/swaps/{sid}").json()  # 详情双案可查, 所选案同钉
    assert d["status"] == "confirmed"
    assert d["selected_case"] == "counter"
    assert (d["original"]["a_member"], d["original"]["b_member"]) == (1, 2)
    assert (d["counter"]["a_member"], d["counter"]["b_member"]) == (2, 3)


def test_confirm_original_applies_original_tuple(client):
    sid = request_swap(client)
    client.post(f"/api/swaps/{sid}/counter", json=COUNTER)

    r = client.post(f"/api/swaps/{sid}/confirm", json={"case": "original"})
    assert r.status_code == 200
    assert r.json()["selected_case"] == "original"

    grid = board_map(client)  # 看板只反映原案交换
    assert grid[(0, 1)] == 2
    assert grid[(1, 2)] == 1
    assert grid[(0, 2)] == 2  # 反案两格不得被混用
    assert grid[(1, 3)] == 3

    d = client.get(f"/api/swaps/{sid}").json()
    assert d["status"] == "confirmed"
    assert d["selected_case"] == "original"
    assert d["counter"] is not None  # 反案保留可查


def test_illegal_counter_keeps_original_pending(client):
    sid = request_swap(client)
    before = client.get(f"/api/swaps/{sid}").json()

    r = client.post(f"/api/swaps/{sid}/counter",
                    json={"a_day": 0, "a_task": 1, "b_day": 1, "b_task": 1})  # 同一人 M1
    assert r.status_code == 400

    r = client.post(f"/api/swaps/{sid}/counter", json=ORIGINAL)  # 与原案同四元组
    assert r.status_code == 400

    after = client.get(f"/api/swaps/{sid}").json()
    assert after["status"] == "pending"
    assert after["counter"] is None  # 非法反案不写入, 原案原样保留
    assert after["original"] == before["original"]

    # 原案仍可确认且按原案落格
    r = client.post(f"/api/swaps/{sid}/confirm", json={"case": "original"})
    assert r.status_code == 200
    grid = board_map(client)
    assert grid[(0, 1)] == 2 and grid[(1, 2)] == 1


def test_confirm_without_case_fails_grid_untouched(client):
    sid = request_swap(client)
    before = board_map(client)

    r = client.post(f"/api/swaps/{sid}/confirm", json={})
    assert r.status_code == 400
    assert r.json()["detail"] == "case_required"

    assert board_map(client) == before  # 格表不变
    assert client.get(f"/api/swaps/{sid}").json()["status"] == "pending"


def test_confirm_counter_without_counter_fails(client):
    sid = request_swap(client)
    r = client.post(f"/api/swaps/{sid}/confirm", json={"case": "counter"})
    assert r.status_code == 400
    assert r.json()["detail"] == "no_counter"
    assert client.get(f"/api/swaps/{sid}").json()["status"] == "pending"
