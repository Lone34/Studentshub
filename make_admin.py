"""
Make Admin - Promote a user to admin role.
Usage: python make_admin.py user@email.com
"""
import sys
from app import app, db
from models import User

if len(sys.argv) < 2:
    print("Usage: python make_admin.py <email>")
    sys.exit(1)

email = sys.argv[1].strip()

with app.app_context():
    user = User.query.filter_by(email=email).first()
    
    if not user:
        print(f"No user found with email: {email}")
    elif user.role == 'super_admin':
        print(f"User '{user.username}' is already a Super Admin. Cannot downgrade.")
    elif user.role == 'admin':
        print(f"User '{user.username}' is already an Admin.")
    else:
        user.role = 'admin'
        if user.credits < 100:
            user.credits = 100
        db.session.commit()
        print(f"User '{user.username}' ({email}) has been promoted to Admin with 100 credits!")
