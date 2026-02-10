from app import app, db, Job, User
from datetime import datetime

with app.app_context():
    # Find a user (admin or any user)
    user = User.query.first()
    if not user:
        print("No users found! Please register a user first.")
        exit()

    print(f"Creating dummy job for user: {user.username} (ID: {user.id})")

    # Use a known solved URL for testing positive match
    # Or a random one to see 'UNSOLVED' or 'CAPTCHA'
    # Let's use a URL that might work or at least trigger the check
    dummy_url = "https://www.chegg.com/homework-help/questions-and-answers/calculus-question-example-q12345" 

    job = Job(
        user_id=user.id,
        subject="Test Notification Job",
        content="This is a test job to verify the notification system.",
        status="Pending",
        chegg_link=dummy_url,
        timestamp=datetime.utcnow()
    )
    
    db.session.add(job)
    db.session.commit()
    
    print(f"Job created! ID: {job.id}. Status: Pending. URL: {dummy_url}")
    print("Wait 1-2 minutes for the scheduler to pick it up.")
