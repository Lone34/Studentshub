"""
Online School Blueprint
Handles grades, subjects, and live classroom functionality
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user
from models import db, Grade, Subject, SchoolClass, ClassAttendance, Tutor, User
from datetime import datetime, date
import uuid
# Import signaling helper
from signaling import get_room_count
import os

school_bp = Blueprint('school', __name__, url_prefix='/school')


# ============================================
# STUDENT ROUTES
# ============================================

@school_bp.route('/')
@login_required
def index():
    """Main school page - shows student's scheduled classes"""
    if not current_user.can_access('school'):
        flash("You need the School Plan (₹1200) to access online classes.")
        return redirect(url_for('payments.pricing'))

    if not current_user.grade_id:
        # Student hasn't enrolled in a grade
        grades = Grade.query.filter_by(is_active=True).order_by(Grade.display_order).all()
        return render_template('school/select_grade.html', grades=grades)
    
    # Get student's grade
    grade = Grade.query.get(current_user.grade_id)
    if not grade:
        flash("Your enrolled grade was not found. Please select a grade.")
        return redirect(url_for('school.select_grade'))
    
    # Get classes for this grade
    all_classes = SchoolClass.query.filter_by(grade_id=grade.id).order_by(SchoolClass.scheduled_date, SchoolClass.start_time).all()
    
    upcoming = []
    ongoing = []
    completed = []
    
    now = datetime.now()
    today = date.today()
    
    for cls in all_classes:
        # Determine status
        is_expired = False
        try:
            # check if time is passed
            end_dt = datetime.combine(cls.scheduled_date, datetime.strptime(cls.end_time, '%H:%M').time())
            if now > end_dt:
                is_expired = True
        except:
            is_expired = False

        if cls.status == 'completed':
            completed.append(cls)
        elif cls.status in ['ongoing', 'live']:
            if is_expired:
                if cls.status == 'live':
                    cls.status = 'completed'
                    cls.ended_at = datetime.utcnow()
                    db.session.commit()
                completed.append(cls)
            else:
                ongoing.append(cls)
        else:
            # Scheduled or other
            if is_expired:
                completed.append(cls) # It's past
            else:
                upcoming.append(cls)
            
    return render_template('school/index.html', 
                         grade=grade, 
                         upcoming=upcoming,
                         ongoing=ongoing,
                         completed=completed,
                         today=today)


@school_bp.route('/select-grade', methods=['GET', 'POST'])
@login_required
def select_grade():
    """Allow student to select/change their enrolled grade"""
    if not current_user.can_access('school'):
        flash("You need the School Plan to select a grade.")
        return redirect(url_for('payments.pricing'))

    if request.method == 'POST':
        grade_id = request.form.get('grade_id')
        if grade_id:
            grade = Grade.query.get(grade_id)
            if grade and grade.is_active:
                current_user.grade_id = grade.id
                db.session.commit()
                flash(f"You are now enrolled in {grade.name}!")
                return redirect(url_for('school.index'))
        flash("Invalid grade selected.")
    
    grades = Grade.query.filter_by(is_active=True).order_by(Grade.display_order).all()
    return render_template('school/select_grade.html', grades=grades)


@school_bp.route('/class/<int:class_id>/join')
@login_required
def join_class(class_id):
    """Join a live school class"""
    if not current_user.can_access('school'):
        flash("Upgrade to School Plan to join classes.")
        return redirect(url_for('payments.pricing'))

    school_class = SchoolClass.query.get_or_404(class_id)
    subject = school_class.subject
    
    # Verify student is enrolled in this grade
    if current_user.grade_id != subject.grade_id:
        flash("You are not enrolled in this grade.")
        return redirect(url_for('school.index'))
    
    # Check if class is live or about to start
    if school_class.status not in ['scheduled', 'live']:
        flash("This class has ended.")
        return redirect(url_for('school.index'))
    
    # Record attendance
    existing = ClassAttendance.query.filter_by(
        class_id=class_id, 
        student_id=current_user.id
    ).first()
    
    if not existing:
        attendance = ClassAttendance(
            class_id=class_id,
            student_id=current_user.id
        )
        db.session.add(attendance)
        db.session.commit()
    
    # Get teacher info
    teacher = Tutor.query.get(school_class.teacher_id)
    
    return render_template('school/classroom.html',
                         school_class=school_class,
                         subject=subject,
                         teacher=teacher,
                         is_teacher=False,
                         student_name=current_user.full_name or current_user.username)


# ============================================
# TEACHER ROUTES
# ============================================

@school_bp.route('/teacher/dashboard')
@login_required
def teacher_dashboard():
    """Teacher's view of their scheduled classes"""
    # Get tutor profile for current user
    tutor = Tutor.query.filter_by(email=current_user.email).first() if current_user.email else None
    
    if not tutor:
        tutor = Tutor.query.filter_by(is_approved=True).first()  # Fallback
    
    if not tutor:
        flash("You don't have a teacher account.")
        return redirect(url_for('dashboard'))
    
    # Get classes assigned to this teacher
    # Filter by date? Let's show all for now, sorted by date/time
    all_classes = SchoolClass.query.filter_by(teacher_id=tutor.id).order_by(SchoolClass.scheduled_date.desc(), SchoolClass.start_time).all()
    
    # Separate into relevant lists
    today_classes = []
    upcoming_classes = []
    history_classes = []
    
    today = date.today()
    now = datetime.now()
    
    for cls in all_classes:
        # Auto-expire if time is passed
        is_expired = False
        try:
            end_dt = datetime.combine(cls.scheduled_date, datetime.strptime(cls.end_time, '%H:%M').time())
            if now > end_dt:
                is_expired = True
                # If it was live, mark as completed in DB to persist this state
                if cls.status == 'live':
                    cls.status = 'completed'
                    cls.ended_at = datetime.utcnow()
                    db.session.commit()
        except:
            is_expired = False

        if cls.scheduled_date == today:
            today_classes.append(cls)
        elif cls.scheduled_date > today:
            upcoming_classes.append(cls)
        else:
            history_classes.append(cls)
            
    # For now, just pass all_classes or structure it
    return render_template('school/teacher_dashboard.html', 
                         tutor=tutor, 
                         today_classes=today_classes,
                         upcoming_classes=upcoming_classes,
                         history_classes=history_classes)


@school_bp.route('/teacher/start-class/<int:class_id>', methods=['POST'])
def start_class(class_id):
    """Teacher starts a scheduled class"""
    school_class = SchoolClass.query.get_or_404(class_id)
    
    # Verify teacher owns this class
    tutor = None
    if current_user.is_authenticated and current_user.email:
        tutor = Tutor.query.filter_by(email=current_user.email).first()
    elif 'tutor_id' in session:
        tutor = db.session.get(Tutor, session['tutor_id'])

    if not tutor or school_class.teacher_id != tutor.id:
        return jsonify({"error": "Unauthorized"}), 403
    
    # Update status
    school_class.status = 'live'
    if not school_class.started_at:
        school_class.started_at = datetime.utcnow()
    
    # Ensure room_id exists (it should from creation)
    if not school_class.room_id:
        school_class.room_id = f"school_{uuid.uuid4().hex[:12]}"
        
    db.session.commit()
    
    return jsonify({
        "success": True,
        "room_id": school_class.room_id,
        "class_id": school_class.id
    })


@school_bp.route('/teacher/class/<int:class_id>')
def teacher_classroom(class_id):
    """Teacher's view of the classroom (broadcasting)"""
    school_class = SchoolClass.query.get_or_404(class_id)
    subject = school_class.subject
    
    # Verify teacher
    tutor = None
    if current_user.is_authenticated and current_user.email:
        tutor = Tutor.query.filter_by(email=current_user.email).first()
    elif 'tutor_id' in session:
        tutor = db.session.get(Tutor, session['tutor_id'])

    if not tutor or school_class.teacher_id != tutor.id:
        flash("Unauthorized access.")
        return redirect(url_for('school.teacher_dashboard'))
    
    return render_template('school/classroom.html',
                         school_class=school_class,
                         subject=subject,
                         teacher=tutor,
                         is_teacher=True)


@school_bp.route('/api/class/<int:class_id>/attendance')
def get_class_attendance(class_id):
    """Get current live attendance count for a class"""
    school_class = SchoolClass.query.get_or_404(class_id)
    # Get count from signaling server
    count = get_room_count(school_class.room_id)
    return jsonify({'count': count})


@school_bp.route('/teacher/end-class/<int:class_id>', methods=['POST'])
def end_class(class_id):
    """Teacher ends a live class"""
    school_class = SchoolClass.query.get_or_404(class_id)
    
    # Verify teacher
    tutor = None
    if current_user.is_authenticated and current_user.email:
        tutor = Tutor.query.filter_by(email=current_user.email).first()
    elif 'tutor_id' in session:
        tutor = db.session.get(Tutor, session['tutor_id'])

    if not tutor or school_class.teacher_id != tutor.id:
        return jsonify({"error": "Unauthorized"}), 403
    
    school_class.status = 'completed' # Use 'completed' to match new status enum
    school_class.ended_at = datetime.utcnow()
    
    # Calculate peak attendance
    attendance_count = ClassAttendance.query.filter_by(class_id=class_id).count()
    school_class.peak_attendance = attendance_count
    
    db.session.commit()
    
    return jsonify({"success": True})


# ============================================
# API ROUTES
# ============================================

@school_bp.route('/api/schedule')
@login_required
def api_schedule():
    """Get today's schedule for the student's grade"""
    if not current_user.can_access('school'):
        return jsonify({"error": "Plan upgrade required"}), 403

    if not current_user.grade_id:
        return jsonify({"error": "Not enrolled in a grade"})
    
    today = date.today()
    classes = SchoolClass.query.filter_by(
        grade_id=current_user.grade_id,
        scheduled_date=today
    ).order_by(SchoolClass.start_time).all()
    
    schedule = []
    for cls in classes:
        schedule.append({
            "id": cls.subject_id, # Keep compatibility or change to class_id
            "name": cls.subject.name,
            "time": cls.start_time,
            "duration": cls.end_time, # Just show end time or calc duration
            "teacher": cls.teacher.display_name if cls.teacher else "TBA",
            "is_live": cls.status == 'live',
            "class_id": cls.id,
            "status": cls.status
        })
    
    return jsonify({"schedule": schedule})


@school_bp.route('/api/class/<int:class_id>/attendance')
@login_required
def api_class_attendance(class_id):
    """Get current attendance count for a class"""
    school_class = SchoolClass.query.get_or_404(class_id)
    count = ClassAttendance.query.filter_by(class_id=class_id).count()
    
    return jsonify({
        "count": count,
        "status": school_class.status
    })


# ============================================
# ADMIN API ROUTES
# ============================================

def admin_required(f):
    """Decorator to require super_admin role"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'super_admin':
            return jsonify({"error": "Unauthorized"}), 403
        return f(*args, **kwargs)
    return decorated_function


# --- GRADES ---
@school_bp.route('/admin/grades', methods=['GET'])
@login_required
@admin_required
def admin_list_grades():
    """List all grades"""
    grades = Grade.query.order_by(Grade.display_order).all()
    return jsonify({
        "grades": [{
            "id": g.id,
            "name": g.name,
            "display_order": g.display_order,
            "is_active": g.is_active,
            "subject_count": len(g.subjects),
            "student_count": len(g.students)
        } for g in grades]
    })


@school_bp.route('/admin/grades', methods=['POST'])
@login_required
@admin_required
def admin_create_grade():
    """Create a new grade"""
    data = request.get_json()
    name = data.get('name', '').strip()
    
    if not name:
        return jsonify({"error": "Name is required"}), 400
    
    # Get next display order
    max_order = db.session.query(db.func.max(Grade.display_order)).scalar() or 0
    
    grade = Grade(
        name=name,
        display_order=max_order + 1,
        is_active=data.get('is_active', True)
    )
    db.session.add(grade)
    db.session.commit()
    
    return jsonify({"success": True, "id": grade.id, "message": f"Grade '{name}' created"})


@school_bp.route('/admin/grades/<int:grade_id>', methods=['PUT'])
@login_required
@admin_required
def admin_update_grade(grade_id):
    """Update a grade"""
    grade = Grade.query.get_or_404(grade_id)
    data = request.get_json()
    
    if 'name' in data:
        grade.name = data['name'].strip()
    if 'display_order' in data:
        grade.display_order = data['display_order']
    if 'is_active' in data:
        grade.is_active = data['is_active']
    
    db.session.commit()
    return jsonify({"success": True, "message": f"Grade updated"})


@school_bp.route('/admin/grades/<int:grade_id>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_grade(grade_id):
    """Delete a grade (and its subjects)"""
    grade = Grade.query.get_or_404(grade_id)
    name = grade.name
    db.session.delete(grade)
    db.session.commit()
    return jsonify({"success": True, "message": f"Grade '{name}' deleted"})


# --- SUBJECTS ---
@school_bp.route('/admin/subjects', methods=['GET'])
@login_required
@admin_required
def admin_list_subjects():
    """List all subjects (optionally filtered by grade)"""
    grade_id = request.args.get('grade_id')
    
    query = Subject.query
    if grade_id:
        query = query.filter_by(grade_id=grade_id)
    
    subjects = query.order_by(Subject.grade_id, Subject.name).all()
    
    return jsonify({
        "subjects": [{
            "id": s.id,
            "name": s.name,
            "grade_id": s.grade_id,
            "grade_name": s.grade.name if s.grade else None,
            "description": s.description,
            "is_active": s.is_active
        } for s in subjects]
    })


@school_bp.route('/admin/subjects', methods=['POST'])
@login_required
@admin_required
def admin_create_subject():
    """Create a new subject (Master Data)"""
    data = request.get_json()
    
    name = data.get('name', '').strip()
    grade_id = data.get('grade_id')
    
    if not name or not grade_id:
        return jsonify({"error": "Name and grade_id are required"}), 400
    
    subject = Subject(
        name=name,
        grade_id=grade_id,
        description=data.get('description'),
        is_active=data.get('is_active', True)
    )
    db.session.add(subject)
    db.session.commit()
    
    return jsonify({"success": True, "id": subject.id, "message": f"Subject '{name}' created"})


# --- CLASSES (SCHEDULE) ---
@school_bp.route('/admin/classes', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_classes():
    """CRUD for SchoolClasses (The Schedule)"""
    if request.method == 'POST':
        data = request.get_json()
        
        # Validate required fields
        required = ['grade_id', 'subject_id', 'date', 'start_time', 'end_time']
        if not all(k in data for k in required):
            return jsonify({"error": "Missing required fields"}), 400
            
        try:
            sch_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            
            new_class = SchoolClass(
                grade_id=data['grade_id'],
                subject_id=data['subject_id'],
                teacher_id=data.get('teacher_id') or None, # Optional
                scheduled_date=sch_date,
                start_time=data['start_time'],
                end_time=data['end_time'],
                status='upcoming',
                room_id=str(uuid.uuid4())
            )
            db.session.add(new_class)
            db.session.commit()
            return jsonify({"success": True, "message": "Class scheduled successfully."})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # GET: List classes (optionally filter by grade/date)
    grade_id = request.args.get('grade_id')
    query = SchoolClass.query.order_by(SchoolClass.scheduled_date.desc(), SchoolClass.start_time)
    
    if grade_id:
        query = query.filter_by(grade_id=grade_id)
        
    classes = query.all()
    return jsonify({
        "classes": [{
            "id": c.id,
            "grade_id": c.grade_id,
            "grade_name": c.grade.name if c.grade else "Unknown",
            "subject_id": c.subject_id,
            "subject_name": c.subject.name if c.subject else "Unknown",
            "teacher_id": c.teacher_id,
            "teacher_name": c.teacher.display_name if c.teacher else "No Tutor",
            "date": c.scheduled_date.strftime('%Y-%m-%d'),
            "start_time": c.start_time,
            "end_time": c.end_time,
            "status": c.status
        } for c in classes]
    })


@school_bp.route('/admin/classes/<int:id>', methods=['PUT', 'DELETE'])
@login_required
@admin_required
def admin_manage_class(id):
    school_class = SchoolClass.query.get_or_404(id)
    
    if request.method == 'DELETE':
        db.session.delete(school_class)
        db.session.commit()
        return jsonify({"success": True})
        
    # PUT: Update details (e.g. assign tutor)
    data = request.get_json()
    if 'teacher_id' in data:
        school_class.teacher_id = data['teacher_id'] or None
    if 'status' in data: 
        school_class.status = data['status']
    if 'start_time' in data:
        school_class.start_time = data['start_time']
    if 'end_time' in data:
        school_class.end_time = data['end_time']
    if 'date' in data:
        school_class.scheduled_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        
    db.session.commit()
    return jsonify({"success": True})


# --- TUTOR MATCHING ---
@school_bp.route('/admin/tutors/match', methods=['GET'])
@login_required
@admin_required
def admin_match_tutors():
    """Find tutors matching Grade AND Subject"""
    grade_id = request.args.get('grade_id')
    subject_id = request.args.get('subject_id')
    
    if not grade_id or not subject_id:
        return jsonify({"tutors": []})
        
    grade = Grade.query.get(grade_id)
    subject = Subject.query.get(subject_id)
    
    if not grade or not subject:
        return jsonify({"tutors": []})
        
    # Filter Logic:
    # 1. Tutor must be approved
    # 2. Tutor.teaching_grades must contain grade.name
    # 3. Tutor.subjects must contain subject.name
    
    all_tutors = Tutor.query.filter_by(is_approved=True).all()
    matched = []
    
    for t in all_tutors:
        # Check Grade
        if not t.teaching_grades: continue
        t_grades = [g.strip().lower() for g in t.teaching_grades.split(',')]
        if grade.name.lower() not in t_grades:
            continue
            
        # Check Subject
        if not t.subjects: continue
        t_subs = [s.strip().lower() for s in t.subjects.split(',')]
        # Simple containment check
        is_match = False
        for sub in t_subs:
            if sub in subject.name.lower() or subject.name.lower() in sub:
                is_match = True
                break
        
        if is_match:
            matched.append({
                "id": t.id,
                "name": t.display_name,
                "subjects": t.subjects
            })
        
    return jsonify({"tutors": matched})


@school_bp.route('/admin/subjects/<int:subject_id>', methods=['PUT'])
@login_required
@admin_required
def admin_update_subject(subject_id):
    """Update a subject"""
    subject = Subject.query.get_or_404(subject_id)
    data = request.get_json()
    
    if 'name' in data:
        subject.name = data['name'].strip()
    if 'description' in data:
        subject.description = data['description']
    if 'is_active' in data:
        subject.is_active = data['is_active']
    
    db.session.commit()
    return jsonify({"success": True, "message": "Subject updated"})


@school_bp.route('/admin/subjects/<int:subject_id>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete_subject(subject_id):
    """Delete a subject"""
    subject = Subject.query.get_or_404(subject_id)
    name = subject.name
    db.session.delete(subject)
    db.session.commit()
    return jsonify({"success": True, "message": f"Subject '{name}' deleted"})


# --- TEACHERS LIST (for dropdown) ---
@school_bp.route('/admin/teachers', methods=['GET'])
@login_required
@admin_required
def admin_list_teachers():
    """List approved tutors, optionally filtered by grade"""
    grade_id = request.args.get('grade_id')
    query = Tutor.query.filter_by(is_approved=True, is_active=True)
    tutors = query.all()
    
    print(f"DEBUG: admin_list_teachers called with grade_id={grade_id}, subject={request.args.get('subject')}", flush=True)
    
    # Filter by grade if requested
    if grade_id:
        grade = Grade.query.get(grade_id)
        if grade:
            print(f"DEBUG: Filtering for Grade: {grade.name}", flush=True)
            # Filter tutors who have this grade in their teaching_grades
            # If they haven't set preferences (empty), assume they teach ALL
            filtered = []
            for t in tutors:
                if not t.teaching_grades or not t.teaching_grades.strip():
                    filtered.append(t)
                else:
                    grades_list = [g.strip() for g in t.teaching_grades.split(',')]
                    if grade.name in grades_list:
                        filtered.append(t)
                    else:
                        print(f"DEBUG: Skipped {t.display_name} (Grades: {grades_list})", flush=True)
            tutors = filtered
            
    # Filter by subject if requested
    subject_filter = request.args.get('subject')
    if subject_filter:
        subject_filter = subject_filter.lower().strip()
        print(f"DEBUG: Filtering for Subject: {subject_filter}", flush=True)
        filtered = []
        for t in tutors:
            if t.subjects:
                # User wants "enrolled in that area". Let's do partial match.
                t_subjects = [s.strip().lower() for s in t.subjects.split(',')]
                # Check if subject_filter is a substring of ANY of the tutor's subjects
                if any(subject_filter in s for s in t_subjects):
                    filtered.append(t)
                else:
                    print(f"DEBUG: Skipped {t.display_name} (Subjects: {t_subjects})", flush=True)
        tutors = filtered

    print(f"DEBUG: Returning {len(tutors)} tutors", flush=True)
    return jsonify({
        "teachers": [{
            "id": t.id,
            "display_name": t.display_name,
            "email": t.email,
            "subjects": t.subjects,
            "teaching_grades": t.teaching_grades
        } for t in tutors]
    })


# --- TUTOR APPROVAL WORKFLOW ---

@school_bp.route('/admin/tutors/pending', methods=['GET'])
@login_required
@admin_required
def admin_list_pending_tutors():
    """List all tutors waiting for approval"""
    pending_tutors = Tutor.query.filter_by(is_approved=False).all()
    
    return jsonify({
        "tutors": [{
            "id": t.id,
            "display_name": t.display_name,
            "email": t.email,
            "phone": t.phone,
            "qualification": t.qualification,
            "experience_years": t.experience_years,
            "subjects": t.subjects,
            "teaching_grades": t.teaching_grades,
            "id_proof_url": url_for('uploaded_file', filename=os.path.basename(t.id_proof_path)) if t.id_proof_path else None,
            "created_at": t.created_at.strftime('%Y-%m-%d') if hasattr(t, 'created_at') else None
        } for t in pending_tutors]
    })


@school_bp.route('/admin/tutors/<int:tutor_id>/approve', methods=['POST'])
@login_required
@admin_required
def admin_approve_tutor(tutor_id):
    """Approve a tutor"""
    tutor = Tutor.query.get_or_404(tutor_id)
    tutor.is_approved = True
    tutor.is_available = True  # Make them available immediately
    db.session.commit()
    return jsonify({"success": True, "message": f"Tutor {tutor.display_name} approved!"})


@school_bp.route('/admin/tutors/<int:tutor_id>/reject', methods=['POST'])
@login_required
@admin_required
def admin_reject_tutor(tutor_id):
    """Reject (delete) a tutor application"""
    tutor = Tutor.query.get_or_404(tutor_id)
    
    # Optional: Delete uploaded ID proof file
    if tutor.id_proof_path and os.path.exists(tutor.id_proof_path):
        try:
            os.remove(tutor.id_proof_path)
        except:
            pass
            
    name = tutor.display_name
    db.session.delete(tutor)
    db.session.commit()
    return jsonify({"success": True, "message": f"Tutor application for {name} rejected."})


# --- SEED DEFAULT GRADES ---
@school_bp.route('/admin/seed-grades', methods=['POST'])
@login_required
@admin_required
def admin_seed_grades():
    """Create default grades from Nursery to 12th"""
    if Grade.query.count() > 0:
        return jsonify({"message": "Grades already exist"})
    
    default_grades = [
        "Nursery", "LKG", "UKG",
        "Class 1", "Class 2", "Class 3", "Class 4", "Class 5",
        "Class 6", "Class 7", "Class 8", "Class 9", "Class 10",
        "Class 11", "Class 12"
    ]
    
    for i, name in enumerate(default_grades):
        grade = Grade(name=name, display_order=i)
        db.session.add(grade)
    
    db.session.commit()
    return jsonify({"success": True, "message": f"Created {len(default_grades)} grades"})


# --- GLOBAL SUBJECTS (Master List) ---
class GlobalSubject(db.Model):
    """Standard list of subjects (e.g. Math, Science) independent of grades"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@school_bp.route('/admin/global-subjects', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_global_subjects():
    """CRUD for Global Subjects"""
    if request.method == 'POST':
        data = request.get_json()
        name = data.get('name', '').strip()
        if not name:
            return jsonify({"error": "Name is required"}), 400
            
        if GlobalSubject.query.filter_by(name=name).first():
            return jsonify({"error": "Subject already exists"}), 400
            
        subject = GlobalSubject(name=name)
        db.session.add(subject)
        db.session.commit()
        return jsonify({"success": True, "message": f"Global Subject '{name}' created"})

    # GET
    subjects = GlobalSubject.query.order_by(GlobalSubject.name).all()
    return jsonify({
        "subjects": [{"id": s.id, "name": s.name, "is_active": s.is_active} for s in subjects]
    })

@school_bp.route('/admin/global-subjects/<int:id>', methods=['DELETE'])
@login_required
@admin_required
def delete_global_subject(id):
    subject = GlobalSubject.query.get_or_404(id)
    db.session.delete(subject)
    db.session.commit()
    return jsonify({"success": True, "message": "Global Subject deleted"})



