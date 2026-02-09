import sqlite3

def migrate():
    db_path = 'instance/chegg_bot.db'
    print(f"Connecting to: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Check SchoolClass table
    cursor.execute("PRAGMA table_info(school_class)")
    columns = [col[1] for col in cursor.fetchall()]
    print("Columns in school_class:", columns)
    
    # 2. Add start_time
    if 'start_time' not in columns:
        try:
            cursor.execute("ALTER TABLE school_class ADD COLUMN start_time VARCHAR(10)")
            print("Added start_time to school_class")
        except Exception as e:
            print(f"Error adding start_time: {e}")

    # 3. Add end_time
    if 'end_time' not in columns:
        try:
            cursor.execute("ALTER TABLE school_class ADD COLUMN end_time VARCHAR(10)")
            print("Added end_time to school_class")
        except Exception as e:
            print(f"Error adding end_time: {e}")

    # 4. Add grade_id (optional, for direct linking if needed, but let's add it for strictness as requested)
    if 'grade_id' not in columns:
        try:
            cursor.execute("ALTER TABLE school_class ADD COLUMN grade_id INTEGER REFERENCES grade(id)")
            print("Added grade_id to school_class")
        except Exception as e:
            print(f"Error adding grade_id: {e}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrate()
