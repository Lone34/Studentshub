from app import app
from models import db, Tutor

with app.app_context():
    tutors = Tutor.query.all()
    print(f"Total Tutors: {len(tutors)}")
    for t in tutors:
        print(f"ID: {t.id}, Name: {t.display_name}, Approved: {t.is_approved}, Active: {t.is_active}, Subjects: '{t.subjects}', Grades: '{t.teaching_grades}'")
