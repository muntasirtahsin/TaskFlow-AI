"""Explainable rule-based priority scoring.

Pipeline (all driven by priority_rules.csv):
  1. Build facts about the task (deadline distance, importance, workload ...).
  2. Fire `add_score` rules -> additive score, clamped to 0..100.
  3. Fire `classify` rules on the score -> Critical / High / Medium / Low.
  4. Fire `min_level` rules -> raise (never lower) the level, e.g. overdue => Critical.
Every fired rule contributes a human readable reason, so the result is fully explainable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from core.inference_engine import KnowledgeBase
from database.models import Task
from utils.constants import LEVEL_NONE, LEVEL_RANK, LEVELS
from utils.helpers import now as _now


@dataclass
class Reason:
    rule_id: str
    text: str
    points: float = 0.0


@dataclass
class PriorityResult:
    task_id: Optional[int]
    score: float
    level: str
    reasons: list[Reason] = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    excluded: bool = False

    @property
    def rank(self) -> int:
        return LEVEL_RANK.get(self.level, -1)

    def explanation(self, title: str = "") -> str:
        head = f"Task: {title}\nPriority: {self.level} (score {self.score:.0f}/100)\nReasons:" if title else \
            f"Priority: {self.level} (score {self.score:.0f}/100)\nReasons:"
        return head + "".join(f"\n  - {r.text}" for r in self.reasons)


class PriorityEngine:
    def __init__(self, kb: KnowledgeBase):
        self.kb = kb

    @staticmethod
    def build_facts(task: Task, now: datetime, available_hours: Optional[float] = None) -> dict:
        remaining_h = task.remaining_minutes / 60.0
        facts = {
            "title": task.title, "category": task.category, "status": task.status,
            "importance": task.importance, "priority": task.priority,
            "estimated_hours": round(task.estimated_minutes / 60.0, 2),
            "remaining_hours": round(remaining_h, 2),
            "completion": task.completion,
            "actual_hours": round(task.actual_minutes / 60.0, 2),
            "is_active": task.is_active,
            "is_in_progress": task.status == "In Progress",
            "is_overrun": task.is_active and task.actual_minutes > task.estimated_minutes,
            "has_deadline": task.deadline is not None,
            "is_overdue": False,
        }
        if task.deadline is not None:
            hours = (task.deadline - now).total_seconds() / 3600.0
            facts["hours_to_deadline"] = round(hours, 2)
            facts["days_to_deadline"] = round(hours / 24.0, 2)
            if hours < 0 and task.is_active:
                facts["is_overdue"] = True
                facts["hours_overdue"] = round(-hours, 1)
                del facts["hours_to_deadline"]  # distance rules only apply to future deadlines
            if available_hours is not None and hours >= 0:
                facts["available_hours"] = round(max(available_hours, 0.1), 1)
                facts["workload_ratio"] = round(remaining_h / max(available_hours, 0.1), 2)
        return facts

    def evaluate(self, task: Task, now: Optional[datetime] = None,
                 available_hours: Optional[float] = None) -> PriorityResult:
        now = now or _now()
        facts = self.build_facts(task, now, available_hours)
        reasons: list[Reason] = []

        # stage 1: scoring / exclusion
        score, excluded = 0.0, False
        for f in self.kb.evaluate("priority", facts):
            if f.action == "exclude":
                excluded = True
                reasons.append(Reason(f.rule.rule_id, f.text, 0))
            elif f.action == "add_score":
                score += f.number or 0.0
                reasons.append(Reason(f.rule.rule_id, f.text, f.number or 0.0))
        if excluded:
            return PriorityResult(task.id, 0.0, LEVEL_NONE, reasons, facts, excluded=True)
        score = max(0.0, min(100.0, score))
        facts["score"] = round(score, 1)

        # stage 2: classification on the score (highest matching level wins)
        level = "Low"
        floor_reasons = []
        for f in self.kb.evaluate("priority", facts):
            if f.action == "classify" and f.action_value in LEVEL_RANK:
                if LEVEL_RANK[f.action_value] >= LEVEL_RANK[level]:
                    level = f.action_value
                    class_reason = Reason(f.rule.rule_id, f.text, 0)
                    floor_reasons = [class_reason]
        # stage 3: level floors
        for f in self.kb.evaluate("priority", facts):
            if f.action == "min_level" and f.action_value in LEVEL_RANK:
                if LEVEL_RANK[f.action_value] > LEVEL_RANK[level]:
                    level = f.action_value
                reasons.append(Reason(f.rule.rule_id, f.text, 0))
        reasons.extend(floor_reasons)
        return PriorityResult(task.id, score, level, reasons, facts)

    @staticmethod
    def sort_key_factory(margin: float = 5.0):
        """Comparator: higher score first; scores within `margin` -> earlier deadline first."""
        import functools

        def cmp(a: tuple[PriorityResult, Task], b: tuple[PriorityResult, Task]) -> int:
            ra, ta = a
            rb, tb = b
            if abs(ra.score - rb.score) > margin:
                return -1 if ra.score > rb.score else 1
            da = ta.deadline or datetime.max
            db = tb.deadline or datetime.max
            if da != db:
                return -1 if da < db else 1
            if ra.score != rb.score:
                return -1 if ra.score > rb.score else 1
            return (ta.id or 0) - (tb.id or 0)

        return functools.cmp_to_key(cmp)
