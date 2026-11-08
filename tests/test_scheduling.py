from datetime import date

import pytest

from app.models import Note
from app.scheduling import complete_review, interval_days, undo_review

# 需求規格書的間隔表：cycle(讀完後) -> (Hard, Medium, Easy)
SPEC_TABLE = {
    1: (1, 1, 2),
    2: (1, 2, 3),
    3: (3, 4, 6),
    4: (5, 7, 11),
    5: (11, 15, 23),
    6: (21, 30, 45),
}


@pytest.mark.parametrize("cycle,expected", SPEC_TABLE.items())
def test_interval_table_matches_spec(cycle, expected):
    got = tuple(interval_days(cycle, t) for t in ("Hard", "Medium", "Easy"))
    assert got == expected


def test_schedule_ends_after_cycle_6():
    assert interval_days(7, "Medium") is None


def test_untagged_counts_as_medium():
    assert interval_days(4, None) == 7


def test_complete_review_updates_everything():
    note = Note(name="x", cycle=2, tag=None)
    today = date(2026, 10, 23)
    log = complete_review(note, "Easy", today)
    assert (note.tag, note.cycle, note.last_reviewed) == ("Easy", 3, today)
    assert note.next_review == date(2026, 10, 29)  # +6 天
    assert log.cycle_after == 3 and log.prev_cycle == 2


def test_seventh_review_clears_next_review():
    note = Note(name="x", cycle=6, tag="Medium", next_review=date(2026, 10, 23))
    complete_review(note, "Medium", date(2026, 10, 23))
    assert note.cycle == 7 and note.next_review is None


def test_undo_restores_previous_state():
    prev = date(2026, 10, 20)
    note = Note(name="x", cycle=1, tag="Hard", last_reviewed=date(2026, 10, 19), next_review=prev)
    log = complete_review(note, "Easy", date(2026, 10, 23))
    undo_review(log)
    assert (note.tag, note.cycle, note.next_review) == ("Hard", 1, prev)


def test_unknown_rating_rejected():
    with pytest.raises(ValueError):
        complete_review(Note(name="x", cycle=0), "Great", date(2026, 10, 23))
