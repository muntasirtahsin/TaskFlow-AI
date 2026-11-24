"""Notification rules and delivery. The UI supplies `sink` (e.g. tray icon balloon / native toast)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

from database.repositories import ScheduleRepository, SettingsRepository, TaskRepository
from utils.constants import ENTRY_PLANNED, KIND_TASK
from utils.helpers import fmt_deadline, now as _now

log = logging.getLogger(__name__)

KIND_SETTING = {
    "upcoming": "notify_upcoming", "deadline": "notify_deadline", "overdue": "notify_overdue",
    "focus_done": "notify_focus_done", "break": "notify_break", "schedule_change": "notify_schedule_change",
}


@dataclass
class Notice:
    key: str
    kind: str
    title: str
    message: str


class NotificationManager:
    def __init__(self, tasks: TaskRepository, schedule: ScheduleRepository, settings: SettingsRepository):
        self.tasks, self.schedule, self.settings = tasks, schedule, settings
        self.sink: Optional[Callable[[str, str], None]] = None
        self.history: list[tuple[datetime, str, str, str]] = []
        self._sent: set[str] = set()

    def enabled(self, kind: str) -> bool:
        return bool(self.settings.get("notifications_enabled")) and bool(self.settings.get(KIND_SETTING.get(kind, "")))

    def emit(self, kind: str, title: str, message: str, key: Optional[str] = None) -> bool:
        """Deliver a notification if its type is enabled (and not already sent for `key`)."""
        if not self.enabled(kind):
            return False
        if key is not None:
            if key in self._sent:
                return False
            self._sent.add(key)
        self.history.append((_now(), kind, title, message))
        del self.history[:-100]
        log.info("Notification [%s] %s - %s", kind, title, message)
        if self.sink:
            try:
                self.sink(title, message)
            except Exception:  # never let a delivery problem crash the app
                log.exception("Notification sink failed")
        return True

    # ---- time based rules ----------------------------------------------------------------
    def due_notices(self, now: Optional[datetime] = None) -> list[Notice]:
        now = now or _now()
        notices: list[Notice] = []
        lead = int(self.settings.get("notify_upcoming_lead"))
        tasks = {t.id: t for t in self.tasks.all()}
        for e in self.schedule.between(now - timedelta(minutes=1), now + timedelta(minutes=lead + 1)):
            t = tasks.get(e.task_id)
            if e.kind == KIND_TASK and e.status == ENTRY_PLANNED and t and t.is_active and now <= e.start <= now + timedelta(minutes=lead):
                mins = max(0, int((e.start - now).total_seconds() // 60))
                notices.append(Notice(f"up:{e.id}:{e.start.isoformat()}", "upcoming", "Starting soon",
                                      f"'{t.title}' starts at {e.start:%H:%M}" + (f" (in {mins} min)." if mins else " (now).")))
        horizon = timedelta(hours=float(self.settings.get("notify_deadline_hours")))
        for t in tasks.values():
            if not t.is_active or not t.deadline:
                continue
            if now < t.deadline <= now + horizon:
                notices.append(Notice(f"dl:{t.id}:{t.deadline.isoformat()}", "deadline", "Deadline approaching",
                                      f"'{t.title}' is due {fmt_deadline(t.deadline, now)}."))
            elif t.deadline < now:
                notices.append(Notice(f"od:{t.id}:{now.date().isoformat()}", "overdue", "Task overdue",
                                      f"'{t.title}' was due {fmt_deadline(t.deadline, now)}."))
        return notices

    def check(self, now: Optional[datetime] = None) -> int:
        sent = 0
        for n in self.due_notices(now):
            if self.emit(n.kind, n.title, n.message, n.key):
                sent += 1
        return sent
