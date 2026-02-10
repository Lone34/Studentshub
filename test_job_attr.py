from app import app, db, Job, User
from datetime import datetime

with app.app_context():
    user = User.query.first()
    if not user:
        print("No users found")
        exit()

    # Create job WITHOUT chegg_link
    job = Job(
        user_id=user.id,
        subject="Test Job",
        content="Test Content",
        status="Pending"
    )
    db.session.add(job)
    db.session.commit()
    
    print(f"Created Job {job.id}")
    
    # Try to access chegg_link
    try:
        print(f"Link: {job.chegg_link}")
    except AttributeError as e:
        print(f"CRITICAL ERROR: {e}")
    except Exception as e:
        print(f"Other Error: {e}")
