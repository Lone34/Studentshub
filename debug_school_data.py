from app import app
from models import Grade, Subject, Tutor

with app.app_context():
    print("--- Grades ---")
    grades = Grade.query.all()
    if not grades:
        print("No grades found.")
    for g in grades:
        print(f"ID: {g.id}, Name: {g.name}, Order: {g.display_order}")

    print("\n--- Subjects ---")
    subjects = Subject.query.all()
    if not subjects:
        print("No subjects found.")
    for s in subjects:
        print(f"ID: {s.id}, Name: {s.name}, GradeID: {s.grade_id}, TeacherID: {s.teacher_id}, Time: {s.schedule_time}")

    print("\n--- Tutors ---")
    tutors = Tutor.query.all()
    for t in tutors:
        print(f"ID: {t.id}, Name: {t.display_name}, Subjects: {t.subjects}")
