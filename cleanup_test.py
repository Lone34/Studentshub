from app import app, db, Job, Notification

with app.app_context():
    # Clean up test jobs
    Job.query.filter(Job.id.in_([3, 4])).delete(synchronize_session=False)
    # Also clean up the test notification if desired, or leave it for user to see
    # Notification.query.filter_by(message="Solution Ready: Test Notification Job").delete()
    
    db.session.commit()
    print("Test jobs 3 and 4 deleted.")
