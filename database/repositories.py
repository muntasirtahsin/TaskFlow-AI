"""Repositories: all SQL lives here. Each returns model objects."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from database.database import Database
from database.models import FocusSession, ScheduleChange, ScheduleEntry, Subtask, Task
from utils.constants import (DEFAULT_SETTINGS, ENTRY_PLANNED, STATUS_COMPLETED, STATUS_IN_PROGRESS)
from utils.helpers import now, parse_date, parse_dt, to_iso
from utils.validators import ValidationError, validate_task, validate_time_range


# ---------------------------------------------------------------------------
class TaskRepository:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _row(r) -> Task:
        return Task(
            id=r["id"], title=r["title"], description=r["description"], category=r["category"],
            priority=r["priority"], importance=r["importance"], estimated_minutes=r["estimated_minutes"],
            deadline=parse_dt(r["deadline"]), preferred_start=parse_date(r["preferred_start"]),
            status=r["status"], completion=r["completion"], created_at=parse_dt(r["created_at"]),
            completed_at=parse_dt(r["completed_at"]), actual_seconds=r["actual_seconds"],
        )

    @staticmethod
    def _normalise(task: Task) -> None:
        """Keep status, completion and completed_at consistent."""
        task.title = task.title.strip()
        if task.status == STATUS_COMPLETED:
            task.completion = 100
            task.completed_at = task.completed_at or now()
        else:
            task.completed_at = None
            if task.completion >= 100:
                task.completion = 99 if task.status != STATUS_COMPLETED else 100
            if task.status == "Pending" and task.completion > 0:
                task.status = STATUS_IN_PROGRESS

    def add(self, task: Task) -> Task:
        validate_task(task)
        self._normalise(task)
        cur = self.db.execute(
            """INSERT INTO tasks (title, description, category, priority, importance, estimated_minutes,
               deadline, preferred_start, status, completion, created_at, completed_at, actual_seconds)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task.title, task.description, task.category, task.priority, task.importance,
             task.estimated_minutes, to_iso(task.deadline),
             task.preferred_start.isoformat() if task.preferred_start else None, task.status,
             task.completion, to_iso(task.created_at), to_iso(task.completed_at), task.actual_seconds))
        task.id = cur.lastrowid
        return task

    def update(self, task: Task) -> Task:
        if task.id is None:
            raise ValidationError("Cannot update a task without an id.")
        validate_task(task)
        self._normalise(task)
        self.db.execute(
            """UPDATE tasks SET title=?, description=?, category=?, priority=?, importance=?,
               estimated_minutes=?, deadline=?, preferred_start=?, status=?, completion=?,
               completed_at=?, actual_seconds=? WHERE id=?""",
            (task.title, task.description, task.category, task.priority, task.importance,
             task.estimated_minutes, to_iso(task.deadline),
             task.preferred_start.isoformat() if task.preferred_start else None, task.status,
             task.completion, to_iso(task.completed_at), task.actual_seconds, task.id))
        return task

    def delete(self, task_id: int) -> None:
        self.db.execute("DELETE FROM tasks WHERE id=?", (task_id,))

    def get(self, task_id: int) -> Optional[Task]:
        rows = self.db.query("SELECT * FROM tasks WHERE id=?", (task_id,))
        return self._row(rows[0]) if rows else None

    def all(self) -> list[Task]:
        return [self._row(r) for r in self.db.query("SELECT * FROM tasks ORDER BY id")]

    def active(self) -> list[Task]:
        return [self._row(r) for r in self.db.query(
            "SELECT * FROM tasks WHERE status IN ('Pending','In Progress') ORDER BY id")]

    def search(self, text: str = "", status: str = "", category: str = "") -> list[Task]:
        sql, params = "SELECT * FROM tasks WHERE 1=1", []
        if text:
            sql += " AND (title LIKE ? OR description LIKE ?)"
            params += [f"%{text}%", f"%{text}%"]
        if status:
            sql += " AND status=?"
            params.append(status)
        if category:
            sql += " AND category=?"
            params.append(category)
        return [self._row(r) for r in self.db.query(sql + " ORDER BY id", params)]

    def add_actual_seconds(self, task_id: int, seconds: int) -> None:
        self.db.execute("UPDATE tasks SET actual_seconds = actual_seconds + ? WHERE id=?", (seconds, task_id))

    def count_by_status(self) -> dict[str, int]:
        return {r["status"]: r["n"] for r in self.db.query("SELECT status, COUNT(*) n FROM tasks GROUP BY status")}


# ---------------------------------------------------------------------------
class SubtaskRepository:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _row(r) -> Subtask:
        return Subtask(id=r["id"], task_id=r["task_id"], title=r["title"],
                       estimated_minutes=r["estimated_minutes"], done=bool(r["done"]), position=r["position"])

    def for_task(self, task_id: int) -> list[Subtask]:
        return [self._row(r) for r in self.db.query(
            "SELECT * FROM subtasks WHERE task_id=? ORDER BY position, id", (task_id,))]

    def add(self, sub: Subtask) -> Subtask:
        if not sub.title.strip():
            raise ValidationError("Subtask title is required.")
        cur = self.db.execute(
            "INSERT INTO subtasks (task_id, title, estimated_minutes, done, position) VALUES (?,?,?,?,?)",
            (sub.task_id, sub.title.strip(), max(5, int(sub.estimated_minutes)), int(sub.done), sub.position))
        sub.id = cur.lastrowid
        return sub

    def set_done(self, sub_id: int, done: bool) -> None:
        self.db.execute("UPDATE subtasks SET done=? WHERE id=?", (int(done), sub_id))

    def delete(self, sub_id: int) -> None:
        self.db.execute("DELETE FROM subtasks WHERE id=?", (sub_id,))

    def replace_for_task(self, task_id: int, subs: Iterable[Subtask]) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM subtasks WHERE task_id=?", (task_id,))
            for i, s in enumerate(subs):
                s.task_id, s.position = task_id, i
                self.add(s)

    def progress(self, task_id: int) -> tuple[int, int]:
        r = self.db.query("SELECT COUNT(*) n, COALESCE(SUM(done),0) d FROM subtasks WHERE task_id=?", (task_id,))[0]
        return int(r["d"]), int(r["n"])


# ---------------------------------------------------------------------------
class ScheduleRepository:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _row(r) -> ScheduleEntry:
        return ScheduleEntry(id=r["id"], task_id=r["task_id"], start=parse_dt(r["start_at"]),
                             end=parse_dt(r["end_at"]), kind=r["kind"], status=r["status"],
                             locked=bool(r["locked"]), label=r["label"], note=r["note"])

    def add(self, e: ScheduleEntry) -> ScheduleEntry:
        validate_time_range(e.start, e.end)
        cur = self.db.execute(
            """INSERT INTO schedule_entries (task_id, label, start_at, end_at, kind, status, locked, note, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (e.task_id, e.label, to_iso(e.start), to_iso(e.end), e.kind, e.status, int(e.locked), e.note, to_iso(now())))
        e.id = cur.lastrowid
        return e

    def add_many(self, entries: Iterable[ScheduleEntry]) -> None:
        with self.db.transaction():
            for e in entries:
                self.add(e)

    def update(self, e: ScheduleEntry) -> None:
        validate_time_range(e.start, e.end)
        self.db.execute(
            "UPDATE schedule_entries SET task_id=?, label=?, start_at=?, end_at=?, kind=?, status=?, locked=?, note=? WHERE id=?",
            (e.task_id, e.label, to_iso(e.start), to_iso(e.end), e.kind, e.status, int(e.locked), e.note, e.id))

    def get(self, entry_id: int) -> Optional[ScheduleEntry]:
        rows = self.db.query("SELECT * FROM schedule_entries WHERE id=?", (entry_id,))
        return self._row(rows[0]) if rows else None

    def delete(self, entry_id: int) -> None:
        self.db.execute("DELETE FROM schedule_entries WHERE id=?", (entry_id,))

    def delete_many(self, ids: Iterable[int]) -> None:
        with self.db.transaction():
            for i in ids:
                self.delete(i)

    def set_status(self, entry_id: int, status: str) -> None:
        self.db.execute("UPDATE schedule_entries SET status=? WHERE id=?", (status, entry_id))

    def between(self, start: datetime, end: datetime) -> list[ScheduleEntry]:
        """Entries overlapping [start, end)."""
        return [self._row(r) for r in self.db.query(
            "SELECT * FROM schedule_entries WHERE end_at > ? AND start_at < ? ORDER BY start_at",
            (to_iso(start), to_iso(end)))]

    def for_day(self, day: date) -> list[ScheduleEntry]:
        start = datetime.combine(day, datetime.min.time())
        return self.between(start, start + timedelta(days=1))

    def for_task(self, task_id: int) -> list[ScheduleEntry]:
        return [self._row(r) for r in self.db.query(
            "SELECT * FROM schedule_entries WHERE task_id=? ORDER BY start_at", (task_id,))]

    def all(self) -> list[ScheduleEntry]:
        return [self._row(r) for r in self.db.query("SELECT * FROM schedule_entries ORDER BY start_at")]

    def future_or_open(self, since: datetime) -> list[ScheduleEntry]:
        """Everything ending after `since` plus planned-but-unfinished past blocks."""
        return [self._row(r) for r in self.db.query(
            "SELECT * FROM schedule_entries WHERE end_at > ? OR status='planned' ORDER BY start_at", (to_iso(since),))]

    def recent_missed_count(self, since: datetime) -> int:
        return self.db.query(
            "SELECT COUNT(*) n FROM schedule_entries WHERE status='missed' AND kind='task' AND start_at >= ?",
            (to_iso(since),))[0]["n"]

    def delete_future_for_task(self, task_id: int, since: datetime) -> int:
        cur = self.db.execute(
            "DELETE FROM schedule_entries WHERE task_id=? AND status='planned' AND end_at > ?",
            (task_id, to_iso(since)))
        return cur.rowcount

    # ---- change log ----
    def log_change(self, change: ScheduleChange) -> None:
        self.db.execute("INSERT INTO schedule_changes (created_at, reason, summary, details) VALUES (?,?,?,?)",
                        (to_iso(change.created_at), change.reason, change.summary, change.details))

    def recent_changes(self, limit: int = 20) -> list[ScheduleChange]:
        return [ScheduleChange(id=r["id"], created_at=parse_dt(r["created_at"]), reason=r["reason"],
                               summary=r["summary"], details=r["details"])
                for r in self.db.query("SELECT * FROM schedule_changes ORDER BY id DESC LIMIT ?", (limit,))]


# ---------------------------------------------------------------------------
class FocusRepository:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _row(r) -> FocusSession:
        return FocusSession(id=r["id"], task_id=r["task_id"], started_at=parse_dt(r["started_at"]),
                            ended_at=parse_dt(r["ended_at"]), duration_seconds=r["duration_seconds"],
                            mode=r["mode"], completed=bool(r["completed"]))

    def add(self, s: FocusSession) -> FocusSession:
        if s.duration_seconds < 0:
            raise ValidationError("Session duration cannot be negative.")
        cur = self.db.execute(
            "INSERT INTO focus_sessions (task_id, started_at, ended_at, duration_seconds, mode, completed) VALUES (?,?,?,?,?,?)",
            (s.task_id, to_iso(s.started_at), to_iso(s.ended_at), s.duration_seconds, s.mode, int(s.completed)))
        s.id = cur.lastrowid
        return s

    def recent(self, limit: int = 15) -> list[FocusSession]:
        return [self._row(r) for r in self.db.query(
            "SELECT * FROM focus_sessions ORDER BY started_at DESC LIMIT ?", (limit,))]

    def between(self, start: datetime, end: datetime) -> list[FocusSession]:
        return [self._row(r) for r in self.db.query(
            "SELECT * FROM focus_sessions WHERE started_at >= ? AND started_at < ? ORDER BY started_at",
            (to_iso(start), to_iso(end)))]

    def seconds_on_day(self, day: date) -> int:
        start = datetime.combine(day, datetime.min.time())
        r = self.db.query("SELECT COALESCE(SUM(duration_seconds),0) s FROM focus_sessions WHERE started_at >= ? AND started_at < ?",
                          (to_iso(start), to_iso(start + timedelta(days=1))))[0]
        return int(r["s"])

    def total_seconds(self) -> int:
        return int(self.db.query("SELECT COALESCE(SUM(duration_seconds),0) s FROM focus_sessions")[0]["s"])


# ---------------------------------------------------------------------------
class SettingsRepository:
    def __init__(self, db: Database):
        self.db = db
        self._cache: dict = {}
        self.reload()

    def reload(self) -> None:
        self._cache = dict(DEFAULT_SETTINGS)
        for r in self.db.query("SELECT key, value FROM settings"):
            try:
                self._cache[r["key"]] = json.loads(r["value"])
            except json.JSONDecodeError:
                pass

    def get(self, key: str):
        return self._cache.get(key, DEFAULT_SETTINGS.get(key))

    def all(self) -> dict:
        return dict(self._cache)

    def set(self, key: str, value) -> None:
        self.set_many({key: value})

    def set_many(self, values: dict) -> None:
        with self.db.transaction():
            for k, v in values.items():
                self.db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                (k, json.dumps(v)))
        self._cache.update(values)

    def reset(self) -> None:
        self.db.execute("DELETE FROM settings")
        self.reload()


# ---------------------------------------------------------------------------
class ProductivityRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, day: date, **fields) -> None:
        cols = ["tasks_completed", "tasks_on_time", "planned_minutes", "done_minutes", "focus_seconds", "productivity_pct"]
        values = [fields.get(c, 0) for c in cols]
        self.db.execute(
            f"""INSERT INTO productivity_records (day, {", ".join(cols)}) VALUES (?, {", ".join("?" * len(cols))})
                ON CONFLICT(day) DO UPDATE SET {", ".join(f"{c}=excluded.{c}" for c in cols)}""",
            [day.isoformat(), *values])

    def range(self, start: date, end: date) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM productivity_records WHERE day >= ? AND day <= ? ORDER BY day",
            (start.isoformat(), end.isoformat()))]


# ---------------------------------------------------------------------------
class KBRepository:
    """Mirror of the CSV knowledge base inside SQLite (CSV stays the source of truth)."""

    def __init__(self, db: Database):
        self.db = db

    def replace(self, kb_name: str, rules) -> None:
        with self.db.transaction():
            self.db.execute("DELETE FROM kb_rules WHERE kb_name=?", (kb_name,))
            for i, r in enumerate(rules):
                self.db.execute(
                    """INSERT OR REPLACE INTO kb_rules (kb_name, rule_id, enabled, fact, operator, value, action, action_value, message, position)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (kb_name, r.rule_id, int(r.enabled), r.fact, r.operator, r.value, r.action, r.action_value, r.message, i))

    def count(self, kb_name: str) -> int:
        return self.db.query("SELECT COUNT(*) n FROM kb_rules WHERE kb_name=?", (kb_name,))[0]["n"]
