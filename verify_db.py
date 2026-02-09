from app import app
from models import db, User
from sqlalchemy import text

def verify():
    with app.app_context():
        try:
            # Try to select the new columns
            with db.engine.connect() as conn:
                result = conn.execute(text("SELECT bio, profile_picture FROM user LIMIT 1"))
                print("Columns exist!")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == '__main__':
    verify()
