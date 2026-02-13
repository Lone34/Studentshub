"""
Migration: Add chat_conversation table and conversation_id to chat_history.
Also groups existing chat history into conversations.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'chegg_bot.db')

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Create chat_conversation table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_conversation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title VARCHAR(200) DEFAULT 'New Chat',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user(id)
        )
    ''')
    print("✓ chat_conversation table created")
    
    # 2. Add conversation_id column to chat_history if missing
    cursor.execute("PRAGMA table_info(chat_history)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'conversation_id' not in columns:
        cursor.execute('ALTER TABLE chat_history ADD COLUMN conversation_id INTEGER REFERENCES chat_conversation(id)')
        print("✓ conversation_id column added to chat_history")
    else:
        print("  conversation_id column already exists")
    
    # 3. Migrate existing orphan messages into conversations (group by user + date)
    cursor.execute('''
        SELECT DISTINCT user_id FROM chat_history 
        WHERE conversation_id IS NULL
    ''')
    users_with_orphans = cursor.fetchall()
    
    for (user_id,) in users_with_orphans:
        # Get the first question as the conversation title
        cursor.execute('''
            SELECT id, question FROM chat_history 
            WHERE user_id = ? AND conversation_id IS NULL 
            ORDER BY timestamp ASC LIMIT 1
        ''', (user_id,))
        first = cursor.fetchone()
        if first:
            title = first[1][:80] + '...' if len(first[1]) > 80 else first[1]
            cursor.execute('''
                INSERT INTO chat_conversation (user_id, title) VALUES (?, ?)
            ''', (user_id, title))
            conv_id = cursor.lastrowid
            
            # Assign all orphan messages to this conversation
            cursor.execute('''
                UPDATE chat_history SET conversation_id = ? 
                WHERE user_id = ? AND conversation_id IS NULL
            ''', (conv_id, user_id))
            
            count = cursor.rowcount
            print(f"  Migrated {count} messages for user {user_id} into conversation '{title[:40]}'")
    
    conn.commit()
    conn.close()
    print("\n✓ Migration complete!")

if __name__ == '__main__':
    migrate()
