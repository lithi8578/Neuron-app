"""網站進入點：路由都在這裡。啟動：uvicorn app.main:app --reload --env-file .env"""

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import auth
from .activity import build_heatmap
from .auth import LoginRequired, current_user
from .config import settings
from .db import Base, engine, get_db
from .models import Note, ReviewLog
from .scheduling import (
    GEMINI_CYCLE,
    MAX_CYCLE,
    RATING_LABELS,
    RATINGS,
    complete_review,
    today_tpe,
    undo_review,
)
from .templating import templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    # MVP：啟動時建立缺少的資料表。之後要改欄位時再導入 Alembic。
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="English Learning System", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",  # 擋掉其他網站送來的表單（CSRF）
    https_only=settings.on_cloud_run,
    max_age=60 * 60 * 24 * 30,  # 30 天內不用重新登入
)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(auth.router)


@app.exception_handler(LoginRequired)
def _redirect_to_login(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


# ──────────────────────────────────────────────────────────
# 小工具
# ──────────────────────────────────────────────────────────
def _parse_date(value: str) -> date | None:
    value = (value or "").strip()
    return date.fromisoformat(value) if value else None


def _clean_tag(value: str) -> str | None:
    value = (value or "").strip()
    if value and value not in RATINGS:
        raise HTTPException(400, "tag 只能是 Easy / Medium / Hard")
    return value or None


def _flash(request: Request, message: str, undo_id: int | None = None) -> None:
    request.session["flash"] = {"message": message, "undo_id": undo_id}


def _get_note(db: Session, note_id: int) -> Note:
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(404, "找不到這篇筆記")
    return note


def _folders(db: Session) -> list[str]:
    """已用過的資料夾，給表單做建議選項。"""
    rows = db.scalars(select(Note.folder).where(Note.folder != "").distinct())
    return sorted(rows)


def _back(request: Request, fallback: str = "/") -> RedirectResponse:
    return RedirectResponse(fallback, status_code=303)


# ──────────────────────────────────────────────────────────
# 主畫面
# ──────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def dashboard(request: Request, db: Session = Depends(get_db), user: str = Depends(current_user)):
    today = today_tpe()
    active = Note.cycle <= MAX_CYCLE

    today_notes = db.scalars(
        select(Note).where(Note.next_review == today, active).order_by(Note.name)
    ).all()
    delayed = db.scalars(
        select(Note).where(Note.next_review < today, active).order_by(Note.next_review, Note.name)
    ).all()
    gemini = db.scalars(
        select(Note).where(Note.cycle >= GEMINI_CYCLE, Note.uploaded.is_(False)).order_by(Note.name)
    ).all()
    history = db.scalars(
        select(Note).where(Note.cycle >= 1).order_by(Note.last_reviewed.desc(), Note.name)
    ).all()
    all_notes = db.scalars(select(Note).order_by(Note.name)).all()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "today": today,
            "today_notes": today_notes,
            "delayed": delayed,
            "gemini": gemini,
            "history": history,
            "all_notes": all_notes,
            "heatmap": build_heatmap(db, today),
            "flash": request.session.pop("flash", None),
        },
    )


# ──────────────────────────────────────────────────────────
# 完成閱讀 / 復原
# ──────────────────────────────────────────────────────────
@app.post("/notes/{note_id}/review")
def review(
    request: Request,
    note_id: int,
    rating: str = Form(...),
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    note = _get_note(db, note_id)
    if rating not in RATINGS:
        raise HTTPException(400, "未知的評級")
    log = complete_review(note, rating, today_tpe())
    db.add(log)
    db.commit()

    nxt = f"下次 {note.next_review.month}/{note.next_review.day}" if note.next_review else "排程結束"
    _flash(request, f"「{note.name}」完成（{RATING_LABELS[rating]}），{nxt}", undo_id=log.id)
    return _back(request)


@app.post("/reviews/{log_id}/undo")
def undo(request: Request, log_id: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    log = db.get(ReviewLog, log_id)
    if not log:
        raise HTTPException(404, "找不到這筆紀錄")
    latest = db.scalars(
        select(ReviewLog).where(ReviewLog.note_id == log.note_id).order_by(ReviewLog.id.desc())
    ).first()
    if latest.id != log.id:
        raise HTTPException(409, "只能復原這篇筆記最近一次的完成")
    undo_review(log)
    name = log.note.name
    db.delete(log)
    db.commit()
    _flash(request, f"已復原「{name}」")
    return _back(request)


@app.post("/notes/{note_id}/uploaded")
def toggle_uploaded(request: Request, note_id: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    note = _get_note(db, note_id)
    note.uploaded = not note.uploaded
    db.commit()
    _flash(request, f"「{note.name}」{'已標記上傳' if note.uploaded else '已取消上傳標記'}")
    return _back(request)


# ──────────────────────────────────────────────────────────
# 新增 / 編輯 / 刪除
# ──────────────────────────────────────────────────────────
def _form(request: Request, db: Session, note: Note | None, error: str = "", values: dict | None = None):
    return templates.TemplateResponse(
        request,
        "note_form.html",
        {
            "note": note,
            "values": values or {},
            "error": error,
            "folders": _folders(db),
            "today": today_tpe(),
        },
        status_code=400 if error else 200,
    )


@app.get("/notes/new")
def new_note(request: Request, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return _form(request, db, None)


@app.post("/notes/new")
def create_note(
    request: Request,
    name: str = Form(...),
    folder: str = Form(""),
    tag: str = Form(""),
    next_review: str = Form(...),
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    values = {"name": name, "folder": folder, "tag": tag, "next_review": next_review}
    name = name.strip()
    if not name:
        return _form(request, db, None, "名稱不能空白", values)
    note = Note(
        name=name,
        folder=folder.strip().strip("/"),
        tag=_clean_tag(tag),
        cycle=0,
        next_review=_parse_date(next_review),
    )
    db.add(note)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _form(request, db, None, f"已經有一篇叫「{name}」的筆記", values)
    _flash(request, f"已新增「{name}」")
    return _back(request)


@app.get("/notes/{note_id}/edit")
def edit_note(request: Request, note_id: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    return _form(request, db, _get_note(db, note_id))


@app.post("/notes/{note_id}/edit")
def update_note(
    request: Request,
    note_id: int,
    name: str = Form(...),
    folder: str = Form(""),
    tag: str = Form(""),
    cycle: int = Form(0),
    last_reviewed: str = Form(""),
    next_review: str = Form(""),
    uploaded: str = Form(""),
    db: Session = Depends(get_db),
    user: str = Depends(current_user),
):
    note = _get_note(db, note_id)
    name = name.strip()
    if not name:
        return _form(request, db, note, "名稱不能空白")
    note.name = name
    note.folder = folder.strip().strip("/")
    note.tag = _clean_tag(tag)
    note.cycle = max(0, cycle)
    note.last_reviewed = _parse_date(last_reviewed)
    note.next_review = _parse_date(next_review)
    note.uploaded = bool(uploaded)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _form(request, db, _get_note(db, note_id), f"已經有一篇叫「{name}」的筆記")
    _flash(request, f"已儲存「{name}」")
    return _back(request)


@app.post("/notes/{note_id}/delete")
def delete_note(request: Request, note_id: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    note = _get_note(db, note_id)
    name = note.name
    db.delete(note)
    db.commit()
    _flash(request, f"已刪除「{name}」")
    return _back(request)
