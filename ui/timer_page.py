"""Focus Timer: stopwatch and Pomodoro modes, sessions saved to the database."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Optional

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QFont, QPainter, QPen
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout,
                               QWidget)

from ui.theme import Theme
from ui.widgets import BasePage, Card, EmptyState, PageHeader, bus, label, make_button
from utils.helpers import fmt_minutes, fmt_seconds, now

IDLE, RUNNING, PAUSED = "idle", "running", "paused"


class Ring(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(300, 300)
        self.fraction = 0.0
        self.time_text = "00:00"
        self.caption = "Ready"
        self.color_key = "accent"

    def set_state(self, fraction: float, text: str, caption: str, color_key: str) -> None:
        self.fraction, self.time_text, self.caption, self.color_key = fraction, text, caption, color_key
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(14, 14, self.width() - 28, self.height() - 28)
        pen = QPen(Theme.qcolor("border"), 10)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawEllipse(rect)
        if self.fraction > 0:
            pen.setColor(Theme.qcolor(self.color_key))
            p.setPen(pen)
            p.drawArc(rect, 90 * 16, int(-360 * 16 * min(self.fraction, 1.0)))
        f = QFont(self.font())
        f.setPointSize(40)
        f.setWeight(QFont.Light)
        p.setFont(f)
        p.setPen(Theme.qcolor("text"))
        p.drawText(self.rect().adjusted(0, -12, 0, -12), Qt.AlignCenter, self.time_text)
        f2 = QFont(self.font())
        f2.setPointSize(10)
        p.setFont(f2)
        p.setPen(Theme.qcolor("muted"))
        p.drawText(self.rect().adjusted(0, 70, 0, 70), Qt.AlignCenter, self.caption)


class TimerPage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.state = IDLE
        self.mode = "stopwatch"
        self.phase = "focus"            # focus | short | long (pomodoro only)
        self.cycles_done = 0
        self._acc = 0.0                 # seconds accumulated before the current run segment
        self._t0 = 0.0
        self._started_at: Optional[datetime] = None
        self._phase_len = 0

        lay = self.root_layout()
        self.header = PageHeader("Focus Timer", "Track deep work and save every session to a task")
        lay.addWidget(self.header)
        body = QHBoxLayout()
        body.setSpacing(16)
        lay.addLayout(body, 1)

        main = Card()
        main.lay.setContentsMargins(24, 20, 24, 20)
        main.lay.setSpacing(14)
        seg = QHBoxLayout()
        seg.addStretch()
        self.seg_group = QButtonGroup(self)
        self.btn_stopwatch = make_button("Stopwatch", "seg")
        self.btn_pomo = make_button("Pomodoro", "seg")
        self.btn_stopwatch.setMinimumWidth(110)
        self.btn_pomo.setMinimumWidth(110)
        for i, b in enumerate((self.btn_stopwatch, self.btn_pomo)):
            b.setCheckable(True)
            self.seg_group.addButton(b, i)
            seg.addWidget(b)
        self.btn_stopwatch.setChecked(True)
        self.seg_group.idClicked.connect(self.set_mode)
        seg.addStretch()
        main.lay.addLayout(seg)

        self.task_combo = QComboBox()
        self.task_combo.setMinimumWidth(320)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(label("Task", "muted"))
        row.addWidget(self.task_combo)
        row.addStretch()
        main.lay.addLayout(row)

        self.ring = Ring()
        main.lay.addWidget(self.ring, 0, Qt.AlignHCenter)
        self.phase_label = label("", "muted")
        self.phase_label.setAlignment(Qt.AlignCenter)
        main.lay.addWidget(self.phase_label)

        ctl = QHBoxLayout()
        ctl.addStretch()
        self.start_btn = make_button("Start", "primary", "play", "", self.start)
        self.pause_btn = make_button("Pause", "", "pause", "", self.pause)
        self.stop_btn = make_button("Stop and save", "", "stop", "", self.stop)
        for b in (self.start_btn, self.pause_btn, self.stop_btn):
            b.setMinimumWidth(110)
            ctl.addWidget(b)
        ctl.addStretch()
        main.lay.addLayout(ctl)
        self.hint = label("", "faint")
        self.hint.setAlignment(Qt.AlignCenter)
        main.lay.addWidget(self.hint)
        main.lay.addStretch()
        body.addWidget(main, 3)

        side = Card()
        self.today_lb = label("0m", "statValue")
        side.title_row("Focus today")
        side.lay.addWidget(self.today_lb)
        self.today_sub = label("", "faint")
        side.lay.addWidget(self.today_sub)
        side.lay.addWidget(label("Recent sessions", "h2"))
        self.sessions = QListWidget()
        side.lay.addWidget(self.sessions, 1)
        self.empty = EmptyState("timer", "No sessions yet", "Start the timer to log your first session.")
        side.lay.addWidget(self.empty, 1)
        body.addWidget(side, 2)

        self.ticker = QTimer(self, interval=250)
        self.ticker.timeout.connect(self.tick)
        self.ticker.start()
        self._sync_buttons()
        self._render()

    # ---- helpers -------------------------------------------------------------------------------
    def elapsed(self) -> float:
        return self._acc + (time.monotonic() - self._t0 if self.state == RUNNING else 0.0)

    def _pomo_len(self, phase: str) -> int:
        key = {"focus": "pomodoro_focus", "short": "pomodoro_short", "long": "pomodoro_long"}[phase]
        return int(self.ctx.settings.get(key)) * 60

    def _task_id(self) -> Optional[int]:
        return self.task_combo.currentData()

    def retheme(self) -> None:
        self.ring.update()

    # ---- controls -------------------------------------------------------------------------------
    def set_mode(self, idx: int) -> None:
        if self.state != IDLE:
            self.seg_group.button(0 if self.mode == "stopwatch" else 1).setChecked(True)
            self.hint.setText("Stop the current session before switching mode.")
            return
        self.mode = "stopwatch" if idx == 0 else "pomodoro"
        self.phase, self.cycles_done = "focus", 0
        self._render()

    def start(self) -> None:
        if self.state == IDLE:
            if self._task_id() is None:
                self.hint.setText("Create a task first, then choose it above.")
                return
            self._acc, self._started_at = 0.0, now()
            self._phase_len = self._pomo_len(self.phase) if self.mode == "pomodoro" else 0
        self._t0 = time.monotonic()
        self.state = RUNNING
        self.hint.setText("")
        self._sync_buttons()

    def pause(self) -> None:
        if self.state == RUNNING:
            self._acc = self.elapsed()
            self.state = PAUSED
            self.pause_btn.setText("Resume")
        elif self.state == PAUSED:
            self._t0 = time.monotonic()
            self.state = RUNNING
        self._sync_buttons()

    def stop(self) -> None:
        if self.state == IDLE:
            return
        if self.mode == "stopwatch" or self.phase == "focus":
            self._save_session(int(self.elapsed()), completed=False)
        self.state = IDLE
        self._acc = 0.0
        if self.mode == "pomodoro":
            self.phase = "focus"
        self._sync_buttons()
        self._render()

    def shutdown(self) -> None:
        if self.state != IDLE:
            self.stop()

    def _save_session(self, seconds: int, completed: bool) -> None:
        if self._started_at is None:
            return
        s = self.ctx.log_focus(self._task_id(), self._started_at, self._started_at + timedelta(seconds=seconds),
                               seconds, self.mode, completed)
        if s:
            bus.focus_changed.emit()
            bus.tasks_changed.emit()
            self._refresh_side()
            bus.toast.emit(f"Saved {fmt_minutes(seconds / 60)} focus session")

    def _sync_buttons(self) -> None:
        idle, running = self.state == IDLE, self.state == RUNNING
        self.start_btn.setVisible(idle)
        self.pause_btn.setVisible(not idle)
        self.pause_btn.setText("Pause" if running else "Resume")
        self.stop_btn.setEnabled(not idle)
        self.task_combo.setEnabled(idle)
        self.btn_stopwatch.setEnabled(idle)
        self.btn_pomo.setEnabled(idle)
        if self.mode == "pomodoro" and idle:
            self.start_btn.setText({"focus": "Start focus", "short": "Start break", "long": "Start long break"}[self.phase])

    # ---- tick --------------------------------------------------------------------------------------
    def tick(self) -> None:
        if self.state == RUNNING and self.mode == "pomodoro" and self.elapsed() >= self._phase_len:
            self._phase_finished()
        self._render()

    def _phase_finished(self) -> None:
        n = self.ctx.notifier
        if self.phase == "focus":
            self._save_session(self._phase_len, completed=True)
            self.cycles_done += 1
            long_break = self.cycles_done % int(self.ctx.settings.get("pomodoro_cycles")) == 0
            self.phase = "long" if long_break else "short"
            n.emit("focus_done", "Focus session complete", f"Session {self.cycles_done} done. Time for a {'long ' if long_break else ''}break.")
            n.emit("break", "Break time", f"Rest for {self._pomo_len(self.phase) // 60} minutes.")
        else:
            n.emit("break", "Break over", "Ready for the next focus session?")
            self.phase = "focus"
        self.state = IDLE
        self._acc = 0.0
        self._sync_buttons()
        if self.ctx.settings.get("pomodoro_auto_start"):
            self.start()

    def _render(self) -> None:
        el = self.elapsed()
        if self.mode == "pomodoro":
            length = self._phase_len if self.state != IDLE else self._pomo_len(self.phase)
            remaining = max(0, length - el)
            frac = el / length if length and self.state != IDLE else 0
            names = {"focus": "Focus", "short": "Short break", "long": "Long break"}
            caption = names[self.phase] + (" · paused" if self.state == PAUSED else "")
            self.ring.set_state(frac, fmt_seconds(int(remaining + 0.999)), caption, "accent" if self.phase == "focus" else "success")
            total = int(self.ctx.settings.get("pomodoro_cycles"))
            dots = "".join("●" if i < self.cycles_done % total else "○" for i in range(total))
            self.phase_label.setText(f"Session {self.cycles_done % total + 1 if self.phase == 'focus' else self.cycles_done % total or total} of {total}   {dots}")
        else:
            caption = "Running" if self.state == RUNNING else "Paused" if self.state == PAUSED else "Ready"
            self.ring.set_state((el % 3600) / 3600 if self.state != IDLE else 0, fmt_seconds(int(el)), caption, "accent")
            self.phase_label.setText("Elapsed time is saved to the selected task when you stop.")

    # ---- data -------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        super().refresh()
        current = self._task_id()
        if self.ctx.ui_focus_task:
            current, self.ctx.ui_focus_task = self.ctx.ui_focus_task, None
        if self.state == IDLE:
            self.task_combo.blockSignals(True)
            self.task_combo.clear()
            for t in self.ctx.tasks.active():
                self.task_combo.addItem(t.title, t.id)
            idx = self.task_combo.findData(current)
            self.task_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.task_combo.blockSignals(False)
            self.start_btn.setEnabled(self.task_combo.count() > 0)
            self.hint.setText("" if self.task_combo.count() else "No active tasks. Create a task to start tracking.")
        self._sync_buttons()
        self._refresh_side()
        self._render()

    def _refresh_side(self) -> None:
        secs = self.ctx.focus.seconds_on_day(now().date())
        self.today_lb.setText(fmt_minutes(secs / 60))
        recent = self.ctx.focus.recent(12)
        self.today_sub.setText(f"{self.ctx.focus.total_seconds() / 3600:.1f}h all time")
        self.sessions.clear()
        self.sessions.setVisible(bool(recent))
        self.empty.setVisible(not recent)
        for s in recent:
            t = self.ctx.tasks.get(s.task_id) if s.task_id else None
            it = QListWidgetItem(f"{t.title if t else 'Deleted task'}\n{s.started_at:%b %d, %H:%M}  ·  {fmt_minutes(s.duration_seconds / 60)}  ·  {s.mode}")
            self.sessions.addItem(it)
