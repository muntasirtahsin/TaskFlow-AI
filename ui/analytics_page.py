"""Analytics: charts, statistics and a locally generated weekly summary."""
from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.theme import Theme
from ui.widgets import (BasePage, Card, ChartCanvas, PageHeader, StatCard, clear_layout, label, scroll_area)
from utils.helpers import fmt_minutes, now


class AnalyticsPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)
        outer.addWidget(scroll_area(body))
        lay.addWidget(PageHeader("Analytics", "Your productivity, computed locally from your own data"))

        grid = QGridLayout()
        grid.setSpacing(14)
        spec = [("completed", "Completed", "check", "success"), ("ontime", "On time", "calendar", "accent"),
                ("overdue", "Overdue", "alert", "danger"), ("focus", "Total focus time", "timer", "info"),
                ("avg", "Avg time / task", "schedule", "accent"), ("ratio", "Actual vs estimate", "chart", "warning")]
        self.stats: dict[str, StatCard] = {}
        for i, (k, t, ic, col) in enumerate(spec):
            self.stats[k] = StatCard(t, ic, col)
            grid.addWidget(self.stats[k], i // 3, i % 3)
        lay.addLayout(grid)

        self.charts: dict[str, ChartCanvas] = {}
        titles = [("daily", "Daily task completion (14 days)"), ("weekly", "Weekly task completion (8 weeks)"),
                  ("monthly", "Monthly productivity (6 months)"), ("status", "Completed vs pending"),
                  ("ontime", "On time vs late"), ("est", "Estimated vs actual duration (minutes)"),
                  ("focus", "Focus time per day (hours)")]
        rows = [("daily", "weekly"), ("monthly", "status"), ("est", "focus")]
        cards = {}
        for key, title in titles:
            c = Card()
            c.title_row(title)
            cv = ChartCanvas(2.5)
            self.charts[key] = cv
            c.lay.addWidget(cv)
            cards[key] = c
        for a, b in rows:
            row = QHBoxLayout()
            row.setSpacing(14)
            row.addWidget(cards[a])
            row.addWidget(cards[b])
            lay.addLayout(row)
        ontime_row = QHBoxLayout()
        ontime_row.addWidget(cards["ontime"], 1)
        self.summary_card = Card()
        self.summary_card.title_row("Weekly summary & suggestions")
        self.summary_body = QVBoxLayout()
        self.summary_body.setSpacing(6)
        self.summary_card.lay.addLayout(self.summary_body)
        ontime_row.addWidget(self.summary_card, 2)
        lay.addLayout(ontime_row)
        lay.addStretch()

    def refresh(self) -> None:
        super().refresh()
        A = self.ctx.analytics
        ov = A.overview(now())
        s = self.stats
        s["completed"].set(str(ov["completed"]), f"of {ov['total']} tasks")
        decided = ov["on_time"] + ov["late"]
        s["ontime"].set(f"{round(100 * ov['on_time'] / decided)}%" if decided else "-", f"{ov['on_time']} on time, {ov['late']} late")
        s["overdue"].set(str(ov["overdue"]), color=Theme.color("danger") if ov["overdue"] else None)
        s["focus"].set(fmt_minutes(ov["focus_seconds"] / 60), "all sessions")
        s["avg"].set(fmt_minutes(ov["avg_seconds_per_task"] / 60) if ov["avg_seconds_per_task"] else "-", "per completed task")
        est = A.estimated_vs_actual(50)
        ratio = (sum(a for _, _, a in est) / sum(e for _, e, _ in est)) if est and sum(e for _, e, _ in est) else None
        s["ratio"].set(f"{ratio:.2f}x" if ratio else "-", "1.0x = perfect estimates")

        C = self.charts
        accent, success, faint, warn, danger, info = (Theme.color(k) for k in ("accent", "success", "faint", "warning", "danger", "info"))

        d = A.daily_completions(14)
        ax = C["daily"].begin()
        ax.bar([x.strftime("%d %b") if i % 2 == 0 else "" for i, (x, _) in enumerate(d)], [c for _, c in d], color=accent, width=0.55)
        ax.set_yticks(range(0, max(max((c for _, c in d), default=0), 3) + 1))
        C["daily"].finish()

        w = A.weekly_completions(8)
        ax = C["weekly"].begin()
        ax.bar([x.strftime("%d %b") for x, _ in w], [c for _, c in w], color=info, width=0.55)
        ax.set_yticks(range(0, max(max((c for _, c in w), default=0), 3) + 1))
        C["weekly"].finish()

        m = A.monthly_productivity(6)
        ax = C["monthly"].begin()
        labels = [x[0] for x in m]
        ax.bar(labels, [x[2] for x in m], color=success, width=0.55, label="Completed on time")
        ax.bar(labels, [x[1] - x[2] for x in m], bottom=[x[2] for x in m], color=warn, width=0.55, label="Completed late")
        ax2 = ax.twinx()
        ax2.plot(labels, [x[3] for x in m], color=accent, marker="o", linewidth=2, label="Focus hours")
        ax2.set_ylim(0, max(1.0, max(x[3] for x in m) * 1.3))
        ax2.tick_params(colors=Theme.color("muted"), labelsize=8, length=0)
        for side in ("top", "right", "left", "bottom"):
            ax2.spines[side].set_visible(False)
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, frameon=False, fontsize=8, labelcolor=Theme.color("muted"), loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3)
        ax.set_yticks(range(0, max(max((x[1] for x in m), default=0), 3) + 1))
        C["monthly"].finish()

        ax = C["status"].begin()
        ax.yaxis.grid(False)
        pending = ov["pending"] + ov["in_progress"]
        if ov["completed"] or pending:
            ax.pie([ov["completed"], pending], colors=[success, faint], startangle=90, counterclock=False,
                   wedgeprops={"width": 0.38, "edgecolor": Theme.color("surface"), "linewidth": 2})
            ax.legend([f"Completed ({ov['completed']})", f"Pending ({pending})"], loc="center left", bbox_to_anchor=(1.0, 0.5),
                      frameon=False, fontsize=8, labelcolor=Theme.color("muted"))
        else:
            _empty(ax)
        C["status"].finish()

        ax = C["ontime"].begin()
        ax.yaxis.grid(False)
        if ov["on_time"] or ov["late"]:
            ax.barh(["Deadlines"], [ov["on_time"]], color=success, label="On time", height=0.45)
            ax.barh(["Deadlines"], [ov["late"]], left=[ov["on_time"]], color=danger, label="Late", height=0.45)
            ax.barh(["Deadlines"], [ov["overdue"]], left=[ov["on_time"] + ov["late"]], color=warn, label="Overdue now", height=0.45)
            ax.legend(frameon=False, fontsize=8, labelcolor=Theme.color("muted"), loc="upper center", ncol=3)
        else:
            _empty(ax)
        C["ontime"].finish()

        ax = C["est"].begin()
        if est:
            import numpy as np
            x = np.arange(len(est))
            ax.bar(x - 0.2, [e for _, e, _ in est], 0.38, color=faint, label="Estimated")
            ax.bar(x + 0.2, [a for _, _, a in est], 0.38, color=accent, label="Actual")
            ax.set_xticks(x)
            ax.set_xticklabels([(t[:10] + "..") if len(t) > 11 else t for t, _, _ in est], rotation=20, ha="right")
            ax.legend(frameon=False, fontsize=8, labelcolor=Theme.color("muted"))
        else:
            _empty(ax, "Complete tasks with tracked time to compare")
        C["est"].finish()

        f = A.daily_focus_hours(14)
        ax = C["focus"].begin()
        ax.bar([x.strftime("%d %b") if i % 2 == 0 else "" for i, (x, _) in enumerate(f)], [h for _, h in f], color=info, width=0.55)
        C["focus"].finish()

        self._summary()

    def _summary(self) -> None:
        clear_layout(self.summary_body)
        facts = self.ctx.recommendation_facts()
        recs = self.ctx.recommender.generate(facts)
        lines = [f"Tasks completed: {facts.get('tasks_completed_week', 0)}",
                 f"Focus time: {facts.get('focus_hours_week', 0)}h",
                 f"Missed blocks: {facts.get('missed_blocks_week', 0)}"]
        if "completion_rate_week" in facts:
            lines.insert(1, f"Completion rate: {facts['completion_rate_week']}%")
        if "on_time_rate" in facts:
            lines.append(f"On-time rate (30 days): {facts['on_time_rate']}%")
        if "estimate_ratio" in facts:
            lines.append(f"Actual vs estimated time: {facts['estimate_ratio']}x")
        lines.append(f"Active streak: {facts.get('streak_days', 0)} days")
        self.summary_body.addWidget(label("Last 7 days", "muted"))
        for ln in lines:
            self.summary_body.addWidget(label("• " + ln))
        self.summary_body.addWidget(label("Suggestions", "muted"))
        colors = {"warning": Theme.color("warning"), "success": Theme.color("success"), "info": Theme.color("info")}
        if not recs:
            self.summary_body.addWidget(label("Nothing to flag. Keep going.", "faint"))
        for r in recs:
            lb = label("▸ " + r.text, wrap=True)
            lb.setStyleSheet(f"color:{colors.get(r.severity)};")
            self.summary_body.addWidget(lb)


def _empty(ax, text: str = "Not enough data yet") -> None:
    ax.axis("off")
    ax.text(0.5, 0.5, text, ha="center", va="center", color=Theme.color("faint"), transform=ax.transAxes)
