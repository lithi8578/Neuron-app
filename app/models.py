from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Note(Base):
    """一篇 MDNOTE 的複習狀態。筆記內容在 Obsidian，這裡只存狀態。"""

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)  # 與 Obsidian 檔名一致
    folder: Mapped[str] = mapped_column(String(200), default="")  # vault 內的資料夾，選填
    tag: Mapped[str | None] = mapped_column(String(10))  # Easy / Medium / Hard；空 = Medium
    cycle: Mapped[int] = mapped_column(Integer, default=0)
    last_reviewed: Mapped[date | None] = mapped_column(Date)
    next_review: Mapped[date | None] = mapped_column(Date, index=True)  # 空 = 排程結束
    uploaded: Mapped[bool] = mapped_column(Boolean, default=False)  # 已上傳 Gemini Notebook
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    reviews: Mapped[list["ReviewLog"]] = relationship(
        back_populates="note", cascade="all, delete-orphan"
    )


class ReviewLog(Base):
    """每次按完成留一筆紀錄；存了按之前的狀態，所以可以復原。"""

    __tablename__ = "review_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"), index=True)
    reviewed_on: Mapped[date] = mapped_column(Date)
    rating: Mapped[str] = mapped_column(String(10))
    cycle_after: Mapped[int] = mapped_column(Integer)

    prev_tag: Mapped[str | None] = mapped_column(String(10))
    prev_cycle: Mapped[int] = mapped_column(Integer)
    prev_last_reviewed: Mapped[date | None] = mapped_column(Date)
    prev_next_review: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    note: Mapped[Note] = relationship(back_populates="reviews")
