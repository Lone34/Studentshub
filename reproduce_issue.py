from app import app
from models import Tutor, Grade

def test_filtering(grade_name_input, subject_input):
    with app.app_context():
        print(f"\n--- Testing Filter: Grade='{grade_name_input}', Subject='{subject_input}' ---")
        
        # 1. Get Grade
        grade = Grade.query.filter_by(name=grade_name_input).first()
        if not grade:
            print(f"Grade '{grade_name_input}' not found.")
            return

        grade_id = grade.id
        print(f"Grade ID: {grade_id}")

        # 2. Get All Active Tutors
        query = Tutor.query.filter_by(is_approved=True, is_active=True)
        tutors = query.all()
        print(f"Initial Tutors: {len(tutors)}")

        # 3. Filter by Grade
        if grade_id:
            grade_obj = Grade.query.get(grade_id)
            filtered = []
            for t in tutors:
                if not t.teaching_grades or not t.teaching_grades.strip():
                    filtered.append(t)
                else:
                    grades_list = [g.strip() for g in t.teaching_grades.split(',')]
                    if grade_obj.name in grades_list:
                        filtered.append(t)
                    else:
                        print(f"  [Grade Filter] Dropped {t.display_name} (Grades: {grades_list})")
            tutors = filtered
            print(f"After Grade Filter: {len(tutors)}")

        # 4. Filter by Subject
        if subject_input:
            subject_filter = subject_input.lower().strip()
            filtered = []
            for t in tutors:
                if t.subjects:
                    t_subjects = [s.strip().lower() for s in t.subjects.split(',')]
                    if any(subject_filter in s for s in t_subjects):
                        filtered.append(t)
                    else:
                        print(f"  [Subject Filter] Dropped {t.display_name} (Subjects: {t_subjects}, Search: '{subject_filter}')")
                else:
                    print(f"  [Subject Filter] Dropped {t.display_name} (No subjects)")
            tutors = filtered
            print(f"After Subject Filter: {len(tutors)}")
        
        # Final Result
        print("Final Tutors:")
        for t in tutors:
            print(f"  - {t.display_name} (ID: {t.id})")

if __name__ == "__main__":
    # Test Case 1: The user's scenario
    test_filtering("Class 10", "math")
    
    # Test Case 2: Partial match
    test_filtering("Class 10", "ma")
    
    # Test Case 3: Empty subject (should list all for grade)
    test_filtering("Class 10", "")
