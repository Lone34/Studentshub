
import sqlite3

DB_PATH = "instance/chegg_bot.db"

def add_column(conn, table_name, column_name, column_type):
    cursor = conn.cursor()
    try:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        print(f"Added column '{column_name}' to '{table_name}'.")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e):
            print(f"Column '{column_name}' already exists in '{table_name}'.")
        else:
            print(f"Error adding '{column_name}': {e}")

def migrate():
    try:
        conn = sqlite3.connect(DB_PATH)
        
        # New Registration Fields
        add_column(conn, "user", "student_type", "VARCHAR(50)")
        add_column(conn, "user", "parent_name", "VARCHAR(150)")
        add_column(conn, "user", "parent_phone", "VARCHAR(20)")
        add_column(conn, "user", "address", "TEXT")
        add_column(conn, "user", "school_name", "VARCHAR(200)")
        add_column(conn, "user", "class_grade", "VARCHAR(50)") # For non-numeric or specific class strings
        
        # Disabled Student Verification
        add_column(conn, "user", "disability_certificate_path", "VARCHAR(500)")
        add_column(conn, "user", "is_verified", "BOOLEAN DEFAULT 1") # Default True (Approved), Disabled needs checking

        conn.commit()
        conn.close()
        print("Migration completed successfully.")
    except Exception as e:
        print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
