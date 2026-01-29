from app import app, db, User

USERNAME_TO_PROMOTE = "Optiwork21@gmail.com" # Your Username

with app.app_context():
    user = User.query.filter_by(username=USERNAME_TO_PROMOTE).first()
    if user:
        user.role = "super_admin" # <--- Set to super_admin
        # Give infinite credits just in case
        user.credits = 999999 
        db.session.commit()
        print(f"Success! User '{USERNAME_TO_PROMOTE}' is now the SUPER ADMIN.")
    else:
        print(f"Error: User '{USERNAME_TO_PROMOTE}' not found.")
