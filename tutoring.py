"""
Tutoring Blueprint - Handles tutor registration, login, and video session management
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime, date
import uuid
import os

from models import db, Tutor, TutoringSession, User, SchoolClass
from flask_login import login_required, current_user

tutoring_bp = Blueprint('tutoring', __name__, url_prefix='/tutoring')

# Platform fixed rate (credits per minute)
RATE_PER_MINUTE = 2

# Allowed file extensions for ID proof
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS





# ============================================
# TUTOR AUTHENTICATION
# ============================================

def tutor_login_required(f):
    """Decorator to require tutor login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'tutor_id' not in session:
            flash('Please login to access tutor dashboard', 'warning')
            return redirect(url_for('tutoring.tutor_login'))
        
        tutor = db.session.get(Tutor, session['tutor_id'])
        if not tutor or not tutor.is_active:
            session.pop('tutor_id', None)
            flash('Session expired. Please login again.', 'warning')
            return redirect(url_for('tutoring.tutor_login'))
        
        if not tutor.is_approved:
            flash('Your account is pending admin approval.', 'info')
            return redirect(url_for('tutoring.pending_approval'))
        
        return f(*args, **kwargs)
    return decorated_function


def get_current_tutor():
    """Get current logged in tutor"""
    if 'tutor_id' in session:
        return db.session.get(Tutor, session['tutor_id'])
    return None


# ============================================
# TUTOR REGISTRATION & LOGIN ROUTES
# ============================================

@tutoring_bp.route('/register', methods=['GET', 'POST'])
@tutoring_bp.route('/register', methods=['GET', 'POST'])
def tutor_register():
    """Simplified Tutor registration page"""
    if request.method == 'POST':
        # Get minimal form data
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # Validations
        errors = []
        if not email or '@' not in email:
            errors.append('Valid email is required')
        if Tutor.query.filter_by(email=email).first():
            errors.append('Email already registered')
        
        # Password Check
        is_valid_pass, pass_msg = validate_password(password)
        if not is_valid_pass:
            errors.append(pass_msg)
            
        if password != confirm_password:
            errors.append('Passwords do not match')
            
        # OTP Check
        otp_code = request.form.get('otp')
        is_valid_otp, otp_msg = verify_otp(email, otp_code)
        if not is_valid_otp:
            errors.append(f"OTP Error: {otp_msg}")
        
        if errors:
            for error in errors:
                flash(error, 'danger')
            return redirect(url_for('register') + '?type=tutor')
        
        # Create tutor with minimal info
        tutor = Tutor(
            email=email,
            password=generate_password_hash(password),
            is_approved=False,
            is_available=False,
            is_active=True
        )
        
        db.session.add(tutor)
        db.session.commit()
        
        # Auto-login after registration
        session['tutor_id'] = tutor.id
        flash('Account created! Please complete your profile to start teaching.', 'success')
        return redirect(url_for('tutoring.onboarding'))
    
    # Redirect GET requests to combined registration page
    return redirect(url_for('register') + '?type=tutor')


@tutoring_bp.route('/login', methods=['GET', 'POST'])
def tutor_login():
    """Tutor login page"""
    if 'tutor_id' in session:
        tutor = db.session.get(Tutor, session['tutor_id'])
        if tutor and tutor.is_approved:
            return redirect(url_for('tutoring.tutor_dashboard'))
        elif tutor:
            return redirect(url_for('tutoring.pending_approval'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        tutor = Tutor.query.filter_by(email=email).first()
        
        if not tutor:
            flash('Email not registered. Please register first.', 'danger')
            return redirect(url_for('login') + '?type=tutor')
        
        if not check_password_hash(tutor.password, password):
            flash('Invalid password.', 'danger')
            return redirect(url_for('login') + '?type=tutor')
        
        if not tutor.is_active:
            flash('Your account has been deactivated. Contact support.', 'danger')
            return redirect(url_for('login') + '?type=tutor')
        
        # Login successful
        # Login successful
        session['tutor_id'] = tutor.id
        
        if not tutor.full_name:
             return redirect(url_for('tutoring.onboarding'))

        if not tutor.is_approved:
            return redirect(url_for('tutoring.pending_approval'))
        
        flash(f'Welcome back, {tutor.display_name}!', 'success')
        return redirect(url_for('tutoring.tutor_dashboard'))
    
    # Redirect GET requests to combined login page
    return redirect(url_for('login') + '?type=tutor')


@tutoring_bp.route('/logout')
def tutor_logout():
    """Tutor logout"""
    session.pop('tutor_id', None)
    flash('Logged out successfully.', 'info')
    return redirect(url_for('tutoring.tutor_login'))


@tutoring_bp.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
    """Tutor onboarding / profile completion"""
    if 'tutor_id' not in session:
        return redirect(url_for('tutoring.tutor_login'))
    
    tutor = db.session.get(Tutor, session['tutor_id'])
    
    if request.method == 'POST':
        # Update profile details
        tutor.full_name = request.form.get('full_name', '').strip()
        tutor.display_name = request.form.get('display_name', '').strip()
        tutor.phone = request.form.get('phone', '').strip()
        tutor.qualification = request.form.get('qualification', '').strip()
        tutor.experience_years = int(request.form.get('experience_years', 0))
        tutor.college = request.form.get('college', '').strip()
        tutor.languages = request.form.get('languages', 'English').strip()
        tutor.bio = request.form.get('bio', '').strip()
        
        # Handle subjects
        subjects_list = request.form.getlist('subjects')
        custom_subject = request.form.get('custom_subject', '').strip()
        if custom_subject:
            subjects_list.append(custom_subject)
        tutor.subjects = ", ".join([s.strip() for s in subjects_list if s.strip()])
        
        # Handle grades
        teaching_grades = request.form.getlist('teaching_grades')
        tutor.teaching_grades = ", ".join(teaching_grades) if teaching_grades else ""
        
        # Handle ID Upload
        if 'id_proof' in request.files:
            file = request.files['id_proof']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"tutor_{tutor.email}_{file.filename}")
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'tutor_docs')
                os.makedirs(upload_folder, exist_ok=True)
                tutor.id_proof_path = os.path.join(upload_folder, filename)
        
        db.session.commit()

        # Lock profile
        tutor.is_profile_complete = True
        db.session.commit()
        
        flash("Profile updated! Your account is pending admin approval.", "success")
        return redirect(url_for('tutoring.pending_approval'))

    # Load subjects/grades for dropdowns
    # Load subjects/grades for dropdowns
    from school import GlobalSubject
    from models import Grade
    
    global_subjects = GlobalSubject.query.filter_by(is_active=True).order_by(GlobalSubject.name).all()
    subject_names = [s.name for s in global_subjects]
    
    grades = Grade.query.filter_by(is_active=True).order_by(Grade.display_order).all()
    
    return render_template('tutoring/onboarding.html', tutor=tutor, subjects=subject_names, grades=grades)

@tutoring_bp.route('/pending-approval')
def pending_approval():
    """Show pending approval message"""
    if 'tutor_id' not in session:
        return redirect(url_for('tutoring.tutor_login'))
    
    tutor = db.session.get(Tutor, session['tutor_id'])
    
    # If profile incomplete, redirect to onboarding
    if not tutor.full_name:
         return redirect(url_for('tutoring.onboarding'))

    if tutor and tutor.is_approved:
        return redirect(url_for('tutoring.tutor_dashboard'))
    
    return render_template('tutoring/pending_approval.html', tutor=tutor)


# ============================================
# TUTOR DASHBOARD
# ============================================

@tutoring_bp.route('/dashboard')
@tutor_login_required
def tutor_dashboard():
    """Tutor main dashboard"""
    tutor = get_current_tutor()
    
    # Get recent sessions
    recent_sessions = TutoringSession.query.filter_by(tutor_id=tutor.id)\
        .order_by(TutoringSession.created_at.desc())\
        .limit(10).all()
    
    # Stats
    stats = {
        'total_sessions': tutor.total_sessions,
        'total_minutes': tutor.total_minutes,
        'total_earnings': tutor.total_earnings,
        'rating': tutor.rating,
        'is_available': tutor.is_available,
        'current_date': date.today()
    }
    
    today = date.today()
    current_dt = datetime.now()
    
    # Get raw classes
    raw_classes = SchoolClass.query.filter_by(teacher_id=tutor.id).filter(SchoolClass.scheduled_date >= today).order_by(SchoolClass.scheduled_date, SchoolClass.start_time).all()
    
    # Process classes to add status derived from time
    school_classes = []
    for cls in raw_classes:
        # Clone or wrap to add attributes without modifying DB object state
        # Since we just need to read in template, we can attach attributes if not committed
        # But safer to create a dict or wrapper
        
        class_data = cls
        class_data.derived_status = 'scheduled'
        
        if cls.status == 'live':
             class_data.derived_status = 'live'
        elif cls.status == 'completed':
             class_data.derived_status = 'completed'
        else:
            # Check time
            try:
                # Parse times
                start_time = datetime.strptime(cls.start_time, '%H:%M').time()
                end_time = datetime.strptime(cls.end_time, '%H:%M').time()
                
                # Combine with scheduled date
                start_dt = datetime.combine(cls.scheduled_date, start_time)
                end_dt = datetime.combine(cls.scheduled_date, end_time)
                
                if current_dt > end_dt:
                     class_data.derived_status = 'completed_time' # Time passed
                elif current_dt >= start_dt:
                     class_data.derived_status = 'ready' # Time is here!
                else:
                     class_data.derived_status = 'future' # Not yet
            except Exception as e:
                print(f"Error parsing time for class {cls.id}: {e}")
                class_data.derived_status = 'future' # Fallback
        school_classes.append(class_data)

    return render_template('tutoring/dashboard.html', 
                         tutor=tutor, 
                         sessions=recent_sessions,
                         school_classes=school_classes,
                         stats=stats,
                         current_dt=current_dt)


@tutoring_bp.route('/tutor/profile/edit', methods=['GET', 'POST'])
@tutor_login_required
def edit_tutor_profile():
    tutor = get_current_tutor()
    
    if request.method == 'POST':
        # Check lock
        if tutor.is_profile_complete:
             # Only allow Profile Picture
            if 'profile_picture' in request.files:
                file = request.files['profile_picture']
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles')
                    os.makedirs(upload_folder, exist_ok=True)
                    
                    ext = filename.rsplit('.', 1)[1].lower()
                    unique_filename = f"tutor_{tutor.id}_{uuid.uuid4().hex[:8]}.{ext}"
                    file.save(os.path.join(upload_folder, unique_filename))
                    
                    tutor.profile_image = f"uploads/profiles/{unique_filename}"
                    db.session.commit()
                    flash('Profile picture updated!', 'success')
            else:
                 flash('Profile details cannot be changed once saved.', 'warning')
            return redirect(url_for('tutoring.edit_tutor_profile'))

        # Normal Edit
        full_name = request.form.get('full_name')
        bio = request.form.get('bio')
        display_name = request.form.get('display_name')
        
        tutor.full_name = full_name
        tutor.bio = bio
        tutor.display_name = display_name
        
        # Profile Picture
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles')
                os.makedirs(upload_folder, exist_ok=True)
                
                ext = filename.rsplit('.', 1)[1].lower()
                unique_filename = f"tutor_{tutor.id}_{uuid.uuid4().hex[:8]}.{ext}"
                file.save(os.path.join(upload_folder, unique_filename))
                
                tutor.profile_image = f"uploads/profiles/{unique_filename}"
        
        tutor.is_profile_complete = True
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('tutoring.edit_tutor_profile'))
        
    return render_template('tutoring/profile.html', tutor=tutor)


@tutoring_bp.route('/toggle-availability', methods=['POST'])
@tutor_login_required
def toggle_availability():
    """Toggle tutor online/offline status"""
    tutor = get_current_tutor()
    tutor.is_available = not tutor.is_available
    tutor.last_online = datetime.utcnow()
    db.session.commit()
    
    return jsonify({
        'success': True,
        'is_available': tutor.is_available,
        'message': 'You are now online!' if tutor.is_available else 'You are now offline.'
    })


# ============================================
# STUDENT-FACING ROUTES (Browse Tutors)
# ============================================

@tutoring_bp.route('/subjects')
@login_required
def browse_subjects():
    """Step 1: Browse available subjects based on student level"""
    
    # 1. Base Query: Active, Approved Tutors
    query = Tutor.query.filter_by(is_approved=True, is_active=True)
    
    # 2. Filter by Student Level
    if current_user.student_type == 'higher_ed':
        # Must teach Higher Education
        # We need to filter in Python or use LIKE query if DB supports it. 
        # SQLite LIKE is case-insensitive by default usually, but let's be safe.
        query = query.filter(Tutor.teaching_grades.ilike('%Higher Education%'))
    else:
        # Must teach the Student's specific grade
        # If student has a grade assigned
        if current_user.enrolled_grade:
             grade_name = current_user.enrolled_grade.name
             query = query.filter(Tutor.teaching_grades.ilike(f'%{grade_name}%'))
        else:
            # Fallback for students without grade? Show everything that ISN'T purely Higher Ed?
            # Or just show all. Let's show all for now if no grade set.
            pass

    eligible_tutors = query.all()
    
    # 3. Aggregate Subjects and Counts
    subject_counts = {}
    
    for tutor in eligible_tutors:
        if not tutor.subjects: continue
        
        # Split by comma and strip
        tutor_subs = [s.strip() for s in tutor.subjects.split(',') if s.strip()]
        
        for sub in tutor_subs:
            subject_counts[sub] = subject_counts.get(sub, 0) + 1
            
    # Sort subjects alphabetically
    sorted_subjects = sorted(subject_counts.keys())
    
    return render_template('tutoring/browse_subjects.html', 
                         subjects=sorted_subjects, 
                         tutor_counts=subject_counts)


@tutoring_bp.route('/browse')
@login_required # Enforce login for this flow now
def browse_tutors():
    """Step 2: Broker Tutors for a specific subject"""
    subject_filter = request.args.get('subject', '')
    
    # If no subject selected, redirect to subject selection
    if not subject_filter:
        return redirect(url_for('tutoring.browse_subjects'))
    
    from flask_login import current_user
    
    # Start with all approved tutors
    query = Tutor.query.filter_by(is_approved=True, is_active=True)
    
    # Filter by Subject
    if subject_filter:
        query = query.filter(Tutor.subjects.ilike(f'%{subject_filter}%'))
    
    # Filter by User Level (Strict Sync)
    if current_user.student_type == 'higher_ed':
         query = query.filter(Tutor.teaching_grades.ilike('%Higher Education%'))
    elif current_user.enrolled_grade:
         # Must match student's grade
         grade_name = current_user.enrolled_grade.name
         query = query.filter(Tutor.teaching_grades.ilike(f'%{grade_name}%'))
    
    tutors = query.order_by(Tutor.rating.desc()).all()
    
    # For the filter dropdown in browse.html (optional, but good for context)
    # We can just pass the single subject since we are in a drill-down
    
    return render_template('tutoring/browse.html', 
                         tutors=tutors, 
                         subjects=[subject_filter], # Only show current subject in filter to avoid confusion? Or all? 
                         # Actually browser.html expects a list of subjects for the filter bar. 
                         # Let's pass empty or just the current one to simplify the view.
                         current_filter=subject_filter,
                         rate_per_minute=RATE_PER_MINUTE)


@tutoring_bp.route('/tutor/<int:tutor_id>')
def tutor_profile(tutor_id):
    """View tutor's public profile"""
    tutor = Tutor.query.get_or_404(tutor_id)
    
    if not tutor.is_approved or not tutor.is_active:
        flash('Tutor not available.', 'warning')
        return redirect(url_for('tutoring.browse_tutors'))
    
    # Get reviews
    reviews = []
    rated_sessions = TutoringSession.query.filter(
        TutoringSession.tutor_id == tutor.id,
        TutoringSession.student_rating.isnot(None)
    ).order_by(TutoringSession.created_at.desc()).limit(10).all()

    for s in rated_sessions:
        student = db.session.get(User, s.student_id)
        reviews.append({
            'student_name': student.username if student else 'Anonymous',
            'rating': s.student_rating,
            'feedback': s.student_feedback,
            'date': s.created_at.strftime('%Y-%m-%d')
        })
    
    return render_template('tutoring/tutor_profile.html', 
                         tutor=tutor,
                         reviews=reviews,
                         rate_per_minute=RATE_PER_MINUTE)


# ============================================
# API ENDPOINTS
# ============================================

@tutoring_bp.route('/api/tutors')
def api_get_tutors():
    """API: Get list of available tutors"""
    subject = request.args.get('subject', '')
    
    from flask_login import current_user
    
    query = Tutor.query.filter_by(is_approved=True, is_active=True, is_available=True)
    
    if subject:
        query = query.filter(Tutor.subjects.ilike(f'%{subject}%'))
    
    all_tutors = query.order_by(Tutor.rating.desc()).all()
    filtered_tutors = []

    # Strict Filtering Logic matching browse_tutors
    if current_user.is_authenticated and current_user.student_type == 'higher_ed':
         filtered_tutors = [t for t in all_tutors if t.teaching_grades and 'Higher Education' in t.teaching_grades]
    elif current_user.is_authenticated:
         # Grade / Disabled / Others -> Exclude if ONLY Higher Education
         filtered_tutors = [t for t in all_tutors if (t.teaching_grades or "") != 'Higher Education']
    else:
        filtered_tutors = all_tutors
    
    return jsonify({
        'tutors': [{
            'id': t.id,
            'display_name': t.display_name,
            'subjects': t.subjects.split(','),
            'rating': t.rating,
            'total_sessions': t.total_sessions,
            'bio': t.bio[:100] + '...' if t.bio and len(t.bio) > 100 else t.bio,
            'languages': t.languages,
            'is_available': t.is_available
        } for t in filtered_tutors],
        'rate_per_minute': RATE_PER_MINUTE
    })


@tutoring_bp.route('/api/pending-sessions')
@tutor_login_required
def api_get_pending_sessions():
    """API: Get pending session requests for current tutor"""
    tutor = get_current_tutor()
    
    # Get pending sessions for this tutor
    pending = TutoringSession.query.filter_by(
        tutor_id=tutor.id,
        status='pending'
    ).order_by(TutoringSession.created_at.desc()).all()
    
    sessions = []
    for s in pending:
        student = db.session.get(User, s.student_id)
        sessions.append({
            'room_id': s.room_id,
            'student_name': student.username if student else 'Student',
            'subject': s.subject or 'General',
            'question': s.question[:150] if s.question else '',
            'created_at': s.created_at.isoformat(),
            'room_url': url_for('tutoring.video_room', room_id=s.room_id)
        })
    
    return jsonify({
        'success': True,
        'pending_count': len(sessions),
        'sessions': sessions
    })


@tutoring_bp.route('/api/session/book', methods=['POST'])
def api_book_session():
    """API: Book a tutoring session (for logged-in students)"""
    from flask_login import current_user
    
    # Check if student is logged in
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'error': 'Please login to book a session'}), 401
    
    data = request.get_json()
    tutor_id = data.get('tutor_id')
    subject = data.get('subject', '')
    question = data.get('question', '')
    
    if not tutor_id:
        return jsonify({'success': False, 'error': 'Tutor ID required'}), 400
    
    # Get tutor
    tutor = db.session.get(Tutor, tutor_id)
    if not tutor:
        return jsonify({'success': False, 'error': 'Tutor not found'}), 404
    
    if not tutor.is_available:
        return jsonify({'success': False, 'error': 'Tutor is currently offline'}), 400
    
    # Check student subscription has tutor credits remaining
    if not current_user.can_access('video_tutor'):
        return jsonify({
            'success': False, 
            'error': 'No tutor session credits remaining. Please upgrade your plan.'
        }), 400
    
    # Create session with unique room ID
    room_id = str(uuid.uuid4())[:8]
    
    tutoring_session = TutoringSession(
        room_id=room_id,
        student_id=current_user.id,
        tutor_id=tutor.id,
        subject=subject,
        question=question,
        rate_per_minute=RATE_PER_MINUTE,
        status='pending'
    )
    
    db.session.add(tutoring_session)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'room_id': room_id,
        'room_url': url_for('tutoring.video_room', room_id=room_id),
        'tutor_name': tutor.display_name,
        'rate_per_minute': RATE_PER_MINUTE
    })


# ============================================
# VIDEO ROOM ROUTES
# ============================================

@tutoring_bp.route('/room/<room_id>')
def video_room(room_id):
    """Video call room"""
    from flask_login import current_user
    
    # Get session
    tutoring_session = TutoringSession.query.filter_by(room_id=room_id).first()
    if not tutoring_session:
        flash('Session not found.', 'danger')
        return redirect(url_for('tutoring.browse_tutors'))
    
    # Determine if user is student or tutor
    is_tutor = False
    is_student = False
    
    if 'tutor_id' in session and session['tutor_id'] == tutoring_session.tutor_id:
        is_tutor = True
    elif current_user.is_authenticated and current_user.id == tutoring_session.student_id:
        is_student = True
    else:
        flash('You do not have access to this session.', 'danger')
        return redirect('/')
    
    tutor = db.session.get(Tutor, tutoring_session.tutor_id)
    student = db.session.get(User, tutoring_session.student_id)
    
    return render_template('tutoring/video_room.html',
                         session=tutoring_session,
                         tutor=tutor,
                         student=student,
                         is_tutor=is_tutor,
                         is_student=is_student,
                         rate_per_minute=RATE_PER_MINUTE)


@tutoring_bp.route('/api/session/<room_id>/start', methods=['POST'])
def api_start_session(room_id):
    """Mark session as started"""
    tutoring_session = TutoringSession.query.filter_by(room_id=room_id).first()
    if not tutoring_session:
        return jsonify({'success': False, 'error': 'Session not found'}), 404
    
    if tutoring_session.status == 'active':
        return jsonify({'success': True, 'message': 'Session already active'})
    
    tutoring_session.status = 'active'
    tutoring_session.started_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({'success': True, 'started_at': tutoring_session.started_at.isoformat()})


@tutoring_bp.route('/api/session/<room_id>/end', methods=['POST'])
def api_end_session(room_id):
    """End session and calculate billing"""
    from flask_login import current_user
    
    tutoring_session = TutoringSession.query.filter_by(room_id=room_id).first()
    if not tutoring_session:
        return jsonify({'success': False, 'error': 'Session not found'}), 404
    
    if tutoring_session.status == 'completed':
        return jsonify({'success': True, 'message': 'Session already ended'})
    
    # Calculate duration
    now = datetime.utcnow()
    if tutoring_session.started_at:
        duration = (now - tutoring_session.started_at).total_seconds() / 60
        duration_minutes = max(1, int(duration))  # Minimum 1 minute
    else:
        duration_minutes = 0
    
    # Deduct 1 tutor credit (Plan -> Wallet)
    from models import Subscription
    student = db.session.get(User, tutoring_session.student_id)
    credits_to_charge = 1  # 1 credit per session regardless of duration
    
    if student and student.active_subscription_id:
        sub = Subscription.query.get(student.active_subscription_id)
        if sub:
            if sub.tutor_credits_used < sub.tutor_credits:
                sub.tutor_credits_used += 1
            elif student.credits > 0:
                student.credits -= 1
    
    # Add to tutor earnings (80% to tutor, 20% platform fee)
    tutor = db.session.get(Tutor, tutoring_session.tutor_id)
    if tutor:
        tutor_earnings = int(credits_to_charge * 0.80)
        tutor.total_earnings += tutor_earnings
        tutor.total_sessions += 1
        tutor.total_minutes += duration_minutes
    
    # Update session
    tutoring_session.status = 'completed'
    tutoring_session.ended_at = now
    tutoring_session.duration_minutes = duration_minutes
    tutoring_session.credits_paid = credits_to_charge
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'duration_minutes': duration_minutes,
        'credits_charged': credits_to_charge
    })


@tutoring_bp.route('/api/session/<room_id>/upload-recording', methods=['POST'])
def api_upload_recording(room_id):
    """Upload session recording"""
    print(f"DEBUG: Upload request received for room {room_id}")
    
    tutoring_session = TutoringSession.query.filter_by(room_id=room_id).first()
    if not tutoring_session:
        print("DEBUG: Session not found")
        return jsonify({'success': False, 'error': 'Session not found'}), 404
    
    if 'recording' not in request.files:
        print("DEBUG: No recording file in request")
        return jsonify({'success': False, 'error': 'No recording file'}), 400
    
    file = request.files['recording']
    print(f"DEBUG: File received: {file.filename}, Content-Type: {file.content_type}")
    
    if file.filename:
        # Save recording
        filename = f"session_{room_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.webm"
        upload_folder = os.path.join('uploads', 'recordings')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        
        try:
            file.save(file_path)
            print(f"DEBUG: File saved to {file_path}, Size: {os.path.getsize(file_path)}")
            
            # Update session
            tutoring_session.recording_path = file_path
            db.session.commit()
            print("DEBUG: Database updated with recording path")
            
            return jsonify({'success': True, 'path': file_path})
        except Exception as e:
            print(f"DEBUG: Error saving file: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    print("DEBUG: Invalid filename")
    return jsonify({'success': False, 'error': 'Invalid file'}), 400


@tutoring_bp.route('/api/session/<room_id>/rate', methods=['POST'])
def api_rate_session(room_id):
    """Rate a completed session"""
    data = request.get_json()
    rating = data.get('rating')
    feedback = data.get('feedback', '')
    
    if not rating or not isinstance(rating, int) or not (1 <= rating <= 5):
        return jsonify({'success': False, 'error': 'Invalid rating'}), 400
    
    tutoring_session = TutoringSession.query.filter_by(room_id=room_id).first()
    if not tutoring_session:
        return jsonify({'success': False, 'error': 'Session not found'}), 404
    
    # Update session
    tutoring_session.student_rating = rating
    tutoring_session.student_feedback = feedback
    db.session.commit()
    
    # Update Tutor Average Rating
    tutor = db.session.get(Tutor, tutoring_session.tutor_id)
    if tutor:
        # Get all rated sessions
        rated_sessions = TutoringSession.query.filter(
            TutoringSession.tutor_id == tutor.id,
            TutoringSession.student_rating.isnot(None)
        ).all()
        
        if rated_sessions:
            total_rating = sum(s.student_rating for s in rated_sessions)
            tutor.rating = total_rating / len(rated_sessions)
            db.session.commit()
            
    return jsonify({'success': True})
