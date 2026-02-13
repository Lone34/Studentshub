"""
Migration: Add per-feature credit pool columns to Subscription table.
Run: python migrate_credits.py
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'chegg_bot.db')

NEW_COLUMNS = [
    ('tutor_credits', 'INTEGER DEFAULT 0'),
    ('expert_credits', 'INTEGER DEFAULT 0'),
    ('ai_credits', 'INTEGER DEFAULT 0'),
    ('tutor_credits_used', 'INTEGER DEFAULT 0'),
    ('expert_credits_used', 'INTEGER DEFAULT 0'),
    ('ai_credits_used', 'INTEGER DEFAULT 0'),
]

# Credit allocations per plan (for backfilling active subscriptions)
PLAN_CREDITS = {
    'basic_299': {'tutor_credits': 5, 'expert_credits': 10, 'ai_credits': 20},
    'pro_499': {'tutor_credits': 10, 'expert_credits': 15, 'ai_credits': 30},
    'school_1200': {'tutor_credits': 10, 'expert_credits': 20, 'ai_credits': 20},
}

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get existing columns
    cursor.execute("PRAGMA table_info(subscription)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    
    added = []
    for col_name, col_type in NEW_COLUMNS:
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE subscription ADD COLUMN {col_name} {col_type}")
            added.append(col_name)
            print(f"  ✅ Added column: {col_name}")
        else:
            print(f"  ⏭️  Column already exists: {col_name}")
    
    conn.commit()
    
    # Backfill active subscriptions with correct credit allocations
    if added:
        print("\n📦 Backfilling active subscriptions with credit allocations...")
        for plan_type, credits in PLAN_CREDITS.items():
            cursor.execute(
                """UPDATE subscription 
                   SET tutor_credits = ?, expert_credits = ?, ai_credits = ?
                   WHERE plan_type = ? AND is_active = 1 
                   AND tutor_credits = 0 AND expert_credits = 0 AND ai_credits = 0""",
                (credits['tutor_credits'], credits['expert_credits'], credits['ai_credits'], plan_type)
            )
            updated = cursor.rowcount
            if updated > 0:
                print(f"  ✅ Updated {updated} active '{plan_type}' subscription(s)")
        conn.commit()
    
    conn.close()
    print("\n🎉 Migration complete!")

if __name__ == '__main__':
    print("🔄 Running credit system migration...\n")
    migrate()
