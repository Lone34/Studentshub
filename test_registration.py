import unittest
from app import app, db, User
from io import BytesIO

class TestRegistrationFlow(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for testing
        self.app = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        
        # Cleanup previous test data
        existing_user = User.query.filter_by(username='disabled_tester').first()
        if existing_user:
            db.session.delete(existing_user)
        
        # Ensure Grades exist
        from app import Grade
        if not Grade.query.first():
            db.session.add(Grade(name='Class 1', display_order=1))
            db.session.add(Grade(name='Class 12', display_order=12))
            # Optional: Add Higher Education as a Grade if we want it in dropdowns? 
            # No, user wants it separate.
            db.session.commit()

        # Ensure test admin exists
        admin = User.query.filter_by(username='test_admin').first()
        if not admin:
            from werkzeug.security import generate_password_hash
            admin = User(username='test_admin', password=generate_password_hash('password'), role='super_admin', is_verified=True)
            db.session.add(admin)
        else:
            admin.role = 'super_admin'
            admin.is_verified = True
            
        db.session.commit()

    def tearDown(self):
        # Cleanup
        user = User.query.filter_by(username='disabled_tester').first()
        if user:
            db.session.delete(user)
            db.session.commit()
        self.app_context.pop()

    def test_disabled_registration_flow(self):
        # 1. Verify Grades on Register Page
        print("Testing Register Page content...")
        register_page = self.app.get('/register')
        self.assertIn(b'Class 1', register_page.data)
        self.assertIn(b'Class 12', register_page.data)
        print("Register page contains grades.")

        # 2. Register
        print("Testing Registration...")
        data = {
            'username': 'disabled_tester',
            'password': 'password123',
            'full_name': 'Disabled Tester',
            'email': 'tester@example.com',
            'student_type': 'disabled',
            'certificate': (BytesIO(b'dummy certificate content'), 'cert.txt')
        }
        response = self.app.post('/register', data=data, content_type='multipart/form-data', follow_redirects=True)
        # Debugging to file
        content = response.data.decode('utf-8')
        with open('test_debug.txt', 'w', encoding='utf-8') as f:
            f.write(f"URL: {response.request.path}\n")
            f.write(f"Status: {response.status_code}\n")
            if 'Registration successful' in content:
                f.write("SUCCESS MESSAGE FOUND\n")
            else:
                f.write("SUCCESS MESSAGE NOT FOUND\n")
                if 'alert' in content or 'bg-red' in content or 'bg-green' in content:
                     f.write("Found alerts in HTML (snippet):\n")
                     start = content.find('Flash Messages')
                     if start != -1:
                         f.write(content[start:start+1000])
                     else:
                         f.write("Could not locate flash block, printing first 1000 chars:\n")
                         f.write(content[:1000])
                else:
                    f.write("No alerts found in HTML.\n")
                    f.write("Full Content:\n")
                    f.write(content)
        
        # Check if redirected to login and flash message present
        self.assertIn('Registration successful', content)
        # self.assertIn('pending verification', content)
        
        # Verify DB state
        user = User.query.filter_by(username='disabled_tester').first()
        self.assertIsNotNone(user)
        self.assertFalse(user.is_verified)
        print("Registration successful, user is unverified.")

        # 3. Attempt Login (Should Fail)
        print("Testing Login Block for Unverified User...")
        with self.app as client:
            response = client.post('/login', data={'username': 'disabled_tester', 'password': 'password123'}, follow_redirects=True)
            self.assertIn(b'pending verification', response.data)
            print("Login blocked successfully.")

        # 4. Login as Admin and Approve
        print("Testing Admin Approval...")
        with self.app as client:
            # Login as admin
            client.post('/login', data={'username': 'test_admin', 'password': 'password'}, follow_redirects=True)
            
            # Approve user
            response = client.post(f'/verify-user/{user.id}/approve', follow_redirects=True)
            self.assertIn(b'has been verified and approved', response.data)
            
            # Verify DB state
            db.session.refresh(user)
            self.assertTrue(user.is_verified)
            print("User approved by admin.")

            # Test Certificate Access
            if user.disability_certificate_path:
                print(f"Testing Certificate Access: /uploads/{user.disability_certificate_path}")
                cert_response = client.get(f'/uploads/{user.disability_certificate_path}')
                self.assertEqual(cert_response.status_code, 200)
                print("Certificate file is accessible.")

        # 5. Login as User and Check Access
        print("Testing User Access...")
        with self.app as client:
            client.post('/login', data={'username': 'disabled_tester', 'password': 'password_wrong'}, follow_redirects=True) # Clear session
            client.post('/login', data={'username': 'disabled_tester', 'password': 'password123'}, follow_redirects=True)
            
            user = User.query.filter_by(username='disabled_tester').first()
            print(f"DEBUG: User student_type={user.student_type}, is_verified={user.is_verified}")
            self.assertTrue(user.can_access('school'))
            print("User has access to 'school' feature.")

    def test_higher_ed_registration(self):
        print("\nTesting Higher Ed Registration...")
        data = {
            'username': 'higher_ed_tester',
            'password': 'password123',
            'full_name': 'HE Tester',
            'email': 'he_tester@example.com',
            'phone': '9876543212',
            'student_type': 'higher_ed',
            'class_grade': 'B.Tech CS'
        }
        response = self.app.post('/register', data=data, follow_redirects=True)
        self.assertIn(b'Account created successfully', response.data)
        
        # Verify DB
        from models import User
        user = User.query.filter_by(username='higher_ed_tester').first()
        self.assertIsNotNone(user)
        self.assertEqual(user.student_type, 'higher_ed')
        self.assertEqual(user.class_grade, 'B.Tech CS')
        
        # Check Dashboard for 'Online School'
        with self.app as client:
            client.post('/login', data={'username': 'higher_ed_tester', 'password': 'password123'}, follow_redirects=True)
            dashboard = client.get('/dashboard')
            # 'Online School' link should be absent for Higher Ed
            self.assertNotIn(b'Online School', dashboard.data)
            self.assertNotIn(b'href="/school/"', dashboard.data)
            print("Higher Ed Dashboard verified: No Online School.")

    def test_disabled_grade_registration(self):
        print("\nTesting Disabled Student Grade Selection...")
        # Get a grade ID
        from app import Grade
        g = Grade.query.first()
        
        data = {
            'username': 'disabled_grade_tester',
            'password': 'password123',
            'full_name': 'Disabled Grade Tester',
            'email': 'dg_tester@example.com',
            'phone': '9876543213',
            'student_type': 'disabled',
            'disabled_grade_id': g.id,
            'certificate': (BytesIO(b"dummy cert"), 'cert.jpg')
        }
        
        response = self.app.post('/register', data=data, content_type='multipart/form-data', follow_redirects=True)
        self.assertIn(b'pending verification', response.data)
        
        from models import User
        user = User.query.filter_by(username='disabled_grade_tester').first()
        self.assertEqual(str(user.grade_id), str(g.id))
        print("Disabled Student Grade saved correctly.")


if __name__ == '__main__':
    unittest.main()
