"""Regenerates the default knowledge base CSV files (knowledge_base/ and knowledge_base/defaults/)."""
import csv
import shutil
from pathlib import Path

COLS = ["rule_id", "enabled", "fact", "operator", "value", "action", "action_value", "message"]
A = "always"

def R(rid, fact, op, val, action, av, msg):
    return [rid, "true", fact, op, val, action, av, msg]

PRIORITY = [
    R("P001", "is_active", "==", "false", "exclude", "", "Task is {status}, so it is excluded from prioritisation."),
    R("P010", "is_overdue", "==", "true", "add_score", "45", "Deadline has already passed ({hours_overdue} hours ago)."),
    R("P011", "is_overdue", "==", "true", "min_level", "Critical", "Overdue tasks are always Critical."),
    R("P012", "hours_to_deadline", "between", "0..24", "add_score", "40", "Deadline is within 24 hours."),
    R("P013", "hours_to_deadline", "between", "24..48", "add_score", "32", "Deadline is within 48 hours."),
    R("P014", "hours_to_deadline", "between", "48..72", "add_score", "25", "Deadline is within 3 days."),
    R("P015", "hours_to_deadline", "between", "72..168", "add_score", "15", "Deadline is within a week."),
    R("P016", "hours_to_deadline", "between", "168..336", "add_score", "8", "Deadline is within two weeks."),
    R("P017", "hours_to_deadline", ">=", "336", "add_score", "2", "Deadline is more than two weeks away."),
    R("P018", "has_deadline", "==", "false", "add_score", "0", "No deadline is set, so urgency stays low."),
    R("P020", "importance", "==", "3", "add_score", "15", "Importance is High."),
    R("P021", "importance", "==", "2", "add_score", "8", "Importance is Medium."),
    R("P022", "importance", "==", "1", "add_score", "2", "Importance is Low."),
    R("P030", "priority", "==", "4", "add_score", "18", "You marked the priority as Critical."),
    R("P031", "priority", "==", "3", "add_score", "12", "You marked the priority as High."),
    R("P032", "priority", "==", "2", "add_score", "6", "You marked the priority as Medium."),
    R("P033", "priority", "==", "1", "add_score", "1", "You marked the priority as Low."),
    R("P040", "workload_ratio", ">=", "1", "add_score", "15", "Remaining work ({remaining_hours}h) is more than the working time left before the deadline ({available_hours}h)."),
    R("P041", "workload_ratio", "between", "0.6..1", "add_score", "8", "Remaining work ({remaining_hours}h) uses most of the {available_hours}h available before the deadline."),
    R("P043", "remaining_hours", ">=", "6", "add_score", "4", "Large remaining workload ({remaining_hours}h)."),
    R("P050", "is_in_progress", "==", "true", "add_score", "5", "Task is already in progress; finishing it avoids context switching."),
    R("P051", "completion", ">=", "75", "add_score", "4", "Task is nearly complete ({completion}%)."),
    R("P052", "is_overrun", "==", "true", "add_score", "4", "Task is taking longer than estimated."),
    R("P062", "remaining_hours", "<=", "0.5", "add_score", "3", "Quick win: only {remaining_hours}h of work left."),
    R("P090", A, "", "", "add_score", "0", "Task is not yet completed."),
    R("P091", A, "", "", "add_score", "0", "Estimated completion time is {estimated_hours} hours."),
    R("P100", "score", ">=", "60", "classify", "Critical", "Score {score} is in the Critical range (60 or more)."),
    R("P101", "score", "between", "40..60", "classify", "High", "Score {score} is in the High range (40 to 59)."),
    R("P102", "score", "between", "22..40", "classify", "Medium", "Score {score} is in the Medium range (22 to 39)."),
    R("P103", "score", "<", "22", "classify", "Low", "Score {score} is in the Low range (below 22)."),
]

SCHEDULING = [
    R("S001", A, "", "", "set_flag", "spill_next_day", "If a task cannot fit into today's available time, it is moved to the next suitable day."),
    R("S002", A, "", "", "set_flag", "exclude_completed", "Completed and cancelled tasks are removed from future scheduling."),
    R("S003", A, "", "", "tie_margin", "5", "If two tasks have similar priority scores (within 5 points), the one with the earlier deadline goes first."),
    R("S004", A, "", "", "set_flag", "respect_deadlines", "Time before a task's deadline is used first; work only goes past a deadline when nothing else fits."),
    R("S005", A, "", "", "set_flag", "keep_locked", "Blocks you customised manually are never moved or deleted automatically."),
    R("S006", A, "", "", "set_flag", "add_breaks", "A break is inserted after every work block."),
    R("S010", "missed_blocks_recent", ">=", "3", "scale_load", "0.75", "You missed {missed_blocks_recent} blocks in the last 7 days, so the daily workload is reduced by 25%."),
    R("S011", "missed_blocks_recent", ">=", "3", "scale_block", "0.75", "Because of the missed blocks, time blocks are shortened by 25% to be more realistic."),
    R("S012", "missed_blocks_recent", ">=", "6", "scale_load", "0.8", "Many missed blocks ({missed_blocks_recent}): workload is reduced by a further 20%."),
]

BREAKDOWN = [
    R("B001", "estimated_hours", ">", "3", "suggest_breakdown", "90", "Estimated duration is {estimated_hours}h (more than 3h). Splitting it into smaller subtasks makes it easier to schedule and track."),
    R("B002", "estimated_hours", ">", "8", "suggest_breakdown", "120", "This is a very large task ({estimated_hours}h). A breakdown is strongly recommended."),
    R("T001", "title", "contains_any", "management system", "template", "Design the database;Create authentication;Build the dashboard;Develop student management;Develop faculty management;Test the application", "Matched the 'management system' template."),
    R("T002", "title", "contains_any", "application|website|software|platform|system|develop|coding", "template", "Gather requirements;Design the architecture and data model;Implement the core features;Build the user interface;Test and fix bugs;Document and deploy", "Matched the 'software project' template."),
    R("T003", "title", "contains_any", "essay|report|paper|thesis|article|assignment|proposal", "template", "Research and collect sources;Create an outline;Write the first draft;Revise and edit;Proofread and format;Submit", "Matched the 'writing' template."),
    R("T004", "title", "contains_any", "presentation|slides|talk|pitch|demo", "template", "Define the key message and audience;Outline the slides;Create content and visuals;Rehearse the delivery;Final review", "Matched the 'presentation' template."),
    R("T005", "title", "contains_any", "exam|test|quiz|study|revision|revise", "template", "List the topics to cover;Review notes and materials;Practise problems or past papers;Summarise weak areas;Final revision", "Matched the 'exam preparation' template."),
    R("T006", "title", "contains_any", "event|party|trip|travel|wedding|conference", "template", "Set goals and budget;Book venue or transport;Make a detailed plan;Prepare materials;Final checks", "Matched the 'event planning' template."),
    R("T007", "title", "contains_any", "research|experiment|lab|survey", "template", "Define the research question;Review existing literature;Collect data;Analyse the results;Write up the findings", "Matched the 'research' template."),
    R("T010", "category", "==", "academic", "template", "Review the requirements;Gather material and notes;Work through the main content;Check and revise;Submit", "Matched the 'Academic' category template."),
    R("T011", "category", "==", "work", "template", "Clarify requirements;Do the main work;Review with stakeholders;Finalise and deliver", "Matched the 'Work' category template."),
    R("T099", A, "", "", "template", "Plan the approach;Do the first part;Do the second part;Review and polish;Finish and wrap up", "Used the generic breakdown template."),
]

RECO = [
    R("R001", "overdue_count", ">=", "1", "recommend", "warning", "You have {overdue_count} overdue task(s). Finish the oldest first or renegotiate its deadline."),
    R("R002", "completion_rate_week", ">=", "80", "recommend", "success", "Strong week: {completion_rate_week}% of this week's work is done. Keep the same pace."),
    R("R003", "completion_rate_week", "<", "50", "recommend", "warning", "Only {completion_rate_week}% of this week's work is done. Plan fewer tasks per day and protect focus time."),
    R("R004", "on_time_rate", "<", "70", "recommend", "warning", "Only {on_time_rate}% of completed tasks met their deadline. Add buffer time before deadlines."),
    R("R005", "estimate_ratio", ">", "1.3", "recommend", "warning", "Tasks take {estimate_ratio}x longer than estimated. Increase your estimates by about 30%."),
    R("R006", "estimate_ratio", "<", "0.7", "recommend", "info", "You finish faster than estimated ({estimate_ratio}x). You can safely plan a little more per day."),
    R("R007", "missed_blocks_week", ">=", "3", "recommend", "warning", "{missed_blocks_week} scheduled blocks were missed this week. Use shorter blocks and a lower daily limit."),
    R("R008", "focus_hours_week", "<", "2", "recommend", "info", "Only {focus_hours_week}h of tracked focus time this week. Try Pomodoro sessions in the Focus Timer."),
    R("R009", "focus_hours_week", ">=", "10", "recommend", "success", "Excellent focus: {focus_hours_week}h tracked this week. Remember to rest."),
    R("R010", "large_task_count", ">=", "1", "recommend", "info", "{large_task_count} task(s) are longer than 3 hours. Break them into subtasks in the AI Planner."),
    R("R011", "today_load_ratio", ">", "1", "recommend", "warning", "Today's plan is {today_load_percent}% of your daily limit. Consider postponing lower priority work."),
    R("R012", "critical_count", ">=", "3", "recommend", "warning", "{critical_count} critical tasks compete for your attention. Defer or delegate low-value work."),
    R("R013", "active_count", "==", "0", "recommend", "success", "No active tasks. Add new tasks or enjoy the free time."),
    R("R014", "unscheduled_count", ">=", "1", "recommend", "warning", "{unscheduled_count} task(s) do not fit into your available time. Extend working hours, add days or reduce scope."),
    R("R015", "streak_days", ">=", "3", "recommend", "success", "{streak_days}-day productivity streak. Nice consistency."),
    R("R016", "due_today_count", ">=", "1", "recommend", "info", "{due_today_count} task(s) are due today."),
]

FILES = {
    "priority_rules.csv": PRIORITY,
    "scheduling_rules.csv": SCHEDULING,
    "task_breakdown_rules.csv": BREAKDOWN,
    "recommendation_rules.csv": RECO,
}

if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent / "knowledge_base"
    (base / "defaults").mkdir(parents=True, exist_ok=True)
    for name, rows in FILES.items():
        with open(base / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(COLS)
            w.writerows(rows)
        shutil.copyfile(base / name, base / "defaults" / name)
    print("written", len(FILES), "files")
