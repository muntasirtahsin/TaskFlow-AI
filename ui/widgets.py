"""Reusable UI building blocks and the shared signal bus."""
from __future__ import annotations

import logging
from typing import Callable, Optional

import matplotlib

matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QMessageBox,  # noqa: E402
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from ui import icons  # noqa: E402
from ui.theme import Theme, with_alpha  # noqa: E402

log = logging.getLogger(__name__)
matplotlib.rcParams["font.family"] = ["Segoe UI", "Helvetica", "DejaVu Sans"]
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)


class Bus(QObject):
    """Application-wide change notifications; pages refresh when they receive them."""
    tasks_changed = Signal()
    schedule_changed = Signal()
    settings_changed = Signal()
    focus_changed = Signal()
    kb_changed = Signal()
    theme_changed = Signal(str)
    navigate = Signal(int)
    toast = Signal(str)

    def data_changed(self) -> None:
        self.tasks_changed.emit()
        self.schedule_changed.emit()


bus = Bus()


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def make_button(text: str = "", kind: str = "", icon_name: Optional[str] = None, tooltip: str = "",
                on_click: Optional[Callable] = None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if icon_name:
        color = Theme.color("accent_text") if kind == "primary" else Theme.color("danger") if kind == "danger" else Theme.color("muted")
        b.setIcon(icons.icon(icon_name, color, 16))
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    if on_click:
        b.clicked.connect(lambda _=False: on_click())
    return b


def icon_button(icon_name: str, tooltip: str, on_click: Optional[Callable] = None, color: str = "muted") -> QPushButton:
    b = QPushButton()
    b.setObjectName("iconBtn")
    b.setIcon(icons.icon(icon_name, Theme.color(color), 18))
    b.setToolTip(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    b.setFixedSize(30, 30)
    if on_click:
        b.clicked.connect(lambda _=False: on_click())
    return b


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


class Card(QFrame):
    """Rounded surface with a subtle shadow."""

    def __init__(self, parent=None, shadow: bool = True, name: str = "card"):
        super().__init__(parent)
        self.setObjectName(name)
        if shadow and not Theme.is_dark():
            fx = QGraphicsDropShadowEffect(self)
            fx.setBlurRadius(18)
            fx.setOffset(0, 2)
            c = QColor(16, 24, 40, 22)
            fx.setColor(c)
            self.setGraphicsEffect(fx)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 14, 16, 14)
        self.lay.setSpacing(10)

    def title_row(self, title: str, *widgets: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(label(title, "h2"))
        row.addStretch()
        for w in widgets:
            row.addWidget(w)
        self.lay.addLayout(row)
        return row


class Badge(QLabel):
    """Small coloured pill."""

    def __init__(self, text: str = "", color: str = "#999999", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self.setStyleSheet(f"background:{with_alpha(color, 0.15)}; color:{color}; border-radius:9px; "
                           f"padding:2px 9px; font-size:11px; font-weight:600;")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set_level(self, level: str) -> None:
        self.setText(level)
        self.set_color(Theme.level_color(level))

    def set_status(self, status: str) -> None:
        self.setText(status)
        self.set_color(Theme.status_color(status))


class StatCard(Card):
    def __init__(self, title: str, icon_name: str, color_key: str = "accent"):
        super().__init__()
        self.lay.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(label(title, "statLabel"))
        top.addStretch()
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon_name, Theme.color(color_key), 16))
        top.addWidget(ic)
        self.lay.addLayout(top)
        self.value = label("0", "statValue")
        self.sub = label("", "faint")
        self.lay.addWidget(self.value)
        self.lay.addWidget(self.sub)

    def set(self, value: str, sub: str = "", color: Optional[str] = None) -> None:
        self.value.setText(value)
        self.sub.setText(sub)
        self.value.setStyleSheet(f"color:{color};" if color else "")


class EmptyState(QWidget):
    def __init__(self, icon_name: str, title: str, text: str = "", parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(6)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon_name, Theme.color("faint"), 36, 1.5))
        ic.setAlignment(Qt.AlignCenter)
        t = label(title, "h2")
        t.setAlignment(Qt.AlignCenter)
        s = label(text, "muted", wrap=True)
        s.setAlignment(Qt.AlignCenter)
        for w in (ic, t, s):
            lay.addWidget(w)


class ChartCanvas(FigureCanvasQTAgg):
    """Matplotlib canvas styled from the active theme."""

    def __init__(self, height: float = 2.6, parent=None):
        self.fig = Figure(figsize=(4, height), dpi=100)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumHeight(int(height * 70))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def begin(self):
        self.fig.clear()
        surface = Theme.color("surface")
        self.fig.patch.set_facecolor(surface)
        ax = self.fig.add_subplot(111)
        self.style(ax)
        return ax

    def style(self, ax) -> None:
        ax.set_facecolor(Theme.color("surface"))
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(Theme.color("border"))
        ax.tick_params(colors=Theme.color("muted"), labelsize=8, length=0)
        ax.yaxis.grid(True, color=Theme.color("border"), linewidth=0.7)
        ax.set_axisbelow(True)

    def finish(self, legend: bool = False) -> None:
        if legend:
            for ax in self.fig.axes:
                leg = ax.legend(frameon=False, fontsize=8, labelcolor=Theme.color("muted"))
        self.fig.tight_layout(pad=1.0)
        self.draw_idle()


def scroll_area(widget: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setWidget(widget)
    widget.setObjectName("transparent")
    return sa


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", *actions: QWidget):
        super().__init__()
        self.setObjectName("transparent")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = label(title, "h1")
        self.subtitle = label(subtitle, "muted")
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        row.addLayout(col)
        row.addStretch()
        for a in actions:
            row.addWidget(a)
        row.setAlignment(Qt.AlignVCenter)


class BasePage(QWidget):
    """Base for all pages: holds the app context and a refresh hook."""

    def __init__(self, ctx):
        super().__init__()
        self.setObjectName("page")
        self.ctx = ctx
        self.dirty = True

    def refresh(self) -> None:  # overridden
        self.dirty = False

    def root_layout(self, margins=(28, 24, 28, 20), spacing: int = 16) -> QVBoxLayout:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*margins)
        lay.setSpacing(spacing)
        return lay


# ---- dialog helpers -------------------------------------------------------------
def confirm(parent, title: str, text: str, ok: str = "Delete", danger: bool = True) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning if danger else QMessageBox.Question)
    box.setWindowTitle(title)
    box.setText(title)
    box.setInformativeText(text)
    yes = box.addButton(ok, QMessageBox.AcceptRole)
    box.addButton("Cancel", QMessageBox.RejectRole)
    box.exec()
    return box.clickedButton() is yes


def show_error(parent, text: str, title: str = "Something went wrong") -> None:
    QMessageBox.warning(parent, title, text)


def show_info(parent, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)
