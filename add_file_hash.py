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
    # Add file_hash column to document table
    print("Adding 'file_hash' column to 'document' table...")
    cursor.execute("ALTER TABLE document ADD COLUMN file_hash TEXT")
    print("Column added successfully.")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e):
        print("Column 'file_hash' already exists.")
    else:
        print(f"Error adding column: {e}")

conn.commit()
conn.close()
print("Migration complete.")
