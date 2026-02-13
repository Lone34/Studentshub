from flask import Blueprint, url_for, session, redirect, request, flash, current_app, render_template, jsonify
from authlib.integrations.flask_client import OAuth
from flask_login import login_user, current_user
from models import db, User, Tutor
from werkzeug.security import generate_password_hash
from utils.otp_helper import send_otp_email, store_otp, verify_otp, generate_otp
import os
import uuid

auth_bp = Blueprint('auth_bp', __name__)
oauth = OAuth()

def configure_oauth(app):
    oauth.init_app(app)
    
    # Register Google
    # Note: Retrieving keys from ENV. 
    # If not present, it will log a warning or error at runtime when accessed.
    oauth.register(
        name='google',
        client_id=os.environ.get('GOOGLE_CLIENT_ID'),
        client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )

@auth_bp.route('/auth/google/login/<role>')
def google_login(role):
    """
    Initiate Google Login.
    role: 'student' or 'tutor' (determines which table to check/create if new)
    """
    # Force logout to prevent session crossover
    if current_user.is_authenticated:
        logout_user()
        session.clear() # Clear all session data to be safe
        
    session['google_auth_role'] = role
    redirect_uri = url_for('auth_bp.google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@auth_bp.route('/auth/google/callback')
def google_callback():
    try:
        token = oauth.google.authorize_access_token()
        if not token:
            flash("Google Auth Failed.", "error")
            return redirect(url_for('login'))
            
        resp = oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo')
        user_info = resp.json()
        
        # Google uses 'sub' as the unique identifier
        google_id = user_info.get('sub')
        email = user_info.get('email')
        name = user_info.get('name')
        picture = user_info.get('picture')
        
        if not google_id:
            flash("Google Login failed: Could not retrieve Google ID.", "error")
            return redirect(url_for('login'))
        
        role = session.get('google_auth_role', 'student') # Default to student if missing
        
        if role == 'tutor':
            # Check Tutor Table (ensure google_id is not None in query context, though we checked above)
            tutor = Tutor.query.filter((Tutor.email == email) | (Tutor.google_id == google_id)).first()
            
            if tutor:
                # Link ID if missing
                if not tutor.google_id:
                    tutor.google_id = google_id
                    db.session.commit()
                
                session['tutor_id'] = tutor.id
                flash(f"Welcome back, {tutor.display_name or tutor.full_name}!", "success")
                return redirect(url_for('tutoring.tutor_dashboard'))
                
            else:
                # Registration Logic for Google Tutor
                # Create pending tutor
                new_tutor = Tutor(
                    email=email,
                    full_name=name,
                    display_name=name, # Default
                    google_id=google_id,
                    profile_image=picture,
                    password=generate_password_hash(str(uuid.uuid4())), # Random secure password
                    is_approved=False
                )
                db.session.add(new_tutor)
                db.session.commit()
                
                session['tutor_id'] = new_tutor.id
                flash("Google Account connected. Please complete your profile.", "info")
                return redirect(url_for('tutoring.onboarding'))
    
        else:
            # Default: Student (User table)
            user = User.query.filter((User.email == email) | (User.google_id == google_id)).first()
            
            if user:
                # Link ID
                if not user.google_id:
                    user.google_id = google_id
                    db.session.commit()
                
                login_user(user)
                flash(f"Welcome back, {user.full_name or user.username}!", "success")
                return redirect(url_for('dashboard'))
                
            else:
                # Register new Student
                username = email.split('@')[0]
                # Ensure unique username
                if User.query.filter_by(username=username).first():
                    username = f"{username}_{str(uuid.uuid4())[:4]}"
                
                new_user = User(
                    email=email,
                    username=username,
                    full_name=name,
                    google_id=google_id,
                    profile_picture=picture,
                    password=generate_password_hash(str(uuid.uuid4())),
                    role='user', # Default
                    credits=0,
                    is_verified=True # Email verified via Google
                )
                db.session.add(new_user)
                db.session.commit()
                
                login_user(new_user)
                # Redirect to PROFILE for onboarding
                flash("Account created! Please complete your profile details.", "info")
                return redirect(url_for('profile'))
    except Exception as e:
        flash(f"Login failed: {str(e)}", "danger")
        return redirect(url_for('login'))

    return redirect(url_for('login'))

@auth_bp.route('/auth/send-otp', methods=['POST'])
def send_otp():
    """Sends OTP to the provided email."""
    data = request.get_json()
    email = data.get('email')
    
    if not email:
        return jsonify({'success': False, 'message': 'Email is required.'}), 400
        
    # Check if email already exists (prevent duplicate registration context)
    # But for login, we might want OTP too? 
    # User said: "tries to register... otp... logs in... email and password"
    # So OTP is for registration.
    
    # Check User
    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': 'Email already registered as Student.'}), 400
    if Tutor.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': 'Email already registered as Tutor.'}), 400

    otp = generate_otp()
    store_otp(email, otp)
    
    success, message = send_otp_email(email, otp)
    
    if success:
        return jsonify({'success': True, 'message': 'OTP sent to your email.'})
    else:
        return jsonify({'success': False, 'message': message}), 500
