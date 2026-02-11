"""
Migration: Add 'questions_posted' column to service_account table.
Run once: python migrate_service_accounts.py
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'chegg_bot.db')

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] Database not found: {DB_PATH}")
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if column already exists
    cursor.execute("PRAGMA table_info(service_account)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'questions_posted' not in columns:
        cursor.execute("ALTER TABLE service_account ADD COLUMN questions_posted INTEGER DEFAULT 0")
        conn.commit()
        print("[OK] Added 'questions_posted' column to service_account table.")
    else:
        print("[SKIP] 'questions_posted' column already exists.")
    
    conn.close()

if __name__ == '__main__':
    migrate()
