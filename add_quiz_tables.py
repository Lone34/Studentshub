from app import app, db
from models import QuizSession, QuizAttempt

def add_quiz_tables():
    with app.app_context():
        # Create tables if they don't exist
        db.create_all()
        print("Database tables created successfully (including new Quiz tables).")

if __name__ == "__main__":
    add_quiz_tables()
