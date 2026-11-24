"""Per-task analysis: explainable priority + rule-based task breakdown suggestions."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from core.inference_engine import KnowledgeBase
from core.priority_engine import PriorityResult
from core.scheduler import ScheduleParams, Scheduler
from database.models import Subtask, Task
from utils.helpers import now as _now


@dataclass
class BreakdownSuggestion:
    task_id: Optional[int]
    reasons: list[str]
    items: list[Subtask]
    template: str = ""


@dataclass
class TaskAnalysis:
    task: Task
    priority: PriorityResult
    breakdown: Optional[BreakdownSuggestion] = None
    hints: list[str] = field(default_factory=list)


class TaskAnalyzer:
    def __init__(self, scheduler: Scheduler, kb: KnowledgeBase, settings):
        self.scheduler, self.kb, self.settings = scheduler, kb, settings

    def _params(self) -> ScheduleParams:
        return ScheduleParams.from_settings(self.settings)

    def analyze(self, tasks: list[Task], now: Optional[datetime] = None) -> list[TaskAnalysis]:
        """Rank active tasks (most important first) with explanations and hints."""
        now = now or _now()
        params = self._params().apply_rules(self.kb, {"missed_blocks_recent": 0})
        active = [t for t in tasks if t.is_active]
        results = self.scheduler.score_tasks(active, now, params)
        ordered = self.scheduler.ordered(active, results, params)
        out = []
        for t in ordered:
            a = TaskAnalysis(t, results[t.id])
            a.breakdown = self.suggest_breakdown(t)
            if a.breakdown:
                a.hints.append(a.breakdown.reasons[0])
            out.append(a)
        return out

    def analyze_one(self, task: Task, now: Optional[datetime] = None) -> TaskAnalysis:
        now = now or _now()
        params = self._params()
        res = self.scheduler.score_tasks([task], now, params)[task.id if task.id is not None else None] \
            if task.id is not None else self.scheduler.priority.evaluate(task, now)
        a = TaskAnalysis(task, res)
        a.breakdown = self.suggest_breakdown(task)
        return a

    # ---- breakdown --------------------------------------------------------------
    def suggest_breakdown(self, task: Task, force: bool = False) -> Optional[BreakdownSuggestion]:
        """Suggest subtasks when the rules say the task is too large (or always when `force`)."""
        facts = {"estimated_hours": task.estimated_minutes / 60.0, "title": task.title, "category": task.category}
        fired = self.kb.evaluate("breakdown", facts)
        triggers = [f for f in fired if f.action == "suggest_breakdown"]
        if not triggers and not force:
            return None
        template = next((f for f in fired if f.action == "template"), None)
        if template is None:
            return None
        titles = [s.strip() for s in template.action_value.split(";") if s.strip()]
        if not titles:
            return None
        per = max(15, int(round(task.estimated_minutes / len(titles) / 5.0)) * 5)
        items = [Subtask(task_id=task.id, title=t, estimated_minutes=per, position=i) for i, t in enumerate(titles)]
        reasons = [triggers[-1].text] if triggers else ["You asked for a breakdown suggestion."]
        reasons.append(template.text)
        return BreakdownSuggestion(task.id, reasons, items, template.rule.rule_id)

    @staticmethod
    def parts_needed(task: Task, target_minutes: int = 90) -> int:
        return max(1, math.ceil(task.estimated_minutes / target_minutes))
