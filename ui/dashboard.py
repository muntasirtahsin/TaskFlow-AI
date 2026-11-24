"""Dashboard: key numbers, today's workload, charts, upcoming deadlines and advice."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from ui.theme import CATEGORY_COLORS, Theme
from ui.widgets import (BasePage, Badge, Card, ChartCanvas, EmptyState, PageHeader, StatCard, bus, clear_layout,
                        label, make_button, scroll_area, show_error)
from utils.constants import ENTRY_DONE, KIND_TASK
from utils.helpers import fmt_deadline, fmt_minutes, fmt_relative, now


class DashboardPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(28, 24, 28, 24)
        self.lay.setSpacing(16)
        outer.addWidget(scroll_area(body))

        self.header = PageHeader("Dashboard", "")
        plan_btn = make_button("Plan my day", "primary", "sparkles", "Recalculate the schedule from current priorities",
                               self.plan)
        self.header.layout().addWidget(plan_btn)
        self.lay.addWidget(self.header)

        self.advice = QVBoxLayout()
        self.advice.setSpacing(8)
        self.lay.addLayout(self.advice)

        grid = QGridLayout()
        grid.setSpacing(14)
        spec = [("total", "Total tasks", "tasks", "accent"), ("completed", "Completed", "check", "success"),
                ("pending", "Pending", "schedule", "faint"), ("in_progress", "In progress", "play", "info"),
                ("overdue", "Overdue", "alert", "danger"), ("due_today", "Due today", "calendar", "warning"),
                ("hours", "Scheduled today", "timer", "accent"), ("prod", "Today's productivity", "chart", "success")]
        self.stats: dict[str, StatCard] = {}
        for i, (key, title, ic, col) in enumerate(spec):
            card = StatCard(title, ic, col)
            self.stats[key] = card
            grid.addWidget(card, i // 4, i % 4)
        self.lay.addLayout(grid)

        mid = QHBoxLayout()
        mid.setSpacing(14)
        self.today_card = Card()
        self.today_list = QVBoxLayout()
        self.today_list.setSpacing(6)
        self.today_card.title_row("Today's workload")
        self.today_card.lay.addLayout(self.today_list)
        self.today_card.lay.addStretch()
        mid.addWidget(self.today_card, 5)

        right = QVBoxLayout()
        right.setSpacing(14)
        self.deadline_card = Card()
        self.deadline_card.title_row("Upcoming deadlines")
        self.deadline_list = QVBoxLayout()
        self.deadline_list.setSpacing(6)
        self.deadline_card.lay.addLayout(self.deadline_list)
        right.addWidget(self.deadline_card)
        mid.addLayout(right, 4)
        self.lay.addLayout(mid)

        charts = QHBoxLayout()
        charts.setSpacing(14)
        self.status_card, self.status_chart = self._chart_card("Tasks by status")
        self.week_card, self.week_chart = self._chart_card("Completed in the last 14 days")
        charts.addWidget(self.status_card, 2)
        charts.addWidget(self.week_card, 3)
        self.lay.addLayout(charts)
        self.lay.addStretch()

    def _chart_card(self, title: str):
        card = Card()
        card.title_row(title)
        chart = ChartCanvas(2.4)
        card.lay.addWidget(chart)
        return card, chart

    def plan(self) -> None:
        try:
            report = self.ctx.generate_plan(reason="Plan generated from dashboard")
        except Exception as exc:
            show_error(self, str(exc))
            return
        bus.schedule_changed.emit()
        bus.toast.emit(report.summary)

    def retheme(self) -> None:
        pass

    def refresh(self) -> None:
        super().refresh()
        n = now()
        ov = self.ctx.analytics.overview(n)
        today = self.ctx.analytics.today(n)
        self.header.subtitle.setText(n.strftime("%A, %B %d").replace(" 0", " ") +
                                     f"  ·  {ov['total'] - ov['completed'] - ov['cancelled']} active tasks")
        s = self.stats
        s["total"].set(str(ov["total"]), f"{ov['cancelled']} cancelled" if ov["cancelled"] else "")
        s["completed"].set(str(ov["completed"]), f"{ov['on_time']} on time" if ov["completed"] else "")
        s["pending"].set(str(ov["pending"]))
        s["in_progress"].set(str(ov["in_progress"]))
        s["overdue"].set(str(ov["overdue"]), "needs attention" if ov["overdue"] else "all clear",
                         Theme.color("danger") if ov["overdue"] else None)
        s["due_today"].set(str(ov["due_today"]))
        s["hours"].set(f"{today['planned_minutes'] / 60:.1f}h", f"{fmt_minutes(today['done_minutes'])} done")
        s["prod"].set(f"{today['productivity_pct']}%" if today["has_plan"] else "-",
                      "of planned work done" if today["has_plan"] else "no plan yet")

        self._advice()
        self._today_list(n)
        self._deadlines(n)
        self._charts(ov)

    def _advice(self) -> None:
        clear_layout(self.advice)
        recs = [r for r in self.ctx.recommendations() if r.severity in ("warning", "info")][:2]
        for r in recs:
            f = Card(shadow=False, name="banner")
            f.lay.setContentsMargins(14, 10, 14, 10)
            color = Theme.color("warning" if r.severity == "warning" else "info")
            row = QHBoxLayout()
            dot = QLabel()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(f"background:{color}; border-radius:4px;")
            row.addWidget(dot)
            row.addWidget(label(r.text, wrap=True), 1)
            f.lay.addLayout(row)
            self.advice.addWidget(f)

    def _today_list(self, n) -> None:
        clear_layout(self.today_list)
        entries = [e for e in self.ctx.schedule.for_day(n.date()) if e.kind == KIND_TASK and e.status != "skipped"]
        if not entries:
            self.today_list.addWidget(EmptyState("schedule", "Nothing scheduled today",
                                                 "Add tasks, then press \"Plan my day\"."))
            return
        for e in entries[:8]:
            t = self.ctx.tasks.get(e.task_id) if e.task_id else None
            row = QHBoxLayout()
            time_lb = label(f"{e.start:%H:%M} - {e.end:%H:%M}", "faint")
            time_lb.setFixedWidth(100)
            row.addWidget(time_lb)
            title = label(t.title if t else e.label or "Block")
            if e.status == ENTRY_DONE:
                title.setStyleSheet(f"color:{Theme.color('faint')}; text-decoration: line-through;")
            row.addWidget(title, 1)
            if t:
                row.addWidget(Badge(t.category, CATEGORY_COLORS.get(t.category, "#999")))
            if e.status == ENTRY_DONE:
                row.addWidget(Badge("Done", Theme.color("success")))
            elif e.end <= n:
                row.addWidget(Badge("Missed", Theme.color("danger")))
            elif e.start <= n < e.end:
                row.addWidget(Badge("Now", Theme.color("accent")))
            self.today_list.addLayout(row)
        if len(entries) > 8:
            self.today_list.addWidget(label(f"+ {len(entries) - 8} more blocks", "faint"))

    def _deadlines(self, n) -> None:
        clear_layout(self.deadline_list)
        tasks = sorted((t for t in self.ctx.tasks.active() if t.deadline), key=lambda t: t.deadline)[:6]
        if not tasks:
            self.deadline_list.addWidget(EmptyState("calendar", "No deadlines", "Tasks with deadlines appear here."))
            return
        for t in tasks:
            row = QHBoxLayout()
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(t.title))
            col.addWidget(label(fmt_deadline(t.deadline, n), "faint"))
            row.addLayout(col, 1)
            late = t.deadline < n
            row.addWidget(Badge(fmt_relative(t.deadline, n), Theme.color("danger" if late else "warning" if (t.deadline - n).days < 2 else "muted")))
            self.deadline_list.addLayout(row)

    def _charts(self, ov: dict) -> None:
        ax = self.status_chart.begin()
        ax.yaxis.grid(False)
        vals = [("Completed", ov["completed"], Theme.color("success")), ("In progress", ov["in_progress"], Theme.color("info")),
                ("Pending", ov["pending"], Theme.color("faint")), ("Cancelled", ov["cancelled"], Theme.color("danger"))]
        vals = [v for v in vals if v[1] > 0]
        if vals:
            ax.pie([v[1] for v in vals], colors=[v[2] for v in vals], startangle=90, counterclock=False,
                   wedgeprops={"width": 0.38, "edgecolor": Theme.color("surface"), "linewidth": 2})
            ax.text(0, 0, str(ov["total"]), ha="center", va="center", fontsize=18, fontweight="bold", color=Theme.color("text"))
            ax.legend([f"{v[0]} ({v[1]})" for v in vals], loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False,
                      fontsize=8, labelcolor=Theme.color("muted"))
        else:
            ax.axis("off")
            ax.text(0.5, 0.5, "No tasks yet", ha="center", va="center", color=Theme.color("faint"), transform=ax.transAxes)
        self.status_chart.finish()

        data = self.ctx.analytics.daily_completions(14)
        ax = self.week_chart.begin()
        ax.bar([d.strftime("%d") for d, _ in data], [c for _, c in data], color=Theme.color("accent"), width=0.55)
        ax.set_yticks(range(0, max(max((c for _, c in data), default=0), 3) + 1))
        self.week_chart.finish()
