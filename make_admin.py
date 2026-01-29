from app import app, db, User

# Replace 'Owner' with the exact username you registered
USERNAME_TO_PROMOTE = "Opti" 

with app.app_context():
    user = User.query.filter_by(username=USERNAME_TO_PROMOTE).first()
    if user:
        user.role = "admin"
        db.session.commit()
        print(f"Success! User '{USERNAME_TO_PROMOTE}' is now an Admin.")
    else:
        print(f"Error: User '{USERNAME_TO_PROMOTE}' not found. Register it first!")
