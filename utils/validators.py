"""Input validation. All validators raise ValidationError with a user-friendly message."""
from __future__ import annotations

import re
from datetime import datetime

from utils.constants import CATEGORIES, KB_ACTIONS, KB_OPERATORS, STATUSES


class ValidationError(ValueError):
    """Raised when user input or stored data violates a constraint."""


def validate_task(task) -> None:
    title = (task.title or "").strip()
    if not title:
        raise ValidationError("Task title is required.")
    if len(title) > 200:
        raise ValidationError("Task title must be 200 characters or fewer.")
    if task.category not in CATEGORIES:
        raise ValidationError(f"Category must be one of: {', '.join(CATEGORIES)}.")
    if task.status not in STATUSES:
        raise ValidationError(f"Invalid status '{task.status}'.")
    if task.priority not in (1, 2, 3, 4):
        raise ValidationError("Priority must be between 1 and 4.")
    if task.importance not in (1, 2, 3):
        raise ValidationError("Importance must be between 1 and 3.")
    if not (5 <= int(task.estimated_minutes) <= 60 * 24 * 14):
        raise ValidationError("Estimated duration must be between 5 minutes and 14 days.")
    if not (0 <= int(task.completion) <= 100):
        raise ValidationError("Completion must be between 0 and 100%.")
    if task.actual_seconds < 0:
        raise ValidationError("Time spent cannot be negative.")
    if task.deadline and task.preferred_start and task.preferred_start > task.deadline.date():
        raise ValidationError("Preferred start date cannot be after the deadline.")


def validate_hhmm(value: str) -> str:
    if not re.fullmatch(r"\d{1,2}:\d{2}", str(value)):
        raise ValidationError(f"'{value}' is not a valid HH:MM time.")
    h, m = (int(x) for x in value.split(":"))
    if h > 23 or m > 59:
        raise ValidationError(f"'{value}' is not a valid time.")
    return f"{h:02d}:{m:02d}"


def validate_time_range(start: datetime, end: datetime) -> None:
    if end <= start:
        raise ValidationError("End time must be after start time.")
    if start.date() != end.date():
        raise ValidationError("A schedule block must start and end on the same day.")


def validate_settings(values: dict) -> None:
    start = validate_hhmm(values["work_start"])
    end = validate_hhmm(values["work_end"])
    if start >= end:
        raise ValidationError("Working day must end after it starts.")
    if not values["available_days"]:
        raise ValidationError("Select at least one available day.")
    if not (0 <= values["break_minutes"] <= 120):
        raise ValidationError("Break duration must be between 0 and 120 minutes.")
    if not (15 <= values["max_continuous_minutes"] <= 480):
        raise ValidationError("Maximum continuous work must be between 15 and 480 minutes.")
    if not (0.5 <= values["daily_limit_hours"] <= 16):
        raise ValidationError("Daily workload limit must be between 0.5 and 16 hours.")
    for key in ("pomodoro_focus", "pomodoro_short", "pomodoro_long", "pomodoro_cycles"):
        if values[key] < 1:
            raise ValidationError("Pomodoro values must be at least 1.")


def validate_rule(rule, kb_name: str) -> list[str]:
    """Return a list of problems with a knowledge-base rule (empty list = valid)."""
    problems = []
    if not rule.rule_id.strip():
        problems.append("rule_id is empty")
    if rule.operator not in KB_OPERATORS:
        problems.append(f"unknown operator '{rule.operator}'")
    if rule.operator != "always" and not rule.fact.strip():
        problems.append("fact is empty")
    if rule.action not in KB_ACTIONS.get(kb_name, []):
        problems.append(f"action '{rule.action}' is not valid for {kb_name} rules")
    if rule.operator == "between" and ".." not in str(rule.value):
        problems.append("'between' needs a value like 0..24")
    if rule.operator in ("<", "<=", ">", ">=") and not re.fullmatch(r"-?\d+(\.\d+)?", str(rule.value).strip()):
        problems.append("numeric operators need a numeric value")
    if rule.action in ("add_score", "scale_load", "scale_block", "tie_margin"):
        try:
            float(rule.action_value)
        except (TypeError, ValueError):
            problems.append(f"action_value must be a number for {rule.action}")
    return problems
