"""Daily Schedule: interactive timeline with drag-to-move, plus change log and day summary."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QHBoxLayout, QListWidget, QListWidgetItem, QMenu, QProgressBar, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from core.scheduler import ScheduleParams
from database.models import ScheduleEntry
from ui import icons
from ui.dialogs import BlockDialog, ReportDialog
from ui.theme import CATEGORY_COLORS, Theme
from ui.widgets import (BasePage, Badge, Card, PageHeader, bus, clear_layout, confirm, icon_button, label,
                        make_button, show_error)
from utils.constants import (ENTRY_DONE, ENTRY_MISSED, ENTRY_PLANNED, ENTRY_SKIPPED, KIND_BREAK, KIND_TASK)
from utils.helpers import fmt_date_short, fmt_minutes, now
from utils.validators import ValidationError

PX_PER_HOUR = 68
GUTTER = 58
SNAP_MIN = 5


@dataclass
class Block:
    entry: ScheduleEntry
    title: str
    color: str
    sub: str = ""


class Timeline(QWidget):
    block_moved = Signal(int, object, object)   # entry id, new start, new end
    block_edit = Signal(int)
    block_menu = Signal(int, object)
    add_at = Signal(object)

    def __init__(self):
        super().__init__()
        self.day: date = date.today()
        self.blocks: list[Block] = []
        self.start_h, self.end_h = 7, 21
        self.work: tuple[int, int] = (9, 17)
        self._drag: Optional[tuple[Block, float, datetime]] = None
        self._drag_start: Optional[datetime] = None
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._relayout()

    def set_data(self, day: date, blocks: list[Block], work: tuple[int, int]) -> None:
        self.day, self.blocks, self.work = day, blocks, work
        lo = min([work[0]] + [b.entry.start.hour for b in blocks]) - 1
        hi = max([work[1]] + [b.entry.end.hour + (1 if b.entry.end.minute else 0) for b in blocks]) + 1
        self.start_h, self.end_h = max(0, lo), min(24, hi)
        self._relayout()
        self.update()

    def _relayout(self) -> None:
        self.setFixedHeight((self.end_h - self.start_h) * PX_PER_HOUR + 20)

    # ---- geometry ---------------------------------------------------------------------------------
    def y_of(self, dt: datetime) -> float:
        return 10 + ((dt.hour + dt.minute / 60.0) - self.start_h) * PX_PER_HOUR

    def time_at(self, y: float) -> datetime:
        minutes = ((y - 10) / PX_PER_HOUR + self.start_h) * 60
        minutes = max(0, min(24 * 60 - 1, round(minutes / SNAP_MIN) * SNAP_MIN))
        return datetime.combine(self.day, datetime.min.time()) + timedelta(minutes=minutes)

    def rect_of(self, b: Block, dy: float = 0) -> QRectF:
        top, bottom = self.y_of(b.entry.start) + dy, self.y_of(b.entry.end) + dy
        floor = 0 if b.entry.kind == KIND_BREAK else 14
        return QRectF(GUTTER + 6, top + 1, self.width() - GUTTER - 18, max(bottom - top - 2, floor))

    def block_at(self, pos) -> Optional[Block]:
        for b in reversed(self.blocks):
            if self.rect_of(b).contains(pos):
                return b
        return None

    # ---- painting ---------------------------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), Theme.qcolor("surface"))
        faint, border, muted = Theme.qcolor("faint"), Theme.qcolor("border"), Theme.qcolor("muted")
        # working-hours band
        band = QRectF(GUTTER, 10 + (self.work[0] - self.start_h) * PX_PER_HOUR, self.width() - GUTTER,
                      (self.work[1] - self.work[0]) * PX_PER_HOUR)
        p.fillRect(band, Theme.qcolor("surface2"))
        small = QFont(self.font())
        small.setPointSizeF(8.5)
        p.setFont(small)
        for h in range(self.start_h, self.end_h + 1):
            y = 10 + (h - self.start_h) * PX_PER_HOUR
            p.setPen(QPen(border, 1))
            p.drawLine(QPointF(GUTTER, y), QPointF(self.width(), y))
            p.setPen(faint)
            p.drawText(QRectF(0, y - 8, GUTTER - 8, 16), Qt.AlignRight | Qt.AlignVCenter, f"{h:02d}:00")
        for b in self.blocks:
            dy = 0.0
            if self._drag and self._drag[0] is b:
                dy = self._drag_dy
            self._paint_block(p, b, dy)
        n = datetime.now()
        if n.date() == self.day and self.start_h <= n.hour < self.end_h:
            y = self.y_of(n)
            p.setPen(QPen(Theme.qcolor("danger"), 1.6))
            p.drawLine(QPointF(GUTTER - 4, y), QPointF(self.width(), y))
            p.setBrush(Theme.qcolor("danger"))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(GUTTER - 4, y), 4, 4)

    _drag_dy = 0.0

    def _paint_block(self, p: QPainter, b: Block, dy: float) -> None:
        r = self.rect_of(b, dy)
        e = b.entry
        base = QColor(b.color)
        if e.kind == KIND_BREAK:
            if r.height() < 16:
                return
            p.setPen(QPen(Theme.qcolor("border"), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 6, 6)
            p.setPen(Theme.qcolor("faint"))
            f = QFont(self.font())
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.drawText(r.adjusted(8, 0, -4, 0), Qt.AlignVCenter, "Break")
            return
        done, missed, skipped = e.status == ENTRY_DONE, e.status == ENTRY_MISSED, e.status == ENTRY_SKIPPED
        fill = QColor(base)
        fill.setAlpha(60 if (done or skipped) else 46 if Theme.is_dark() else 38)
        p.setBrush(fill)
        pen = QPen(Theme.qcolor("danger") if missed else base, 1.2)
        if missed:
            pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.drawRoundedRect(r, 8, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(base)
        p.drawRoundedRect(QRectF(r.left(), r.top() + 3, 4, r.height() - 6), 2, 2)
        title_font = QFont(self.font())
        title_font.setBold(True)
        title_font.setStrikeOut(done or skipped)
        p.setFont(title_font)
        p.setPen(Theme.qcolor("faint" if (done or skipped) else "text"))
        text_rect = r.adjusted(12, 4, -26, -2)
        fm = QFontMetrics(title_font)
        p.drawText(QRectF(text_rect.left(), text_rect.top(), text_rect.width(), fm.height()), Qt.AlignLeft,
                   fm.elidedText(b.title, Qt.ElideRight, int(text_rect.width())))
        if r.height() > 36:
            sub_font = QFont(self.font())
            sub_font.setPointSizeF(8.5)
            p.setFont(sub_font)
            p.setPen(muted_color())
            status = " · done" if done else " · missed" if missed else " · skipped" if skipped else ""
            p.drawText(QRectF(text_rect.left(), text_rect.top() + fm.height() + 1, text_rect.width(), 16), Qt.AlignLeft,
                       f"{e.start:%H:%M} - {e.end:%H:%M}  ({fmt_minutes(e.minutes)}){status}")
        if e.locked:
            p.drawPixmap(int(r.right() - 20), int(r.top() + 6), icons.pixmap("lock", Theme.color("muted"), 13))

    # ---- mouse ------------------------------------------------------------------------------------------
    def mousePressEvent(self, ev):
        b = self.block_at(ev.position())
        if ev.button() == Qt.LeftButton and b and b.entry.kind == KIND_TASK and b.entry.status != ENTRY_DONE:
            self._drag = (b, ev.position().y(), b.entry.start)
            self._drag_dy = 0.0
            self.setCursor(Qt.ClosedHandCursor)
        elif ev.button() == Qt.RightButton and b:
            self.block_menu.emit(b.entry.id, ev.globalPosition().toPoint())

    def mouseMoveEvent(self, ev):
        if self._drag:
            self._drag_dy = ev.position().y() - self._drag[1]
            self.update()
        else:
            b = self.block_at(ev.position())
            self.setCursor(Qt.OpenHandCursor if b and b.entry.kind == KIND_TASK and b.entry.status != ENTRY_DONE else Qt.ArrowCursor)

    def mouseReleaseEvent(self, ev):
        if self._drag and ev.button() == Qt.LeftButton:
            b, y0, start0 = self._drag
            self._drag = None
            self.setCursor(Qt.ArrowCursor)
            if abs(self._drag_dy) > 6:
                new_start = self.time_at(self.y_of(start0) + self._drag_dy)
                new_end = new_start + (b.entry.end - b.entry.start)
                self._drag_dy = 0
                self.block_moved.emit(b.entry.id, new_start, new_end)
            else:
                self._drag_dy = 0
            self.update()

    def mouseDoubleClickEvent(self, ev):
        b = self.block_at(ev.position())
        if b and b.entry.kind == KIND_TASK:
            self._drag = None
            self.block_edit.emit(b.entry.id)
        elif not b and ev.position().x() > GUTTER:
            self.add_at.emit(self.time_at(ev.position().y()))


def muted_color() -> QColor:
    return Theme.qcolor("muted")


# -------------------------------------------------------------------------------------------------------
class SchedulePage(BasePage):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.day = date.today()
        lay = self.root_layout()
        self.header = PageHeader("Daily Schedule", "")
        for w in (make_button("Unavailable today", "", "x", "Mark this day as unavailable and replan", self.unavailable),
                  make_button("Add block", "", "plus", "Add a manual block", self.add_block),
                  make_button("Replan", "primary", "refresh", "Preview and apply an intelligent replan", self.replan)):
            self.header.layout().addWidget(w)
        lay.addWidget(self.header)

        nav = QHBoxLayout()
        nav.setSpacing(6)
        nav.addWidget(icon_button("left", "Previous day", lambda: self.shift(-1)))
        self.day_label = label("", "h2")
        self.day_label.setMinimumWidth(190)
        self.day_label.setAlignment(Qt.AlignCenter)
        nav.addWidget(self.day_label)
        nav.addWidget(icon_button("right", "Next day", lambda: self.shift(1)))
        nav.addWidget(make_button("Today", on_click=self.today))
        nav.addStretch()
        nav.addWidget(label("Drag blocks to move them · double-click to edit · right-click for more", "faint"))
        lay.addLayout(nav)

        body = QHBoxLayout()
        body.setSpacing(16)
        lay.addLayout(body, 1)
        self.timeline = Timeline()
        self.timeline.block_moved.connect(self.on_moved)
        self.timeline.block_edit.connect(self.edit_block)
        self.timeline.block_menu.connect(self.block_menu)
        self.timeline.add_at.connect(self.add_block_at)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.timeline)
        self.scroll.setStyleSheet(f"QScrollArea {{ border:1px solid {Theme.color('border')}; border-radius:12px; background:{Theme.color('surface')}; }}")
        body.addWidget(self.scroll, 5)

        side = QVBoxLayout()
        side.setSpacing(14)
        self.summary = Card()
        self.summary.title_row("Day summary")
        self.sum_body = QVBoxLayout()
        self.summary.lay.addLayout(self.sum_body)
        side.addWidget(self.summary)
        self.log_card = Card()
        self.log_card.title_row("Schedule changes")
        self.log = QListWidget()
        self.log.itemActivated.connect(self.show_change)
        self.log.itemClicked.connect(self.show_change)
        self.log_card.lay.addWidget(self.log, 1)
        side.addWidget(self.log_card, 1)
        body.addLayout(side, 2)
        self._changes = []

    def retheme(self) -> None:
        self.scroll.setStyleSheet(f"QScrollArea {{ border:1px solid {Theme.color('border')}; border-radius:12px; background:{Theme.color('surface')}; }}")

    # ---- navigation ------------------------------------------------------------------------------------
    def shift(self, days: int) -> None:
        self.day += timedelta(days=days)
        self.refresh()

    def today(self) -> None:
        self.day = date.today()
        self.refresh()

    # ---- data ----------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        super().refresh()
        rel = fmt_date_short(self.day)
        self.day_label.setText((f"{rel}  ·  {self.day:%b %d}" if rel in ("Today", "Tomorrow", "Yesterday") else f"{self.day:%A, %b %d}").replace(" 0", " "))
        self.header.subtitle.setText(self.day.strftime("%A") + ("  (not a working day)" if not ScheduleParams.from_settings(self.ctx.settings).is_workday(self.day) else ""))
        params = ScheduleParams.from_settings(self.ctx.settings)
        entries = self.ctx.schedule.for_day(self.day)
        blocks = []
        for e in entries:
            t = self.ctx.tasks.get(e.task_id) if e.task_id else None
            if e.kind == KIND_BREAK:
                blocks.append(Block(e, "Break", Theme.color("faint")))
            else:
                color = CATEGORY_COLORS.get(t.category, "#9AA1AF") if t else Theme.color("accent")
                blocks.append(Block(e, t.title if t else (e.label or "Block"), color))
        self.timeline.set_data(self.day, blocks, (params.work_start.hour, params.work_end.hour + (1 if params.work_end.minute else 0)))
        if self.day == date.today():
            first = now().hour - 1
            self.scroll.verticalScrollBar().setValue(max(0, (first - self.timeline.start_h) * PX_PER_HOUR))
        else:
            self.scroll.verticalScrollBar().setValue(0)
        self._summary(entries, params)
        self._log()

    def _summary(self, entries, params) -> None:
        clear_layout(self.sum_body)
        work = [e for e in entries if e.kind == KIND_TASK and e.status != ENTRY_SKIPPED]
        planned = sum(e.minutes for e in work)
        done = sum(e.minutes for e in work if e.status == ENTRY_DONE)
        limit = params.daily_limit_minutes
        self.sum_body.addWidget(label(f"{planned / 60:.1f}h planned of {limit / 60:.1f}h limit", "h2"))
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(min(100, int(100 * planned / limit)) if limit else 0)
        if planned > limit:
            bar.setStyleSheet(f"QProgressBar::chunk {{ background:{Theme.color('danger')}; }}")
        self.sum_body.addWidget(bar)
        self.sum_body.addWidget(label(f"{len(work)} blocks  ·  {fmt_minutes(done)} done", "muted"))
        if planned > limit:
            self.sum_body.addWidget(label("This day is over your workload limit.", "muted"))
        missed = [e for e in work if e.status == ENTRY_MISSED]
        if missed:
            self.sum_body.addWidget(Badge(f"{len(missed)} missed", Theme.color("danger")))
        if not work:
            self.sum_body.addWidget(label("Nothing scheduled. Use Replan or double-click the timeline.", "faint", wrap=True))

    def _log(self) -> None:
        self.log.clear()
        self._changes = self.ctx.schedule.recent_changes(25)
        if not self._changes:
            it = QListWidgetItem("No changes yet.")
            it.setFlags(Qt.NoItemFlags)
            self.log.addItem(it)
        for c in self._changes:
            it = QListWidgetItem(f"{c.created_at:%b %d, %H:%M}\n{c.summary}")
            it.setData(Qt.UserRole, c.id)
            self.log.addItem(it)

    def show_change(self, item) -> None:
        cid = item.data(Qt.UserRole)
        c = next((x for x in self._changes if x.id == cid), None)
        if c:
            class _R:
                summary = c.summary

                @staticmethod
                def text():
                    return c.details or c.summary
            ReportDialog(_R, f"Schedule change - {c.created_at:%b %d, %H:%M}", self, apply_button=False).exec()

    # ---- actions ----------------------------------------------------------------------------------------------------
    def replan(self) -> None:
        report = self.ctx.preview_replan("Manual replan")
        dlg = ReportDialog(report, "Replan preview", self, apply_button=report.has_changes)
        if dlg.exec() and report.has_changes:
            self.ctx.apply_report(report)
            bus.schedule_changed.emit()
            bus.toast.emit(report.summary)
        elif not report.has_changes:
            self.ctx.rescheduler.settings.set("last_plan_signature", report.signature)

    def unavailable(self) -> None:
        if confirm(self, f"Mark {fmt_date_short(self.day)} as unavailable?",
                   "Work planned for this day will be moved to the next suitable days. You will see an explanation afterwards.",
                   "Mark unavailable", danger=False):
            report = self.ctx.mark_unavailable(self.day)
            bus.data_changed()
            ReportDialog(report, "Schedule updated", self, apply_button=False).exec()

    def add_block(self) -> None:
        if BlockDialog(self.ctx, day=self.day, parent=self).exec():
            bus.schedule_changed.emit()

    def add_block_at(self, dt: datetime) -> None:
        dlg = BlockDialog(self.ctx, day=dt.date(), parent=self)
        from PySide6.QtCore import QTime
        dlg.start.setTime(QTime(dt.hour, dt.minute))
        dlg.end.setTime(QTime(min(dt.hour + 1, 23), dt.minute))
        if dlg.exec():
            bus.schedule_changed.emit()

    def on_moved(self, entry_id: int, start: datetime, end: datetime) -> None:
        try:
            self.ctx.move_block(entry_id, start, end)
            bus.toast.emit("Block moved and locked - automatic replanning will leave it alone.")
        except ValidationError as exc:
            show_error(self, str(exc), "Cannot move block")
        bus.schedule_changed.emit()

    def edit_block(self, entry_id: int) -> None:
        e = self.ctx.schedule.get(entry_id)
        if e and BlockDialog(self.ctx, e, parent=self).exec():
            bus.schedule_changed.emit()

    def block_menu(self, entry_id: int, pos) -> None:
        e = self.ctx.schedule.get(entry_id)
        if not e:
            return
        m = QMenu(self)
        if e.kind == KIND_BREAK:
            m.addAction("Delete break", lambda: self._delete(entry_id))
        else:
            if e.status != ENTRY_DONE:
                m.addAction("Mark done", lambda: self._act(self.ctx.complete_block, entry_id))
            else:
                m.addAction("Mark not done", lambda: self._act(self.ctx.reopen_block, entry_id))
            if e.status == ENTRY_PLANNED:
                m.addAction("Skip this block", lambda: self._act(self.ctx.skip_block, entry_id))
            if e.status in (ENTRY_SKIPPED, ENTRY_MISSED):
                m.addAction("Plan again", lambda: self._act(self.ctx.reopen_block, entry_id))
            m.addAction("Edit...", lambda: self.edit_block(entry_id))
            m.addAction("Unlock (let AI move it)" if e.locked else "Lock in place", lambda: self._act(self.ctx.toggle_lock, entry_id))
            if e.task_id:
                m.addAction("Start focus session", lambda: self._focus(e.task_id))
            m.addSeparator()
            m.addAction("Delete block", lambda: self._delete(entry_id))
        m.exec(pos)

    def _act(self, fn, entry_id: int) -> None:
        try:
            fn(entry_id)
        except Exception as exc:
            show_error(self, str(exc))
        bus.data_changed()

    def _delete(self, entry_id: int) -> None:
        self.ctx.delete_block(entry_id)
        bus.schedule_changed.emit()

    def _focus(self, task_id: int) -> None:
        self.ctx.ui_focus_task = task_id
        bus.navigate.emit(5)
