from datetime import date, timedelta

from app.activity import build_heatmap, level_for, streaks
from app.db import Base, SessionLocal, engine
from app.models import Note, ReviewLog

D = timedelta(days=1)
TODAY = date(2026, 11, 8)  # 週日


def test_levels():
    assert level_for(0, 10) == 0
    assert level_for(1, 10) == 1  # 有讀就至少 1 級
    assert level_for(5, 10) == 2
    assert level_for(10, 10) == 4
    assert level_for(3, 0) == 0


def test_streak_not_broken_if_today_not_read_yet():
    active = {TODAY - D, TODAY - 2 * D, TODAY - 3 * D}
    assert streaks(active, TODAY) == (3, 3)


def test_streak_counts_today_and_finds_longest():
    active = {TODAY, TODAY - D} | {TODAY - k * D for k in range(10, 15)}
    assert streaks(active, TODAY) == (2, 5)


def test_streak_broken():
    assert streaks({TODAY - 2 * D}, TODAY) == (0, 1)
    assert streaks(set(), TODAY) == (0, 0)


def _log(note, day):
    return ReviewLog(note=note, reviewed_on=day, rating="Medium", cycle_after=1, prev_cycle=0)


def test_build_heatmap_counts_and_shape():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.query(ReviewLog).delete()
        db.query(Note).delete()
        n = Note(name="hm-test", cycle=0)
        db.add_all([n, _log(n, TODAY), _log(n, TODAY), _log(n, TODAY - D), _log(n, date(2024, 1, 1))])
        db.commit()

        hm = build_heatmap(db, TODAY)

    assert len(hm.weeks) == 53 and all(len(w) == 7 for w in hm.weeks)
    assert hm.weeks[-1][0].day == TODAY  # 今天是週日 → 最後一欄的第一格
    assert all(c.future for c in hm.weeks[-1][1:])  # 週一到週六還沒到
    assert hm.weeks[0][0].day.weekday() == 6  # 每欄從週日開始
    assert hm.today_count == 2
    assert hm.total == 3  # 2024 年那筆不在一年範圍內
    assert hm.active_days == 2
    assert (hm.current_streak, hm.longest_streak) == (2, 2)
    assert hm.weeks[-1][0].level == 4 and hm.weeks[-2][6].level == 2
