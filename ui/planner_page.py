"""AI Planner: explainable priority ranking, recommendations and task breakdown suggestions."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem,
                               QProgressBar, QTableWidget, QVBoxLayout, QWidget)

from database.models import Subtask
from ui.dialogs import ReportDialog
from ui.theme import Theme
from ui.widgets import (BasePage, Badge, Card, EmptyState, PageHeader, bus, clear_layout, label, make_button,
                        scroll_area, show_error, show_info)
from utils.helpers import fmt_deadline, fmt_minutes, now


class PlannerPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        lay = self.root_layout()
        self.header = PageHeader("AI Planner", "Every score below comes from editable rules in the Knowledge Base")
        self.header.layout().addWidget(make_button("Preview replan", "", "refresh", "See what an automatic replan would change", self.preview))
        self.header.layout().addWidget(make_button("Generate plan", "primary", "sparkles", "Build the schedule from these priorities", self.generate))
        lay.addWidget(self.header)

        self.advice = QVBoxLayout()
        self.advice.setSpacing(6)
        lay.addLayout(self.advice)

        body = QHBoxLayout()
        body.setSpacing(16)
        lay.addLayout(body, 1)

        left = Card()
        left.title_row("Priority ranking")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "Task", "Priority", "Score"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for i, w in ((0, 36), (2, 90), (3, 60)):
            hh.setSectionResizeMode(i, QHeaderView.Fixed)
            self.table.setColumnWidth(i, w)
        self.table.itemSelectionChanged.connect(self.show_selected)
        left.lay.addWidget(self.table, 1)
        self.empty = EmptyState("sparkles", "Nothing to prioritise", "Add tasks and the expert system will rank them here.")
        left.lay.addWidget(self.empty)
        body.addWidget(left, 5)

        self.detail = Card()
        self.detail_body = QVBoxLayout()
        self.detail_body.setSpacing(12)
        self.detail.lay.addLayout(self.detail_body)
        body.addWidget(scroll_area_wrap(self.detail), 6)
        self.analyses = []
        self.suggestion_list: QListWidget | None = None
        self.forced: set[int] = set()
        self.rejected: set[int] = set()

    # ---- header actions -----------------------------------------------------------------------
    def generate(self) -> None:
        try:
            report = self.ctx.generate_plan(reason="Plan generated from AI Planner")
        except Exception as exc:
            show_error(self, str(exc))
            return
        bus.schedule_changed.emit()
        ReportDialog(report, "Plan generated", self, apply_button=False).exec()
        bus.navigate.emit(3)

    def preview(self) -> None:
        report = self.ctx.preview_replan("Manual replan")
        dlg = ReportDialog(report, "Preview: what a replan would change", self, apply_button=report.has_changes)
        if dlg.exec() and report.has_changes:
            self.ctx.apply_report(report)
            bus.schedule_changed.emit()
            bus.toast.emit(report.summary)

    # ---- data -------------------------------------------------------------------------------------
    def refresh(self) -> None:
        super().refresh()
        n = now()
        selected_id = self._selected_id()
        if self.ctx.ui_planner_task:
            selected_id = self.ctx.ui_planner_task
            self.forced.add(selected_id)
            self.ctx.ui_planner_task = None
        self.analyses = self.ctx.analyzer.analyze(self.ctx.tasks.active(), n)
        self.empty.setVisible(not self.analyses)
        self.table.setVisible(bool(self.analyses))
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.analyses))
        for r, a in enumerate(self.analyses):
            self.table.setCellWidget(r, 0, _cell(label(str(r + 1), "faint")))
            wrap = QWidget()
            col = QVBoxLayout(wrap)
            col.setContentsMargins(4, 3, 4, 3)
            col.setSpacing(0)
            col.addWidget(label(a.task.title))
            col.addWidget(label(fmt_deadline(a.task.deadline, n) + "  ·  " + fmt_minutes(a.task.remaining_minutes) + " left", "faint"))
            self.table.setCellWidget(r, 1, wrap)
            b = Badge()
            b.set_level(a.priority.level)
            self.table.setCellWidget(r, 2, _cell(b))
            self.table.setCellWidget(r, 3, _cell(label(f"{a.priority.score:.0f}", "muted")))
        self.table.blockSignals(False)
        row = next((i for i, a in enumerate(self.analyses) if a.task.id == selected_id), 0 if self.analyses else -1)
        if row >= 0:
            self.table.selectRow(row)
        self.show_selected()
        self._advice()

    def _advice(self) -> None:
        clear_layout(self.advice)
        for r in self.ctx.recommendations()[:3]:
            f = Card(shadow=False, name="banner")
            f.lay.setContentsMargins(14, 8, 14, 8)
            color = Theme.color({"warning": "warning", "success": "success"}.get(r.severity, "info"))
            row = QHBoxLayout()
            dot = QLabel()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(f"background:{color}; border-radius:4px;")
            row.addWidget(dot)
            row.addWidget(label(r.text, wrap=True), 1)
            f.lay.addLayout(row)
            self.advice.addWidget(f)

    def _selected_id(self):
        r = self.table.currentRow()
        return self.analyses[r].task.id if 0 <= r < len(self.analyses) else None

    # ---- detail panel ------------------------------------------------------------------------------
    def show_selected(self) -> None:
        clear_layout(self.detail_body)
        self.suggestion_list = None
        r = self.table.currentRow()
        if not (0 <= r < len(self.analyses)):
            self.detail_body.addWidget(EmptyState("sparkles", "Select a task", "See why it received its priority."))
            return
        a = self.analyses[r]
        t, res = a.task, a.priority
        head = QHBoxLayout()
        title = label(t.title, "h1")
        title.setWordWrap(True)
        head.addWidget(title, 1)
        b = Badge()
        b.set_level(res.level)
        head.addWidget(b)
        self.detail_body.addLayout(head)
        meta = f"{t.category}  ·  {fmt_deadline(t.deadline, now())}  ·  estimate {fmt_minutes(t.estimated_minutes)}  ·  {t.completion}% done"
        self.detail_body.addWidget(label(meta, "muted", wrap=True))

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(res.score))
        bar.setStyleSheet(f"QProgressBar::chunk {{ background:{Theme.level_color(res.level)}; border-radius:3px; }}")
        self.detail_body.addWidget(label(f"Priority score {res.score:.0f} / 100", "h2"))
        self.detail_body.addWidget(bar)

        self.detail_body.addWidget(label("Why this priority", "h2"))
        for reason in res.reasons:
            row = QHBoxLayout()
            pts = label(f"+{reason.points:g}" if reason.points else "·", "muted")
            pts.setFixedWidth(34)
            pts.setStyleSheet(f"color:{Theme.color('accent') if reason.points else Theme.color('faint')}; font-weight:600;")
            row.addWidget(pts)
            row.addWidget(label(reason.text, wrap=True), 1)
            row.addWidget(label(reason.rule_id, "faint"))
            self.detail_body.addLayout(row)

        self._breakdown_panel(a)
        self.detail_body.addStretch()

    def _breakdown_panel(self, a) -> None:
        t = a.task
        existing = self.ctx.subtasks.for_task(t.id)
        self.detail_body.addWidget(label("Task breakdown", "h2"))
        if existing:
            done = sum(1 for s in existing if s.done)
            self.detail_body.addWidget(label(f"{done} of {len(existing)} subtasks done", "muted"))
            for s in existing:
                row = QHBoxLayout()
                row.addWidget(label(("✓  " if s.done else "○  ") + s.title), 1)
                row.addWidget(label(fmt_minutes(s.estimated_minutes), "faint"))
                self.detail_body.addLayout(row)
        sugg = a.breakdown if t.id not in self.rejected else None
        if t.id in self.forced and sugg is None:
            sugg = self.ctx.analyzer.suggest_breakdown(t, force=True)
        if sugg is None:
            self.detail_body.addWidget(label("The rules do not recommend splitting this task.", "muted"))
            self.detail_body.addWidget(make_button("Suggest a breakdown anyway", "", "wand", "", lambda: self._force(t.id)))
            return
        self.detail_body.addWidget(label("Suggested by the expert system:", "muted"))
        for reason in sugg.reasons:
            self.detail_body.addWidget(label("• " + reason, "faint", wrap=True))
        self.suggestion_list = QListWidget()
        self.suggestion_list.setFixedHeight(min(240, 40 + 34 * len(sugg.items)))
        names = {s.title for s in existing}
        for it in sugg.items:
            item = QListWidgetItem(it.title)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
            item.setCheckState(Qt.Unchecked if it.title in names else Qt.Checked)
            item.setData(Qt.UserRole, it.estimated_minutes)
            item.setToolTip(f"{it.estimated_minutes} min - double-click to edit the title")
            self.suggestion_list.addItem(item)
        self.detail_body.addWidget(self.suggestion_list)
        self.detail_body.addWidget(label("Tick the steps you want, edit titles by double-clicking, then accept.", "faint"))
        row = QHBoxLayout()
        row.addWidget(make_button("Accept selected", "primary", "check", "", lambda: self._accept(t.id)))
        row.addWidget(make_button("Reject", "", "x", "Dismiss this suggestion", lambda: self._reject(t.id)))
        row.addStretch()
        self.detail_body.addLayout(row)

    def _force(self, task_id: int) -> None:
        self.forced.add(task_id)
        self.rejected.discard(task_id)
        self.show_selected()

    def _reject(self, task_id: int) -> None:
        self.rejected.add(task_id)
        self.forced.discard(task_id)
        self.show_selected()

    def _accept(self, task_id: int) -> None:
        if not self.suggestion_list:
            return
        items = []
        for i in range(self.suggestion_list.count()):
            it = self.suggestion_list.item(i)
            if it.checkState() == Qt.Checked and it.text().strip():
                items.append(Subtask(task_id=task_id, title=it.text().strip(), estimated_minutes=it.data(Qt.UserRole) or 30))
        if not items:
            show_info(self, "Nothing selected", "Tick at least one suggested subtask to accept.")
            return
        keep = self.ctx.subtasks.for_task(task_id)
        try:
            self.ctx.subtasks.replace_for_task(task_id, keep + items)
        except Exception as exc:
            show_error(self, str(exc))
            return
        self.forced.discard(task_id)
        bus.tasks_changed.emit()
        bus.toast.emit(f"Added {len(items)} subtasks")


def _cell(w: QWidget) -> QWidget:
    host = QWidget()
    lay = QHBoxLayout(host)
    lay.setContentsMargins(4, 0, 4, 0)
    lay.addWidget(w, 0, Qt.AlignVCenter)
    return host


def scroll_area_wrap(card: Card):
    host = QWidget()
    host.setObjectName("transparent")
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(card)
    lay.addStretch()
    sa = scroll_area(host)
    return sa
