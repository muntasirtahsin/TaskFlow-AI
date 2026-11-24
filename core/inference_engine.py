"""Knowledge base (CSV) + forward-chaining inference engine.

A rule is: IF <fact> <operator> <value> THEN <action>(<action_value>), with a human readable
`message` template used for explanations. Rules are data, not code: users can edit the CSV files
(or use the Knowledge Base page) and the behaviour of the system changes accordingly.
"""
from __future__ import annotations

import csv
import logging
import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Optional

from utils.constants import KB_COLUMNS, KB_FILES
from utils.validators import validate_rule

log = logging.getLogger(__name__)


@dataclass
class Rule:
    rule_id: str = ""
    enabled: bool = True
    fact: str = ""
    operator: str = "always"
    value: str = ""
    action: str = ""
    action_value: str = ""
    message: str = ""

    def to_row(self) -> dict:
        d = {c: getattr(self, c) for c in KB_COLUMNS}
        d["enabled"] = "true" if self.enabled else "false"
        return d

    @property
    def condition_text(self) -> str:
        if self.operator == "always":
            return "always"
        return f"{self.fact} {self.operator} {self.value}"

    @property
    def action_text(self) -> str:
        return f"{self.action}({self.action_value})" if self.action_value != "" else self.action


@dataclass
class Firing:
    """A rule that matched, with its rendered explanation."""
    rule: Rule
    text: str
    number: Optional[float] = None  # action_value as a number when numeric

    @property
    def action(self) -> str:
        return self.rule.action

    @property
    def action_value(self) -> str:
        return self.rule.action_value


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _coerce(raw):
    if isinstance(raw, (bool, int, float)):
        return raw
    text = str(raw).strip()
    low = text.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    try:
        return float(text)
    except ValueError:
        return low


def _fmt(v):
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.1f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:.0f}"
    return v


class InferenceEngine:
    """Evaluates rules against a dictionary of facts (stateless, deterministic)."""

    @staticmethod
    def matches(rule: Rule, facts: dict) -> bool:
        op = rule.operator
        if op == "always":
            return True
        if rule.fact not in facts or facts[rule.fact] is None:
            return False
        actual = facts[rule.fact]
        try:
            if op == "between":
                lo, hi = (float(x) for x in str(rule.value).split(".."))
                return lo <= float(actual) < hi
            if op in ("in", "contains_any"):
                options = [o.strip().lower() for o in str(rule.value).split("|") if o.strip()]
                text = str(actual).lower()
                return text in options if op == "in" else any(o in text for o in options)
            expected = _coerce(rule.value)
            actual = _coerce(actual)
            if op == "==":
                return actual == expected
            if op == "!=":
                return actual != expected
            a, e = float(actual), float(expected)
            return {"<": a < e, "<=": a <= e, ">": a > e, ">=": a >= e}[op]
        except (ValueError, TypeError, KeyError):
            return False

    def evaluate(self, rules: list[Rule], facts: dict) -> list[Firing]:
        display = _SafeDict({k: _fmt(v) for k, v in facts.items()})
        fired = []
        for rule in rules:
            if not rule.enabled or not self.matches(rule, facts):
                continue
            try:
                text = rule.message.format_map(display)
            except (ValueError, IndexError, KeyError):
                text = rule.message
            num = None
            try:
                num = float(rule.action_value)
            except (TypeError, ValueError):
                pass
            fired.append(Firing(rule, text, num))
        return fired


class KnowledgeBase:
    """Loads, validates, edits and persists the CSV rule files."""

    def __init__(self, kb_dir: Path, defaults_dir: Optional[Path] = None,
                 on_change: Optional[Callable[[str, list[Rule]], None]] = None):
        self.dir = Path(kb_dir)
        self.defaults_dir = Path(defaults_dir) if defaults_dir else self.dir / "defaults"
        self.on_change = on_change
        self.errors: dict[str, list[str]] = {}
        self._rules: dict[str, list[Rule]] = {}
        self.engine = InferenceEngine()
        self.load_all()

    def path(self, name: str) -> Path:
        return self.dir / KB_FILES[name]

    def load_all(self) -> None:
        for name in KB_FILES:
            self.load(name)

    def load(self, name: str) -> list[Rule]:
        path = self.path(name)
        if not path.exists() and (self.defaults_dir / KB_FILES[name]).exists():
            self.dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.defaults_dir / KB_FILES[name], path)
        rules, errors = [], []
        try:
            with open(path, newline="", encoding="utf-8-sig") as fh:
                for line_no, row in enumerate(csv.DictReader(fh), start=2):
                    rule = Rule(
                        rule_id=(row.get("rule_id") or "").strip(),
                        enabled=(row.get("enabled") or "true").strip().lower() not in ("false", "0", "no"),
                        fact=(row.get("fact") or "").strip(),
                        operator=(row.get("operator") or "always").strip(),
                        value=(row.get("value") or "").strip(),
                        action=(row.get("action") or "").strip(),
                        action_value=(row.get("action_value") or "").strip(),
                        message=(row.get("message") or "").strip(),
                    )
                    problems = validate_rule(rule, name)
                    if problems:
                        errors.append(f"line {line_no} ({rule.rule_id or '?'}): {'; '.join(problems)}")
                        continue
                    rules.append(rule)
        except (OSError, csv.Error) as exc:
            errors.append(f"cannot read {path.name}: {exc}")
        for e in errors:
            log.warning("Knowledge base %s: %s", name, e)
        self.errors[name] = errors
        self._rules[name] = rules
        if self.on_change:
            self.on_change(name, rules)
        return rules

    def rules(self, name: str, enabled_only: bool = True) -> list[Rule]:
        rules = self._rules.get(name, [])
        return [r for r in rules if r.enabled] if enabled_only else list(rules)

    def save(self, name: str, rules: list[Rule]) -> None:
        for r in rules:
            problems = validate_rule(r, name)
            if problems:
                raise ValueError(f"Rule '{r.rule_id}': {'; '.join(problems)}")
        ids = [r.rule_id for r in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("Rule IDs must be unique.")
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path(name).with_suffix(".tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=KB_COLUMNS)
            writer.writeheader()
            for r in rules:
                writer.writerow(r.to_row())
        tmp.replace(self.path(name))
        self.load(name)

    def restore_defaults(self, name: str) -> None:
        src = self.defaults_dir / KB_FILES[name]
        if not src.exists():
            raise FileNotFoundError(f"No default file for {name}")
        shutil.copyfile(src, self.path(name))
        self.load(name)

    def evaluate(self, name: str, facts: dict) -> list[Firing]:
        return self.engine.evaluate(self.rules(name), facts)
