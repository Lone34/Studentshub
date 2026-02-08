import sqlite3

def add_column():
    db_path = 'instance/chegg_bot.db'
    print(f"Connecting to: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check existing tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print("Tables found:", [t[0] for t in tables])
    
    if 'tutor' in [t[0] for t in tables]:
        # Check columns in tutor
        cursor.execute("PRAGMA table_info(tutor)")
        columns = [col[1] for col in cursor.fetchall()]
        print("Columns in tutor:", columns)
        
        if 'teaching_grades' not in columns:
            try:
                cursor.execute("ALTER TABLE tutor ADD COLUMN teaching_grades VARCHAR(500)")
                print("Column 'teaching_grades' added successfully.")
                conn.commit()
            except sqlite3.OperationalError as e:
                print(f"Error adding column: {e}")
        else:
            print("Column 'teaching_grades' already exists.")
    else:
        print("ERROR: table 'tutor' NOT FOUND in this database.")
        
    conn.close()

if __name__ == "__main__":
    add_column()
