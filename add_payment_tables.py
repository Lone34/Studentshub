from app import app, db
from models import Subscription, Transaction
import sqlite3

def migrate_database():
    with app.app_context():
        # Create tables if they don't exist
        db.create_all()
        print("Database tables created (if they didn't exist).")

        # Add foreign key column to User table if it doesn't exist
        conn = sqlite3.connect('instance/chegg_bot.db')
        cursor = conn.cursor()
        
        try:
            cursor.execute("ALTER TABLE user ADD COLUMN active_subscription_id INTEGER REFERENCES subscription(id)")
            print("Added active_subscription_id column to User table.")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e):
                print("Column active_subscription_id already exists in User table.")
            else:
                print(f"Error adding column: {e}")
        
        conn.commit()
        conn.close()

if __name__ == "__main__":
    migrate_database()
