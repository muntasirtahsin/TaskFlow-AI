"""Application service layer: wires repositories and engines, and exposes high-level operations.

The UI talks to this class only; it contains no Qt code so it can be tested headlessly.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from core.analytics import Analytics
from core.data_manager import DataManager
from core.inference_engine import KnowledgeBase
from core.notification_manager import NotificationManager
from core.priority_engine import PriorityEngine
from core.recommendation_engine import RecommendationEngine
from core.rescheduler import RescheduleReport, Rescheduler
from core.scheduler import ScheduleParams, Scheduler
from core.task_analyzer import TaskAnalyzer
from database.database import Database
from database.models import FocusSession, ScheduleEntry, Subtask, Task
from database.repositories import (FocusRepository, KBRepository, ProductivityRepository, ScheduleRepository,
                                   SettingsRepository, SubtaskRepository, TaskRepository)
from utils import constants as C
from utils.helpers import now as _now, setup_logging
from utils.validators import ValidationError, validate_settings, validate_time_range

log = logging.getLogger(__name__)


class AppContext:
    def __init__(self, data_dir: Optional[Path] = None, kb_dir: Optional[Path] = None,
                 defaults_dir: Optional[Path] = None):
        data_dir = Path(data_dir) if data_dir else C.DATA_DIR
        self.data_dir = data_dir
        setup_logging(data_dir / "logs")
        self.db = Database(data_dir / "taskflow.db")
        self.tasks = TaskRepository(self.db)
        self.subtasks = SubtaskRepository(self.db)
        self.schedule = ScheduleRepository(self.db)
        self.focus = FocusRepository(self.db)
        self.settings = SettingsRepository(self.db)
        self.productivity = ProductivityRepository(self.db)
        self.kb_repo = KBRepository(self.db)
        self.kb = KnowledgeBase(kb_dir or C.KB_DIR, defaults_dir or C.KB_DEFAULTS_DIR,
                                on_change=lambda name, rules: self.kb_repo.replace(name, rules))
        self.priority = PriorityEngine(self.kb)
        self.scheduler = Scheduler(self.priority, self.kb)
        self.rescheduler = Rescheduler(self.db, self.tasks, self.schedule, self.settings, self.scheduler, self.kb)
        self.analyzer = TaskAnalyzer(self.scheduler, self.kb, self.settings)
        self.analytics = Analytics(self.tasks, self.schedule, self.focus)
        self.recommender = RecommendationEngine(self.kb)
        self.notifier = NotificationManager(self.tasks, self.schedule, self.settings)
        self.data = DataManager(self.db, data_dir / "backups")
        self.ui_focus_task: Optional[int] = None      # hand-off between pages (task -> timer / planner)
        self.ui_planner_task: Optional[int] = None

    # ---- tasks ---------------------------------------------------------------------------
    def save_task(self, task: Task, subtasks: Optional[list[Subtask]] = None) -> Task:
        with self.db.transaction():
            if task.id is None:
                self.tasks.add(task)
            else:
                self.tasks.update(task)
            if subtasks is not None:
                self.subtasks.replace_for_task(task.id, subtasks)
            if not task.is_active:  # finished tasks leave the schedule
                self.schedule.delete_future_for_task(task.id, _now())
            self.record_productivity(_now().date())
        return task

    def delete_task(self, task_id: int) -> None:
        self.tasks.delete(task_id)

    def set_status(self, task_id: int, status: str) -> Task:
        task = self.tasks.get(task_id)
        if task is None:
            raise ValidationError("Task no longer exists.")
        task.status = status
        return self.save_task(task)

    def create_quick(self, title: str, **fields) -> Task:
        t = Task(title=title, estimated_minutes=int(self.settings.get("default_duration_minutes")), **fields)
        return self.save_task(t)

    # ---- schedule operations ---------------------------------------------------------------------
    def generate_plan(self, now: Optional[datetime] = None, reason: str = "Plan generated") -> RescheduleReport:
        return self.rescheduler.run(now, reason)

    def preview_replan(self, reason: str = "Manual replan") -> RescheduleReport:
        return self.rescheduler.analyze(reason=reason)

    def apply_report(self, report: RescheduleReport) -> RescheduleReport:
        return self.rescheduler.apply(report)

    def complete_block(self, entry_id: int) -> None:
        e = self.schedule.get(entry_id)
        if not e or e.kind != C.KIND_TASK:
            return
        with self.db.transaction():
            self.schedule.set_status(entry_id, C.ENTRY_DONE)
            if e.task_id:
                t = self.tasks.get(e.task_id)
                if t and t.is_active:
                    share = e.minutes / max(t.estimated_minutes, 1) * 100
                    t.completion = min(100, int(round(t.completion + share)))
                    later = [x for x in self.schedule.for_task(t.id)
                             if x.status == C.ENTRY_PLANNED and x.kind == C.KIND_TASK and x.id != entry_id]
                    if t.completion >= 100 and not later:
                        t.status = C.STATUS_COMPLETED
                    else:
                        t.completion = min(t.completion, 99)
                        t.status = C.STATUS_IN_PROGRESS
                    self.tasks.update(t)
            self.record_productivity(e.start.date())

    def skip_block(self, entry_id: int) -> None:
        self.schedule.set_status(entry_id, C.ENTRY_SKIPPED)

    def reopen_block(self, entry_id: int) -> None:
        self.schedule.set_status(entry_id, C.ENTRY_PLANNED)

    def toggle_lock(self, entry_id: int) -> None:
        e = self.schedule.get(entry_id)
        if e:
            e.locked = not e.locked
            self.schedule.update(e)

    def _check_overlap(self, start: datetime, end: datetime, ignore_id: Optional[int]) -> None:
        validate_time_range(start, end)
        clashes = [x for x in self.schedule.between(start, end)
                   if x.id != ignore_id and x.kind == C.KIND_TASK and x.status != C.ENTRY_SKIPPED]
        if clashes:
            names = ", ".join(self._entry_title(x) for x in clashes[:3])
            raise ValidationError(f"This time overlaps with: {names}.")

    def _entry_title(self, e: ScheduleEntry) -> str:
        t = self.tasks.get(e.task_id) if e.task_id else None
        return t.title if t else (e.label or "Block")

    def move_block(self, entry_id: int, start: datetime, end: datetime) -> ScheduleEntry:
        """Manual edit: validates overlap, removes auto breaks in the way, and locks the block."""
        e = self.schedule.get(entry_id)
        if not e:
            raise ValidationError("Block no longer exists.")
        self._check_overlap(start, end, entry_id)
        with self.db.transaction():
            for x in self.schedule.between(start, end):
                if x.kind == C.KIND_BREAK and x.id != entry_id:
                    self.schedule.delete(x.id)
            e.start, e.end, e.locked = start, end, True
            self.schedule.update(e)
        return e

    def add_manual_block(self, task_id: Optional[int], start: datetime, end: datetime, label: str = "") -> ScheduleEntry:
        if task_id is None and not label.strip():
            raise ValidationError("Choose a task or give the block a label.")
        self._check_overlap(start, end, None)
        with self.db.transaction():
            for x in self.schedule.between(start, end):
                if x.kind == C.KIND_BREAK:
                    self.schedule.delete(x.id)
            return self.schedule.add(ScheduleEntry(task_id=task_id, start=start, end=end, label=label.strip(), locked=True))

    def delete_block(self, entry_id: int) -> None:
        self.schedule.delete(entry_id)

    def mark_unavailable(self, day: date) -> RescheduleReport:
        days = set(self.settings.get("unavailable_dates") or [])
        days.add(day.isoformat())
        self.settings.set("unavailable_dates", sorted(days))
        return self.rescheduler.run(reason=f"Unavailable on {day:%a %d %b}")

    # ---- focus -----------------------------------------------------------------------------------
    def log_focus(self, task_id: Optional[int], started: datetime, ended: datetime, seconds: int,
                  mode: str, completed: bool = True) -> Optional[FocusSession]:
        if seconds < 5:
            return None  # ignore accidental clicks
        with self.db.transaction():
            s = self.focus.add(FocusSession(task_id=task_id, started_at=started, ended_at=ended,
                                            duration_seconds=int(seconds), mode=mode, completed=completed))
            if task_id:
                self.tasks.add_actual_seconds(task_id, int(seconds))
                t = self.tasks.get(task_id)
                if t and t.status == C.STATUS_PENDING:
                    t.status = C.STATUS_IN_PROGRESS
                    self.tasks.update(t)
            self.record_productivity(started.date())
        return s

    # ---- settings ----------------------------------------------------------------------------------
    def save_settings(self, values: dict) -> None:
        merged = {**self.settings.all(), **values}
        validate_settings(merged)
        self.settings.set_many(values)

    # ---- statistics --------------------------------------------------------------------------------
    def record_productivity(self, day: date) -> None:
        start = datetime.combine(day, datetime.min.time())
        entries = [e for e in self.schedule.for_day(day) if e.kind == C.KIND_TASK]
        planned = sum(e.minutes for e in entries if e.status != C.ENTRY_SKIPPED)
        done = sum(e.minutes for e in entries if e.status == C.ENTRY_DONE)
        completed = [t for t in self.tasks.all() if t.completed_at and t.completed_at.date() == day]
        self.productivity.upsert(
            day, tasks_completed=len(completed),
            tasks_on_time=sum(1 for t in completed if t.deadline is None or t.completed_at <= t.deadline),
            planned_minutes=planned, done_minutes=done, focus_seconds=self.focus.seconds_on_day(day),
            productivity_pct=round(100 * done / planned, 1) if planned else 0.0)

    def recommendation_facts(self, now: Optional[datetime] = None) -> dict:
        now = now or _now()
        facts = self.analytics.weekly_facts(now)
        analyses = self.analyzer.analyze(self.tasks.active(), now)
        facts["critical_count"] = sum(1 for a in analyses if a.priority.level == "Critical")
        params = ScheduleParams.from_settings(self.settings)
        today_min = sum(e.minutes for e in self.schedule.for_day(now.date()) if e.kind == C.KIND_TASK and e.status != C.ENTRY_SKIPPED)
        if today_min:
            facts["today_load_ratio"] = round(today_min / params.daily_limit_minutes, 2)
        horizon_end = now + timedelta(days=params.horizon_days)
        planned: dict[int, int] = {}
        for e in self.schedule.between(now, horizon_end):
            if e.kind == C.KIND_TASK and e.task_id and e.status == C.ENTRY_PLANNED:
                planned[e.task_id] = planned.get(e.task_id, 0) + e.minutes
        facts["unscheduled_count"] = sum(1 for a in analyses if planned.get(a.task.id, 0) < a.task.remaining_minutes * 0.9)
        return facts

    def recommendations(self, now: Optional[datetime] = None):
        return self.recommender.generate(self.recommendation_facts(now))

    def close(self) -> None:
        self.db.close()
