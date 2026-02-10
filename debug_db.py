from app import app, db
from models import Job

with app.app_context():
    print("--- DEBUG: JOBS ---")
    jobs = Job.query.order_by(Job.timestamp.desc()).limit(5).all()
    for j in jobs:
        print(f"Job ID: {j.id}, Status: '{j.status}'")
        print(f"  Result Msg: '{j.result_message}'")
        print(f"  Link: {j.chegg_link}")
        print("-" * 20)
