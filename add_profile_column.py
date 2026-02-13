from app import app, db
from sqlalchemy import text

def add_column():
    with app.app_context():
        # Add to User table
        try:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE user ADD COLUMN is_profile_complete BOOLEAN DEFAULT 0"))
                conn.commit()
            print("Added is_profile_complete to User table.")
        except Exception as e:
            print(f"User table error (maybe column exists): {e}")

        # Add to Tutor table
        try:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE tutor ADD COLUMN is_profile_complete BOOLEAN DEFAULT 0"))
                conn.commit()
            print("Added is_profile_complete to Tutor table.")
        except Exception as e:
            print(f"Tutor table error (maybe column exists): {e}")

if __name__ == "__main__":
    add_column()
