"""
seed_sample_data.py
-------------------
Populates taskflow.db with realistic sample tasks + subtasks + schedule entries
covering 10 days PAST and 30 days FUTURE from today (2026-11-24).

Run:
    python seed_sample_data.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH = Path(r"D:\Downloads\code\projects\AIES_for_Tahsin\taskflow_ai\data\taskflow.db")

TODAY = date(2026, 11, 24)
NOW   = datetime(2026, 11, 24, 10, 0, 0)

def dt(d: date, hour: int = 9, minute: int = 0) -> str:
    return datetime(d.year, d.month, d.day, hour, minute).isoformat()

def ago(days: int) -> date:
    return TODAY - timedelta(days=days)

def ahead(days: int) -> date:
    return TODAY + timedelta(days=days)

# ---------------------------------------------------------------------------
# TASK DEFINITIONS
# Each entry:  (title, description, category, priority, importance,
#               est_min, deadline_date, preferred_start, status,
#               completion, created_offset_days_ago, completed_at_date|None,
#               actual_seconds)
# ---------------------------------------------------------------------------
TASKS = [
    # ── PAST tasks (overdue / completed) ────────────────────────────────────
    (
        "Submit Final Year Project Report",
        "Compile all research chapters and submit the PDF to the department portal.",
        "Academic", 4, 3, 180,
        ago(8),          # deadline already passed
        ago(12),         # preferred_start
        "Completed", 100, 14, ago(9), 10800,
    ),
    (
        "Fix Critical Login Bug",
        "Users cannot log in when 2FA is enabled. Investigate and patch the auth service.",
        "Work", 4, 3, 90,
        ago(6),
        ago(7),
        "Completed", 100, 8, ago(6), 5400,
    ),
    (
        "Grocery Shopping",
        "Weekly groceries: vegetables, fruits, dairy, and household supplies.",
        "Personal", 2, 2, 60,
        ago(5),
        ago(5),
        "Completed", 100, 6, ago(5), 3600,
    ),
    (
        "Team Retrospective Meeting",
        "Conduct the sprint retrospective and document action items in Confluence.",
        "Work", 2, 2, 60,
        ago(4),
        ago(4),
        "Completed", 100, 5, ago(4), 3600,
    ),
    (
        "Overdue: Update Portfolio Website",
        "Refresh project case studies and add the new AI dashboard project.",
        "Project", 3, 2, 120,
        ago(3),          # deadline passed — still not done
        ago(6),
        "In Progress", 40, 7, None, 2880,
    ),
    (
        "Read 'Deep Work' — Chapter 4-6",
        "Continue reading Cal Newport's Deep Work and take notes.",
        "Personal", 1, 2, 90,
        ago(2),
        ago(3),
        "Completed", 100, 4, ago(2), 5400,
    ),
    (
        "Overdue: API Rate-Limit Refactor",
        "Migrate rate-limiting logic from Redis to in-process token bucket.",
        "Work", 3, 3, 150,
        ago(1),          # yesterday deadline — still pending
        ago(5),
        "Pending", 0, 6, None, 0,
    ),
    (
        "Setup CI/CD Pipeline",
        "Configure GitHub Actions for automated tests and Docker image builds.",
        "Project", 3, 3, 120,
        ago(2),
        ago(4),
        "Completed", 100, 5, ago(1), 7200,
    ),

    # ── TODAY / NEAR FUTURE tasks ───────────────────────────────────────────
    (
        "Weekly Team Standup",
        "Lead the Monday standup. Share sprint progress and blockers.",
        "Work", 2, 2, 30,
        TODAY,
        TODAY,
        "In Progress", 50, 1, None, 900,
    ),
    (
        "Database Schema Migration v2",
        "Add `user_preferences` table and migrate existing settings rows.",
        "Work", 3, 3, 90,
        ahead(2),
        TODAY,
        "Pending", 0, 1, None, 0,
    ),
    (
        "Write Unit Tests for Auth Module",
        "Cover login, logout, token refresh, and 2FA flows with pytest.",
        "Work", 3, 2, 120,
        ahead(3),
        ahead(1),
        "Pending", 0, 2, None, 0,
    ),
    (
        "Design System Review",
        "Audit component library for accessibility (WCAG 2.1 AA) compliance.",
        "Project", 2, 2, 90,
        ahead(5),
        ahead(2),
        "Pending", 0, 1, None, 0,
    ),
    (
        "Machine Learning Model Evaluation",
        "Compare XGBoost vs LightGBM on the customer churn dataset.",
        "Academic", 4, 3, 180,
        ahead(5),
        ahead(1),
        "Pending", 0, 3, None, 0,
    ),
    (
        "Morning Jog — This Week",
        "30-min jog every morning before work. Log distance in Strava.",
        "Personal", 1, 2, 30,
        ahead(6),
        TODAY,
        "In Progress", 20, 1, None, 1800,
    ),
    (
        "Client Demo Preparation",
        "Prepare slides and live demo environment for the Q4 product showcase.",
        "Work", 4, 3, 150,
        ahead(7),
        ahead(3),
        "Pending", 0, 2, None, 0,
    ),
    (
        "Refactor Frontend State Management",
        "Replace Redux with Zustand across the dashboard module.",
        "Project", 3, 2, 240,
        ahead(10),
        ahead(4),
        "Pending", 0, 1, None, 0,
    ),

    # ── MID-FUTURE tasks (10-20 days ahead) ─────────────────────────────────
    (
        "Mid-Term Exam Revision — Algorithms",
        "Revise graph algorithms, dynamic programming, and complexity theory.",
        "Academic", 4, 3, 300,
        ahead(12),
        ahead(8),
        "Pending", 0, 1, None, 0,
    ),
    (
        "Sprint Planning — December Sprint",
        "Define backlog items, estimate story points, set sprint goal.",
        "Work", 3, 3, 90,
        ahead(13),
        ahead(13),
        "Pending", 0, 1, None, 0,
    ),
    (
        "Annual Performance Self-Review",
        "Complete self-evaluation form and submit to HR portal by deadline.",
        "Work", 3, 3, 120,
        ahead(15),
        ahead(12),
        "Pending", 0, 2, None, 0,
    ),
    (
        "Build Personal Finance Dashboard",
        "Create a Python + Streamlit app to visualise monthly expenses.",
        "Project", 2, 2, 300,
        ahead(17),
        ahead(10),
        "Pending", 0, 1, None, 0,
    ),
    (
        "Read Research Papers — Transformer Architecture",
        "Read and annotate 3 papers on attention mechanisms for the literature review.",
        "Academic", 3, 3, 180,
        ahead(18),
        ahead(14),
        "Pending", 0, 1, None, 0,
    ),
    (
        "Home Office Declutter",
        "Organise desk, cables, and filing cabinet. Dispose of unused equipment.",
        "Personal", 1, 1, 90,
        ahead(19),
        ahead(16),
        "Pending", 0, 1, None, 0,
    ),

    # ── FAR FUTURE tasks (20-30 days ahead) ─────────────────────────────────
    (
        "Deploy v2.0 to Production",
        "Roll out the new microservices architecture to the production cluster.",
        "Work", 4, 3, 180,
        ahead(22),
        ahead(20),
        "Pending", 0, 1, None, 0,
    ),
    (
        "Write Technical Blog Post",
        "Publish an article on building real-time dashboards with FastAPI + WebSocket.",
        "Project", 2, 2, 120,
        ahead(24),
        ahead(21),
        "Pending", 0, 1, None, 0,
    ),
    (
        "Year-End Budget Review",
        "Analyse spending vs. budget across all categories. Plan for January.",
        "Personal", 2, 2, 90,
        ahead(26),
        ahead(24),
        "Pending", 0, 1, None, 0,
    ),
    (
        "Capstone Project Final Presentation",
        "Deliver 20-min final presentation to faculty panel. Include live demo.",
        "Academic", 4, 3, 120,
        ahead(28),
        ahead(25),
        "Pending", 0, 1, None, 0,
    ),
    (
        "Team Christmas Lunch Planning",
        "Book a restaurant, collect dietary requirements, send calendar invites.",
        "Work", 1, 1, 60,
        ahead(30),
        ahead(27),
        "Pending", 0, 1, None, 0,
    ),
]

# ---------------------------------------------------------------------------
# SUBTASKS per task title (partial list for variety)
# ---------------------------------------------------------------------------
SUBTASK_MAP: dict[str, list[tuple[str, int, bool]]] = {
    "Submit Final Year Project Report": [
        ("Write abstract",          30, True),
        ("Compile bibliography",    45, True),
        ("Format as IEEE template", 30, True),
        ("Proofread final draft",   60, True),
    ],
    "Fix Critical Login Bug": [
        ("Reproduce on staging",        20, True),
        ("Identify root cause",         30, True),
        ("Write patch + unit test",     45, True),
        ("Deploy hotfix to production", 15, True),
    ],
    "Machine Learning Model Evaluation": [
        ("Prepare feature pipeline",    60, False),
        ("Train XGBoost baseline",      45, False),
        ("Train LightGBM",              45, False),
        ("Compare metrics & document",  30, False),
    ],
    "Client Demo Preparation": [
        ("Outline demo script",         30, False),
        ("Prepare slide deck",          60, False),
        ("Set up demo environment",     45, False),
        ("Dry run with team",           30, False),
    ],
    "Refactor Frontend State Management": [
        ("Audit existing Redux usage",  60, False),
        ("Install Zustand",             15, False),
        ("Migrate auth slice",          90, False),
        ("Migrate dashboard slice",     90, False),
        ("Remove Redux dependencies",   30, False),
    ],
    "Deploy v2.0 to Production": [
        ("Run smoke tests on staging",  45, False),
        ("Update k8s manifests",        30, False),
        ("Coordinate maintenance window", 15, False),
        ("Monitor post-deploy metrics", 30, False),
    ],
    "Capstone Project Final Presentation": [
        ("Draft slide deck",            90, False),
        ("Record demo video backup",    30, False),
        ("Rehearse solo",               60, False),
        ("Rehearse with supervisor",    45, False),
    ],
    "Setup CI/CD Pipeline": [
        ("Write GitHub Actions workflow", 60, True),
        ("Add Docker build step",        30, True),
        ("Configure secrets",            20, True),
        ("Test full pipeline run",       30, True),
    ],
    "Database Schema Migration v2": [
        ("Write migration script",      45, False),
        ("Test on dev DB",              30, False),
        ("Backup prod DB",              15, False),
        ("Apply migration",             15, False),
    ],
    "Write Unit Tests for Auth Module": [
        ("Test login flow",             30, False),
        ("Test logout + session expiry", 30, False),
        ("Test 2FA enrollment",         30, False),
        ("Test token refresh",          30, False),
    ],
}

# ---------------------------------------------------------------------------
# SCHEDULE ENTRIES — a sampler (task_title -> [(day_offset, start_h, end_h, status)])
# ---------------------------------------------------------------------------
SCHEDULE_MAP: dict[str, list[tuple[int, int, int, str]]] = {
    "Submit Final Year Project Report":     [(-14, 9, 12, "done"), (-13, 14, 17, "done"), (-10, 9, 11, "done")],
    "Fix Critical Login Bug":               [(-8,  9, 11, "done"), (-7, 14, 15, "done")],
    "Grocery Shopping":                     [(-5, 10, 11, "done")],
    "Overdue: Update Portfolio Website":    [(-6, 15, 17, "missed"), (-2, 9, 11, "missed")],
    "Overdue: API Rate-Limit Refactor":     [(-3, 10, 12, "missed")],
    "Setup CI/CD Pipeline":                 [(-5, 9, 11, "done"), (-4, 13, 15, "done")],
    "Weekly Team Standup":                  [(0,  9, 10, "planned")],
    "Database Schema Migration v2":         [(0, 14, 15, "planned"), (2, 9, 11, "planned")],
    "Write Unit Tests for Auth Module":     [(1, 10, 12, "planned"), (3, 9, 10, "planned")],
    "Design System Review":                 [(2, 14, 16, "planned")],
    "Machine Learning Model Evaluation":    [(1, 9, 12, "planned"), (3, 13, 16, "planned")],
    "Morning Jog — This Week":             [(0, 7, 7, "planned"), (1, 7, 7, "planned"), (2, 7, 7, "planned")],
    "Client Demo Preparation":              [(3, 9, 12, "planned"), (5, 14, 16, "planned")],
    "Refactor Frontend State Management":   [(4, 9, 12, "planned"), (6, 9, 12, "planned"), (8, 9, 12, "planned")],
    "Mid-Term Exam Revision — Algorithms":  [(8, 18, 20, "planned"), (10, 18, 21, "planned"), (11, 10, 13, "planned")],
    "Sprint Planning — December Sprint":    [(13, 10, 12, "planned")],
    "Annual Performance Self-Review":       [(12, 14, 16, "planned")],
    "Build Personal Finance Dashboard":     [(10, 15, 17, "planned"), (14, 15, 17, "planned"), (16, 9, 11, "planned")],
    "Deploy v2.0 to Production":            [(20, 9, 12, "planned"), (21, 9, 10, "planned")],
    "Capstone Project Final Presentation":  [(25, 14, 16, "planned"), (27, 9, 11, "planned")],
}

# ---------------------------------------------------------------------------

def main():
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    inserted_tasks = []

    with conn:
        for (title, desc, cat, pri, imp, est,
             deadline, pref_start, status, comp,
             created_ago, completed_at, actual_secs) in TASKS:

            created_dt = datetime(TODAY.year, TODAY.month, TODAY.day, 9, 0) - timedelta(days=created_ago)
            deadline_str   = datetime(deadline.year, deadline.month, deadline.day, 23, 59).isoformat() if deadline else None
            pref_start_str = pref_start.isoformat() if pref_start else None
            completed_str  = datetime(completed_at.year, completed_at.month, completed_at.day, 17, 0).isoformat() if completed_at else None

            cur = conn.execute(
                """INSERT INTO tasks
                   (title, description, category, priority, importance, estimated_minutes,
                    deadline, preferred_start, status, completion, created_at, completed_at, actual_seconds)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (title, desc, cat, pri, imp, est,
                 deadline_str, pref_start_str, status, comp,
                 created_dt.isoformat(), completed_str, actual_secs)
            )
            task_id = cur.lastrowid
            inserted_tasks.append((task_id, title))
            print(f"  ✔ Task #{task_id}: {title}")

        # Subtasks
        print("\nInserting subtasks…")
        title_to_id = {title: tid for tid, title in inserted_tasks}
        for task_title, subs in SUBTASK_MAP.items():
            tid = title_to_id.get(task_title)
            if not tid:
                continue
            for pos, (stitle, smin, sdone) in enumerate(subs):
                conn.execute(
                    "INSERT INTO subtasks (task_id, title, estimated_minutes, done, position) VALUES (?,?,?,?,?)",
                    (tid, stitle, smin, int(sdone), pos)
                )
            print(f"  ✔ {len(subs)} subtasks → Task: {task_title}")

        # Schedule entries
        print("\nInserting schedule entries…")
        for task_title, slots in SCHEDULE_MAP.items():
            tid = title_to_id.get(task_title)
            if not tid:
                continue
            for (day_offset, start_h, end_h, entry_status) in slots:
                day = TODAY + timedelta(days=day_offset)
                s = datetime(day.year, day.month, day.day, start_h, 0)
                e = datetime(day.year, day.month, day.day, end_h, 30)
                if e <= s:
                    e = s + timedelta(minutes=30)
                conn.execute(
                    """INSERT INTO schedule_entries
                       (task_id, label, start_at, end_at, kind, status, locked, note, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (tid, "", s.isoformat(), e.isoformat(), "task", entry_status, 0, "", NOW.isoformat())
                )
            print(f"  ✔ {len(slots)} schedule entries → {task_title}")

    conn.close()
    print("\n✅ Seed data inserted successfully!")
    print(f"   {len(TASKS)} tasks  |  Categories: Academic, Work, Personal, Project")
    print(f"   Date range: {ago(10)} (past) → {ahead(30)} (future)")


if __name__ == "__main__":
    main()
