"""Date/time, formatting and parsing helpers (all datetimes are naive local time)."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from utils.constants import CATEGORIES, WEEKDAYS


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def to_iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(timespec="seconds") if dt else None


def parse_dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


def parse_date(s: Optional[str]) -> Optional[date]:
    return date.fromisoformat(s) if s else None


def parse_hhmm(s: str) -> time:
    h, m = s.strip().split(":")
    return time(int(h), int(m))


def fmt_hhmm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def fmt_minutes(m: float) -> str:
    m = int(round(m))
    if m < 60:
        return f"{m}m"
    h, r = divmod(m, 60)
    return f"{h}h" if r == 0 else f"{h}h {r:02d}m"


def fmt_seconds(s: int) -> str:
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def fmt_date_short(d: date, ref: Optional[date] = None) -> str:
    ref = ref or date.today()
    if d == ref:
        return "Today"
    if d == ref + timedelta(days=1):
        return "Tomorrow"
    if d == ref - timedelta(days=1):
        return "Yesterday"
    return d.strftime("%a, %b %d").replace(" 0", " ")


def fmt_deadline(dt: Optional[datetime], ref: Optional[datetime] = None) -> str:
    if dt is None:
        return "No deadline"
    ref = ref or now()
    return f"{fmt_date_short(dt.date(), ref.date())}, {dt.strftime('%H:%M')}"


def fmt_relative(dt: Optional[datetime], ref: Optional[datetime] = None) -> str:
    """Human readable distance to a deadline: 'in 3h', 'overdue by 2d'."""
    if dt is None:
        return ""
    ref = ref or now()
    secs = (dt - ref).total_seconds()
    mins = abs(secs) / 60
    if mins < 60:
        txt = f"{int(mins)}m"
    elif mins < 60 * 48:
        txt = f"{int(mins // 60)}h"
    else:
        txt = f"{int(mins // 1440)}d"
    return f"in {txt}" if secs >= 0 else f"overdue by {txt}"


def round_up(dt: datetime, step: int = 5) -> datetime:
    dt = dt.replace(second=0, microsecond=0)
    extra = (-dt.minute) % step
    return dt + timedelta(minutes=extra)


def minutes_between(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 60.0


def at(d: date, t: time) -> datetime:
    return datetime.combine(d, t)


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def daterange(start: date, days: int):
    for i in range(days):
        yield start + timedelta(days=i)


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(getattr(h, "_taskflow", False) for h in root.handlers):
        return
    handler = RotatingFileHandler(log_dir / "taskflow.log", maxBytes=512_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler._taskflow = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(logging.INFO)


# ---- quick add parsing -----------------------------------------------------
_DUR_RE = re.compile(r"^(?:(\d+(?:\.\d+)?)h)?(?:(\d+)m)?$", re.I)
_TIME_RE = re.compile(r"^@(\d{1,2}):(\d{2})$")
_DAY_NAMES = {n.lower(): i for i, n in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}
_DAY_NAMES.update({n.lower(): i for i, n in enumerate(WEEKDAYS)})


def parse_quick_add(text: str, today: Optional[date] = None, default_minutes: int = 60) -> dict:
    """Parse 'Write report #work 2h tomorrow @15:00 !' into task fields.

    Tokens: #category, durations (2h, 90m, 1h30m), today/tomorrow/weekday/YYYY-MM-DD,
    @HH:MM deadline time, '!' (High) or '!!' (Critical) priority.
    """
    today = today or date.today()
    title_words: list[str] = []
    category, minutes, due, due_time, priority = "Other", default_minutes, None, time(17, 0), 2
    for word in text.split():
        low = word.lower()
        if low.startswith("#") and len(low) > 1:
            match = [c for c in CATEGORIES if c.lower().startswith(low[1:])]
            if match:
                category = match[0]
                continue
        if low in ("!", "!!"):
            priority = 3 if low == "!" else 4
            continue
        m = _TIME_RE.match(word)
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
            due_time = time(int(m.group(1)), int(m.group(2)))
            continue
        if low == "today":
            due = today
            continue
        if low == "tomorrow":
            due = today + timedelta(days=1)
            continue
        if low in _DAY_NAMES:
            delta = (_DAY_NAMES[low] - today.weekday()) % 7 or 7
            due = today + timedelta(days=delta)
            continue
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", word):
            try:
                due = date.fromisoformat(word)
                continue
            except ValueError:
                pass
        dm = _DUR_RE.match(low)
        if dm and low and (dm.group(1) or dm.group(2)):
            total = 0.0
            if dm.group(1):
                total += float(dm.group(1)) * 60
            if dm.group(2):
                total += int(dm.group(2))
            if total > 0:
                minutes = int(round(total))
                continue
        title_words.append(word)
    return {
        "title": " ".join(title_words).strip(),
        "category": category,
        "estimated_minutes": minutes,
        "deadline": datetime.combine(due, due_time) if due else None,
        "priority": priority,
    }
