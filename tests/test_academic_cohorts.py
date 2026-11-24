from datetime import date
import unittest

from academic_cohorts import academic_year_for,index_history,roster_on


class AcademicCohortTests(unittest.TestCase):
    def setUp(self):
        self.students={1:{"active":True,"exit_date":None},2:{"active":False,"exit_date":date(2026,6,2)},3:{"active":True,"exit_date":None}}
        self.history=index_history([
            dict(student_id=1,academic_year="2025/2026",class_id=7,class_name="3 A",graduation_date=None),
            dict(student_id=1,academic_year="2026/2027",class_id=11,class_name="4 A",graduation_date=None),
            dict(student_id=2,academic_year="2025/2026",class_id=17,class_name="6 A",graduation_date=date(2026,6,2)),
            dict(student_id=3,academic_year="2026/2027",class_id=1,class_name="1 A",graduation_date=None),
        ])

    def test_new_students_have_no_previous_year_transactions(self):
        self.assertNotIn(3,roster_on(self.history,self.students,date(2026,5,1)))
        self.assertIn(3,roster_on(self.history,self.students,date(2026,7,13)))

    def test_current_inactive_status_does_not_remove_historical_student(self):
        self.assertIn(2,roster_on(self.history,self.students,date(2025,11,5)))

    def test_graduation_stops_transactions_on_effective_date(self):
        self.assertIn(2,roster_on(self.history,self.students,date(2026,6,1)))
        self.assertNotIn(2,roster_on(self.history,self.students,date(2026,6,2)))
        self.assertNotIn(2,roster_on(self.history,self.students,date(2026,11,23)))

    def test_class_promotes_at_school_year_change(self):
        self.assertEqual(roster_on(self.history,self.students,date(2026,6,26))[1]["class_name"],"3 A")
        self.assertEqual(roster_on(self.history,self.students,date(2026,7,13))[1]["class_name"],"4 A")

    def test_july_rollover_and_missing_history(self):
        self.assertEqual(academic_year_for(date(2026,6,30)),"2025/2026")
        self.assertEqual(academic_year_for(date(2026,7,1)),"2026/2027")
        self.assertEqual(roster_on(self.history,self.students,date(2027,7,13)),{})

    def test_duplicate_annual_roster_is_rejected(self):
        row=self.history["2025/2026"][1]
        with self.assertRaises(ValueError):index_history([row,row])


class AttendanceTrendTests(unittest.TestCase):
    def test_months_compare_per_recorded_day(self):
        from attendance_trends import average_academic_series
        result=average_academic_series({'masuk':[8403,8951]},[15,16])
        self.assertEqual(result['masuk'],[560.2,559.4])

    def test_future_month_is_gap_not_zero_and_totals_unchanged(self):
        from attendance_trends import average_academic_series
        source={'masuk':[100,0]}
        self.assertEqual(average_academic_series(source,[2,0])['masuk'],[50.0,None])
        self.assertEqual(source,{'masuk':[100,0]})


if __name__=="__main__":unittest.main()
