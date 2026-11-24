"""Plain data classes used across the application."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from utils.constants import (ACTIVE_STATUSES, ENTRY_PLANNED, KIND_TASK, STATUS_IN_PROGRESS, STATUS_PENDING)
from utils.helpers import now


@dataclass
class Task:
    id: Optional[int] = None
    title: str = ""
    description: str = ""
    category: str = "Other"
    priority: int = 2          # 1 Low .. 4 Critical (user assigned)
    importance: int = 2        # 1 Low .. 3 High
    estimated_minutes: int = 60
    deadline: Optional[datetime] = None
    preferred_start: Optional[date] = None
    status: str = STATUS_PENDING
    completion: int = 0
    created_at: datetime = field(default_factory=now)
    completed_at: Optional[datetime] = None
    actual_seconds: int = 0

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def actual_minutes(self) -> float:
        return self.actual_seconds / 60.0

    @property
    def remaining_minutes(self) -> int:
        """Minutes of work still to schedule (0 for finished tasks)."""
        if not self.is_active or self.completion >= 100:
            return 0
        base = self.estimated_minutes * (1 - self.completion / 100.0)
        if self.status == STATUS_IN_PROGRESS and self.actual_minutes > self.estimated_minutes:
            base = max(base, self.estimated_minutes * 0.25)  # overrun: reserve extra time
        return max(15, int(round(base / 5.0)) * 5)


@dataclass
class Subtask:
    id: Optional[int] = None
    task_id: Optional[int] = None
    title: str = ""
    estimated_minutes: int = 30
    done: bool = False
    position: int = 0


@dataclass
class ScheduleEntry:
    id: Optional[int] = None
    task_id: Optional[int] = None
    start: datetime = field(default_factory=now)
    end: datetime = field(default_factory=now)
    kind: str = KIND_TASK
    status: str = ENTRY_PLANNED
    locked: bool = False      # True when the user customised this block
    label: str = ""           # used by custom blocks without a task
    note: str = ""

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)

    @property
    def day(self) -> date:
        return self.start.date()


@dataclass
class FocusSession:
    id: Optional[int] = None
    task_id: Optional[int] = None
    started_at: datetime = field(default_factory=now)
    ended_at: datetime = field(default_factory=now)
    duration_seconds: int = 0
    mode: str = "stopwatch"   # stopwatch | pomodoro
    completed: bool = True


@dataclass
class ScheduleChange:
    id: Optional[int] = None
    created_at: datetime = field(default_factory=now)
    reason: str = ""
    summary: str = ""
    details: str = ""
