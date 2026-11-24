"""Local, rule-based recommendations (recommendation_rules.csv)."""
from __future__ import annotations

from dataclasses import dataclass

from core.inference_engine import KnowledgeBase


@dataclass
class Recommendation:
    rule_id: str
    severity: str  # info | warning | success
    text: str


class RecommendationEngine:
    ORDER = {"warning": 0, "info": 1, "success": 2}

    def __init__(self, kb: KnowledgeBase):
        self.kb = kb

    def generate(self, facts: dict) -> list[Recommendation]:
        facts = dict(facts)
        if "today_load_ratio" in facts:
            facts["today_load_percent"] = round(facts["today_load_ratio"] * 100)
        recs = [Recommendation(f.rule.rule_id, f.action_value if f.action_value in self.ORDER else "info", f.text)
                for f in self.kb.evaluate("recommendation", facts)]
        return sorted(recs, key=lambda r: self.ORDER[r.severity])

    @staticmethod
    def weekly_summary(facts: dict, recs: list[Recommendation]) -> str:
        lines = ["Weekly productivity summary (last 7 days)", ""]
        lines.append(f"- Tasks completed: {facts.get('tasks_completed_week', 0)}")
        if "completion_rate_week" in facts:
            lines.append(f"- Completion rate: {facts['completion_rate_week']}%")
        if "on_time_rate" in facts:
            lines.append(f"- Completed on time (30 days): {facts['on_time_rate']}%")
        lines.append(f"- Focus time: {facts.get('focus_hours_week', 0)}h")
        lines.append(f"- Missed scheduled blocks: {facts.get('missed_blocks_week', 0)}")
        if "estimate_ratio" in facts:
            lines.append(f"- Actual vs estimated time: {facts['estimate_ratio']}x")
        lines.append("")
        lines.append("Suggestions")
        lines += [f"- {r.text}" for r in recs] or ["- Nothing to flag. Keep going."]
        return "\n".join(lines)
