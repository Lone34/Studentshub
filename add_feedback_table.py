import sqlite3
import os

# Connect to the database
db_path = os.path.join('instance', 'chegg_bot.db')
if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Create feedback table
    print("Creating 'feedback' table...")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_approved BOOLEAN DEFAULT 0,
            rating INTEGER DEFAULT 5,
            FOREIGN KEY (user_id) REFERENCES user (id)
        )
    ''')
    print("Table 'feedback' created successfully.")
except sqlite3.OperationalError as e:
    print(f"Error creating table: {e}")

conn.commit()
conn.close()
print("Migration complete.")
