"""Backup, restore, export and reset of user data."""
from __future__ import annotations

import csv
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from database.database import Database, DatabaseError

log = logging.getLogger(__name__)

DATA_TABLES = ["schedule_changes", "focus_sessions", "schedule_entries", "subtasks", "tasks",
               "productivity_records", "settings"]
EXPORT_TABLES = ["tasks", "subtasks", "schedule_entries", "focus_sessions", "productivity_records", "settings"]
REQUIRED_TABLES = {"tasks", "subtasks", "schedule_entries", "focus_sessions", "settings", "productivity_records"}


class DataManager:
    def __init__(self, db: Database, backup_dir: Path):
        self.db, self.backup_dir = db, Path(backup_dir)

    def backup(self, target: Path | None = None) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        target = Path(target) if target else self.backup_dir / f"taskflow_{datetime.now():%Y%m%d_%H%M%S}.db"
        dest = sqlite3.connect(str(target))
        try:
            with self.db._lock:
                self.db.conn.backup(dest)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Backup failed: {exc}") from exc
        finally:
            dest.close()
        log.info("Backup written to %s", target)
        return target

    def restore(self, source: Path) -> None:
        source = Path(source)
        try:
            src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
            tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.Error as exc:
            raise DatabaseError(f"'{source.name}' is not a valid backup: {exc}") from exc
        if not REQUIRED_TABLES <= tables:
            src.close()
            raise DatabaseError("This file is not a TaskFlow AI backup (tables are missing).")
        self.backup()  # safety copy of the current state first
        try:
            with self.db._lock:
                src.backup(self.db.conn)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Restore failed: {exc}") from exc
        finally:
            src.close()
        self.db.migrate()
        log.info("Database restored from %s", source)

    def export_json(self, path: Path) -> Path:
        data = {"exported_at": datetime.now().isoformat(timespec="seconds"), "version": self.db.version}
        for table in EXPORT_TABLES:
            data[table] = [dict(r) for r in self.db.query(f"SELECT * FROM {table}")]
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return Path(path)

    def export_csv(self, folder: Path) -> list[Path]:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        written = []
        for table in ("tasks", "subtasks", "schedule_entries", "focus_sessions"):
            rows = self.db.query(f"SELECT * FROM {table}")
            cols = [d[0] for d in self.db.execute(f"SELECT * FROM {table} LIMIT 0").description]
            path = folder / f"{table}.csv"
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(cols)
                w.writerows([tuple(r) for r in rows])
            written.append(path)
        return written

    def reset(self) -> None:
        self.backup()  # always keep a safety copy
        with self.db.transaction():
            for table in DATA_TABLES:
                self.db.execute(f"DELETE FROM {table}")
            self.db.execute("DELETE FROM sqlite_sequence")
        log.warning("Application data was reset")
