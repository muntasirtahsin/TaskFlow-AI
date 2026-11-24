"""Shared dialogs: reschedule report and schedule block editor."""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QDate, QTime, Qt
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialog, QFormLayout, QHBoxLayout, QLineEdit, QTextEdit, QTimeEdit,
                               QVBoxLayout)

from ui.widgets import label, make_button, show_error
from utils.validators import ValidationError


class ReportDialog(QDialog):
    """Explains a (proposed or applied) schedule change in plain language."""

    def __init__(self, report, title: str, parent=None, apply_button: bool = True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(560, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        lay.addWidget(label(title, "h1"))
        lay.addWidget(label(report.summary, "muted", wrap=True))
        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText(report.text())
        lay.addWidget(view, 1)
        if apply_button:
            lay.addWidget(label("Nothing has been changed yet. Blocks you customised manually are never moved.", "faint", wrap=True))
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(make_button("Close" if not apply_button else "Cancel", on_click=self.reject))
        if apply_button:
            row.addWidget(make_button("Apply changes", "primary", on_click=self.accept))
        lay.addLayout(row)


class BlockDialog(QDialog):
    """Create or edit a schedule block (task or custom label)."""

    def __init__(self, ctx, entry=None, day=None, parent=None):
        super().__init__(parent)
        self.ctx, self.entry = ctx, entry
        self.setWindowTitle("Edit block" if entry else "Add block")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        lay.addWidget(label("Edit block" if entry else "Add block", "h1"))
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.task = QComboBox()
        self.task.addItem("Custom block (no task)", None)
        for t in ctx.tasks.active():
            self.task.addItem(t.title, t.id)
        self.label_edit = QLineEdit(entry.label if entry else "")
        self.label_edit.setPlaceholderText("e.g. Meeting, Gym")
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("ddd, MMM d yyyy")
        self.start = QTimeEdit()
        self.end = QTimeEdit()
        for w in (self.start, self.end):
            w.setDisplayFormat("HH:mm")
        d = entry.start.date() if entry else (day or datetime.now().date())
        s = entry.start if entry else datetime.combine(d, datetime.now().replace(minute=0, second=0).time()) + timedelta(hours=1)
        e = entry.end if entry else s + timedelta(minutes=60)
        self.date.setDate(QDate(d.year, d.month, d.day))
        self.start.setTime(QTime(s.hour, s.minute))
        self.end.setTime(QTime(e.hour, e.minute))
        if entry and entry.task_id:
            idx = self.task.findData(entry.task_id)
            self.task.setCurrentIndex(max(idx, 0))
        elif day is not None and not entry and self.task.count() > 1:
            self.task.setCurrentIndex(1)
        form.addRow("Task", self.task)
        form.addRow("Label", self.label_edit)
        form.addRow("Date", self.date)
        form.addRow("Start", self.start)
        form.addRow("End", self.end)
        lay.addLayout(form)
        lay.addWidget(label("Manually edited blocks are locked: automatic rescheduling will not move them.", "faint", wrap=True))
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(make_button("Cancel", on_click=self.reject))
        row.addWidget(make_button("Save", "primary", on_click=self._save))
        lay.addLayout(row)
        self.task.currentIndexChanged.connect(lambda: self.label_edit.setEnabled(self.task.currentData() is None))
        self.label_edit.setEnabled(self.task.currentData() is None)

    def _save(self) -> None:
        d = self.date.date().toPython()
        start = datetime.combine(d, self.start.time().toPython())
        end = datetime.combine(d, self.end.time().toPython())
        task_id = self.task.currentData()
        try:
            if self.entry:
                self.entry.task_id = task_id
                self.entry.label = self.label_edit.text().strip() if task_id is None else ""
                self.ctx.schedule.update(self.entry)  # keep label/task changes
                self.ctx.move_block(self.entry.id, start, end)
            else:
                self.ctx.add_manual_block(task_id, start, end, self.label_edit.text())
        except ValidationError as exc:
            show_error(self, str(exc), "Cannot save block")
            return
        self.accept()
