"""Calendar: month grid with deadlines and scheduled workload, plus a day agenda."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.scheduler import ScheduleParams
from ui.theme import CATEGORY_COLORS, Theme, with_alpha
from ui.widgets import (BasePage, Badge, Card, EmptyState, PageHeader, bus, clear_layout, icon_button, label,
                        make_button)
from utils.constants import ENTRY_DONE, ENTRY_SKIPPED, KIND_TASK, WEEKDAYS
from utils.helpers import fmt_date_short, fmt_minutes


class DayCell(QFrame):
    clicked = Signal(object)

    def __init__(self, d: date):
        super().__init__()
        self.date = d
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(92)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(8, 6, 8, 6)
        self.lay.setSpacing(2)

    def mousePressEvent(self, ev):
        self.clicked.emit(self.date)


class CalendarPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        today = date.today()
        self.month = date(today.year, today.month, 1)
        self.selected = today
        lay = self.root_layout()
        self.header = PageHeader("Calendar", "")
        lay.addWidget(self.header)
        nav = QHBoxLayout()
        nav.addWidget(icon_button("left", "Previous month", lambda: self.shift(-1)))
        self.month_label = label("", "h1")
        self.month_label.setMinimumWidth(190)
        self.month_label.setAlignment(Qt.AlignCenter)
        nav.addWidget(self.month_label)
        nav.addWidget(icon_button("right", "Next month", lambda: self.shift(1)))
        nav.addWidget(make_button("Today", on_click=self.go_today))
        nav.addStretch()
        for text, color in (("Deadline", Theme.color("danger")), ("Scheduled work", Theme.color("accent")), ("Unavailable", Theme.color("faint"))):
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{color};")
            nav.addWidget(dot)
            nav.addWidget(label(text, "faint"))
        lay.addLayout(nav)

        body = QHBoxLayout()
        body.setSpacing(16)
        lay.addLayout(body, 1)
        self.grid_host = Card()
        self.grid = QGridLayout()
        self.grid.setSpacing(4)
        self.grid_host.lay.addLayout(self.grid)
        body.addWidget(self.grid_host, 5)

        self.agenda = Card()
        self.agenda_title = label("", "h2")
        self.agenda.lay.addWidget(self.agenda_title)
        self.agenda_body = QVBoxLayout()
        self.agenda_body.setSpacing(8)
        self.agenda.lay.addLayout(self.agenda_body)
        self.agenda.lay.addStretch()
        body.addWidget(self.agenda, 2)

    def shift(self, months: int) -> None:
        y, m = self.month.year, self.month.month + months
        while m < 1:
            y, m = y - 1, m + 12
        while m > 12:
            y, m = y + 1, m - 12
        self.month = date(y, m, 1)
        self.refresh()

    def go_today(self) -> None:
        t = date.today()
        self.month, self.selected = date(t.year, t.month, 1), t
        self.refresh()

    def select(self, d: date) -> None:
        self.selected = d
        if (d.year, d.month) != (self.month.year, self.month.month):
            self.month = date(d.year, d.month, 1)
        self.refresh()

    def refresh(self) -> None:
        super().refresh()
        clear_layout(self.grid)
        self.month_label.setText(self.month.strftime("%B %Y"))
        for i, name in enumerate(WEEKDAYS):
            h = label(name, "faint")
            h.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(h, 0, i)
        weeks = calendar.Calendar(0).monthdatescalendar(self.month.year, self.month.month)
        first, last = weeks[0][0], weeks[-1][-1]
        params = ScheduleParams.from_settings(self.ctx.settings)
        tasks = self.ctx.tasks.active()
        deadlines: dict[date, list] = {}
        for t in tasks:
            if t.deadline:
                deadlines.setdefault(t.deadline.date(), []).append(t)
        load: dict[date, int] = {}
        for e in self.ctx.schedule.between(datetime.combine(first, datetime.min.time()), datetime.combine(last + timedelta(days=1), datetime.min.time())):
            if e.kind == KIND_TASK and e.status != ENTRY_SKIPPED:
                load[e.day] = load.get(e.day, 0) + e.minutes
        today = date.today()
        for r, week in enumerate(weeks, start=1):
            for c, d in enumerate(week):
                cell = DayCell(d)
                in_month = d.month == self.month.month
                border = Theme.color("accent") if d == self.selected else Theme.color("border")
                bg = Theme.color("accent_soft") if d == today else Theme.color("surface" if in_month else "surface2")
                width = 2 if d == self.selected else 1
                cell.setStyleSheet(f"QFrame {{ background:{bg}; border:{width}px solid {border}; border-radius:9px; }} QLabel {{ border:none; background:transparent; }}")
                top = QHBoxLayout()
                num = QLabel(str(d.day))
                num.setStyleSheet(f"font-weight:{700 if d == today else 500}; color:{Theme.color('accent') if d == today else Theme.color('text' if in_month else 'faint')};")
                top.addWidget(num)
                top.addStretch()
                if d in params.unavailable or d.weekday() not in params.days:
                    off = QLabel("●")
                    off.setStyleSheet(f"color:{Theme.color('faint')}; font-size:8px;")
                    off.setToolTip("Not a working day" if d not in params.unavailable else "You are unavailable")
                    top.addWidget(off)
                cell.lay.addLayout(top)
                for t in deadlines.get(d, [])[:2]:
                    chip = QLabel("● " + t.title)
                    chip.setStyleSheet(f"color:{Theme.color('danger')}; font-size:11px;")
                    chip.setMaximumWidth(150)
                    chip.setToolTip(f"Due: {t.title}")
                    cell.lay.addWidget(chip)
                if len(deadlines.get(d, [])) > 2:
                    cell.lay.addWidget(label(f"+{len(deadlines[d]) - 2} more due", "faint"))
                if load.get(d):
                    w = QLabel(f"● {fmt_minutes(load[d])} planned")
                    w.setStyleSheet(f"color:{Theme.color('accent')}; font-size:11px;")
                    cell.lay.addWidget(w)
                cell.lay.addStretch()
                cell.clicked.connect(self.select)
                self.grid.addWidget(cell, r, c)
        for c in range(7):
            self.grid.setColumnStretch(c, 1)
        self.header.subtitle.setText(f"{sum(len(v) for v in deadlines.values())} upcoming deadlines")
        self._agenda()

    def _agenda(self) -> None:
        clear_layout(self.agenda_body)
        d = self.selected
        self.agenda_title.setText(f"{fmt_date_short(d)}  ·  {d:%A, %b %d}".replace(" 0", " "))
        due = [t for t in self.ctx.tasks.active() if t.deadline and t.deadline.date() == d]
        entries = [e for e in self.ctx.schedule.for_day(d) if e.kind == KIND_TASK and e.status != ENTRY_SKIPPED]
        if not due and not entries:
            self.agenda_body.addWidget(EmptyState("calendar", "Free day", "No deadlines or scheduled work."))
        if due:
            self.agenda_body.addWidget(label("Due", "muted"))
            for t in due:
                row = QHBoxLayout()
                row.addWidget(label(t.title, wrap=True), 1)
                row.addWidget(Badge(f"{t.deadline:%H:%M}", Theme.color("danger")))
                self.agenda_body.addLayout(row)
        if entries:
            self.agenda_body.addWidget(label("Scheduled", "muted"))
            for e in entries:
                t = self.ctx.tasks.get(e.task_id) if e.task_id else None
                row = QHBoxLayout()
                dot = QLabel("●")
                dot.setStyleSheet(f"color:{CATEGORY_COLORS.get(t.category, '#999') if t else Theme.color('accent')};")
                row.addWidget(dot)
                title = label(t.title if t else e.label or "Block", wrap=True)
                if e.status == ENTRY_DONE:
                    title.setStyleSheet(f"color:{Theme.color('faint')}; text-decoration:line-through;")
                row.addWidget(title, 1)
                row.addWidget(label(f"{e.start:%H:%M}-{e.end:%H:%M}", "faint"))
                self.agenda_body.addLayout(row)
        btn = make_button("Open in Daily Schedule", "", "schedule", "", self._open_day)
        self.agenda_body.addWidget(btn)

    def _open_day(self) -> None:
        page = self.window().pages[3] if hasattr(self.window(), "pages") else None
        if page is not None:
            page.day = self.selected
            page.dirty = True
        bus.navigate.emit(3)
