"""
Tutoring Blueprint - Handles tutor registration, login, and video session management
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime, date
import uuid
import os

from models import db, Tutor, TutoringSession, User, SchoolClass

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
def tutor_register():
    """Tutor registration page"""
    if request.method == 'POST':
        # Get form data
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()
        display_name = request.form.get('display_name', '').strip()
        qualification = request.form.get('qualification', '').strip()
        experience_years = request.form.get('experience_years', 0)
        college = request.form.get('college', '').strip()
        subjects_list = request.form.getlist('subjects')
        custom_subject = request.form.get('custom_subject', '').strip()
        if custom_subject:
            subjects_list.append(custom_subject)
        subjects = ", ".join([s.strip() for s in subjects_list if s.strip()])
        teaching_grades = request.form.getlist('teaching_grades')  # Get list of selected grades
        teaching_grades_str = ", ".join(teaching_grades) if teaching_grades else ""
        languages = request.form.get('languages', 'English').strip()
        bio = request.form.get('bio', '').strip()
        
        # Validations
        errors = []
        
        if not email or '@' not in email:
            errors.append('Valid email is required')
        
        if Tutor.query.filter_by(email=email).first():
            errors.append('Email already registered')
        
        if len(password) < 6:
            errors.append('Password must be at least 6 characters')
        
        if password != confirm_password:
            errors.append('Passwords do not match')
        
        if not full_name:
            errors.append('Full name is required')
        
        if not phone or len(phone) < 10:
            errors.append('Valid phone number is required')
        
        if not display_name:
            errors.append('Display name is required')
        
        if not qualification:
            errors.append('Qualification is required')
        
        if not subjects:
            errors.append('At least one subject is required')
            
        if not teaching_grades_str:
            errors.append('Please select at least one grade you can teach')
        
        if errors:
            for error in errors:
                flash(error, 'danger')
            return redirect(url_for('register') + '?type=tutor')
        
        # Handle ID proof upload
        id_proof_path = None
        if 'id_proof' in request.files:
            file = request.files['id_proof']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"tutor_{email}_{file.filename}")
                upload_folder = os.path.join('uploads', 'tutor_docs')
                os.makedirs(upload_folder, exist_ok=True)
                file_path = os.path.join(upload_folder, filename)
                file.save(file_path)
                id_proof_path = file_path
        
        # Create tutor
        tutor = Tutor(
            email=email,
            password=generate_password_hash(password),
            full_name=full_name,
            phone=phone,
            display_name=display_name,
            qualification=qualification,
            experience_years=int(experience_years) if experience_years else 0,
            college=college,
            subjects=subjects,
            teaching_grades=teaching_grades_str,
            languages=languages,
            bio=bio,
            id_proof_path=id_proof_path,
            is_approved=False,  # Requires admin approval
            is_available=False,
            is_active=True
        )
        
        db.session.add(tutor)
        db.session.commit()
        
        flash('Registration successful! Please wait for admin approval.', 'success')
        return redirect(url_for('login') + '?type=tutor')
    
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
        session['tutor_id'] = tutor.id
        
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


@tutoring_bp.route('/pending-approval')
def pending_approval():
    """Show pending approval message"""
    if 'tutor_id' not in session:
        return redirect(url_for('tutoring.tutor_login'))
    
    tutor = db.session.get(Tutor, session['tutor_id'])
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
                from flask import current_app
                upload_folder = os.path.join(current_app.root_path, 'static/uploads/profiles')
                os.makedirs(upload_folder, exist_ok=True)
                
                ext = filename.rsplit('.', 1)[1].lower()
                unique_filename = f"tutor_{tutor.id}_{uuid.uuid4().hex[:8]}.{ext}"
                file.save(os.path.join(upload_folder, unique_filename))
                
                tutor.profile_image = f"uploads/profiles/{unique_filename}"
        
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

@tutoring_bp.route('/browse')
def browse_tutors():
    """Browse available tutors (for students)"""
    subject_filter = request.args.get('subject', '')
    
    from flask_login import current_user
    
    # Get approved and available tutors
    query = Tutor.query.filter_by(is_approved=True, is_active=True)
    
    if subject_filter:
        query = query.filter(Tutor.subjects.ilike(f'%{subject_filter}%'))
    
    all_tutors = query.order_by(Tutor.rating.desc()).all()
    filtered_tutors = []
    
    # Filter based on Student Type
    if current_user.is_authenticated:
        if current_user.student_type == 'higher_ed':
            # Show ONLY tutors who teach Higher Education
            filtered_tutors = [t for t in all_tutors if t.teaching_grades and 'Higher Education' in t.teaching_grades]
        else:
            # Show tutors who teach Grades (exclude those who ONLY teach Higher Ed)
            filtered_tutors = []
            for t in all_tutors:
                grades = t.teaching_grades or ""
                # Include if:
                # 1. Does NOT contain "Higher Education"
                # OR
                # 2. Contains "Higher Education" BUT also other grades (length > 1 implied, but string split is safer)
                
                # Simplified: Exclude ONLY if "Higher Education" is the ONLY thing they teach.
                # If grades is empty, they teach nothing? Maybe show them? Or hide? 
                # Let's hide if empty to be safe, or show if we want.
                # But to fix error:
                
                if 'Higher Education' not in grades:
                     filtered_tutors.append(t)
                elif len(grades.split(',')) > 1:
                     filtered_tutors.append(t)
            
    else:
        # For guests (landing page link?), show all? Or hide Higher Ed exclusive?
        filtered_tutors = all_tutors

    tutors = filtered_tutors
    
    # Get unique subjects from all tutors
    all_subjects = set()
    for t in Tutor.query.filter_by(is_approved=True).all():
        for s in t.subjects.split(','):
            all_subjects.add(s.strip())
    
    return render_template('tutoring/browse.html', 
                         tutors=tutors, 
                         subjects=sorted(all_subjects),
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
    
    # Check student credits (minimum 10 minutes worth)
    min_credits = RATE_PER_MINUTE * 10
    if current_user.credits < min_credits:
        return jsonify({
            'success': False, 
            'error': f'Insufficient credits. You need at least {min_credits} credits (for 10 minutes)'
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
    
    # Calculate credits
    credits_to_charge = duration_minutes * tutoring_session.rate_per_minute
    
    # Deduct from student
    student = db.session.get(User, tutoring_session.student_id)
    if student:
        student.credits = max(0, student.credits - credits_to_charge)
    
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
