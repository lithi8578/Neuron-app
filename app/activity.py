"""閱讀熱度圖：像 GitHub 的每日 commit 圖，只是改成每天完成閱讀的篇數。"""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import ReviewLog

WEEKS = 53  # 跟 GitHub 一樣顯示約一年
MONTH_LABELS = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]


@dataclass
class Cell:
    day: date
    count: int
    level: int  # 0 = 沒讀，1–4 = 越多越深
    future: bool  # 今天之後的格子（本週還沒到的日子）


@dataclass
class Heatmap:
    weeks: list[list[Cell]]  # 每一欄是一週，週日在最上面
    month_labels: list[tuple[int, str]]  # (欄位索引, 月份文字)
    total: int  # 圖表範圍內的總篇數
    active_days: int
    today_count: int
    current_streak: int
    longest_streak: int
    max_count: int
    legend: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])


def level_for(count: int, max_count: int) -> int:
    """依當天篇數佔最多那天的比例分 4 級；有讀就至少 1 級。"""
    if count <= 0 or max_count <= 0:
        return 0
    return max(1, min(4, math.ceil(4 * count / max_count)))


def daily_counts(db: Session, since: date | None = None) -> dict[date, int]:
    """{日期: 當天完成篇數}。"""
    stmt = select(ReviewLog.reviewed_on, func.count()).group_by(ReviewLog.reviewed_on)
    if since:
        stmt = stmt.where(ReviewLog.reviewed_on >= since)
    return {d: n for d, n in db.execute(stmt)}


def streaks(active: set[date], today: date) -> tuple[int, int]:
    """
    回傳 (目前連續天數, 最長連續天數)。
    今天還沒讀不算中斷：從昨天往回算，跟 GitHub 一樣。
    """
    current = 0
    d = today if today in active else today - timedelta(days=1)
    while d in active:
        current += 1
        d -= timedelta(days=1)

    longest = run = 0
    prev = None
    for d in sorted(active):
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        longest = max(longest, run)
        prev = d
    return current, longest


def build_heatmap(db: Session, today: date, weeks: int = WEEKS) -> Heatmap:
    # 起點：往回 weeks-1 週的那個週日，這樣最後一欄剛好是本週
    days_since_sunday = (today.weekday() + 1) % 7  # Python 週一 = 0
    start = today - timedelta(days=days_since_sunday + 7 * (weeks - 1))

    counts = daily_counts(db, since=start)
    max_count = max(counts.values(), default=0)

    columns: list[list[Cell]] = []
    month_labels: list[tuple[int, str]] = []
    last_month = None
    for w in range(weeks):
        col = []
        for i in range(7):
            d = start + timedelta(days=7 * w + i)
            n = counts.get(d, 0)
            col.append(Cell(d, n, level_for(n, max_count), d > today))
        columns.append(col)
        # 該週第一天換了月份，就在這欄上方標月份
        if col[0].day.month != last_month:
            month_labels.append((w, MONTH_LABELS[col[0].day.month - 1]))
            last_month = col[0].day.month

    # 第一欄常是上個月的尾巴，標籤會跟下一個擠在一起，太近就省略（GitHub 也這樣）
    if len(month_labels) >= 2 and month_labels[1][0] - month_labels[0][0] < 3:
        month_labels.pop(0)

    # 連續天數要看全部歷史，不只圖表範圍
    all_active = set(daily_counts(db))
    current, longest = streaks(all_active, today)

    return Heatmap(
        weeks=columns,
        month_labels=month_labels,
        total=sum(counts.values()),
        active_days=sum(1 for n in counts.values() if n > 0),
        today_count=counts.get(today, 0),
        current_streak=current,
        longest_streak=longest,
        max_count=max_count,
    )
