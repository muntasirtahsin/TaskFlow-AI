"""Design tokens and stylesheet generation (light / dark)."""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from utils.constants import ASSETS_DIR, STYLES_DIR

LIGHT = {
    "bg": "#F7F7F8", "sidebar": "#FBFBFC", "surface": "#FFFFFF", "surface2": "#F3F4F6",
    "border": "#E6E7EB", "text": "#16181D", "muted": "#5B6270", "faint": "#9AA1AF",
    "hover": "#F0F1F4", "pressed": "#E7E9EE", "scroll": "#D5D8DF",
    "accent": "#5E6AD2", "accent_hover": "#4F5BC4", "accent_soft": "#ECEEFC", "accent_text": "#FFFFFF",
    "success": "#2E9E6B", "warning": "#D9820B", "danger": "#DC4A4F", "info": "#3B82C4",
    "danger_soft": "#FCECEC", "shadow": "#10182822",
}
DARK = {
    "bg": "#101114", "sidebar": "#14151A", "surface": "#1A1B21", "surface2": "#22242B",
    "border": "#2B2D36", "text": "#ECEDF0", "muted": "#A0A5B1", "faint": "#6E7380",
    "hover": "#23252C", "pressed": "#2B2E37", "scroll": "#363944",
    "accent": "#7B86F0", "accent_hover": "#8D97F4", "accent_soft": "#272A44", "accent_text": "#0E0F14",
    "success": "#4CC38A", "warning": "#F0A237", "danger": "#F0686D", "info": "#5AA6E8",
    "danger_soft": "#3A2224", "shadow": "#00000066",
}

LEVEL_COLOR_KEYS = {"Critical": "danger", "High": "warning", "Medium": "info", "Low": "faint", "None": "faint"}
STATUS_COLOR_KEYS = {"Pending": "faint", "In Progress": "info", "Completed": "success", "Cancelled": "danger"}
CATEGORY_COLORS = {"Academic": "#8B7CF6", "Work": "#3B82C4", "Personal": "#E5739B", "Project": "#2E9E6B", "Other": "#9AA1AF"}


class Theme:
    name = "light"
    tokens = dict(LIGHT)

    @classmethod
    def color(cls, key: str) -> str:
        return cls.tokens.get(key, key)

    @classmethod
    def qcolor(cls, key: str) -> QColor:
        return QColor(cls.color(key))

    @classmethod
    def level_color(cls, level: str) -> str:
        return cls.color(LEVEL_COLOR_KEYS.get(level, "faint"))

    @classmethod
    def status_color(cls, status: str) -> str:
        return cls.color(STATUS_COLOR_KEYS.get(status, "faint"))

    @classmethod
    def is_dark(cls) -> bool:
        return cls.name == "dark"

    @classmethod
    def stylesheet(cls) -> str:
        qss = (STYLES_DIR / "base.qss").read_text(encoding="utf-8")
        tokens = dict(cls.tokens)
        tokens["check_icon"] = (ASSETS_DIR / "icons" / "check_white.svg").as_posix()
        for key, value in tokens.items():
            qss = qss.replace(f"@{key}@", value)
        return qss

    @classmethod
    def apply(cls, name: str) -> None:
        cls.name = "dark" if name == "dark" else "light"
        cls.tokens = dict(DARK if cls.name == "dark" else LIGHT)
        app = QApplication.instance()
        if app:
            app.setStyleSheet(cls.stylesheet())


def with_alpha(color: str, alpha: float) -> str:
    c = QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"
