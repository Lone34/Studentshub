from app import app, db
import logging

logging.basicConfig(level=logging.INFO)

def create_tables():
    with app.app_context():
        try:
            db.create_all()
            print("Database tables created successfully (including Notification).")
        except Exception as e:
            print(f"Error creating tables: {e}")

if __name__ == "__main__":
    create_tables()
