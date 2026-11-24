"""Knowledge Base: view and edit the CSV rules that drive every decision."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from core.inference_engine import Rule
from ui.theme import Theme
from ui.widgets import BasePage, Card, PageHeader, bus, confirm, label, make_button, show_error, show_info
from utils.constants import KB_ACTIONS, KB_FILES, KB_OPERATORS, KB_TITLES

DESCRIPTIONS = {
    "priority": "Scores each task. 'add_score' rules add points, 'classify' rules turn the score into Critical / High / Medium / Low, "
                "'min_level' rules raise the level (e.g. overdue = Critical), 'exclude' removes finished tasks.\n"
                "Facts: importance, priority, hours_to_deadline, is_overdue, hours_overdue, estimated_hours, remaining_hours, completion, "
                "workload_ratio, available_hours, is_in_progress, is_overrun, has_deadline, status, score.",
    "scheduling": "Policies for the scheduler and rescheduler. 'set_flag' switches behaviours on, 'tie_margin' sets the score gap for "
                  "deadline tie-breaking, 'scale_load' / 'scale_block' reduce workload and block length after missed blocks.\n"
                  "Facts: missed_blocks_recent. Flags: spill_next_day, exclude_completed, respect_deadlines, keep_locked, add_breaks.",
    "breakdown": "Decides when a task should be split and which subtasks to propose. 'suggest_breakdown' fires on large tasks; "
                 "'template' rules (first match wins) provide the subtasks as a ';' separated list in action_value.\n"
                 "Facts: estimated_hours, title, category.",
    "recommendation": "Produces advice for the dashboard, planner and weekly summary. action_value is the severity: info, warning or success.\n"
                      "Facts: overdue_count, completion_rate_week, on_time_rate, estimate_ratio, missed_blocks_week, focus_hours_week, "
                      "large_task_count, today_load_ratio, critical_count, active_count, unscheduled_count, streak_days, due_today_count.",
}
HEADERS = ["On", "Rule ID", "Fact", "Operator", "Value", "Action", "Action value", "Explanation message"]


class RuleTable(QWidget):
    def __init__(self, ctx, name: str, page):
        super().__init__()
        self.ctx, self.name, self.page = ctx, name, page
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(label(DESCRIPTIONS[name], "muted", wrap=True))
        self.status = label("", "faint")
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(7, QHeaderView.Stretch)
        for i, w in ((0, 44), (1, 70), (2, 150), (3, 110), (4, 120), (5, 140), (6, 150)):
            hh.setSectionResizeMode(i, QHeaderView.Interactive)
            self.table.setColumnWidth(i, w)
        self.table.itemChanged.connect(lambda *_: self._mark_dirty())
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(make_button("Add rule", "", "plus", "", self.add_rule))
        row.addWidget(make_button("Delete rule", "danger", "trash", "", self.delete_rule))
        row.addWidget(self.status)
        row.addStretch()
        row.addWidget(make_button("Restore defaults", "", "undo", "", self.restore))
        row.addWidget(make_button("Reload file", "", "refresh", "", self.reload))
        self.save_btn = make_button("Save changes", "primary", "check", "", self.save)
        row.addWidget(self.save_btn)
        lay.addLayout(row)
        self.dirty = False
        self.loaded = False
        self.save_btn.setEnabled(False)

    def ensure_loaded(self) -> None:
        if not self.loaded:
            self.reload()

    def _mark_dirty(self, dirty: bool = True) -> None:
        self.dirty = dirty
        self.save_btn.setEnabled(dirty)
        errs = self.ctx.kb.errors.get(self.name, [])
        self.status.setText("Unsaved changes" if dirty else (f"{len(errs)} invalid row(s) skipped - see log" if errs else
                            f"{len(self.ctx.kb.rules(self.name, False))} rules  ·  {self.ctx.kb.path(self.name).name}"))

    def reload(self) -> None:
        self.ctx.kb.load(self.name)
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for rule in self.ctx.kb.rules(self.name, enabled_only=False):
            self._append(rule)
        self.table.blockSignals(False)
        self.loaded = True
        self._mark_dirty(False)

    def _append(self, rule: Rule) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        chk = QCheckBox()
        chk.setChecked(rule.enabled)
        chk.toggled.connect(lambda *_: self._mark_dirty())
        host = QWidget()
        hl = QHBoxLayout(host)
        hl.setContentsMargins(10, 0, 0, 0)
        hl.addWidget(chk)
        self.table.setCellWidget(r, 0, host)
        for col, text in ((1, rule.rule_id), (2, rule.fact), (4, rule.value), (6, rule.action_value), (7, rule.message)):
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            self.table.setItem(r, col, item)
        op = QComboBox()
        op.addItems(KB_OPERATORS)
        op.setCurrentText(rule.operator)
        op.currentTextChanged.connect(lambda *_: self._mark_dirty())
        self.table.setCellWidget(r, 3, op)
        act = QComboBox()
        act.addItems(KB_ACTIONS[self.name])
        act.setCurrentText(rule.action)
        act.currentTextChanged.connect(lambda *_: self._mark_dirty())
        self.table.setCellWidget(r, 5, act)

    def add_rule(self) -> None:
        existing = {self.table.item(r, 1).text() for r in range(self.table.rowCount()) if self.table.item(r, 1)}
        prefix = {"priority": "P", "scheduling": "S", "breakdown": "B", "recommendation": "R"}[self.name]
        n = 200
        while f"{prefix}{n}" in existing:
            n += 1
        self.table.blockSignals(True)
        self._append(Rule(rule_id=f"{prefix}{n}", fact="", operator=">", value="0", action=KB_ACTIONS[self.name][0], action_value="", message="New rule"))
        self.table.blockSignals(False)
        self.table.scrollToBottom()
        self.table.selectRow(self.table.rowCount() - 1)
        self._mark_dirty()

    def delete_rule(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            show_info(self, "Select a rule", "Click a row first, then delete it.")
            return
        if confirm(self, "Delete this rule?", "The AI will stop using it as soon as you save."):
            self.table.removeRow(r)
            self._mark_dirty()

    def collect(self) -> list[Rule]:
        rules = []
        for r in range(self.table.rowCount()):
            def cell(c):
                it = self.table.item(r, c)
                return it.text().strip() if it else ""
            chk = self.table.cellWidget(r, 0).findChild(QCheckBox)
            rules.append(Rule(rule_id=cell(1), enabled=chk.isChecked(), fact=cell(2),
                              operator=self.table.cellWidget(r, 3).currentText(), value=cell(4),
                              action=self.table.cellWidget(r, 5).currentText(), action_value=cell(6), message=cell(7)))
        return rules

    def save(self) -> None:
        try:
            self.ctx.kb.save(self.name, self.collect())
        except ValueError as exc:
            show_error(self, str(exc), "Cannot save rules")
            return
        self._mark_dirty(False)
        bus.kb_changed.emit()
        bus.toast.emit("Rules saved. Priorities and plans will use them from now on.")

    def restore(self) -> None:
        if confirm(self, "Restore default rules?", "Your edits to this rule set will be replaced by the original rules.", "Restore"):
            self.ctx.kb.restore_defaults(self.name)
            self.reload()
            bus.kb_changed.emit()


class KnowledgePage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        lay = self.root_layout()
        lay.addWidget(PageHeader("Knowledge Base", "The expert system's rules. Edit them here or directly in the CSV files."))
        how = Card()
        how.lay.addWidget(label("How the AI decides", "h2"))
        how.lay.addWidget(label(
            "Each rule reads: IF fact operator value THEN action. The inference engine gathers facts about a task or your week, "
            "fires every matching rule, and uses the actions to compute scores, schedules and advice. "
            "Every fired rule also produces the human-readable reason you see in the AI Planner.", "muted", wrap=True))
        lay.addWidget(how)
        self.tabs = QTabWidget()
        self.rule_tables = {}
        for name in KB_FILES:
            rt = RuleTable(ctx, name, self)
            self.rule_tables[name] = rt
            self.tabs.addTab(rt, KB_TITLES[name])
        self.tabs.currentChanged.connect(lambda i: self.tabs.widget(i).ensure_loaded())
        lay.addWidget(self.tabs, 1)
        path_lb = label(f"Files are stored in: {ctx.kb.dir}", "faint")
        path_lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(path_lb)

    def refresh(self) -> None:
        super().refresh()
        current = self.tabs.currentWidget()
        for rt in self.rule_tables.values():
            if rt.dirty:
                continue
            if rt is current:
                rt.reload()
            else:
                rt.loaded = False  # reload lazily when its tab is opened
