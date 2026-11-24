"""Core logic tests: database, rules, priority, scheduling, rescheduling, analytics, data management."""
from datetime import date, datetime, timedelta

import pytest

from core.scheduler import ScheduleParams, overlapping
from database.models import Task
from utils.constants import (ENTRY_DONE, ENTRY_MISSED, ENTRY_PLANNED, KIND_BREAK, KIND_TASK, STATUS_COMPLETED)
from utils.helpers import parse_quick_add
from utils.validators import ValidationError

MON = datetime(2030, 1, 7, 8, 0)  # a Monday, before working hours


def mk(ctx, title="Task", minutes=60, deadline=None, priority=2, importance=2, **kw):
    return ctx.save_task(Task(title=title, estimated_minutes=minutes, deadline=deadline,
                              priority=priority, importance=importance, **kw))


# ---------------------------------------------------------------- database / CRUD
def test_schema_version_and_persistence(tmp_path):
    from core.app_context import AppContext
    import shutil
    from tests.conftest import ROOT
    kb = tmp_path / "kb"
    shutil.copytree(ROOT / "knowledge_base", kb)
    c = AppContext(tmp_path / "d", kb, ROOT / "knowledge_base" / "defaults")
    assert c.db.version == 2
    t = mk(c, "Persist me", 45)
    c.close()
    c2 = AppContext(tmp_path / "d", kb, ROOT / "knowledge_base" / "defaults")
    assert c2.tasks.get(t.id).title == "Persist me"
    c2.close()


def test_task_validation(ctx):
    with pytest.raises(ValidationError):
        ctx.save_task(Task(title="  "))
    with pytest.raises(ValidationError):
        ctx.save_task(Task(title="x", estimated_minutes=1))
    with pytest.raises(ValidationError):
        ctx.save_task(Task(title="x", completion=150))


def test_complete_sets_fields_and_clears_schedule(ctx):
    t = mk(ctx, "A", 60)
    ctx.generate_plan(MON)
    assert ctx.schedule.for_task(t.id)
    t.status = STATUS_COMPLETED
    ctx.save_task(t)
    got = ctx.tasks.get(t.id)
    assert got.completion == 100 and got.completed_at
    assert all(e.end <= datetime.now() for e in ctx.schedule.for_task(t.id)) or not ctx.schedule.for_task(t.id)


def test_cascade_delete(ctx):
    t = mk(ctx, "A", 60)
    ctx.generate_plan(MON)
    ctx.delete_task(t.id)
    assert ctx.schedule.for_task(t.id) == []


def test_transaction_rollback(ctx):
    with pytest.raises(RuntimeError):
        with ctx.db.transaction():
            ctx.tasks.add(Task(title="ghost"))
            raise RuntimeError("boom")
    assert ctx.tasks.search("ghost") == []


# ---------------------------------------------------------------- inference & priority
def test_overdue_is_critical(ctx):
    t = mk(ctx, "Late", 60, deadline=MON - timedelta(days=1), priority=1, importance=1)
    res = ctx.priority.evaluate(t, MON)
    assert res.level == "Critical"
    assert any("passed" in r.text for r in res.reasons)


def test_explainable_critical_example(ctx):
    t = mk(ctx, "Complete Assignment", 180, deadline=MON + timedelta(hours=20), priority=3, importance=3)
    res = ctx.priority.evaluate(t, MON, available_hours=8)
    assert res.level == "Critical"
    texts = " ".join(r.text for r in res.reasons)
    assert "within 24 hours" in texts and "Importance is High" in texts and "3 hours" in texts


def test_levels_ordering_is_deterministic(ctx):
    a = mk(ctx, "soon", 60, deadline=MON + timedelta(days=1), importance=3, priority=3)
    b = mk(ctx, "later", 60, deadline=MON + timedelta(days=20), importance=1, priority=1)
    ra, rb = ctx.priority.evaluate(a, MON), ctx.priority.evaluate(b, MON)
    assert ra.score > rb.score and rb.level == "Low"
    assert ctx.priority.evaluate(a, MON).score == ra.score  # deterministic


def test_completed_excluded(ctx):
    t = mk(ctx, "done", 60, status=STATUS_COMPLETED)
    assert ctx.priority.evaluate(t, MON).excluded


def test_rules_are_editable(ctx):
    rules = ctx.kb.rules("priority", enabled_only=False)
    for r in rules:
        if r.rule_id == "P020":
            r.enabled = False
    ctx.kb.save("priority", rules)
    t = Task(id=1, title="x", importance=3, priority=2)
    res = ctx.priority.evaluate(t, MON)
    assert not any(r.rule_id == "P020" for r in res.reasons)
    ctx.kb.restore_defaults("priority")
    assert any(r.rule_id == "P020" for r in ctx.priority.evaluate(t, MON).reasons)


def test_bad_csv_rows_are_skipped(ctx):
    path = ctx.kb.path("priority")
    path.write_text(path.read_text(encoding="utf-8") + "BAD,true,x,~~,1,add_score,5,oops\n", encoding="utf-8")
    ctx.kb.load("priority")
    assert any("BAD" in e for e in ctx.kb.errors["priority"])
    assert ctx.kb.rules("priority")  # the rest still loads


def test_breakdown_template_and_threshold(ctx):
    t = Task(title="Build a University Management System", estimated_minutes=600)
    s = ctx.analyzer.suggest_breakdown(t)
    assert s and [i.title for i in s.items][:2] == ["Design the database", "Create authentication"]
    assert ctx.analyzer.suggest_breakdown(Task(title="Email", estimated_minutes=30)) is None
    assert ctx.analyzer.suggest_breakdown(Task(title="Email", estimated_minutes=30), force=True)


# ---------------------------------------------------------------- scheduling
def test_schedule_respects_constraints(ctx):
    for i in range(5):
        mk(ctx, f"T{i}", 150, deadline=MON + timedelta(days=5))
    report = ctx.generate_plan(MON)
    entries = ctx.schedule.all()
    assert entries and not overlapping(entries)
    p = ScheduleParams.from_settings(ctx.settings)
    per_day = {}
    for e in entries:
        assert p.is_workday(e.day), "scheduled on a non-working day"
        assert e.start.time() >= p.work_start and e.end.time() <= p.work_end
        if e.kind == KIND_TASK:
            assert e.minutes <= p.max_block
            per_day[e.day] = per_day.get(e.day, 0) + e.minutes
    assert all(m <= p.daily_limit_minutes for m in per_day.values())
    assert any(e.kind == KIND_BREAK for e in entries)
    # every task fully scheduled
    for t in ctx.tasks.all():
        assert sum(e.minutes for e in ctx.schedule.for_task(t.id)) == 150


def test_priority_goes_first_and_deadline_respected(ctx):
    urgent = mk(ctx, "urgent", 120, deadline=MON + timedelta(hours=30), priority=4, importance=3)
    mk(ctx, "chill", 120, priority=1, importance=1)
    ctx.generate_plan(MON)
    first = [e for e in ctx.schedule.all() if e.kind == KIND_TASK][0]
    assert first.task_id == urgent.id
    assert max(e.end for e in ctx.schedule.for_task(urgent.id)) <= urgent.deadline


def test_weekend_and_unavailable_dates_skipped(ctx):
    mk(ctx, "big", 60 * 14, deadline=MON + timedelta(days=14))
    ctx.settings.set("unavailable_dates", [(MON.date() + timedelta(days=1)).isoformat()])
    ctx.generate_plan(MON)
    days = {e.day for e in ctx.schedule.all()}
    assert MON.date() + timedelta(days=1) not in days
    assert all(d.weekday() < 5 for d in days)


def test_overflow_moves_to_next_day(ctx):
    mk(ctx, "huge", 60 * 9, deadline=MON + timedelta(days=10))
    ctx.generate_plan(MON)
    days = {e.day for e in ctx.schedule.all() if e.kind == KIND_TASK}
    assert len(days) >= 2


def test_cannot_meet_deadline_warns(ctx):
    mk(ctx, "impossible", 60 * 5, deadline=MON + timedelta(hours=2))
    report = ctx.generate_plan(MON)
    assert any("cannot be finished before" in w for w in report.warnings)


def test_preferred_period_and_start_date(ctx):
    ctx.settings.set("preferred_period", "afternoon")
    mk(ctx, "pm", 60, preferred_start=MON.date() + timedelta(days=1))
    ctx.generate_plan(MON)
    e = [x for x in ctx.schedule.all() if x.kind == KIND_TASK][0]
    assert e.day >= MON.date() + timedelta(days=1) and e.start.hour >= 12


def test_completed_tasks_not_scheduled(ctx):
    mk(ctx, "done", 60, status=STATUS_COMPLETED)
    ctx.generate_plan(MON)
    assert ctx.schedule.all() == []


# ---------------------------------------------------------------- rescheduling
def test_missed_block_is_rescheduled(ctx):
    t = mk(ctx, "work", 90, deadline=MON + timedelta(days=3))
    ctx.generate_plan(MON)
    first = ctx.schedule.for_task(t.id)[0]
    later = first.end + timedelta(hours=1)
    triggers = ctx.rescheduler.detect_triggers(later)
    assert any(x.kind == "missed" for x in triggers)
    report = ctx.rescheduler.autopilot(later)
    assert report and report.applied
    statuses = [e.status for e in ctx.schedule.for_task(t.id)]
    assert ENTRY_MISSED in statuses and ENTRY_PLANNED in statuses
    new = [e for e in ctx.schedule.for_task(t.id) if e.status == ENTRY_PLANNED]
    assert all(e.start >= later for e in new)
    assert ctx.schedule.recent_changes()  # explanation logged


def test_locked_blocks_survive_replan(ctx):
    t = mk(ctx, "manual", 60)
    mk(ctx, "other", 120)
    ctx.generate_plan(MON)
    e = ctx.schedule.for_task(t.id)[0]
    new_start = datetime(2030, 1, 8, 15, 0)
    ctx.move_block(e.id, new_start, new_start + timedelta(minutes=60))
    mk(ctx, "urgent!", 240, deadline=MON + timedelta(hours=26), priority=4, importance=3)
    ctx.rescheduler.run(MON + timedelta(minutes=5), "test")
    kept = ctx.schedule.get(e.id)
    assert kept and kept.locked and kept.start == new_start
    assert not overlapping(ctx.schedule.all())


def test_new_urgent_task_triggers_and_gets_priority(ctx):
    mk(ctx, "normal", 120, deadline=MON + timedelta(days=7))
    ctx.generate_plan(MON)
    urgent = mk(ctx, "fire", 120, deadline=MON + timedelta(hours=28), priority=4, importance=3)
    report = ctx.rescheduler.autopilot(MON + timedelta(minutes=1))
    assert report is not None
    first = [e for e in ctx.schedule.all() if e.kind == KIND_TASK and e.status == ENTRY_PLANNED][0]
    assert first.task_id == urgent.id


def test_deadline_change_triggers_replan(ctx):
    t = mk(ctx, "dl", 60, deadline=MON + timedelta(days=9))
    mk(ctx, "other", 60, deadline=MON + timedelta(days=5))
    ctx.generate_plan(MON)
    t.deadline = MON + timedelta(hours=26)
    t.priority = 4
    ctx.save_task(t)
    assert any(x.kind == "changed" for x in ctx.rescheduler.detect_triggers(MON + timedelta(minutes=1)))


def test_unavailable_day_replans_with_explanation(ctx):
    mk(ctx, "a", 60 * 8, deadline=MON + timedelta(days=10))
    ctx.generate_plan(MON)
    assert MON.date() in {e.day for e in ctx.schedule.all()}
    ctx.settings.set("unavailable_dates", [MON.date().isoformat()])
    rep = ctx.rescheduler.run(MON, "Unavailable")
    assert MON.date() not in {e.day for e in ctx.schedule.all()}
    assert "moved" in rep.summary or "scheduled" in rep.summary
    assert rep.text()


def test_overrun_reserves_extra_time(ctx):
    t = mk(ctx, "slow", 60, status="In Progress", completion=90)
    t.actual_seconds = 120 * 60
    ctx.save_task(t)
    assert ctx.tasks.get(t.id).remaining_minutes >= 15
    assert any(x.kind == "overrun" for x in ctx.rescheduler.detect_triggers(MON))


def test_misses_reduce_load(ctx):
    for i in range(3):
        mk(ctx, f"t{i}", 60, deadline=MON + timedelta(days=2))
    ctx.generate_plan(MON)
    for e in ctx.schedule.all():
        if e.kind == KIND_TASK:
            ctx.schedule.set_status(e.id, ENTRY_MISSED)
    p = ctx.rescheduler.params(MON + timedelta(days=1))
    assert p.load_factor < 1 and p.block_factor < 1 and p.notes


def test_complete_block_updates_progress(ctx):
    t = mk(ctx, "w", 120)
    ctx.generate_plan(MON)
    e = ctx.schedule.for_task(t.id)[0]
    ctx.complete_block(e.id)
    got = ctx.tasks.get(t.id)
    assert got.completion > 0 and got.status in ("In Progress", "Completed")


def test_manual_overlap_rejected(ctx):
    a = mk(ctx, "a", 60)
    b = mk(ctx, "b", 60)
    ctx.generate_plan(MON)
    ea = [e for e in ctx.schedule.for_task(a.id)][0]
    eb = [e for e in ctx.schedule.for_task(b.id)][0]
    with pytest.raises(ValidationError):
        ctx.move_block(eb.id, ea.start, ea.end)


# ---------------------------------------------------------------- focus / analytics / data
def test_focus_logging_updates_task(ctx):
    t = mk(ctx, "f", 60)
    s = ctx.log_focus(t.id, MON, MON + timedelta(minutes=25), 1500, "pomodoro")
    assert s and ctx.tasks.get(t.id).actual_seconds == 1500
    assert ctx.tasks.get(t.id).status == "In Progress"
    assert ctx.log_focus(t.id, MON, MON, 2, "stopwatch") is None


def test_analytics_overview(ctx):
    now = datetime.now()
    mk(ctx, "o", 60, deadline=now - timedelta(days=1))
    d = mk(ctx, "d", 60, deadline=now + timedelta(days=1))
    d.status = STATUS_COMPLETED
    ctx.save_task(d)
    o = ctx.analytics.overview(now)
    assert o["total"] == 2 and o["completed"] == 1 and o["overdue"] == 1 and o["on_time"] == 1
    assert sum(c for _, c in ctx.analytics.daily_completions(7)) == 1
    assert len(ctx.analytics.monthly_productivity(6)) == 6


def test_recommendations_from_rules(ctx):
    mk(ctx, "o", 60, deadline=datetime.now() - timedelta(days=2))
    recs = ctx.recommendations()
    assert any(r.rule_id == "R001" for r in recs)


def test_backup_restore_export_reset(ctx, tmp_path):
    mk(ctx, "keep", 60)
    b = ctx.data.backup(tmp_path / "b.db")
    ctx.data.reset()
    assert ctx.tasks.all() == []
    ctx.data.restore(b)
    assert [t.title for t in ctx.tasks.all()] == ["keep"]
    assert ctx.data.export_json(tmp_path / "e.json").exists()
    assert len(ctx.data.export_csv(tmp_path / "csv")) == 4
    bad = tmp_path / "bad.db"
    bad.write_text("nope")
    from database.database import DatabaseError
    with pytest.raises(DatabaseError):
        ctx.data.restore(bad)


def test_notifications(ctx):
    now = datetime.now().replace(second=0, microsecond=0)
    t = mk(ctx, "n", 60, deadline=now + timedelta(hours=3))
    mk(ctx, "late", 60, deadline=now - timedelta(hours=3))
    got = []
    ctx.notifier.sink = lambda title, msg: got.append(title)
    assert ctx.notifier.check(now) == 2
    assert ctx.notifier.check(now) == 0  # no duplicates
    ctx.settings.set("notifications_enabled", False)
    assert not ctx.notifier.emit("focus_done", "x", "y")


def test_quick_add_parser():
    r = parse_quick_add("Write report #work 2h tomorrow @15:00 !", today=date(2030, 1, 7))
    assert r["title"] == "Write report" and r["category"] == "Work" and r["estimated_minutes"] == 120
    assert r["deadline"] == datetime(2030, 1, 8, 15, 0) and r["priority"] == 3
    assert parse_quick_add("Call mom")["deadline"] is None
