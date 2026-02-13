from app import app, db, User
import sys

def check_email(email):
    with app.app_context():
        users = User.query.filter_by(email=email).all()
        print(f"--- Users with email '{email}' ---")
        if not users:
            print("No users found.")
        for u in users:
            print(f"ID: {u.id}, Username: {u.username}, Role: {u.role}, Email: {u.email}, GoogleID: {u.google_id}")
        
        print("\n--- All Super Admins ---")
        admins = User.query.filter_by(role='super_admin').all()
        for a in admins:
            print(f"ID: {a.id}, Username: {a.username}, Email: {a.email}")

        print("\n--- Recent Users (created last 24h) ---")
        recent = User.query.order_by(User.created_at.desc()).limit(5).all()
        for u in recent:
            print(f"ID: {u.id}, Username: {u.username}, Role: {u.role}, Email: {u.email} Created: {u.created_at}")

if __name__ == "__main__":
    target_email = "tufailahmad8409@gmail.com"
    check_email(target_email)
