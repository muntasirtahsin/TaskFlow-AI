"""Constraint-based daily scheduler.

Constraints honoured: working window, available weekdays, unavailable dates, daily workload limit,
maximum continuous block, breaks between blocks, preferred working period, deadlines, preferred
start dates, locked (manually customised) blocks and non-overlap.

Strategy: tasks are ranked by the explainable priority score (ties -> earlier deadline), then each
task's remaining work is split into blocks and placed into the earliest free slot that satisfies the
constraints. Work is first placed *before* the deadline; only what cannot fit is placed afterwards and
flagged as late. Everything that cannot be placed inside the horizon is reported as unscheduled.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

from core.inference_engine import KnowledgeBase
from core.priority_engine import PriorityEngine, PriorityResult
from database.models import ScheduleEntry, Task
from utils.constants import ENTRY_DONE, ENTRY_PLANNED, KIND_BREAK, KIND_TASK
from utils.helpers import at, fmt_deadline, parse_date, parse_hhmm, round_up

log = logging.getLogger(__name__)

Interval = tuple[datetime, datetime]
PERIODS = {"morning": (time(0, 0), time(12, 0)), "afternoon": (time(12, 0), time(17, 0)), "evening": (time(17, 0), time(23, 59))}


@dataclass
class ScheduleParams:
    work_start: time = time(9, 0)
    work_end: time = time(17, 0)
    days: set = field(default_factory=lambda: {0, 1, 2, 3, 4})
    break_minutes: int = 10
    max_block: int = 90
    min_block: int = 25
    preferred_period: str = "any"
    daily_limit_minutes: float = 360
    horizon_days: int = 21
    unavailable: set = field(default_factory=set)
    load_factor: float = 1.0
    block_factor: float = 1.0
    tie_margin: float = 5.0
    flags: set = field(default_factory=lambda: {"spill_next_day", "exclude_completed", "respect_deadlines", "keep_locked", "add_breaks"})
    notes: list = field(default_factory=list)  # explanations of rules that changed the parameters

    @classmethod
    def from_settings(cls, settings) -> "ScheduleParams":
        unavailable = set()
        for s in settings.get("unavailable_dates") or []:
            try:
                unavailable.add(parse_date(s))
            except ValueError:
                pass
        return cls(
            work_start=parse_hhmm(settings.get("work_start")), work_end=parse_hhmm(settings.get("work_end")),
            days=set(settings.get("available_days")), break_minutes=int(settings.get("break_minutes")),
            max_block=int(settings.get("max_continuous_minutes")), min_block=int(settings.get("min_block_minutes")),
            preferred_period=settings.get("preferred_period"),
            daily_limit_minutes=float(settings.get("daily_limit_hours")) * 60,
            horizon_days=int(settings.get("horizon_days")), unavailable=unavailable)

    def apply_rules(self, kb: KnowledgeBase, facts: dict) -> "ScheduleParams":
        """Run scheduling_rules.csv; flags are rebuilt from the rules so disabling a rule disables the policy."""
        self.flags = set()
        for f in kb.evaluate("scheduling", facts):
            a = f.action
            if a == "scale_load" and f.number:
                self.load_factor *= f.number
                self.notes.append(f.text)
            elif a == "scale_block" and f.number:
                self.block_factor *= f.number
                self.notes.append(f.text)
            elif a == "tie_margin" and f.number is not None:
                self.tie_margin = f.number
            elif a == "set_flag":
                self.flags.add(f.action_value)
        if "add_breaks" not in self.flags:
            self.break_minutes = 0
        return self

    # -- helpers
    def is_workday(self, d: date) -> bool:
        return d.weekday() in self.days and d not in self.unavailable

    @property
    def effective_max_block(self) -> int:
        return max(self.min_block, int(self.max_block * self.block_factor))

    @property
    def day_capacity(self) -> float:
        return self.daily_limit_minutes * self.load_factor


@dataclass
class PlanResult:
    entries: list[ScheduleEntry] = field(default_factory=list)
    unscheduled: dict = field(default_factory=dict)   # task_id -> minutes that could not be placed
    late: dict = field(default_factory=dict)          # task_id -> datetime the work finishes (after deadline)
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    results: dict = field(default_factory=dict)       # task_id -> PriorityResult


# ---------------------------------------------------------------------------
def capacity_hours(params: ScheduleParams, now: datetime, deadline: datetime) -> float:
    """Working hours available between now and deadline (respecting days, window and daily limit)."""
    total = 0.0
    day = now.date()
    while day <= deadline.date() and (day - now.date()).days <= 400:
        if params.is_workday(day):
            start, end = at(day, params.work_start), at(day, params.work_end)
            start, end = max(start, now), min(end, deadline)
            if end > start:
                total += min((end - start).total_seconds() / 60.0, params.day_capacity)
        day += timedelta(days=1)
    return total / 60.0


def _subtract(intervals: list[Interval], s: datetime, e: datetime) -> list[Interval]:
    out = []
    for a, b in intervals:
        if e <= a or s >= b:
            out.append((a, b))
            continue
        if a < s:
            out.append((a, s))
        if e < b:
            out.append((e, b))
    return out


def _minutes(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() // 60)


class Scheduler:
    def __init__(self, priority_engine: PriorityEngine, kb: KnowledgeBase):
        self.priority = priority_engine
        self.kb = kb

    # ---- scoring ------------------------------------------------------------
    def score_tasks(self, tasks: list[Task], now: datetime, params: ScheduleParams) -> dict[int, PriorityResult]:
        out = {}
        for t in tasks:
            avail = capacity_hours(params, now, t.deadline) if t.deadline and t.deadline > now else None
            if avail is not None and avail < 0.05:
                avail = None  # no working time at all before the deadline: a calendar problem, not a workload one
            out[t.id] = self.priority.evaluate(t, now, avail)
        return out

    def ordered(self, tasks: list[Task], results: dict, params: ScheduleParams) -> list[Task]:
        key = PriorityEngine.sort_key_factory(params.tie_margin)
        pairs = sorted(((results[t.id], t) for t in tasks), key=key)
        return [t for _, t in pairs]

    # ---- planning -----------------------------------------------------------
    def plan(self, tasks: list[Task], now: datetime, fixed: list[ScheduleEntry],
             params: ScheduleParams, results: Optional[dict] = None) -> PlanResult:
        """Create new (unsaved) entries for `tasks`, working around `fixed` entries."""
        res = PlanResult(notes=list(params.notes))
        candidates = [t for t in tasks if t.is_active and t.remaining_minutes > 0]
        results = results or self.score_tasks(candidates, now, params)
        res.results = results
        order = self.ordered(candidates, results, params)

        start_day = now.date()
        horizon_end = start_day + timedelta(days=params.horizon_days)
        latest_deadline = max((t.deadline.date() for t in candidates if t.deadline), default=start_day)
        horizon_end = min(max(horizon_end, latest_deadline + timedelta(days=1)), start_day + timedelta(days=120))
        days = [start_day + timedelta(days=i) for i in range((horizon_end - start_day).days + 1)]
        if "spill_next_day" not in params.flags:
            days = days[:1]

        # free windows per day (minus fixed entries) and capacity already consumed
        free: dict[date, list[Interval]] = {}
        used: dict[date, float] = {}
        earliest = round_up(now, 5)
        for d in days:
            if not params.is_workday(d):
                continue
            s, e = at(d, params.work_start), at(d, params.work_end)
            s = max(s, earliest)
            windows = [(s, e)] if e > s else []
            used[d] = 0.0
            for fe in fixed:
                if fe.day != d:
                    continue
                windows = _subtract(windows, fe.start, fe.end)
                if fe.kind == KIND_TASK:
                    used[d] += fe.minutes
            free[d] = windows

        # minutes of each task already covered by fixed future blocks
        covered: dict[int, int] = {}
        for fe in fixed:
            if fe.kind == KIND_TASK and fe.task_id and fe.status == ENTRY_PLANNED and fe.end > now:
                covered[fe.task_id] = covered.get(fe.task_id, 0) + fe.minutes

        placed: list[ScheduleEntry] = []
        for task in order:
            remaining = task.remaining_minutes - covered.get(task.id, 0)
            if remaining <= 0:
                continue
            first_day = max(start_day, task.preferred_start or start_day)
            deadline = task.deadline if "respect_deadlines" in params.flags else None
            phases = [deadline, None] if deadline else [None]
            last_end: Optional[datetime] = None
            for phase_limit in phases:
                if remaining <= 0:
                    break
                for d in days:
                    if remaining <= 0:
                        break
                    if d < first_day or d not in free:
                        continue
                    if phase_limit and d > phase_limit.date():
                        break
                    remaining, ends = self._fill_day(d, task, remaining, free, used, params, placed, phase_limit)
                    if ends:
                        last_end = max(ends) if last_end is None else max(last_end, max(ends))
            if task.deadline and last_end and last_end > task.deadline:
                res.late[task.id] = last_end
                res.warnings.append(f"'{task.title}' cannot be finished before its deadline "
                                    f"({fmt_deadline(task.deadline, now)}); work is planned until {fmt_deadline(last_end, now)}.")
            if remaining > 0:
                res.unscheduled[task.id] = remaining
                res.warnings.append(f"'{task.title}': {remaining} minutes do not fit into the next {params.horizon_days} days.")

        res.entries = self._finalise_breaks(placed, params)
        return res

    # ---- internals ----------------------------------------------------------
    def _windows_in_order(self, windows: list[Interval], params: ScheduleParams, d: date) -> list[Interval]:
        if params.preferred_period not in PERIODS:
            return windows
        ps, pe = at(d, PERIODS[params.preferred_period][0]), at(d, PERIODS[params.preferred_period][1])
        inside, outside = [], []
        for a, b in windows:
            lo, hi = max(a, ps), min(b, pe)
            if hi > lo:
                inside.append((lo, hi))
                if a < lo:
                    outside.append((a, lo))
                if hi < b:
                    outside.append((hi, b))
            else:
                outside.append((a, b))
        return sorted(inside) + sorted(outside)

    def _fill_day(self, d: date, task: Task, remaining: int, free, used, params: ScheduleParams,
                  placed: list[ScheduleEntry], limit: Optional[datetime]):
        ends: list[datetime] = []
        cap_left = params.day_capacity - used[d]
        brk = params.break_minutes
        while remaining > 0 and cap_left >= min(params.min_block, remaining):
            want = int(min(remaining, params.effective_max_block, cap_left))
            slot = None
            for a, b in self._windows_in_order(free[d], params, d):
                if limit:
                    b = min(b, limit)
                avail = _minutes(a, b)
                length = min(want, avail)
                if length >= min(want, params.min_block) and length > 0:
                    slot = (a, length)
                    break
            if slot is None:
                break
            start, length = slot
            # keep leftover fragments useful: if what remains afterwards would be tiny, take it too
            tail = remaining - length
            if 0 < tail < params.min_block and length + tail <= params.effective_max_block + params.min_block \
                    and cap_left >= length + tail and any(
                        a <= start and start + timedelta(minutes=length + tail) <= b for a, b in free[d]):
                length += tail
            end = start + timedelta(minutes=length)
            placed.append(ScheduleEntry(task_id=task.id, start=start, end=end, kind=KIND_TASK, status=ENTRY_PLANNED))
            free[d] = _subtract(free[d], start, end + timedelta(minutes=brk))
            used[d] += length
            cap_left -= length
            remaining -= length
            ends.append(end)
        return remaining, ends

    def _finalise_breaks(self, blocks: list[ScheduleEntry], params: ScheduleParams) -> list[ScheduleEntry]:
        """Insert a break after each block when the next block of the day follows within break distance."""
        out = list(blocks)
        if params.break_minutes <= 0:
            return out
        by_day: dict[date, list[ScheduleEntry]] = {}
        for b in blocks:
            by_day.setdefault(b.day, []).append(b)
        for day_blocks in by_day.values():
            day_blocks.sort(key=lambda e: e.start)
            for cur, nxt in zip(day_blocks, day_blocks[1:]):
                gap = _minutes(cur.end, nxt.start)
                if gap >= 5:
                    brk_end = min(nxt.start, cur.end + timedelta(minutes=params.break_minutes))
                    out.append(ScheduleEntry(task_id=None, start=cur.end, end=brk_end, kind=KIND_BREAK,
                                             label="Break"))
        out.sort(key=lambda e: e.start)
        return out


def overlapping(entries: list[ScheduleEntry]) -> list[tuple[ScheduleEntry, ScheduleEntry]]:
    """Return every pair of overlapping entries (used by tests and the UI conflict check)."""
    ordered = sorted(entries, key=lambda e: e.start)
    out = []
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if b.start >= a.end:
                break
            out.append((a, b))
    return out
