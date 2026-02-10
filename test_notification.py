from app import app, db, User, Notification

def test_notification():
    with app.app_context():
        # Ensure tables exist
        db.create_all()
        
        user = User.query.first()
        if not user:
            print("No user found! Create a user first.")
            # Create dummy user if needed
            new_user = User(username="testuser", password="password")
            db.session.add(new_user)
            db.session.commit()
            user = new_user
            print(f"Created dummy user: {user.username}")

        print(f"Testing notification for user: {user.username}")
        
        # Create
        notif = Notification(user_id=user.id, message="Test Notification System", link="http://example.com")
        db.session.add(notif)
        db.session.commit()
        print("Notification created.")
        
        # Fetch
        n = Notification.query.filter_by(user_id=user.id, message="Test Notification System").order_by(Notification.id.desc()).first()
        if n:
            print(f"SUCCESS: Found notification '{n.message}' with ID {n.id}")
            # Clean up
            db.session.delete(n)
            db.session.commit()
            print("Cleanup: Notification deleted.")
        else:
            print("FAILURE: Notification not found.")

if __name__ == "__main__":
    test_notification()
