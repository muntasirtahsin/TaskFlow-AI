"""Seeds a demo dataset (used for screenshots/tests): python tools/demo_data.py"""
from datetime import datetime, timedelta

from database.models import Task


def seed(ctx):
    n = datetime.now().replace(second=0, microsecond=0)
    d = lambda days, h=17: (n + timedelta(days=days)).replace(hour=h, minute=0)
    rows = [
        ("Complete Assignment", "Academic", 3, 3, 180, d(1), "Operating systems report"),
        ("Build a University Management System", "Project", 2, 3, 720, d(10), ""),
        ("Prepare team presentation", "Work", 3, 2, 120, d(2, 12), "Quarterly review"),
        ("Pay electricity bill", "Personal", 2, 1, 15, d(0, 23), ""),
        ("Study for algorithms exam", "Academic", 3, 3, 240, d(4), ""),
        ("Reply to client emails", "Work", 2, 2, 45, d(0, 20), ""),
        ("Plan weekend trip", "Personal", 1, 1, 90, d(6), ""),
        ("Fix login bug", "Work", 4, 3, 150, d(-1, 10), "Overdue example"),
    ]
    for title, cat, pr, imp, mins, dl, desc in rows:
        ctx.save_task(Task(title=title, category=cat, priority=pr, importance=imp, estimated_minutes=mins, deadline=dl, description=desc))
    done = ctx.save_task(Task(title="Submit lab report", category="Academic", estimated_minutes=60, deadline=d(-2)))
    done.status = "Completed"
    done.actual_seconds = 4200
    ctx.save_task(done)
    ctx.generate_plan()
    return ctx
