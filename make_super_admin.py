"""
Make Super Admin - Promote a user to super_admin role.
Usage: python make_super_admin.py user@email.com
"""
import sys
from app import app, db
from models import User

if len(sys.argv) < 2:
    print("Usage: python make_super_admin.py <email>")
    sys.exit(1)

email = sys.argv[1].strip()

with app.app_context():
    user = User.query.filter_by(email=email).first()
    
    if not user:
        print(f"No user found with email: {email}")
    elif user.role == 'super_admin':
        print(f"User '{user.username}' is already a Super Admin.")
    else:
        user.role = 'super_admin'
        db.session.commit()
        print(f"User '{user.username}' ({email}) has been promoted to Super Admin!")
