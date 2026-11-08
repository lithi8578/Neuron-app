from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Note
from app.scheduling import today_tpe


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def logged_in(client):
    client.post("/auth/dev")
    return client


def note_by_name(name):
    with SessionLocal() as s:
        return s.query(Note).filter_by(name=name).one_or_none()


def test_requires_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_google_routes_off_without_credentials(client):
    assert client.get("/auth/google", follow_redirects=False).status_code == 404


def test_full_flow(logged_in):
    c = logged_in
    today = today_tpe()

    # 新增：首次閱讀日 = 今天 → 出現在 Today
    r = c.post("/notes/new", data={"name": "abandon 用法", "folder": "English/單字", "next_review": today.isoformat()})
    assert r.status_code == 200 and "已新增" in r.text and "今天沒有要讀的筆記" not in r.text
    assert "obsidian://open?vault=Obsidian-Master&amp;file=English/%E5%96%AE%E5%AD%97/abandon%20%E7%94%A8%E6%B3%95" in r.text

    # 名稱重複
    r = c.post("/notes/new", data={"name": "abandon 用法", "next_review": today.isoformat()})
    assert r.status_code == 400 and "已經有一篇" in r.text

    # 完成（困難）：cycle 1、明天再讀，離開 Today
    nid = note_by_name("abandon 用法").id
    r = c.post(f"/notes/{nid}/review", data={"rating": "Hard"})
    n = note_by_name("abandon 用法")
    assert (n.cycle, n.tag, n.next_review) == (1, "Hard", today + timedelta(days=1))
    assert "今天沒有要讀的筆記" in r.text and "復原" in r.text

    # 復原
    undo_id = int(r.text.split("/reviews/")[1].split("/undo")[0])
    c.post(f"/reviews/{undo_id}/undo")
    n = note_by_name("abandon 用法")
    assert (n.cycle, n.tag, n.next_review) == (0, None, today)

    # 編輯成 cycle 5 → 進 Gemini；標記已上傳後離開
    c.post(f"/notes/{nid}/edit", data={"name": "abandon 用法", "folder": "", "tag": "Easy", "cycle": "5",
                                       "last_reviewed": "", "next_review": (today - timedelta(days=2)).isoformat()})
    r = c.get("/")
    assert "原定" in r.text  # 延遲
    assert "已讀 5 次以上" in r.text
    c.post(f"/notes/{nid}/uploaded")
    assert note_by_name("abandon 用法").uploaded is True

    # 錯誤評級
    assert c.post(f"/notes/{nid}/review", data={"rating": "Great"}).status_code == 400

    # 刪除
    c.post(f"/notes/{nid}/delete")
    assert note_by_name("abandon 用法") is None


def test_logout(logged_in):
    logged_in.post("/logout")
    assert logged_in.get("/", follow_redirects=False).status_code == 303
