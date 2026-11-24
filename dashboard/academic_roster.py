"""Historical roster reads for the isolated dummy preview only."""
from academic_cohorts import academic_year_for
from .db_access import get_cursor


def roster_for(day, *, class_id=None, activity_id=None):
    params=[academic_year_for(day),day,day]
    extra=""
    joins=""
    if class_id is not None:
        extra+=" AND h.class_id=%s"
        params.append(class_id)
    if activity_id is not None:
        joins="JOIN extracurricular_members em ON em.student_id=s.id AND em.extracurricular_id=%s"
        params.insert(0,activity_id)
        if activity_id in (1,7):
            extra+=" AND substring(trim(h.class_name) from '^[1-6]')::int "+("BETWEEN 1 AND 3" if activity_id==1 else "BETWEEN 4 AND 6")
        else:
            extra+=" AND em.active AND (em.joined_at IS NULL OR em.joined_at<=%s)"
            params.append(day)
    with get_cursor() as cur:
        cur.execute(f"""SELECT s.id,s.id AS student_id,h.full_name,h.student_number,h.sequence,h.nisn,
            COALESCE(h.gender,s.gender) AS gender,h.class_id,h.class_name,h.academic_year,
            s.active AS student_active,TRUE AS member_active
            FROM student_class_history h JOIN students s ON s.id=h.student_id {joins}
            WHERE h.academic_year=%s AND (h.graduation_date IS NULL OR %s<h.graduation_date)
              AND (s.exit_date IS NULL OR %s<s.exit_date) {extra}
            ORDER BY h.class_name,COALESCE(h.sequence,9999),h.full_name""",params)
        return [dict(row) for row in cur.fetchall()]


def classes_for(day):
    with get_cursor() as cur:
        cur.execute("""SELECT h.class_id AS id,min(h.class_name) AS name,h.academic_year,
            NULL::jsonb AS metadata,TRUE AS active FROM student_class_history h
            WHERE h.academic_year=%s GROUP BY h.class_id,h.academic_year ORDER BY name""",
            (academic_year_for(day),))
        return [dict(row) for row in cur.fetchall()]


def class_breakdown(day):
    with get_cursor() as cur:
        cur.execute("""SELECT h.class_id AS id,min(h.class_name) AS name,h.academic_year,
            count(*) FILTER(WHERE a.status='masuk') AS masuk,
            count(*) FILTER(WHERE a.status='sakit') AS sakit,
            count(*) FILTER(WHERE a.status='izin') AS izin,
            count(*) FILTER(WHERE a.status='alpa') AS alpa,count(*) AS total_students
            FROM student_class_history h JOIN students s ON s.id=h.student_id
            LEFT JOIN attendance_records a ON a.student_id=h.student_id AND a.class_id=h.class_id AND a.attendance_date=%s
            WHERE h.academic_year=%s AND (h.graduation_date IS NULL OR %s<h.graduation_date)
              AND (s.exit_date IS NULL OR %s<s.exit_date)
            GROUP BY h.class_id,h.academic_year ORDER BY name""",
            (day,academic_year_for(day),day,day))
        return [dict(row) for row in cur.fetchall()]


def history_join(student_expr, day_expr):
    return f"""LEFT JOIN student_class_history academic_history
        ON academic_history.student_id={student_expr} AND academic_history.academic_year=
        to_char({day_expr}-INTERVAL '6 months','YYYY')||'/'||to_char({day_expr}+INTERVAL '6 months','YYYY') """


def activity_detail(activity_id, day):
    with get_cursor() as cur:
        cur.execute("""SELECT h.full_name,h.class_name,a.status
            FROM extracurricular_attendance_records a JOIN students s ON s.id=a.student_id
            JOIN student_class_history h ON h.student_id=a.student_id AND h.academic_year=%s
            WHERE a.extracurricular_id=%s AND a.attendance_date=%s ORDER BY h.class_name,s.full_name""",
            (academic_year_for(day),activity_id,day))
        return [dict(row) for row in cur.fetchall()]


def historical_export_labels(rows):
    if not rows:
        return rows
    with get_cursor() as cur:
        cur.execute("SELECT student_id,academic_year,class_name FROM student_class_history WHERE student_id=ANY(%s)",
            (list({row["student_id"] for row in rows}),))
        lookup={(row["student_id"],row["academic_year"]):row["class_name"] for row in cur.fetchall()}
    for row in rows:
        row["class_name"]=lookup.get((row["student_id"],academic_year_for(row["attendance_date"])),row["class_name"])
    return rows
