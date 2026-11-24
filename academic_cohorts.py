"""Resolve dated enrollment from real annual class snapshots, not current grade."""
from datetime import date


def academic_year_for(day: date) -> str:
    start = day.year if day.month >= 7 else day.year - 1
    return f"{start}/{start + 1}"


def index_history(history):
    result = {}
    for row in history:
        if row["student_id"] is None:
            continue
        cohort = result.setdefault(row["academic_year"], {})
        if row["student_id"] in cohort:
            raise ValueError("Duplicate student in annual class history")
        cohort[row["student_id"]] = row
    return result


def enrolled_on(history_row, student, day: date) -> bool:
    if history_row["academic_year"] != academic_year_for(day):
        return False
    exits = [d for d in (history_row.get("graduation_date"), student.get("exit_date")) if d]
    return not exits or day < min(exits)


def roster_on(index, students, day: date):
    return {sid: row for sid, row in index.get(academic_year_for(day), {}).items()
            if sid in students and enrolled_on(row, students[sid], day)}
