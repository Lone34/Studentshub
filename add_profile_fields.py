from app import app
from models import db
from sqlalchemy import text

def add_columns():
    with app.app_context():
        # User table
        try:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE user ADD COLUMN bio TEXT"))
                conn.commit()
                print("Added bio to User")
        except Exception as e:
            print(f"Bio likely exists or error: {e}")

        try:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE user ADD COLUMN profile_picture VARCHAR(255)"))
                conn.commit()
                print("Added profile_picture to User")
        except Exception as e:
            print(f"Profile picture likely exists or error: {e}")

if __name__ == '__main__':
    add_columns()
