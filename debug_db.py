from app import app, db
from models import Tutor, Grade

with app.app_context():
    print("--- STARTING DEBUG ---", flush=True)
    print("t", flush=True)
    print("--- GRADES ---", flush=True)
    grades = Grade.query.all()
    for g in grades:
        print(f"ID: {g.id}, Name: '{g.name}'", flush=True)

    print("\n--- TUTORS ---", flush=True)
    tutors = Tutor.query.all()
    for t in tutors:
        print(f"ID: {t.id}, Name: {t.display_name}", flush=True)
        print(f"  Approved: {t.is_approved}, Available: {t.is_available}", flush=True)
        print(f"  Grades String: '{t.teaching_grades}'", flush=True)
        print(f"  Subjects String: '{t.subjects}'", flush=True)
        
        # Test filtering logic manually
        if t.teaching_grades:
            g_list = [g.strip() for g in t.teaching_grades.split(',')]
            print(f"  Parsed Grades: {g_list}", flush=True)
    print("--- END DEBUG ---", flush=True)
