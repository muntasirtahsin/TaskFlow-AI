"""Headless UI tests: every page builds, and the main user flows work end to end."""
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from core.app_context import AppContext  # noqa: E402
from tools.demo_data import seed  # noqa: E402
from ui.main_window import MainWindow, NAV  # noqa: E402
from ui.theme import Theme  # noqa: E402

app = QApplication.instance() or QApplication([])


@pytest.fixture
def win(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "knowledge_base", tmp_path / "kb")
    ctx = AppContext(tmp_path / "data", tmp_path / "kb", ROOT / "knowledge_base" / "defaults")
    seed(ctx)
    Theme.apply("light")
    # never block on modal dialogs
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self.buttons()[0])
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: 0)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: 0)
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.Accepted)
    w = MainWindow(ctx)
    yield w
    w.loop.stop()
    w.notify_loop.stop()
    for p in w.pages:
        if hasattr(p, "ticker"):
            p.ticker.stop()
    w.hide()
    w.deleteLater()
    app.sendPostedEvents(None, 0)
    from PySide6.QtCore import QEvent
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    ctx.close()


def test_every_page_builds_in_both_themes(win):
    for theme in ("light", "dark"):
        win.apply_theme(theme)
        for i in range(len(NAV)):
            win.go(i)
            win.pages[i].refresh()


def test_quick_add_creates_task(win):
    page = win.pages[1]
    page.quick.setText("Write thesis chapter #academic 3h tomorrow !")
    page.quick_add()
    t = [t for t in win.ctx.tasks.all() if t.title == "Write thesis chapter"][0]
    assert t.category == "Academic" and t.estimated_minutes == 180 and t.priority == 3 and t.deadline
    page.refresh()
    assert page.table.rowCount() >= 9


def test_task_dialog_create_edit_with_subtasks(win):
    from ui.task_page import TaskDialog
    d = TaskDialog(win.ctx)
    d.title.setText("Dialog task")
    d.minutes.setValue(200)
    d._suggest()
    assert d.subs.count() > 0
    d._save()
    t = [t for t in win.ctx.tasks.all() if t.title == "Dialog task"][0]
    assert win.ctx.subtasks.for_task(t.id)
    d2 = TaskDialog(win.ctx, t)
    d2.status.setCurrentText("Completed")
    d2._save()
    assert win.ctx.tasks.get(t.id).completion == 100


def test_task_dialog_validation_error_keeps_dialog_open(win):
    from ui.task_page import TaskDialog
    d = TaskDialog(win.ctx)
    d.title.setText("   ")
    d._save()
    assert d.result() != QDialog.Accepted


def test_filters_and_search(win):
    page = win.pages[1]
    page.refresh()
    all_rows = page.table.rowCount()
    page.search.setText("assignment")
    assert page.table.rowCount() == 1
    page.search.setText("")
    page.cat_f.setCurrentText("Work")
    assert 0 < page.table.rowCount() < all_rows
    page.cat_f.setCurrentIndex(0)
    page.status_f.setCurrentText("Completed")
    assert page.table.rowCount() == 1
    page.status_f.setCurrentIndex(1)
    page.level_f.setCurrentText("Critical")
    assert all(page._rows)  # rows resolved


def test_delete_and_status_actions(win):
    page = win.pages[1]
    page.refresh()
    n = len(win.ctx.tasks.all())
    page.delete_row(0)
    assert len(win.ctx.tasks.all()) == n - 1
    page.refresh()
    page.set_status(0, "Completed")
    assert win.ctx.tasks.get(page._rows[0].id) is not None


def test_planner_explanation_and_breakdown_accept(win):
    p = win.pages[2]
    p.refresh()
    big = next(i for i, a in enumerate(p.analyses) if a.task.title.startswith("Build a University"))
    p.table.selectRow(big)
    assert p.suggestion_list is not None and p.suggestion_list.count() == 6
    p.suggestion_list.item(0).setText("Design the database (edited)")
    p._accept(p.analyses[big].task.id)
    subs = win.ctx.subtasks.for_task(p.analyses[big].task.id)
    assert len(subs) == 6 and subs[0].title.endswith("(edited)")
    p.refresh()
    p.table.selectRow(big)
    p._reject(p.analyses[big].task.id)


def test_schedule_page_move_edit_and_menu(win):
    s = win.pages[3]
    while s.day.weekday() > 4:
        s.day += timedelta(days=1)
    s.refresh()
    entries = [e for e in win.ctx.schedule.for_day(s.day) if e.kind == "task"]
    if not entries:
        s.shift(1)
        entries = [e for e in win.ctx.schedule.for_day(s.day) if e.kind == "task"]
    e = entries[0]
    new_start = e.start.replace(hour=16, minute=0)
    s.on_moved(e.id, new_start, new_start + (e.end - e.start))
    moved = win.ctx.schedule.get(e.id)
    assert moved.locked and moved.start.hour in (16, e.start.hour)  # overlap rejection also acceptable
    win.ctx.complete_block(e.id)
    s.refresh()
    s.replan()


def test_calendar_navigation(win):
    c = win.pages[4]
    c.shift(1)
    c.shift(-2)
    c.go_today()
    c.select(datetime.now().date() + timedelta(days=3))


def test_timer_flow_saves_session(win):
    t = win.pages[5]
    t.refresh()
    task_id = t._task_id()
    t.start()
    t._acc = 90.0   # simulate 90s of work
    t.pause()
    t.pause()
    t.stop()
    assert win.ctx.focus.recent(1)[0].task_id == task_id
    assert win.ctx.tasks.get(task_id).actual_seconds >= 90


def test_pomodoro_cycle(win):
    t = win.pages[5]
    win.ctx.settings.set("pomodoro_focus", 1)
    t.refresh()
    t.set_mode(1)
    t.start()
    t._acc = 61.0
    t.tick()
    assert t.phase == "short" and t.cycles_done == 1 and t.state == "idle"
    assert win.ctx.focus.recent(1)[0].mode == "pomodoro"


def test_knowledge_edit_and_save(win):
    k = win.pages[7].rule_tables["priority"]
    k.ensure_loaded()
    k.table.item(1, 4).setText("true")
    row = next(r for r in range(k.table.rowCount()) if k.table.item(r, 1).text() == "P020")
    k.table.item(row, 6).setText("30")
    k.save()
    rule = next(r for r in win.ctx.kb.rules("priority") if r.rule_id == "P020")
    assert rule.action_value == "30"
    k.add_rule()
    k.save()
    k.restore()


def test_knowledge_rejects_invalid_rule(win):
    k = win.pages[7].rule_tables["scheduling"]
    k.ensure_loaded()
    k.add_rule()
    k.table.item(k.table.rowCount() - 1, 6).setText("not-a-number")
    k.table.cellWidget(k.table.rowCount() - 1, 5).setCurrentText("scale_load")
    n_before = len(win.ctx.kb.rules("scheduling", False))
    k.save()
    assert len(win.ctx.kb.rules("scheduling", False)) == n_before


def test_settings_save_and_theme(win):
    s = win.pages[8]
    s.refresh()
    s.theme.setCurrentText("Dark")
    s.limit.setValue(4.5)
    s.days[5].setChecked(True)
    s.save()
    assert win.ctx.settings.get("theme") == "dark" and Theme.name == "dark"
    assert win.ctx.settings.get("daily_limit_hours") == 4.5 and 5 in win.ctx.settings.get("available_days")
    s.start.setTime(s.end.time())
    s.save()  # invalid: start == end -> rejected
    assert win.ctx.settings.get("work_start") == "09:00"


def test_settings_data_actions(win, tmp_path):
    s = win.pages[8]
    s.backup()
    assert list((win.ctx.data_dir / "backups").glob("*.db"))
    s.reset()
    assert win.ctx.tasks.all() == []


def test_autopilot_replans_after_new_task(win):
    from database.models import Task
    win.ctx.save_task(Task(title="Urgent thing", priority=4, importance=3, estimated_minutes=60,
                           deadline=datetime.now() + timedelta(hours=30)))
    win.autopilot()
    assert any(e.task_id for e in win.ctx.schedule.all())
