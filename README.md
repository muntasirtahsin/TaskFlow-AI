# TaskFlow AI

An offline, autonomous task manager and time planner for the desktop. It analyses your tasks with a
rule-based expert system, explains every priority it assigns, builds a constraint-based daily schedule
and **re-plans automatically** when reality changes (missed blocks, overruns, new urgent tasks, changed
deadlines, days off).

No cloud, no AI API, no account, no internet: everything runs locally with Python, SQLite and CSV rules.

## Setup

Requires Python 3.10+ (developed on 3.15) on Windows, macOS or Linux.

```powershell
cd taskflow_ai
python -m pip install -r requirements.txt
python main.py
```

Run the test-suite (50 tests: core logic and headless UI flows):

```powershell
python -m pytest tests -q
```

Your data lives in `data/taskflow.db` (SQLite, created on first start and kept across restarts).
Logs are written to `data/logs/taskflow.log`, backups to `data/backups/`.

## Using the app

| Page | What it does |
|---|---|
| **Dashboard** | Totals, overdue / due today, today's scheduled hours and productivity %, today's workload, upcoming deadlines, status and completion charts, rule-based advice. "Plan my day" re-plans instantly. |
| **My Tasks** | Create, edit, delete, search, filter (status, category, AI priority) and sort tasks. Quick-add bar: `Write report #work 2h tomorrow @15:00 !` (`#category`, `2h`/`90m`, `today`/`tomorrow`/weekday/`YYYY-MM-DD`, `@HH:MM`, `!` High, `!!` Critical). Right-click for status changes, focus session, breakdown. `Ctrl+N` creates a task anywhere. |
| **AI Planner** | Ranks active tasks and shows *why* each got its priority (every fired rule with its points and rule ID). Suggests task breakdowns from templates: tick, edit or reject the proposed subtasks. Shows local recommendations, previews replans. |
| **Daily Schedule** | Interactive timeline. Drag a block to move it, double-click to edit, double-click empty space to add a block, right-click for done / skip / lock / delete / focus. Manually changed blocks are **locked** and never moved by the AI. A change log explains every automatic re-plan. |
| **Calendar** | Month view with deadlines, planned workload and unavailable days; click a day for its agenda. |
| **Focus Timer** | Stopwatch or Pomodoro (configurable focus / short / long break / cycles). Pause, resume, stop. Every session is saved to the selected task and adds to its time spent. |
| **Analytics** | Daily / weekly / monthly completion, completed vs pending, on-time vs late, focus time, average time per task, estimated vs actual duration, plus a weekly summary with suggestions. |
| **Knowledge Base** | View and edit all expert-system rules (4 CSV files) in tables. Add / delete / disable rules, restore defaults. Changes take effect immediately. |
| **Settings** | Theme, working hours and days, daily limit, breaks, max continuous work, preferred period, default duration, planning horizon, unavailable dates, notifications, Pomodoro, autonomous mode, backup / restore, JSON & CSV export, reset. |

## How the AI works

Everything intelligent is a **knowledge base of rules** (`knowledge_base/*.csv`) executed by a small
forward-chaining **inference engine** (`core/inference_engine.py`). A rule is

```
IF <fact> <operator> <value>  THEN  <action>(<action_value>)      + a message template used for the explanation
```

CSV columns: `rule_id, enabled, fact, operator, value, action, action_value, message`.
Operators: `< <= > >= == != between in contains_any always`.

* **`priority_rules.csv`**: `add_score` rules (deadline urgency, importance, user priority, remaining workload vs available
  working time, in-progress / nearly done / overrun), `classify` rules (score -> Critical / High / Medium / Low),
  `min_level` rules (overdue => Critical) and `exclude` (finished tasks). Scores are deterministic, never random.
* **`scheduling_rules.csv`**: policies for the scheduler: move to next day when a day is full, drop completed tasks, tie-break
  similar scores by earlier deadline, keep manual blocks, add breaks, and *reduce daily load and block length when blocks are
  repeatedly missed*.
* **`task_breakdown_rules.csv`**: when to suggest a breakdown (e.g. > 3 h) and the subtask templates (software project,
  management system, essay / report, presentation, exam, event, research, category and generic fallbacks).
* **`recommendation_rules.csv`**: advice for the dashboard, planner and weekly summary.

Example explanation (AI Planner):

```
Task: Complete Assignment
Priority: Critical (score 67/100)
Reasons:
  - Deadline is within 24 hours.
  - Importance is High.
  - You marked the priority as High.
  - Task is not yet completed.
  - Estimated completion time is 3 hours.
  - Score 67 is in the Critical range (60 or more).
```

### Scheduling (`core/scheduler.py`)

Tasks are ranked by priority score (similar scores: earlier deadline first). Remaining work is split into blocks and placed
in the earliest free slot that respects: working window, available weekdays, unavailable dates, daily workload limit, maximum
continuous block, minimum block, preferred period, preferred start date, locked blocks and non-overlap. A break is inserted
between blocks. Work is placed **before the deadline first**; anything that cannot fit is placed afterwards and flagged as
late, or reported as unscheduled. Overflow moves to the next suitable day.

### Autonomous rescheduling (`core/rescheduler.py`)

A background loop (every minute, plus after every task / settings change) detects: missed blocks, time overruns, new or
changed tasks (deadline, priority, importance, size), unavailable days with planned work, tasks without time, and overloaded
days. When something actionable is found it computes a proposal, applies it in **one transaction** and writes an explanation to
the change log (and shows a notification). Manual re-plans always show a preview first ("Replan" / "Preview replan") with the
reasons and every move. Locked (manually customised) blocks are never changed; conflicts with them are reported as warnings.
Turn this off under *Settings -> Autonomous mode*.

## Project layout

```
taskflow_ai/
├── main.py                  entry point
├── requirements.txt
├── ui/                      PySide6 pages, theme, icons, shared widgets, dialogs
├── core/                    inference_engine, priority_engine, scheduler, rescheduler, task_analyzer,
│                            recommendation_engine, notification_manager, analytics, data_manager, app_context
├── database/                database.py (schema + migrations), models.py, repositories.py
├── knowledge_base/          the four rule CSVs (+ defaults/ used by "Restore defaults")
├── utils/                   constants, helpers, validators
├── assets/                  icons and the QSS stylesheet template (themes are generated from tokens)
├── tools/                   build_kb.py (regenerates default rules), demo_data.py, screenshots.py
├── tests/                   pytest suite
└── data/                    taskflow.db, logs, backups (created at runtime)
```

`core/` contains no Qt code; `AppContext` is the only object the UI talks to, so all logic is testable headlessly.

## Database

SQLite with foreign keys, CHECK constraints and versioned migrations (`PRAGMA user_version`): `tasks`, `subtasks`,
`schedule_entries`, `focus_sessions`, `kb_rules` (mirror of the CSV rules), `settings`, `productivity_records`,
`schedule_changes` (re-plan log). All multi-step writes run in transactions with rollback on error.

## Notifications

Desktop notifications (system tray balloon / native toast where supported, in-app toast otherwise) for upcoming scheduled
blocks, approaching deadlines, overdue tasks, finished focus sessions, break reminders and schedule changes. Each type can be
switched off and the lead times are configurable.

## Notes

* All times are local, naive datetimes.
* Editing a CSV file by hand works too: use *Reload file* on the Knowledge Base page. Invalid rows are skipped and logged.
* To render every page to PNG for a visual check: `python tools/screenshots.py out_dir [dark]`.
