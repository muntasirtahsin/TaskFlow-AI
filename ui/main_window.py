"""Main window: sidebar navigation, page stack, tray notifications and the autonomous background loop."""
from __future__ import annotations

import logging

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QMainWindow, QPushButton, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from core.app_context import AppContext
from ui import icons
from ui.analytics_page import AnalyticsPage
from ui.calendar_page import CalendarPage
from ui.dashboard import DashboardPage
from ui.knowledge_page import KnowledgePage
from ui.planner_page import PlannerPage
from ui.schedule_page import SchedulePage
from ui.settings_page import SettingsPage
from ui.task_page import TaskPage
from ui.theme import Theme
from ui.timer_page import TimerPage
from ui.widgets import bus, label
from utils.constants import APP_NAME, ASSETS_DIR

log = logging.getLogger(__name__)

NAV = [
    ("Dashboard", "dashboard", DashboardPage),
    ("My Tasks", "tasks", TaskPage),
    ("AI Planner", "sparkles", PlannerPage),
    ("Daily Schedule", "schedule", SchedulePage),
    ("Calendar", "calendar", CalendarPage),
    ("Focus Timer", "timer", TimerPage),
    ("Analytics", "chart", AnalyticsPage),
    ("Knowledge Base", "book", KnowledgePage),
    ("Settings", "settings", SettingsPage),
]


class Toast(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setMaximumWidth(380)
        self.hide()
        self._timer = QTimer(self, singleShot=True, interval=5000)
        self._timer.timeout.connect(self.hide)

    def show_text(self, text: str) -> None:
        self.setStyleSheet(f"background:{Theme.color('text')}; color:{Theme.color('bg')}; padding:11px 16px; "
                           "border-radius:10px; font-weight:500;")
        self.setText(text)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._timer.start()

    def reposition(self) -> None:
        p = self.parentWidget()
        if p:
            self.move(p.width() - self.width() - 24, p.height() - self.height() - 24)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        self.resize(1320, 840)
        self.setMinimumSize(1000, 660)
        self.setWindowIcon(QIcon(str(ASSETS_DIR / "icons" / "app.svg")))

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(228)
        self.side_lay = QVBoxLayout(self.sidebar)
        self.side_lay.setContentsMargins(14, 18, 14, 14)
        self.side_lay.setSpacing(2)
        outer.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)

        self.pages = []
        self.nav_buttons: list[QPushButton] = []
        self._build_sidebar()
        self.toast = Toast(self.centralWidget())
        self._setup_tray()
        self._connect_signals()
        self.go(0)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.new_task_shortcut)

        # autonomous background loop
        self.loop = QTimer(self, interval=60_000)
        self.loop.timeout.connect(self.background_tick)
        self.loop.start()
        self.notify_loop = QTimer(self, interval=30_000)
        self.notify_loop.timeout.connect(self.ctx.notifier.check)
        self.notify_loop.start()
        self._debounce = QTimer(self, singleShot=True, interval=600)
        self._debounce.timeout.connect(self.autopilot)
        QTimer.singleShot(400, self.autopilot)

    # ---- construction -----------------------------------------------------------------
    def _build_sidebar(self) -> None:
        brand = QHBoxLayout()
        mark = QLabel()
        mark.setObjectName("brandMark")
        mark.setFixedSize(30, 30)
        mark.setPixmap(icons.pixmap("check", "#FFFFFF", 18, 2.4))
        mark.setAlignment(Qt.AlignCenter)
        brand.addWidget(mark)
        brand.addWidget(label(APP_NAME, "brand"))
        brand.addStretch()
        self.side_lay.addLayout(brand)
        self.side_lay.addSpacing(16)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for i, (name, icon_name, page_cls) in enumerate(NAV):
            if name == "Settings":
                self.side_lay.addStretch()
            btn = QPushButton(f"  {name}")
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("icon_name", icon_name)
            btn.clicked.connect(lambda _=False, idx=i: self.go(idx))
            self.group.addButton(btn, i)
            self.nav_buttons.append(btn)
            self.side_lay.addWidget(btn)
            page = page_cls(self.ctx)
            self.pages.append(page)
            self.stack.addWidget(page)
        self.theme_btn = QPushButton("  Dark mode")
        self.theme_btn.setObjectName("nav")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.clicked.connect(self.toggle_theme)
        self.side_lay.addWidget(self.theme_btn)
        self._refresh_icons()

    def _refresh_icons(self) -> None:
        for btn in self.nav_buttons:
            active = btn.isChecked()
            btn.setIcon(icons.icon(btn.property("icon_name"), Theme.color("accent" if active else "muted"), 18))
        dark = Theme.is_dark()
        self.theme_btn.setIcon(icons.icon("sun" if dark else "moon", Theme.color("muted"), 18))
        self.theme_btn.setText("  Light mode" if dark else "  Dark mode")

    def _setup_tray(self) -> None:
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(QIcon(str(ASSETS_DIR / "icons" / "app.svg")), self)
            self.tray.setToolTip(APP_NAME)
            self.tray.show()
        self.ctx.notifier.sink = self._deliver_notification

    def _deliver_notification(self, title: str, message: str) -> None:
        if self.tray is not None:
            self.tray.showMessage(title, message, QSystemTrayIcon.Information, 7000)
        if not self.isActiveWindow() or self.tray is None:
            self.toast.show_text(f"{title}: {message}")

    def _connect_signals(self) -> None:
        for sig in (bus.tasks_changed, bus.schedule_changed, bus.focus_changed, bus.settings_changed, bus.kb_changed):
            sig.connect(self._mark_dirty)
        bus.tasks_changed.connect(lambda: self._debounce.start())
        bus.settings_changed.connect(lambda: self._debounce.start())
        bus.navigate.connect(self.go)
        bus.toast.connect(self.toast.show_text)
        bus.theme_changed.connect(lambda _: self._refresh_icons())

    # ---- navigation -----------------------------------------------------------------------
    def _mark_dirty(self) -> None:
        for p in self.pages:
            p.dirty = True
        QTimer.singleShot(0, self._refresh_current)

    def _refresh_current(self) -> None:
        page = self.stack.currentWidget()
        if getattr(page, "dirty", False):
            self._safe_refresh(page)

    def _safe_refresh(self, page) -> None:
        try:
            page.refresh()
        except Exception:  # keep the app alive if one page fails
            log.exception("Page refresh failed: %s", type(page).__name__)

    def go(self, index: int) -> None:
        page = self.pages[index]
        self.nav_buttons[index].setChecked(True)
        self.stack.setCurrentIndex(index)
        if page.dirty:
            self._safe_refresh(page)
        self._refresh_icons()
        fx = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(fx)
        anim = QPropertyAnimation(fx, b"opacity", page)
        anim.setDuration(160)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: page.setGraphicsEffect(None))
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def new_task_shortcut(self) -> None:
        self.go(1)
        self.pages[1].new_task()

    def toggle_theme(self) -> None:
        new = "light" if Theme.is_dark() else "dark"
        self.ctx.settings.set("theme", new)
        self.apply_theme(new)

    def apply_theme(self, name: str) -> None:
        Theme.apply(name)
        for p in self.pages:
            p.dirty = True
            if hasattr(p, "retheme"):
                p.retheme()
        bus.theme_changed.emit(name)
        self._refresh_current()

    # ---- autonomous loop ----------------------------------------------------------------------
    def autopilot(self) -> None:
        if not self.ctx.settings.get("auto_reschedule"):
            return
        try:
            report = self.ctx.rescheduler.autopilot()
        except Exception:
            log.exception("Autopilot failed")
            return
        if report:
            self.ctx.notifier.emit("schedule_change", "Schedule updated", report.summary)
            bus.toast.emit(report.summary + " See Daily Schedule for details.")
            bus.schedule_changed.emit()

    def background_tick(self) -> None:
        self.autopilot()
        self.ctx.notifier.check()
        self._mark_dirty() if self.stack.currentWidget().__class__.__name__ in ("DashboardPage", "SchedulePage") else None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.toast.reposition()

    def closeEvent(self, event) -> None:
        for p in self.pages:
            if hasattr(p, "shutdown"):
                p.shutdown()
        if self.tray:
            self.tray.hide()
        self.ctx.close()
        super().closeEvent(event)
