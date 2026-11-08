"""間隔複習規則（對應「Neuron 間隔複習系統_需求規格」）。"""

import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .models import Note, ReviewLog

TPE = ZoneInfo("Asia/Taipei")

RATINGS = ("Easy", "Medium", "Hard")
RATING_LABELS = {"Easy": "簡單", "Medium": "普通", "Hard": "困難"}

# 基準間隔（Medium），第 n 次讀完後用第 n 個
BASE_INTERVALS = [1, 2, 4, 7, 15, 30]
MULTIPLIERS = {"Hard": 0.7, "Medium": 1.0, "Easy": 1.5}
MAX_CYCLE = len(BASE_INTERVALS)  # 超過 6 次就排程結束

GEMINI_CYCLE = 5  # cycle 達到這個值就列入 Gemini 待上傳


def today_tpe() -> date:
    """日界線 00:00，時區 Asia/Taipei。"""
    return datetime.now(TPE).date()


def interval_days(cycle_after: int, tag: str | None) -> int | None:
    """
    讀完後到下一次閱讀的天數。cycle_after 是加 1 之後的值。
    超過 MAX_CYCLE 回傳 None（排程結束）。
    """
    if cycle_after < 1 or cycle_after > MAX_CYCLE:
        return None
    base = BASE_INTERVALS[cycle_after - 1]
    raw = base * MULTIPLIERS.get(tag or "Medium", 1.0)
    # 四捨五入（不用 Python 的 round：它把 10.5 捨成 10）
    return max(1, math.floor(raw + 0.5))


def complete_review(note: Note, rating: str, today: date) -> ReviewLog:
    """完成一次閱讀：一次更新 tag、cycle、last_reviewed、next_review，並回傳紀錄。"""
    if rating not in RATINGS:
        raise ValueError(f"未知的評級：{rating}")

    log = ReviewLog(
        note=note,
        reviewed_on=today,
        rating=rating,
        prev_tag=note.tag,
        prev_cycle=note.cycle,
        prev_last_reviewed=note.last_reviewed,
        prev_next_review=note.next_review,
    )

    note.tag = rating
    note.cycle = (note.cycle or 0) + 1
    note.last_reviewed = today
    days = interval_days(note.cycle, rating)
    note.next_review = today + timedelta(days=days) if days is not None else None

    log.cycle_after = note.cycle
    return log


def undo_review(log: ReviewLog) -> None:
    """把筆記還原成這次完成之前的狀態。"""
    note = log.note
    note.tag = log.prev_tag
    note.cycle = log.prev_cycle
    note.last_reviewed = log.prev_last_reviewed
    note.next_review = log.prev_next_review
