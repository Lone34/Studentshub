
from app import app
from models import db, User, Tutor, Grade

with app.app_context():
    print("--- TUTORS & GRADES ---")
    tutors = Tutor.query.all()
    for t in tutors:
        print(f"Tutor: {t.display_name} | Email: {t.email}")
        print(f"  Approved: {t.is_approved} | Active: {t.is_active}")
        print(f"  Subjects: {t.subjects}")
        print(f"  Teaching Grades: '{t.teaching_grades}'")
        print("-" * 20)

    print("\n--- STUDENTS & GRADES ---")
    # Just list a few students to see typical data
    students = User.query.filter(User.role != 'admin').limit(5).all()
    for s in students:
         grade_name = s.enrolled_grade.name if s.enrolled_grade else "None"
         print(f"Student: {s.username} | Type: {s.student_type} | Grade: {grade_name}")

    print("\n--- GRADES CHECK ---")
    grades = Grade.query.all()
    print([g.name for g in grades])
