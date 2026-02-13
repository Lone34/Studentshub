import sqlite3
import os

DB_NAME = "chegg_bot.db"
FULL_PATH = os.path.abspath(DB_NAME)

print(f"Targeting DB: {FULL_PATH}")

if not os.path.exists(DB_NAME):
    print("DB file not found!")
    exit(1)

conn = sqlite3.connect(DB_NAME)
cursor = conn.cursor()

def check_col(table, col):
    cursor.execute(f"PRAGMA table_info({table})")
    cols = [c[1] for c in cursor.fetchall()]
    return col in cols

try:
    # 1. User Table
    if not check_col("user", "google_id"):
        print("Adding google_id to user...")
        cursor.execute("ALTER TABLE user ADD COLUMN google_id TEXT UNIQUE")
        print("Added.")
    else:
        print("google_id already in user.")

    # 2. Tutor Table
    if not check_col("tutor", "google_id"):
        print("Adding google_id to tutor...")
        cursor.execute("ALTER TABLE tutor ADD COLUMN google_id TEXT UNIQUE")
        print("Added.")
    else:
        print("google_id already in tutor.")

    conn.commit()
    print("Committed changes.")

    # Verify
    if check_col("user", "google_id") and check_col("tutor", "google_id"):
        print("VERIFICATION: SUCCESS. Columns exist.")
    else:
        print("VERIFICATION: FAILED. Columns missing.")

except Exception as e:
    print(f"Error: {e}")
    conn.rollback()
finally:
    conn.close()
