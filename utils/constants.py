"""Application-wide constants and default configuration."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "TaskFlow AI"
APP_VERSION = "1.0.0"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TASKFLOW_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "taskflow.db"
BACKUP_DIR = DATA_DIR / "backups"
LOG_DIR = DATA_DIR / "logs"
KB_DIR = Path(os.environ.get("TASKFLOW_KB_DIR", BASE_DIR / "knowledge_base"))
KB_DEFAULTS_DIR = BASE_DIR / "knowledge_base" / "defaults"
ASSETS_DIR = BASE_DIR / "assets"
STYLES_DIR = ASSETS_DIR / "styles"

# ---- Task vocabulary -------------------------------------------------------
CATEGORIES = ["Academic", "Work", "Personal", "Project", "Other"]

STATUS_PENDING = "Pending"
STATUS_IN_PROGRESS = "In Progress"
STATUS_COMPLETED = "Completed"
STATUS_CANCELLED = "Cancelled"
STATUSES = [STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_CANCELLED]
ACTIVE_STATUSES = (STATUS_PENDING, STATUS_IN_PROGRESS)

PRIORITY_LABELS = {1: "Low", 2: "Medium", 3: "High", 4: "Critical"}
IMPORTANCE_LABELS = {1: "Low", 2: "Medium", 3: "High"}

LEVELS = ["Low", "Medium", "High", "Critical"]  # ascending order
LEVEL_RANK = {name: i for i, name in enumerate(LEVELS)}
LEVEL_NONE = "None"

# ---- Schedule entries ------------------------------------------------------
KIND_TASK = "task"
KIND_BREAK = "break"
ENTRY_PLANNED = "planned"
ENTRY_DONE = "done"
ENTRY_MISSED = "missed"
ENTRY_SKIPPED = "skipped"

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# ---- Knowledge base --------------------------------------------------------
KB_FILES = {
    "priority": "priority_rules.csv",
    "scheduling": "scheduling_rules.csv",
    "breakdown": "task_breakdown_rules.csv",
    "recommendation": "recommendation_rules.csv",
}
KB_TITLES = {
    "priority": "Priority rules",
    "scheduling": "Scheduling rules",
    "breakdown": "Task breakdown rules",
    "recommendation": "Recommendation rules",
}
KB_COLUMNS = ["rule_id", "enabled", "fact", "operator", "value", "action", "action_value", "message"]
KB_OPERATORS = ["<", "<=", ">", ">=", "==", "!=", "between", "in", "contains_any", "always"]
KB_ACTIONS = {
    "priority": ["add_score", "min_level", "classify", "exclude"],
    "scheduling": ["scale_load", "scale_block", "tie_margin", "set_flag"],
    "breakdown": ["suggest_breakdown", "template"],
    "recommendation": ["recommend"],
}

# ---- Default user settings -------------------------------------------------
DEFAULT_SETTINGS = {
    "theme": "light",
    "work_start": "09:00",
    "work_end": "17:00",
    "available_days": [0, 1, 2, 3, 4],
    "break_minutes": 10,
    "max_continuous_minutes": 90,
    "min_block_minutes": 25,
    "preferred_period": "any",  # any | morning | afternoon | evening
    "daily_limit_hours": 6.0,
    "default_duration_minutes": 60,
    "horizon_days": 21,
    "unavailable_dates": [],
    "auto_reschedule": True,
    "notifications_enabled": True,
    "notify_upcoming": True,
    "notify_upcoming_lead": 10,
    "notify_deadline": True,
    "notify_deadline_hours": 24,
    "notify_overdue": True,
    "notify_focus_done": True,
    "notify_break": True,
    "notify_schedule_change": True,
    "pomodoro_focus": 25,
    "pomodoro_short": 5,
    "pomodoro_long": 20,
    "pomodoro_cycles": 4,
    "pomodoro_auto_start": False,
    "last_plan_signature": "",
}
