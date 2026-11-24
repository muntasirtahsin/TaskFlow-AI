"""SQLite connection management, schema creation and migrations."""
from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)

# Each migration is (target_version, SQL script). Applied in order; PRAGMA user_version tracks state.
MIGRATIONS: list[tuple[int, str]] = [
    (1, """
    CREATE TABLE tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL DEFAULT 'Other',
        priority INTEGER NOT NULL DEFAULT 2 CHECK (priority BETWEEN 1 AND 4),
        importance INTEGER NOT NULL DEFAULT 2 CHECK (importance BETWEEN 1 AND 3),
        estimated_minutes INTEGER NOT NULL DEFAULT 60 CHECK (estimated_minutes > 0),
        deadline TEXT,
        preferred_start TEXT,
        status TEXT NOT NULL DEFAULT 'Pending'
            CHECK (status IN ('Pending','In Progress','Completed','Cancelled')),
        completion INTEGER NOT NULL DEFAULT 0 CHECK (completion BETWEEN 0 AND 100),
        created_at TEXT NOT NULL,
        completed_at TEXT,
        actual_seconds INTEGER NOT NULL DEFAULT 0 CHECK (actual_seconds >= 0)
    );
    CREATE INDEX idx_tasks_status ON tasks(status);
    CREATE INDEX idx_tasks_deadline ON tasks(deadline);

    CREATE TABLE subtasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        estimated_minutes INTEGER NOT NULL DEFAULT 30,
        done INTEGER NOT NULL DEFAULT 0,
        position INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_subtasks_task ON subtasks(task_id);

    CREATE TABLE schedule_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
        label TEXT NOT NULL DEFAULT '',
        start_at TEXT NOT NULL,
        end_at TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'task' CHECK (kind IN ('task','break')),
        status TEXT NOT NULL DEFAULT 'planned'
            CHECK (status IN ('planned','done','missed','skipped')),
        locked INTEGER NOT NULL DEFAULT 0,
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_schedule_start ON schedule_entries(start_at);
    CREATE INDEX idx_schedule_task ON schedule_entries(task_id);

    CREATE TABLE focus_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT NOT NULL,
        duration_seconds INTEGER NOT NULL CHECK (duration_seconds >= 0),
        mode TEXT NOT NULL DEFAULT 'stopwatch',
        completed INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX idx_focus_started ON focus_sessions(started_at);

    CREATE TABLE kb_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kb_name TEXT NOT NULL,
        rule_id TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        fact TEXT NOT NULL DEFAULT '',
        operator TEXT NOT NULL DEFAULT 'always',
        value TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL DEFAULT '',
        action_value TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL DEFAULT '',
        position INTEGER NOT NULL DEFAULT 0,
        UNIQUE (kb_name, rule_id)
    );

    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE productivity_records (
        day TEXT PRIMARY KEY,
        tasks_completed INTEGER NOT NULL DEFAULT 0,
        tasks_on_time INTEGER NOT NULL DEFAULT 0,
        planned_minutes INTEGER NOT NULL DEFAULT 0,
        done_minutes INTEGER NOT NULL DEFAULT 0,
        focus_seconds INTEGER NOT NULL DEFAULT 0,
        productivity_pct REAL NOT NULL DEFAULT 0
    );
    """),
    (2, """
    CREATE TABLE schedule_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        reason TEXT NOT NULL,
        summary TEXT NOT NULL,
        details TEXT NOT NULL DEFAULT ''
    );
    """),
]

LATEST_VERSION = MIGRATIONS[-1][0]


class DatabaseError(RuntimeError):
    pass


class Database:
    """Thin wrapper around a sqlite3 connection with nested transaction support."""

    def __init__(self, path: Path | str):
        self.path = Path(path) if str(path) != ":memory:" else path
        if isinstance(self.path, Path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._depth = 0
        self.conn = self._open()
        self.migrate()

    def _open(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Cannot open database: {exc}") from exc
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.Error:
            pass
        return conn

    # ---- migrations ---------------------------------------------------------
    @property
    def version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self) -> None:
        current = self.version
        for target, script in MIGRATIONS:
            if target <= current:
                continue
            log.info("Applying database migration %s", target)
            try:
                self.conn.execute("BEGIN")
                for statement in _split_sql(script):
                    self.conn.execute(statement)
                self.conn.execute(f"PRAGMA user_version = {target}")
                self.conn.execute("COMMIT")
            except sqlite3.Error as exc:
                self.conn.execute("ROLLBACK")
                raise DatabaseError(f"Migration {target} failed: {exc}") from exc

    # ---- transactions -------------------------------------------------------
    @contextmanager
    def transaction(self):
        with self._lock:
            outer = self._depth == 0
            if outer:
                self.conn.execute("BEGIN")
            self._depth += 1
            try:
                yield self.conn
            except BaseException:
                self._depth -= 1
                if outer:
                    self.conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outer:
                    self.conn.execute("COMMIT")

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self._lock:
            try:
                return self.conn.execute(sql, params)
            except sqlite3.Error as exc:
                log.exception("SQL failed: %s", sql)
                raise DatabaseError(str(exc)) from exc

    def query(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        return self.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass

    def checkpoint(self) -> None:
        """Flush WAL so the .db file alone is a complete copy (used before backups)."""
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass


def _split_sql(script: str) -> list[str]:
    return [s.strip() for s in script.split(";") if s.strip()]
