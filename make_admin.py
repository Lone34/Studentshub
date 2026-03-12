"""
Make Admin - Run this script to promote a user to admin role.
Usage: python make_admin.py
"""
from app import app, db
from models import User

with app.app_context():
    email = input("Enter the email of the user to make Admin: ").strip()
    
    user = User.query.filter_by(email=email).first()
    
    if not user:
        print(f"❌ No user found with email: {email}")
    elif user.role == 'super_admin':
        print(f"⚠️  User '{user.username}' is already a Super Admin. Cannot downgrade.")
    elif user.role == 'admin':
        print(f"⚠️  User '{user.username}' is already an Admin.")
    else:
        user.role = 'admin'
        if user.credits < 100:
            user.credits = 100
        db.session.commit()
        print(f"✅ User '{user.username}' ({email}) has been promoted to Admin with 100 credits!")
