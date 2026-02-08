import requests
import json

# Setup
BASE_URL = "http://127.0.0.1:5000"
LOGIN_URL = f"{BASE_URL}/login"
TEACHERS_URL = f"{BASE_URL}/school/admin/teachers"

# Create session
session = requests.Session()

# Login as admin
# (Assuming 'admin' user exists or I can use the new tutor?)
# Wait, I need an admin account. 
# In app.py /lone-admin/ sets a session 'user_id' if accessed directly?
# No, /lone-admin/ checks current_user.
# I need to login.
# Assuming I can login as the user 'admin' if it exists.
# Or I can inspect the DB for an admin user.
# Better: use app.test_client() to avoid network/auth issues if possible?
# But checking the actual running server is better.

# Let's try to login as the 'lone-admin' or just use app test client in a script essentially running inside the app context.

from app import app, db
from models import User

with app.test_client() as client:
    # Function to simulate login
    # In Flask-Login, we can manipulate the session or login via route.
    # Let's verify if there is an admin user.
    with app.app_context():
        admin = User.query.filter_by(role='super_admin').first()
        if not admin:
            admin = User.query.filter_by(role='admin').first()
        
        if not admin:
            print("No admin user found to test with.")
            exit()
            
        print(f"Testing as user: {admin.username} ({admin.role})")
        
        # Login
        client.post('/login', data={'email': admin.email, 'password': 'password'}, follow_redirects=True) 
        # Note: we don't know the password.
        
        # Alternative: Use Flask-Login's login_user in a temporary route? 
        # Or just mock the session.
        with client.session_transaction() as sess:
            sess['user_id'] = admin.id
            sess['_fresh'] = True
            
    # Now request the API
    print("--- Requesting Grade 13 (Class 10) ---")
    res = client.get('/school/admin/teachers?grade_id=13')
    print(f"Status: {res.status_code}")
    print(f"Response: {res.get_json()}")
    
    print("\n--- Requesting Grade 13 + Subject 'math' ---")
    res = client.get('/school/admin/teachers?grade_id=13&subject=math')
    print(f"Status: {res.status_code}")
    print(f"Response: {res.get_json()}")

    print("\n--- Requesting Grade 13 + Subject 'Math' (case test) ---")
    res = client.get('/school/admin/teachers?grade_id=13&subject=Math')
    print(f"Status: {res.status_code}")
    print(f"Response: {res.get_json()}")
