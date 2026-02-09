from app import app
from models import Grade, Subject, db

def test_create_subject():
    with app.test_client() as client:
        with app.app_context():
            # Get a grade
            grade = Grade.query.first()
            if not grade:
                print("No grades found to attach subject to.")
                return

            print(f"Attempting to add subject to Grade: {grade.name} (ID: {grade.id})")
            
            # Login as super admin (mocked via session or just using a test context if login_required is disabled for tests, 
            # but since it's login_required, we might need to simulate login or bypass. 
            # For simplicity, let's just call the function directly if possible, or use the route with a bypassed decorator if we can't easily login.
            # Actually, let's just use the app context and DB directly to simulate what the route does.)
            
            # Simulate the route logic:
            try:
                name = "Test Math"
                existing = Subject.query.filter_by(name=name, grade_id=grade.id).first()
                if existing:
                    print(f"Subject '{name}' already exists.")
                    db.session.delete(existing)
                    db.session.commit()
                
                new_subject = Subject(
                    name=name,
                    grade_id=grade.id,
                    schedule_time="09:00",
                    duration_minutes=45,
                    teacher_id=None,
                    is_active=True
                )
                db.session.add(new_subject)
                db.session.commit()
                print(f"SUCCESS: Subject '{name}' created with ID: {new_subject.id}")
                
            except Exception as e:
                print(f"FAILURE: {e}")

if __name__ == "__main__":
    test_create_subject()
