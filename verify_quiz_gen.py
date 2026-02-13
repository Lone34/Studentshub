from ai_tutor import generate_quiz
import json

def test_quiz_generation():
    print("Testing Quiz Generation...")
    
    subject = "Physics"
    grade = "Class 10"
    
    quiz = generate_quiz(subject, grade, difficulty='hard')
    
    if not quiz:
        print("FAILED: No quiz generated.")
        return
        
    print(f"SUCCESS: Generated {len(quiz)} questions.")
    print("Sample Question:")
    print(json.dumps(quiz[0], indent=2))
    
    # Validate structure
    for q in quiz:
        assert 'question' in q
        assert 'options' in q
        assert 'answer' in q
        assert 'explanation' in q
        assert len(q['options']) == 4

    print("Validation Successful: Structure is correct.")

if __name__ == "__main__":
    test_quiz_generation()
