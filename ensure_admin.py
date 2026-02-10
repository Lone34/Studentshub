from app import app, db, User
from werkzeug.security import generate_password_hash

with app.app_context():
    admin = User.query.filter_by(role='super_admin').first()
    if admin:
        print(f"Admin found: username={admin.username}, password='password' (assuming default)")
    else:
        print("Creating admin user 'superadmin' with password 'password'")
        admin = User(username='superadmin', password=generate_password_hash('password'), role='super_admin', is_verified=True)
        db.session.add(admin)
        db.session.commit()
        print("Admin created.")
