"""
Make Super Admin - Run this script to promote a user to super_admin role.
Usage: python make_super_admin.py
"""
from app import app, db
from models import User

with app.app_context():
    email = input("Enter the email of the user to make Super Admin: ").strip()
    
    user = User.query.filter_by(email=email).first()
    
    if not user:
        print(f"❌ No user found with email: {email}")
    elif user.role == 'super_admin':
        print(f"⚠️  User '{user.username}' is already a Super Admin.")
    else:
        user.role = 'super_admin'
        db.session.commit()
        print(f"✅ User '{user.username}' ({email}) has been promoted to Super Admin!")
