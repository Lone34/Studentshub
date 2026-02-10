from app import app, db, Job, Notification

with app.app_context():
    # Clean up test jobs
    Job.query.filter(Job.id == 6).delete(synchronize_session=False)
    # Clean up the test notification
    Notification.query.filter_by(message="Solution Ready: Test Notification Job").delete()
    
    db.session.commit()
    print("Test job 6 and its notification deleted.")
