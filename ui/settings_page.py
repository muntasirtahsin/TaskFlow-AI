"""Settings: appearance, working hours, scheduling, notifications, pomodoro and data management."""
from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QListWidget, QSpinBox, QTimeEdit, QVBoxLayout, QWidget)

from ui.theme import Theme
from ui.widgets import (BasePage, Card, PageHeader, bus, confirm, label, make_button, scroll_area, show_error,
                        show_info)
from utils.constants import BACKUP_DIR, WEEKDAYS
from utils.helpers import fmt_hhmm, parse_hhmm
from utils.validators import ValidationError


class SettingsPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)
        outer.addWidget(scroll_area(body))
        self.header = PageHeader("Settings", "Everything is stored locally on this computer")
        self.header.layout().addWidget(make_button("Save settings", "primary", "check", "", self.save))
        lay.addWidget(self.header)

        # appearance
        c = self._section(lay, "Appearance")
        self.theme = QComboBox()
        self.theme.addItems(["Light", "Dark"])
        c.addRow("Theme", self.theme)

        # working time
        c = self._section(lay, "Working hours & scheduling")
        self.start = QTimeEdit()
        self.end = QTimeEdit()
        for w in (self.start, self.end):
            w.setDisplayFormat("HH:mm")
        row = QHBoxLayout()
        row.addWidget(self.start)
        row.addWidget(label("to", "muted"))
        row.addWidget(self.end)
        row.addStretch()
        c.addRow("Daily working hours", row)
        days = QHBoxLayout()
        self.days = []
        for i, name in enumerate(WEEKDAYS):
            cb = QCheckBox(name)
            self.days.append(cb)
            days.addWidget(cb)
        days.addStretch()
        c.addRow("Available days", days)
        self.limit = QDoubleSpinBox()
        self.limit.setRange(0.5, 16)
        self.limit.setSingleStep(0.5)
        self.limit.setSuffix(" h")
        c.addRow("Daily workload limit", self.limit)
        self.max_block = QSpinBox()
        self.max_block.setRange(15, 480)
        self.max_block.setSingleStep(15)
        self.max_block.setSuffix(" min")
        c.addRow("Max continuous work", self.max_block)
        self.min_block = QSpinBox()
        self.min_block.setRange(5, 120)
        self.min_block.setSingleStep(5)
        self.min_block.setSuffix(" min")
        c.addRow("Minimum block length", self.min_block)
        self.brk = QSpinBox()
        self.brk.setRange(0, 120)
        self.brk.setSingleStep(5)
        self.brk.setSuffix(" min")
        c.addRow("Break between blocks", self.brk)
        self.period = QComboBox()
        for text, val in (("No preference", "any"), ("Morning", "morning"), ("Afternoon", "afternoon"), ("Evening", "evening")):
            self.period.addItem(text, val)
        c.addRow("Preferred working period", self.period)
        self.default_dur = QSpinBox()
        self.default_dur.setRange(5, 960)
        self.default_dur.setSingleStep(15)
        self.default_dur.setSuffix(" min")
        c.addRow("Default task duration", self.default_dur)
        self.horizon = QSpinBox()
        self.horizon.setRange(3, 120)
        self.horizon.setSuffix(" days")
        c.addRow("Planning horizon", self.horizon)
        self.auto = QCheckBox("Automatically reschedule when tasks change, blocks are missed or time runs over")
        c.addRow("Autonomous mode", self.auto)

        # unavailable
        card = Card()
        card.title_row("Days off / unavailable dates")
        card.lay.addWidget(label("No work will be scheduled on these dates. Blocks already planned there are moved automatically.", "muted", wrap=True))
        row = QHBoxLayout()
        self.off_date = QDateEdit(QDate.currentDate())
        self.off_date.setCalendarPopup(True)
        row.addWidget(self.off_date)
        row.addWidget(make_button("Add", "", "plus", "", self.add_off))
        row.addWidget(make_button("Remove selected", "", "trash", "", self.remove_off))
        row.addStretch()
        card.lay.addLayout(row)
        self.off_list = QListWidget()
        self.off_list.setMaximumHeight(110)
        card.lay.addWidget(self.off_list)
        lay.addWidget(card)

        # notifications
        c = self._section(lay, "Notifications")
        self.notify_on = QCheckBox("Enable desktop notifications")
        c.addRow("", self.notify_on)
        self.n_flags = {}
        for key, text in (("notify_upcoming", "Upcoming scheduled tasks"), ("notify_deadline", "Approaching deadlines"),
                          ("notify_overdue", "Overdue tasks"), ("notify_focus_done", "Focus session completed"),
                          ("notify_break", "Break reminders"), ("notify_schedule_change", "Schedule changes")):
            cb = QCheckBox(text)
            self.n_flags[key] = cb
            c.addRow("", cb)
        self.lead = QSpinBox()
        self.lead.setRange(1, 120)
        self.lead.setSuffix(" min before")
        c.addRow("Remind before a block", self.lead)
        self.dl_hours = QSpinBox()
        self.dl_hours.setRange(1, 240)
        self.dl_hours.setSuffix(" h before")
        c.addRow("Remind before a deadline", self.dl_hours)

        # pomodoro
        c = self._section(lay, "Pomodoro")
        self.p_focus, self.p_short, self.p_long, self.p_cycles = QSpinBox(), QSpinBox(), QSpinBox(), QSpinBox()
        for w, lo, hi, suf in ((self.p_focus, 5, 120, " min"), (self.p_short, 1, 30, " min"), (self.p_long, 5, 60, " min"), (self.p_cycles, 2, 10, " sessions")):
            w.setRange(lo, hi)
            w.setSuffix(suf)
        c.addRow("Focus length", self.p_focus)
        c.addRow("Short break", self.p_short)
        c.addRow("Long break", self.p_long)
        c.addRow("Long break after", self.p_cycles)
        self.p_auto = QCheckBox("Start the next phase automatically")
        c.addRow("", self.p_auto)

        # data
        card = Card()
        card.title_row("Data")
        card.lay.addWidget(label(f"Your database lives in the data folder next to the app. Backups are saved to {BACKUP_DIR}.", "muted", wrap=True))
        row = QHBoxLayout()
        row.addWidget(make_button("Back up now", "", "download", "", self.backup))
        row.addWidget(make_button("Restore backup...", "", "upload", "", self.restore))
        row.addWidget(make_button("Export JSON...", "", "folder", "", self.export_json))
        row.addWidget(make_button("Export CSV...", "", "folder", "", self.export_csv))
        row.addStretch()
        row.addWidget(make_button("Reset all data...", "danger", "trash", "", self.reset))
        card.lay.addLayout(row)
        lay.addWidget(card)
        lay.addStretch()

    def _section(self, lay, title: str) -> QFormLayout:
        card = Card()
        card.title_row(title)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        card.lay.addLayout(form)
        lay.addWidget(card)
        return form

    # ---- load / save -----------------------------------------------------------------------------
    def refresh(self) -> None:
        super().refresh()
        s = self.ctx.settings.get
        self.theme.setCurrentText("Dark" if s("theme") == "dark" else "Light")
        t = parse_hhmm(s("work_start"))
        self.start.setTime(QTime(t.hour, t.minute))
        t = parse_hhmm(s("work_end"))
        self.end.setTime(QTime(t.hour, t.minute))
        for i, cb in enumerate(self.days):
            cb.setChecked(i in s("available_days"))
        self.limit.setValue(float(s("daily_limit_hours")))
        self.max_block.setValue(int(s("max_continuous_minutes")))
        self.min_block.setValue(int(s("min_block_minutes")))
        self.brk.setValue(int(s("break_minutes")))
        self.period.setCurrentIndex(max(0, self.period.findData(s("preferred_period"))))
        self.default_dur.setValue(int(s("default_duration_minutes")))
        self.horizon.setValue(int(s("horizon_days")))
        self.auto.setChecked(bool(s("auto_reschedule")))
        self.notify_on.setChecked(bool(s("notifications_enabled")))
        for k, cb in self.n_flags.items():
            cb.setChecked(bool(s(k)))
        self.lead.setValue(int(s("notify_upcoming_lead")))
        self.dl_hours.setValue(int(s("notify_deadline_hours")))
        self.p_focus.setValue(int(s("pomodoro_focus")))
        self.p_short.setValue(int(s("pomodoro_short")))
        self.p_long.setValue(int(s("pomodoro_long")))
        self.p_cycles.setValue(int(s("pomodoro_cycles")))
        self.p_auto.setChecked(bool(s("pomodoro_auto_start")))
        self.off_list.clear()
        for d in sorted(s("unavailable_dates") or []):
            self.off_list.addItem(d)

    def _values(self) -> dict:
        v = {
            "theme": self.theme.currentText().lower(),
            "work_start": fmt_hhmm(self.start.time().toPython()), "work_end": fmt_hhmm(self.end.time().toPython()),
            "available_days": [i for i, cb in enumerate(self.days) if cb.isChecked()],
            "daily_limit_hours": self.limit.value(), "max_continuous_minutes": self.max_block.value(),
            "min_block_minutes": self.min_block.value(), "break_minutes": self.brk.value(),
            "preferred_period": self.period.currentData(), "default_duration_minutes": self.default_dur.value(),
            "horizon_days": self.horizon.value(), "auto_reschedule": self.auto.isChecked(),
            "notifications_enabled": self.notify_on.isChecked(), "notify_upcoming_lead": self.lead.value(),
            "notify_deadline_hours": self.dl_hours.value(), "pomodoro_focus": self.p_focus.value(),
            "pomodoro_short": self.p_short.value(), "pomodoro_long": self.p_long.value(),
            "pomodoro_cycles": self.p_cycles.value(), "pomodoro_auto_start": self.p_auto.isChecked(),
            "unavailable_dates": [self.off_list.item(i).text() for i in range(self.off_list.count())],
        }
        v.update({k: cb.isChecked() for k, cb in self.n_flags.items()})
        return v

    def save(self) -> None:
        values = self._values()
        try:
            self.ctx.save_settings(values)
        except ValidationError as exc:
            show_error(self, str(exc), "Invalid settings")
            return
        win = self.window()
        if hasattr(win, "apply_theme") and values["theme"] != Theme.name:
            win.apply_theme(values["theme"])
        bus.settings_changed.emit()
        bus.schedule_changed.emit()
        bus.toast.emit("Settings saved")

    # ---- unavailable dates --------------------------------------------------------------------------
    def add_off(self) -> None:
        d = self.off_date.date().toPython().isoformat()
        if d not in [self.off_list.item(i).text() for i in range(self.off_list.count())]:
            self.off_list.addItem(d)
            self.off_list.sortItems()

    def remove_off(self) -> None:
        for it in self.off_list.selectedItems():
            self.off_list.takeItem(self.off_list.row(it))

    # ---- data management --------------------------------------------------------------------------------
    def backup(self) -> None:
        try:
            path = self.ctx.data.backup()
        except Exception as exc:
            show_error(self, str(exc), "Backup failed")
            return
        show_info(self, "Backup created", f"Saved to:\n{path}")

    def restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a backup", str(self.ctx.data.backup_dir), "TaskFlow backup (*.db)")
        if not path:
            return
        if not confirm(self, "Restore this backup?", "Current data will be replaced (a safety backup is made first).", "Restore", danger=True):
            return
        try:
            self.ctx.data.restore(path)
            self.ctx.settings.reload()
        except Exception as exc:
            show_error(self, str(exc), "Restore failed")
            return
        win = self.window()
        if hasattr(win, "apply_theme"):
            win.apply_theme(self.ctx.settings.get("theme"))
        bus.data_changed()
        bus.settings_changed.emit()
        show_info(self, "Restored", "Your data was restored from the backup.")

    def export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export data", "taskflow_export.json", "JSON (*.json)")
        if path:
            try:
                self.ctx.data.export_json(path)
                show_info(self, "Exported", f"Saved to {path}")
            except Exception as exc:
                show_error(self, str(exc), "Export failed")

    def export_csv(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose export folder")
        if folder:
            try:
                files = self.ctx.data.export_csv(folder)
                show_info(self, "Exported", f"{len(files)} CSV files saved to {folder}")
            except Exception as exc:
                show_error(self, str(exc), "Export failed")

    def reset(self) -> None:
        if not confirm(self, "Reset all application data?",
                       "All tasks, schedules, focus sessions and settings will be permanently deleted. "
                       "A backup is saved first so you can restore it.", "Delete everything"):
            return
        try:
            self.ctx.data.reset()
        except Exception as exc:
            show_error(self, str(exc), "Reset failed")
            return
        self.ctx.settings.reload()
        win = self.window()
        if hasattr(win, "apply_theme"):
            win.apply_theme(self.ctx.settings.get("theme"))
        bus.data_changed()
        bus.settings_changed.emit()
        self.refresh()
        show_info(self, "Data reset", "The application was reset to a clean state.")
