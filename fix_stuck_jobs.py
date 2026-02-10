from app import app, db
from models import Job, ServiceAccount
import chegg_api
import time

def fix_stuck_jobs():
    with app.app_context():
        # Find stuck jobs (Completed but no link)
        stuck_jobs = Job.query.filter(Job.status == 'Completed', Job.chegg_link == None).all()
        
        print(f"Found {len(stuck_jobs)} stuck jobs.")
        
        for job in stuck_jobs:
            print(f"Fixing Job #{job.id} (Account: {job.service_account_name})...")
            
            # Find account
            account = ServiceAccount.query.filter_by(name=job.service_account_name).first()
            if not account:
                print(f"  - Account '{job.service_account_name}' not found!")
                continue
                
            # Fetch latest link
            link = chegg_api.get_latest_question_url(account.cookie_data, account.proxy)
            
            if link:
                print(f"  - Found Link: {link}")
                job.chegg_link = link
                job.status = 'Pending' # Reset to Pending so checker picks it up
                db.session.commit()
                print("  - Updated Job status to Pending.")
            else:
                print("  - Could not find link on Chegg.")
            
            time.sleep(1)

if __name__ == "__main__":
    fix_stuck_jobs()
