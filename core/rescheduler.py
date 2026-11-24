"""Autonomous rescheduling.

`detect_triggers` watches the data (missed blocks, overruns, new/changed tasks, unavailable days ...).
`analyze` builds a *proposal* (a RescheduleReport) without touching the database; `apply` commits it
inside one transaction and writes an explanation to the change log. Manually customised (locked)
blocks are never moved or deleted - conflicts with them are reported as warnings instead.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from core.scheduler import ScheduleParams, Scheduler
from database.database import Database
from database.models import ScheduleChange, ScheduleEntry, Task
from database.repositories import ScheduleRepository, SettingsRepository, TaskRepository
from utils.constants import ENTRY_DONE, ENTRY_MISSED, ENTRY_PLANNED, KIND_BREAK, KIND_TASK
from utils.helpers import fmt_date_short, now as _now, to_iso

log = logging.getLogger(__name__)

ACTIONABLE = {"missed", "overrun", "unscheduled", "changed", "unavailable", "stale"}


@dataclass
class Trigger:
    kind: str
    message: str
    task_id: Optional[int] = None


@dataclass
class Change:
    kind: str           # added | moved | removed | kept | missed | warning
    title: str
    detail: str

    def __str__(self) -> str:
        return f"{self.title}: {self.detail}"


@dataclass
class RescheduleReport:
    reason: str
    now: datetime
    triggers: list = field(default_factory=list)
    changes: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    new_entries: list = field(default_factory=list)
    remove_ids: list = field(default_factory=list)
    missed_ids: list = field(default_factory=list)
    signature: str = ""
    applied: bool = False

    @property
    def has_changes(self) -> bool:
        return bool([c for c in self.changes if c.kind != "kept"]) or bool(self.missed_ids)

    @property
    def is_major(self) -> bool:
        return len([c for c in self.changes if c.kind in ("moved", "removed")]) >= 4 or bool(self.warnings)

    @property
    def summary(self) -> str:
        counts: dict[str, int] = {}
        for c in self.changes:
            counts[c.kind] = counts.get(c.kind, 0) + 1
        parts = []
        for kind, label in (("added", "scheduled"), ("moved", "moved"), ("removed", "removed"), ("missed", "missed")):
            if counts.get(kind):
                parts.append(f"{counts[kind]} {label}")
        body = ", ".join(parts) if parts else "no changes needed"
        return f"{self.reason}: {body}."

    def text(self) -> str:
        lines = [self.summary, ""]
        if self.triggers:
            lines.append("Why the plan was recalculated:")
            lines += [f"  - {t.message}" for t in self.triggers]
            lines.append("")
        if self.changes:
            lines.append("What changed:")
            lines += [f"  - {c}" for c in self.changes if c.kind != "kept"]
            lines.append("")
        if self.notes:
            lines.append("Scheduling rules applied:")
            lines += [f"  - {n}" for n in self.notes]
            lines.append("")
        if self.warnings:
            lines.append("Warnings:")
            lines += [f"  - {w}" for w in self.warnings]
        return "\n".join(lines).strip()


def tasks_signature(tasks: list[Task]) -> str:
    """Hash of everything that should trigger a replan when edited (deadline, priority, size ...)."""
    rows = sorted((t.id, to_iso(t.deadline), t.priority, t.importance, t.status, t.estimated_minutes,
                   t.preferred_start.isoformat() if t.preferred_start else "") for t in tasks if t.is_active)
    return hashlib.sha1(json.dumps(rows).encode()).hexdigest()


class Rescheduler:
    def __init__(self, db: Database, tasks: TaskRepository, schedule: ScheduleRepository,
                 settings: SettingsRepository, scheduler: Scheduler, kb):
        self.db, self.tasks, self.schedule = db, tasks, schedule
        self.settings, self.scheduler, self.kb = settings, scheduler, kb

    # ---- parameters -----------------------------------------------------------
    def params(self, now: datetime, extra_missed: int = 0) -> ScheduleParams:
        p = ScheduleParams.from_settings(self.settings)
        missed = self.schedule.recent_missed_count(now - timedelta(days=7)) + extra_missed
        return p.apply_rules(self.kb, {"missed_blocks_recent": missed})

    # ---- trigger detection ------------------------------------------------------
    def detect_triggers(self, now: Optional[datetime] = None) -> list[Trigger]:
        now = now or _now()
        active = {t.id: t for t in self.tasks.active()}
        triggers: list[Trigger] = []
        entries = self.schedule.future_or_open(now - timedelta(days=1))
        params = ScheduleParams.from_settings(self.settings)

        for e in entries:
            if e.kind == KIND_TASK and e.status == ENTRY_PLANNED and e.end <= now and e.task_id in active:
                triggers.append(Trigger("missed", f"A scheduled block for '{active[e.task_id].title}' "
                                        f"({e.start:%a %H:%M}) was not completed.", e.task_id))
        for t in active.values():
            if t.actual_minutes > t.estimated_minutes and t.completion < 100:
                triggers.append(Trigger("overrun", f"'{t.title}' has taken {t.actual_minutes:.0f} min, longer than "
                                        f"the {t.estimated_minutes} min estimate.", t.id))
            if t.deadline and t.deadline < now:
                triggers.append(Trigger("overdue", f"'{t.title}' is overdue.", t.id))
        planned_future: dict[int, int] = {}
        for e in entries:
            if e.kind == KIND_TASK and e.status == ENTRY_PLANNED and e.end > now and e.task_id:
                planned_future[e.task_id] = planned_future.get(e.task_id, 0) + e.minutes
                if e.start.date() in params.unavailable and not e.locked:
                    triggers.append(Trigger("unavailable", f"You are unavailable on {fmt_date_short(e.start.date())} "
                                            "but work is planned that day.", e.task_id))
        for t in active.values():
            if planned_future.get(t.id, 0) + 1 < t.remaining_minutes * 0.5:
                triggers.append(Trigger("unscheduled", f"'{t.title}' has little or no time scheduled.", t.id))
        sig = self.settings.get("last_plan_signature")
        if sig and sig != tasks_signature(list(active.values())):
            triggers.append(Trigger("changed", "A task was added or its deadline, priority, importance or size changed."))
        # overload: more planned work on a day than the limit allows
        per_day: dict = {}
        for e in entries:
            if e.kind == KIND_TASK and e.status in (ENTRY_PLANNED, ENTRY_DONE) and e.end > now:
                per_day[e.start.date()] = per_day.get(e.start.date(), 0) + e.minutes
        for d, m in per_day.items():
            if m > params.daily_limit_minutes + 1 and any(not e.locked and e.start.date() == d for e in entries):
                triggers.append(Trigger("stale", f"{fmt_date_short(d)} is overloaded ({m / 60:.1f}h planned, "
                                        f"limit {params.daily_limit_minutes / 60:.1f}h)."))
        return triggers

    # ---- proposal ------------------------------------------------------------------
    def analyze(self, now: Optional[datetime] = None, reason: str = "Replan",
                triggers: Optional[list[Trigger]] = None) -> RescheduleReport:
        now = now or _now()
        triggers = triggers if triggers is not None else self.detect_triggers(now)
        report = RescheduleReport(reason=reason, now=now, triggers=[t for t in triggers if t.kind != "overdue"])
        tasks = {t.id: t for t in self.tasks.all()}
        active = [t for t in tasks.values() if t.is_active]
        entries = self.schedule.future_or_open(now - timedelta(days=1))
        title = lambda e: tasks[e.task_id].title if e.task_id in tasks else (e.label or "Block")

        # 1. blocks whose time passed without completion are marked missed
        missed = [e for e in entries if e.kind == KIND_TASK and e.status == ENTRY_PLANNED and e.end <= now]
        for e in missed:
            report.missed_ids.append(e.id)
            report.changes.append(Change("missed", title(e), f"block on {e.start:%a %d %b %H:%M} was not completed"))

        keep_locked = "keep_locked" in self.scheduler_flags(now)
        fixed: list[ScheduleEntry] = []
        old_blocks: dict[int, list[ScheduleEntry]] = {}
        for e in entries:
            if e.id in report.missed_ids or e.end <= now and e.status != ENTRY_DONE:
                continue
            if e.status == ENTRY_DONE:
                fixed.append(e)
                continue
            if e.status != ENTRY_PLANNED:
                continue
            task = tasks.get(e.task_id) if e.task_id else None
            finished_task = task is not None and not task.is_active
            if finished_task:  # finished/cancelled tasks leave the schedule
                report.remove_ids.append(e.id)
                if e.kind == KIND_TASK:
                    report.changes.append(Change("removed", title(e), f"{e.start:%a %d %b %H:%M} removed - task is {task.status.lower()}"))
                continue
            running = e.start <= now < e.end
            if e.kind == KIND_TASK and (e.locked and keep_locked or running):
                fixed.append(e)
                continue
            if e.kind == KIND_TASK and e.locked and not keep_locked:
                pass  # policy disabled: treated like any other block
            if e.kind == KIND_BREAK:
                report.remove_ids.append(e.id)  # breaks are regenerated
                continue
            report.remove_ids.append(e.id)
            old_blocks.setdefault(e.task_id, []).append(e)

        params = self.params(now, extra_missed=len(missed))
        report.notes = list(params.notes)
        plan = self.scheduler.plan(active, now, fixed, params)
        report.new_entries = plan.entries
        report.warnings += plan.warnings

        # locked blocks that conflict with availability
        for e in fixed:
            if e.locked and e.kind == KIND_TASK and (e.start.date() in params.unavailable or e.start.weekday() not in params.days):
                report.warnings.append(f"Your customised block '{title(e)}' on {fmt_date_short(e.start.date())} "
                                       "falls on a day you marked unavailable; it was left untouched.")

        # 2. explain differences per task
        new_by_task: dict[int, list[ScheduleEntry]] = {}
        for e in plan.entries:
            if e.kind == KIND_TASK:
                new_by_task.setdefault(e.task_id, []).append(e)
        missed_tasks = {e.task_id for e in missed}
        overrun = {t.id for t in active if t.actual_minutes > t.estimated_minutes}
        for tid in sorted(set(old_blocks) | set(new_by_task), key=lambda i: tasks[i].title if i in tasks else ""):
            task = tasks.get(tid)
            if not task:
                continue
            old = sorted((e.start, e.end) for e in old_blocks.get(tid, []))
            new = sorted((e.start, e.end) for e in new_by_task.get(tid, []))
            if old == new:
                continue
            why = "missed block" if tid in missed_tasks else "ran over its estimate" if tid in overrun else \
                "priorities or availability changed"
            res = plan.results.get(tid)
            lvl = f" [{res.level}]" if res else ""
            if not old:
                report.changes.append(Change("added", task.title + lvl, f"scheduled {_fmt_blocks(new)}"))
            elif not new:
                report.changes.append(Change("removed", task.title, f"removed from the plan ({_fmt_blocks(old)})"
                                             + (" - no free time left" if task.is_active else "")))
            else:
                report.changes.append(Change("moved", task.title + lvl,
                                             f"{_fmt_blocks(old)} -> {_fmt_blocks(new)} ({why})"))
        for tid, mins in plan.unscheduled.items():
            if tid in tasks:
                report.changes.append(Change("warning", tasks[tid].title, f"{mins} min could not be placed"))
        report.signature = tasks_signature(active)
        return report

    def scheduler_flags(self, now: datetime) -> set:
        return self.params(now).flags

    # ---- commit -------------------------------------------------------------------------
    def apply(self, report: RescheduleReport) -> RescheduleReport:
        with self.db.transaction():
            for eid in report.missed_ids:
                self.schedule.set_status(eid, ENTRY_MISSED)
            self.schedule.delete_many(report.remove_ids)
            self.schedule.add_many(report.new_entries)
            self.settings.set("last_plan_signature", report.signature)
            if report.has_changes or report.warnings:
                self.schedule.log_change(ScheduleChange(reason=report.reason, summary=report.summary,
                                                        details=report.text()))
        report.applied = True
        return report

    def run(self, now: Optional[datetime] = None, reason: str = "Replan") -> RescheduleReport:
        report = self.analyze(now, reason)
        return self.apply(report)

    def autopilot(self, now: Optional[datetime] = None) -> Optional[RescheduleReport]:
        """Check for actionable triggers and replan automatically when something really changes."""
        now = now or _now()
        triggers = self.detect_triggers(now)
        if not any(t.kind in ACTIONABLE for t in triggers):
            return None
        report = self.analyze(now, "Automatic replan", triggers)
        if not report.has_changes:
            # nothing to move, but remember the signature so we do not retrigger endlessly
            self.settings.set("last_plan_signature", report.signature)
            return None
        return self.apply(report)


def _fmt_blocks(blocks: list[tuple[datetime, datetime]]) -> str:
    shown = [f"{s:%a %d %b %H:%M}-{e:%H:%M}" for s, e in blocks[:3]]
    more = f" (+{len(blocks) - 3} more)" if len(blocks) > 3 else ""
    return ", ".join(shown) + more
