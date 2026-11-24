"""Productivity statistics computed from stored data."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Optional

from database.repositories import FocusRepository, ScheduleRepository, TaskRepository
from utils.constants import ENTRY_DONE, ENTRY_MISSED, KIND_TASK, STATUS_COMPLETED, STATUS_IN_PROGRESS, STATUS_PENDING, STATUS_CANCELLED
from utils.helpers import now as _now, week_start


class Analytics:
    def __init__(self, tasks: TaskRepository, schedule: ScheduleRepository, focus: FocusRepository):
        self.tasks, self.schedule, self.focus = tasks, schedule, focus

    # ---- headline numbers -------------------------------------------------------
    def overview(self, now: Optional[datetime] = None) -> dict:
        now = now or _now()
        tasks = self.tasks.all()
        completed = [t for t in tasks if t.status == STATUS_COMPLETED]
        active = [t for t in tasks if t.is_active]
        with_deadline = [t for t in completed if t.deadline and t.completed_at]
        on_time = [t for t in with_deadline if t.completed_at <= t.deadline]
        timed = [t for t in completed if t.actual_seconds > 0]
        return {
            "total": len(tasks),
            "completed": len(completed),
            "pending": sum(1 for t in tasks if t.status == STATUS_PENDING),
            "in_progress": sum(1 for t in tasks if t.status == STATUS_IN_PROGRESS),
            "cancelled": sum(1 for t in tasks if t.status == STATUS_CANCELLED),
            "overdue": sum(1 for t in active if t.deadline and t.deadline < now),
            "due_today": sum(1 for t in active if t.deadline and t.deadline.date() == now.date() and t.deadline >= now),
            "on_time": len(on_time),
            "late": len(with_deadline) - len(on_time),
            "focus_seconds": self.focus.total_seconds(),
            "avg_seconds_per_task": (sum(t.actual_seconds for t in timed) / len(timed)) if timed else 0,
        }

    def today(self, now: Optional[datetime] = None) -> dict:
        now = now or _now()
        entries = [e for e in self.schedule.for_day(now.date()) if e.kind == KIND_TASK]
        planned = sum(e.minutes for e in entries if e.status != "skipped")
        done = sum(e.minutes for e in entries if e.status == ENTRY_DONE)
        return {"planned_minutes": planned, "done_minutes": done,
                "productivity_pct": round(100 * done / planned) if planned else 0,
                "has_plan": planned > 0}

    # ---- time series ----------------------------------------------------------------
    def daily_completions(self, days: int = 14, end: Optional[date] = None) -> list[tuple[date, int]]:
        end = end or _now().date()
        counts = Counter(t.completed_at.date() for t in self.tasks.all() if t.completed_at)
        return [(end - timedelta(days=i), counts.get(end - timedelta(days=i), 0)) for i in range(days - 1, -1, -1)]

    def weekly_completions(self, weeks: int = 8, end: Optional[date] = None) -> list[tuple[date, int]]:
        end = end or _now().date()
        counts = Counter(week_start(t.completed_at.date()) for t in self.tasks.all() if t.completed_at)
        start = week_start(end)
        return [(start - timedelta(weeks=i), counts.get(start - timedelta(weeks=i), 0)) for i in range(weeks - 1, -1, -1)]

    def monthly_productivity(self, months: int = 6, end: Optional[date] = None) -> list[tuple[str, int, int, float]]:
        """(label, completed, completed_on_time, focus_hours) per month, oldest first."""
        end = end or _now().date()
        year, month = end.year, end.month
        keys = []
        for _ in range(months):
            keys.append((year, month))
            month -= 1
            if month == 0:
                year, month = year - 1, 12
        keys.reverse()
        done, ontime, focus = Counter(), Counter(), Counter()
        for t in self.tasks.all():
            if t.completed_at:
                k = (t.completed_at.year, t.completed_at.month)
                done[k] += 1
                if t.deadline is None or t.completed_at <= t.deadline:
                    ontime[k] += 1
        for s in self.focus.between(datetime(keys[0][0], keys[0][1], 1), datetime.combine(end + timedelta(days=1), datetime.min.time())):
            focus[(s.started_at.year, s.started_at.month)] += s.duration_seconds
        return [(date(y, m, 1).strftime("%b %y"), done[(y, m)], ontime[(y, m)], round(focus[(y, m)] / 3600, 1)) for y, m in keys]

    def daily_focus_hours(self, days: int = 14, end: Optional[date] = None) -> list[tuple[date, float]]:
        end = end or _now().date()
        start = end - timedelta(days=days - 1)
        sums = Counter()
        for s in self.focus.between(datetime.combine(start, datetime.min.time()), datetime.combine(end + timedelta(days=1), datetime.min.time())):
            sums[s.started_at.date()] += s.duration_seconds
        return [(start + timedelta(days=i), round(sums[start + timedelta(days=i)] / 3600, 2)) for i in range(days)]

    def estimated_vs_actual(self, limit: int = 8) -> list[tuple[str, float, float]]:
        rows = [t for t in self.tasks.all() if t.actual_seconds > 0 and t.status == STATUS_COMPLETED]
        rows.sort(key=lambda t: t.completed_at or datetime.min, reverse=True)
        return [(t.title, float(t.estimated_minutes), round(t.actual_minutes, 1)) for t in rows[:limit]][::-1]

    # ---- facts for the recommendation rules -------------------------------------------------
    def weekly_facts(self, now: Optional[datetime] = None) -> dict:
        now = now or _now()
        week_ago, month_ago = now - timedelta(days=7), now - timedelta(days=30)
        tasks = self.tasks.all()
        done_week = [t for t in tasks if t.completed_at and t.completed_at >= week_ago]
        due_window = [t for t in tasks if t.is_active and t.deadline and week_ago <= t.deadline <= now + timedelta(days=7)]
        done_month = [t for t in tasks if t.completed_at and t.completed_at >= month_ago]
        with_dl = [t for t in done_month if t.deadline]
        timed = [t for t in done_month if t.actual_seconds > 0 and t.estimated_minutes > 0]
        entries = self.schedule.between(week_ago, now)
        facts = {
            "tasks_completed_week": len(done_week),
            "missed_blocks_week": sum(1 for e in entries if e.kind == KIND_TASK and e.status == ENTRY_MISSED),
            "focus_hours_week": round(sum(s.duration_seconds for s in self.focus.between(week_ago, now)) / 3600, 1),
            "overdue_count": sum(1 for t in tasks if t.is_active and t.deadline and t.deadline < now),
            "due_today_count": sum(1 for t in tasks if t.is_active and t.deadline and t.deadline.date() == now.date() and t.deadline >= now),
            "active_count": sum(1 for t in tasks if t.is_active),
            "large_task_count": sum(1 for t in tasks if t.is_active and t.estimated_minutes > 180),
        }
        if done_week or due_window:
            facts["completion_rate_week"] = round(100 * len(done_week) / (len(done_week) + len(due_window)))
        if with_dl:
            facts["on_time_rate"] = round(100 * sum(1 for t in with_dl if t.completed_at <= t.deadline) / len(with_dl))
        if timed:
            facts["estimate_ratio"] = round(sum(t.actual_seconds / 60 for t in timed) / sum(t.estimated_minutes for t in timed), 2)
        facts["streak_days"] = self.streak(now.date())
        return facts

    def streak(self, today: date) -> int:
        active_days = {t.completed_at.date() for t in self.tasks.all() if t.completed_at}
        for s in self.focus.between(datetime.combine(today - timedelta(days=60), datetime.min.time()), datetime.combine(today + timedelta(days=1), datetime.min.time())):
            if s.duration_seconds >= 600:
                active_days.add(s.started_at.date())
        n, d = 0, today
        if d not in active_days:
            d -= timedelta(days=1)  # today is still in progress
        while d in active_days:
            n += 1
            d -= timedelta(days=1)
        return n
