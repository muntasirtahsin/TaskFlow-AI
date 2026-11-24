"""My Tasks: create, edit, delete, search, filter and manage tasks (+ the task editor dialog)."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from PySide6.QtCore import QDate, QDateTime, QSize, Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QDialog,
                               QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QProgressBar, QSlider, QSpinBox, QStackedLayout, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from database.models import Subtask, Task
from ui import icons
from ui.theme import CATEGORY_COLORS, Theme
from ui.widgets import (BasePage, Badge, EmptyState, PageHeader, bus, confirm, icon_button, label, make_button,
                        show_error)
from utils.constants import (CATEGORIES, IMPORTANCE_LABELS, PRIORITY_LABELS, STATUS_CANCELLED, STATUS_COMPLETED,
                             STATUS_IN_PROGRESS, STATUS_PENDING, STATUSES)
from utils.helpers import fmt_deadline, fmt_minutes, fmt_relative, now, parse_quick_add
from utils.validators import ValidationError


class TaskDialog(QDialog):
    def __init__(self, ctx, task: Task | None = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.task = task or Task(estimated_minutes=int(ctx.settings.get("default_duration_minutes")))
        self.is_new = task is None
        self.setWindowTitle("New task" if self.is_new else "Edit task")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(14)
        lay.addWidget(label("New task" if self.is_new else "Edit task", "h1"))

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft)
        t = self.task
        self.title = QLineEdit(t.title)
        self.title.setPlaceholderText("What needs to be done?")
        self.title.setMaxLength(200)
        self.desc = QTextEdit(t.description)
        self.desc.setFixedHeight(70)
        self.desc.setPlaceholderText("Optional details")
        self.category = QComboBox()
        self.category.addItems(CATEGORIES)
        self.category.setCurrentText(t.category)
        self.priority = QComboBox()
        for k, v in PRIORITY_LABELS.items():
            self.priority.addItem(v, k)
        self.priority.setCurrentIndex(t.priority - 1)
        self.importance = QComboBox()
        for k, v in IMPORTANCE_LABELS.items():
            self.importance.addItem(v, k)
        self.importance.setCurrentIndex(t.importance - 1)
        self.minutes = QSpinBox()
        self.minutes.setRange(5, 60 * 24 * 14)
        self.minutes.setSingleStep(15)
        self.minutes.setSuffix(" min")
        self.minutes.setValue(t.estimated_minutes)
        self.minutes_hint = label("", "faint")
        self.minutes.valueChanged.connect(lambda v: self.minutes_hint.setText(f"= {fmt_minutes(v)}"))
        self.minutes_hint.setText(f"= {fmt_minutes(t.estimated_minutes)}")

        self.has_deadline = QCheckBox("Deadline")
        self.deadline = QDateTimeEdit()
        self.deadline.setCalendarPopup(True)
        self.deadline.setDisplayFormat("ddd, MMM d yyyy  HH:mm")
        dl = t.deadline or datetime.combine(now().date() + timedelta(days=1), time(17, 0))
        self.deadline.setDateTime(QDateTime(dl.year, dl.month, dl.day, dl.hour, dl.minute, 0))
        self.has_deadline.setChecked(t.deadline is not None)
        self.deadline.setEnabled(t.deadline is not None)
        self.has_deadline.toggled.connect(self.deadline.setEnabled)

        self.has_start = QCheckBox("Preferred start")
        self.start = QDateEdit()
        self.start.setCalendarPopup(True)
        self.start.setDisplayFormat("ddd, MMM d yyyy")
        sd = t.preferred_start or now().date()
        self.start.setDate(QDate(sd.year, sd.month, sd.day))
        self.has_start.setChecked(t.preferred_start is not None)
        self.start.setEnabled(t.preferred_start is not None)
        self.has_start.toggled.connect(self.start.setEnabled)

        self.status = QComboBox()
        self.status.addItems(STATUSES)
        self.status.setCurrentText(t.status)
        self.completion = QSlider(Qt.Horizontal)
        self.completion.setRange(0, 100)
        self.completion.setSingleStep(5)
        self.completion.setValue(t.completion)
        self.completion_lb = label(f"{t.completion}%", "muted")
        self.completion_lb.setFixedWidth(40)
        self.completion.valueChanged.connect(lambda v: self.completion_lb.setText(f"{v}%"))
        self.status.currentTextChanged.connect(self._status_changed)
        self.actual = QSpinBox()
        self.actual.setRange(0, 60 * 24 * 60)
        self.actual.setSuffix(" min")
        self.actual.setValue(int(t.actual_minutes))

        form.addRow("Title", self.title)
        form.addRow("Description", self.desc)
        row = QHBoxLayout()
        row.addWidget(self.category)
        row.addWidget(self.priority)
        row.addWidget(self.importance)
        form.addRow("Category / Priority / Importance", row)
        dur = QHBoxLayout()
        dur.addWidget(self.minutes)
        dur.addWidget(self.minutes_hint)
        dur.addStretch()
        form.addRow("Estimated duration", dur)
        form.addRow(self.has_deadline, self.deadline)
        form.addRow(self.has_start, self.start)
        form.addRow("Status", self.status)
        comp = QHBoxLayout()
        comp.addWidget(self.completion)
        comp.addWidget(self.completion_lb)
        form.addRow("Completion", comp)
        form.addRow("Time spent", self.actual)
        lay.addLayout(form)

        # subtasks
        lay.addWidget(label("Subtasks", "h2"))
        self.subs = QListWidget()
        self.subs.setFixedHeight(110)
        self.subs.itemChanged.connect(lambda *_: None)
        lay.addWidget(self.subs)
        self._load_subtasks()
        add_row = QHBoxLayout()
        self.sub_input = QLineEdit()
        self.sub_input.setPlaceholderText("Add a subtask and press Enter")
        self.sub_input.returnPressed.connect(self._add_sub)
        add_row.addWidget(self.sub_input, 1)
        add_row.addWidget(make_button("Add", on_click=self._add_sub))
        add_row.addWidget(make_button("Suggest", "", "sparkles", "Suggest a breakdown from the knowledge base", self._suggest))
        add_row.addWidget(make_button("Remove", "", "trash", "", self._remove_sub))
        lay.addLayout(add_row)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(make_button("Cancel", on_click=self.reject))
        buttons.addWidget(make_button("Create task" if self.is_new else "Save changes", "primary", on_click=self._save))
        lay.addLayout(buttons)
        self.title.setFocus()

    # ---- subtasks -----------------------------------------------------------------------
    def _load_subtasks(self) -> None:
        if self.task.id:
            for s in self.ctx.subtasks.for_task(self.task.id):
                self._add_sub_item(s.title, s.estimated_minutes, s.done)

    def _add_sub_item(self, title: str, minutes: int, done: bool = False) -> None:
        item = QListWidgetItem(title)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
        item.setCheckState(Qt.Checked if done else Qt.Unchecked)
        item.setData(Qt.UserRole, minutes)
        item.setToolTip(f"{minutes} min  (double-click to rename)")
        self.subs.addItem(item)

    def _add_sub(self) -> None:
        text = self.sub_input.text().strip()
        if text:
            self._add_sub_item(text, 30)
            self.sub_input.clear()

    def _remove_sub(self) -> None:
        for item in self.subs.selectedItems():
            self.subs.takeItem(self.subs.row(item))

    def _suggest(self) -> None:
        probe = Task(title=self.title.text() or "Task", category=self.category.currentText(),
                     estimated_minutes=self.minutes.value())
        s = self.ctx.analyzer.suggest_breakdown(probe, force=True)
        if not s:
            show_error(self, "No breakdown template matched.", "No suggestion")
            return
        existing = {self.subs.item(i).text() for i in range(self.subs.count())}
        for it in s.items:
            if it.title not in existing:
                self._add_sub_item(it.title, it.estimated_minutes)

    def _status_changed(self, status: str) -> None:
        if status == STATUS_COMPLETED:
            self.completion.setValue(100)
        elif status == STATUS_PENDING and self.completion.value() == 100:
            self.completion.setValue(0)

    # ---- save -------------------------------------------------------------------------------
    def _save(self) -> None:
        t = self.task
        t.title = self.title.text().strip()
        t.description = self.desc.toPlainText().strip()
        t.category = self.category.currentText()
        t.priority = self.priority.currentData()
        t.importance = self.importance.currentData()
        t.estimated_minutes = self.minutes.value()
        t.deadline = self.deadline.dateTime().toPython().replace(second=0, microsecond=0) if self.has_deadline.isChecked() else None
        t.preferred_start = self.start.date().toPython() if self.has_start.isChecked() else None
        t.status = self.status.currentText()
        t.completion = self.completion.value()
        if self.actual.value() != int(t.actual_minutes):
            t.actual_seconds = self.actual.value() * 60
        subs = []
        for i in range(self.subs.count()):
            it = self.subs.item(i)
            if it.text().strip():
                subs.append(Subtask(title=it.text().strip(), estimated_minutes=it.data(Qt.UserRole) or 30,
                                    done=it.checkState() == Qt.Checked))
        try:
            self.ctx.save_task(t, subs)
        except (ValidationError, Exception) as exc:
            show_error(self, str(exc), "Cannot save task")
            return
        self.accept()


# ---------------------------------------------------------------------------------------------------
class TaskPage(BasePage):
    COLS = ["", "Task", "Category", "AI priority", "Status", "Deadline", "Estimate", "Progress", ""]

    def __init__(self, ctx):
        super().__init__(ctx)
        lay = self.root_layout()
        self.header = PageHeader("My Tasks", "")
        self.header.layout().addWidget(make_button("New task", "primary", "plus", "Create a task (Ctrl+N)", self.new_task))
        lay.addWidget(self.header)

        self.quick = QLineEdit()
        self.quick.setObjectName("quickAdd")
        self.quick.setPlaceholderText("Quick add:  Write report #work 2h tomorrow @15:00 !     (press Enter)")
        self.quick.returnPressed.connect(self.quick_add)
        lay.addWidget(self.quick)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search tasks")
        self.search.addAction(icons.icon("search", Theme.color("faint"), 16), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.status_f = QComboBox()
        self.status_f.addItems(["Active", "All statuses"] + STATUSES)
        self.cat_f = QComboBox()
        self.cat_f.addItems(["All categories"] + CATEGORIES)
        self.level_f = QComboBox()
        self.level_f.addItems(["Any AI priority", "Critical", "High", "Medium", "Low"])
        self.sort_f = QComboBox()
        self.sort_f.addItems(["Sort: AI priority", "Sort: Deadline", "Sort: Newest", "Sort: Title"])
        for c in (self.status_f, self.cat_f, self.level_f, self.sort_f):
            c.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.search, 1)
        for c in (self.status_f, self.cat_f, self.level_f, self.sort_f):
            filters.addWidget(c)
        lay.addLayout(filters)

        host = QWidget()
        self.stack = QStackedLayout(host)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        self.table.cellDoubleClicked.connect(lambda r, c: self.edit_row(r))
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for i, w in ((0, 44), (2, 100), (3, 100), (4, 110), (5, 150), (6, 80), (7, 120), (8, 84)):
            hh.setSectionResizeMode(i, QHeaderView.Fixed)
            self.table.setColumnWidth(i, w)
        self.empty = EmptyState("tasks", "No tasks here", "Create your first task with the quick-add bar above or press New task.")
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        lay.addWidget(host, 1)
        self._rows: list[Task] = []

    # ---- actions ---------------------------------------------------------------------------------
    def new_task(self) -> None:
        if TaskDialog(self.ctx, parent=self).exec() == QDialog.Accepted:
            bus.data_changed()

    def quick_add(self) -> None:
        text = self.quick.text().strip()
        if not text:
            return
        p = parse_quick_add(text, default_minutes=int(self.ctx.settings.get("default_duration_minutes")))
        if not p["title"]:
            show_error(self, "Please type a task title.", "Quick add")
            return
        try:
            self.ctx.save_task(Task(**p))
        except ValidationError as exc:
            show_error(self, str(exc), "Quick add")
            return
        self.quick.clear()
        bus.data_changed()
        bus.toast.emit(f"Added '{p['title']}'")

    def _task_at(self, row: int) -> Task | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def edit_row(self, row: int) -> None:
        t = self._task_at(row)
        if t and TaskDialog(self.ctx, self.ctx.tasks.get(t.id), self).exec() == QDialog.Accepted:
            bus.data_changed()

    def delete_row(self, row: int) -> None:
        t = self._task_at(row)
        if t and confirm(self, f"Delete '{t.title}'?", "The task, its subtasks and scheduled blocks will be permanently removed."):
            self.ctx.delete_task(t.id)
            bus.data_changed()

    def set_status(self, row: int, status: str) -> None:
        t = self._task_at(row)
        if t:
            try:
                self.ctx.set_status(t.id, status)
            except ValidationError as exc:
                show_error(self, str(exc))
            bus.data_changed()

    def context_menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        t = self._task_at(row)
        if not t:
            return
        m = QMenu(self)
        m.addAction("Edit", lambda: self.edit_row(row))
        if t.status != STATUS_IN_PROGRESS:
            m.addAction("Mark in progress", lambda: self.set_status(row, STATUS_IN_PROGRESS))
        if t.status != STATUS_COMPLETED:
            m.addAction("Mark completed", lambda: self.set_status(row, STATUS_COMPLETED))
        if t.status in (STATUS_COMPLETED, STATUS_CANCELLED):
            m.addAction("Reopen", lambda: self.set_status(row, STATUS_PENDING))
        else:
            m.addAction("Cancel task", lambda: self.set_status(row, STATUS_CANCELLED))
        m.addSeparator()
        if t.is_active:
            m.addAction("Start focus session", lambda: self.focus_task(t.id))
            m.addAction("Suggest breakdown", lambda: self.open_planner(t.id))
        m.addSeparator()
        m.addAction("Delete", lambda: self.delete_row(row))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def focus_task(self, task_id: int) -> None:
        self.ctx.ui_focus_task = task_id
        bus.navigate.emit(5)

    def open_planner(self, task_id: int) -> None:
        self.ctx.ui_planner_task = task_id
        bus.navigate.emit(2)

    # ---- table -----------------------------------------------------------------------------------------
    def _filtered(self) -> list[tuple[Task, object]]:
        tasks = self.ctx.tasks.search(self.search.text().strip(),
                                      status=self.status_f.currentText() if self.status_f.currentIndex() >= 2 else "",
                                      category=self.cat_f.currentText() if self.cat_f.currentIndex() > 0 else "")
        if self.status_f.currentIndex() == 0:
            tasks = [t for t in tasks if t.is_active]
        n = now()
        analyses = {a.task.id: a.priority for a in self.ctx.analyzer.analyze(self.ctx.tasks.active(), n)}
        order = {tid: i for i, tid in enumerate(analyses)}
        pairs = [(t, analyses.get(t.id)) for t in tasks]
        if self.level_f.currentIndex() > 0:
            pairs = [p for p in pairs if p[1] and p[1].level == self.level_f.currentText()]
        sort = self.sort_f.currentIndex()
        if sort == 0:
            pairs.sort(key=lambda p: (order.get(p[0].id, 10**6), p[0].id))
        elif sort == 1:
            pairs.sort(key=lambda p: (p[0].deadline is None, p[0].deadline or datetime.max))
        elif sort == 2:
            pairs.sort(key=lambda p: p[0].created_at, reverse=True)
        else:
            pairs.sort(key=lambda p: p[0].title.lower())
        return pairs

    def refresh(self) -> None:
        super().refresh()
        pairs = self._filtered()
        self._rows = [p[0] for p in pairs]
        total = self.ctx.tasks.count_by_status()
        self.header.subtitle.setText(f"{sum(total.values())} tasks  ·  {len(pairs)} shown")
        self.stack.setCurrentIndex(0 if pairs else 1)
        self.table.setRowCount(len(pairs))
        n = now()
        for r, (t, res) in enumerate(pairs):
            chk = QCheckBox()
            chk.setChecked(t.status == STATUS_COMPLETED)
            chk.setToolTip("Mark complete / reopen")
            chk.clicked.connect(lambda checked, row=r: self.set_status(row, STATUS_COMPLETED if checked else STATUS_PENDING))
            self.table.setCellWidget(r, 0, self._center(chk))

            cell = QWidget()
            col = QVBoxLayout(cell)
            col.setContentsMargins(4, 4, 4, 4)
            col.setSpacing(0)
            title = label(t.title)
            title.setStyleSheet("font-weight:600;" + (f"color:{Theme.color('faint')}; text-decoration:line-through;" if not t.is_active else ""))
            col.addWidget(title)
            done, count = self.ctx.subtasks.progress(t.id)
            sub = f"{done}/{count} subtasks" if count else (t.description.split("\n")[0][:70] if t.description else "")
            if sub:
                col.addWidget(label(sub, "faint"))
            self.table.setCellWidget(r, 1, cell)
            self.table.setCellWidget(r, 2, self._center(Badge(t.category, CATEGORY_COLORS.get(t.category, "#999"))))
            lvl = Badge("-", Theme.color("faint"))
            if res and not res.excluded:
                lvl.set_level(res.level)
                lvl.setToolTip(res.explanation(t.title))
            self.table.setCellWidget(r, 3, self._center(lvl))
            st = Badge()
            st.set_status(t.status)
            self.table.setCellWidget(r, 4, self._center(st))
            dl = QWidget()
            dcol = QVBoxLayout(dl)
            dcol.setContentsMargins(4, 4, 4, 4)
            dcol.setSpacing(0)
            dcol.addWidget(label(fmt_deadline(t.deadline, n)))
            if t.deadline and t.is_active:
                rel = label(fmt_relative(t.deadline, n), "faint")
                if t.deadline < n:
                    rel.setStyleSheet(f"color:{Theme.color('danger')}; font-size:12px; font-weight:600;")
                dcol.addWidget(rel)
            self.table.setCellWidget(r, 5, dl)
            self.table.setCellWidget(r, 6, self._center(label(fmt_minutes(t.estimated_minutes), "muted")))
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(t.completion)
            wrap = QWidget()
            wl = QHBoxLayout(wrap)
            wl.setContentsMargins(4, 0, 4, 0)
            wl.addWidget(bar, 1)
            wl.addWidget(label(f"{t.completion}%", "faint"))
            self.table.setCellWidget(r, 7, wrap)
            acts = QWidget()
            al = QHBoxLayout(acts)
            al.setContentsMargins(0, 0, 0, 0)
            al.setSpacing(0)
            al.addWidget(icon_button("edit", "Edit", lambda row=r: self.edit_row(row)))
            al.addWidget(icon_button("trash", "Delete", lambda row=r: self.delete_row(row), "danger"))
            self.table.setCellWidget(r, 8, acts)

    @staticmethod
    def _center(w: QWidget) -> QWidget:
        host = QWidget()
        lay = QHBoxLayout(host)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.addWidget(w, 0, Qt.AlignVCenter)
        return host
