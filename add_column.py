import sqlite3
import os

def add_column():
    print("Attempting to add chegg_link column to job table...")
    try:
        db_path = 'instance/chegg_bot.db'
        if not os.path.exists(db_path):
             db_path = 'chegg_bot.db'
             
        print(f"Connecting to: {db_path}")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if column exists
        cursor.execute("PRAGMA table_info(job)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if 'chegg_link' not in columns:
            cursor.execute("ALTER TABLE job ADD COLUMN chegg_link TEXT")
            conn.commit()
            print("Column 'chegg_link' added successfully.")
        else:
            print("Column 'chegg_link' already exists.")
            
        conn.close()
    except Exception as e:
        print(f"Error adding column: {e}")

if __name__ == "__main__":
    add_column()
