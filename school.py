"""
Online School Blueprint
Handles grades, subjects, and live classroom functionality
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import db, Grade, Subject, SchoolClass, ClassAttendance, Tutor, User
from datetime import datetime, date
import uuid
import os

school_bp = Blueprint('school', __name__, url_prefix='/school')


# ============================================
# STUDENT ROUTES
# ============================================

@school_bp.route('/')
@login_required
def index():
    """Main school page - shows student's enrolled grade subjects"""
    if not current_user.grade_id:
        # Student hasn't enrolled in a grade
        grades = Grade.query.filter_by(is_active=True).order_by(Grade.display_order).all()
        return render_template('school/select_grade.html', grades=grades)
    
    # Get student's grade and its subjects
    grade = Grade.query.get(current_user.grade_id)
    if not grade:
        flash("Your enrolled grade was not found. Please select a grade.")
        return redirect(url_for('school.select_grade'))
    
    # Get today's schedule
    today = datetime.now().strftime('%a').lower()[:3]  # mon, tue, wed, etc.
    subjects = Subject.query.filter_by(
        grade_id=grade.id, 
        is_active=True
    ).order_by(Subject.schedule_time).all()
    
    # Filter subjects that run today
    today_subjects = [s for s in subjects if today in (s.schedule_days or '').lower()]
    
    # Get live classes for today
    live_classes = SchoolClass.query.filter(
        SchoolClass.subject_id.in_([s.id for s in today_subjects]),
        SchoolClass.scheduled_date == date.today(),
        SchoolClass.status.in_(['scheduled', 'live'])
    ).all()
    
    # Create a lookup for easy template access
    live_class_map = {lc.subject_id: lc for lc in live_classes}
    
    return render_template('school/index.html', 
                         grade=grade, 
                         subjects=today_subjects,
                         all_subjects=subjects,
                         live_class_map=live_class_map,
                         today=today)


@school_bp.route('/select-grade', methods=['GET', 'POST'])
@login_required
def select_grade():
    """Allow student to select/change their enrolled grade"""
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
                         is_teacher=False)


# ============================================
# TEACHER ROUTES
# ============================================

@school_bp.route('/teacher/dashboard')
@login_required
def teacher_dashboard():
    """Teacher's view of their school classes"""
    # Get tutor profile for current user (via email match or separate login)
    tutor = Tutor.query.filter_by(email=current_user.email).first() if current_user.email else None
    
    if not tutor:
        # Try to find by matching username pattern
        tutor = Tutor.query.filter_by(is_approved=True).first()  # Fallback for testing
    
    if not tutor:
        flash("You don't have a teacher account.")
        return redirect(url_for('dashboard'))
    
    # Get subjects assigned to this teacher
    subjects = Subject.query.filter_by(teacher_id=tutor.id, is_active=True).all()
    
    # Get today's classes
    today = date.today()
    today_classes = SchoolClass.query.filter(
        SchoolClass.teacher_id == tutor.id,
        SchoolClass.scheduled_date == today
    ).all()
    
    return render_template('school/teacher_dashboard.html',
                         tutor=tutor,
                         subjects=subjects,
                         today_classes=today_classes)


@school_bp.route('/teacher/start-class/<int:subject_id>', methods=['POST'])
@login_required
def start_class(subject_id):
    """Teacher starts a live class for a subject"""
    subject = Subject.query.get_or_404(subject_id)
    
    # Verify teacher owns this subject
    tutor = Tutor.query.filter_by(email=current_user.email).first() if current_user.email else None
    if not tutor or subject.teacher_id != tutor.id:
        return jsonify({"error": "Unauthorized"}), 403
    
    # Check for existing live class today
    existing = SchoolClass.query.filter_by(
        subject_id=subject_id,
        scheduled_date=date.today(),
        status='live'
    ).first()
    
    if existing:
        return jsonify({
            "success": True,
            "room_id": existing.room_id,
            "class_id": existing.id
        })
    
    # Create new class session
    room_id = f"school_{uuid.uuid4().hex[:12]}"
    school_class = SchoolClass(
        subject_id=subject_id,
        teacher_id=tutor.id,
        room_id=room_id,
        scheduled_date=date.today(),
        status='live',
        started_at=datetime.utcnow()
    )
    db.session.add(school_class)
    db.session.commit()
    
    return jsonify({
        "success": True,
        "room_id": room_id,
        "class_id": school_class.id
    })


@school_bp.route('/teacher/class/<int:class_id>')
@login_required
def teacher_classroom(class_id):
    """Teacher's view of the classroom (broadcasting)"""
    school_class = SchoolClass.query.get_or_404(class_id)
    subject = school_class.subject
    
    # Verify teacher
    tutor = Tutor.query.filter_by(email=current_user.email).first() if current_user.email else None
    if not tutor or school_class.teacher_id != tutor.id:
        flash("Unauthorized access.")
        return redirect(url_for('school.teacher_dashboard'))
    
    return render_template('school/classroom.html',
                         school_class=school_class,
                         subject=subject,
                         teacher=tutor,
                         is_teacher=True)


@school_bp.route('/teacher/end-class/<int:class_id>', methods=['POST'])
@login_required
def end_class(class_id):
    """Teacher ends a live class"""
    school_class = SchoolClass.query.get_or_404(class_id)
    
    # Verify teacher
    tutor = Tutor.query.filter_by(email=current_user.email).first() if current_user.email else None
    if not tutor or school_class.teacher_id != tutor.id:
        return jsonify({"error": "Unauthorized"}), 403
    
    school_class.status = 'ended'
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
    if not current_user.grade_id:
        return jsonify({"error": "Not enrolled in a grade"})
    
    today = datetime.now().strftime('%a').lower()[:3]
    subjects = Subject.query.filter_by(
        grade_id=current_user.grade_id,
        is_active=True
    ).order_by(Subject.schedule_time).all()
    
    schedule = []
    for subject in subjects:
        if today in (subject.schedule_days or '').lower():
            # Check if class is live
            live_class = SchoolClass.query.filter_by(
                subject_id=subject.id,
                scheduled_date=date.today(),
                status='live'
            ).first()
            
            schedule.append({
                "id": subject.id,
                "name": subject.name,
                "time": subject.schedule_time,
                "duration": subject.duration_minutes,
                "teacher": subject.teacher.display_name if subject.teacher else "TBA",
                "is_live": live_class is not None,
                "class_id": live_class.id if live_class else None
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
    
    subjects = query.order_by(Subject.grade_id, Subject.schedule_time).all()
    
    return jsonify({
        "subjects": [{
            "id": s.id,
            "name": s.name,
            "grade_id": s.grade_id,
            "grade_name": s.grade.name if s.grade else None,
            "schedule_time": s.schedule_time,
            "schedule_days": s.schedule_days,
            "duration_minutes": s.duration_minutes,
            "teacher_id": s.teacher_id,
            "teacher_name": s.teacher.display_name if s.teacher else None,
            "is_active": s.is_active
        } for s in subjects]
    })


@school_bp.route('/admin/subjects', methods=['POST'])
@login_required
@admin_required
def admin_create_subject():
    """Create a new subject"""
    data = request.get_json()
    
    name = data.get('name', '').strip()
    grade_id = data.get('grade_id')
    
    if not name or not grade_id:
        return jsonify({"error": "Name and grade_id are required"}), 400
    
    subject = Subject(
        name=name,
        grade_id=grade_id,
        description=data.get('description'),
        schedule_time=data.get('schedule_time'),
        schedule_days=data.get('schedule_days', 'mon,tue,wed,thu,fri'),
        duration_minutes=data.get('duration_minutes', 45),
        teacher_id=data.get('teacher_id'),
        is_active=data.get('is_active', True)
    )
    db.session.add(subject)
    db.session.commit()
    
    return jsonify({"success": True, "id": subject.id, "message": f"Subject '{name}' created"})


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
    if 'schedule_time' in data:
        subject.schedule_time = data['schedule_time']
    if 'schedule_days' in data:
        subject.schedule_days = data['schedule_days']
    if 'duration_minutes' in data:
        subject.duration_minutes = data['duration_minutes']
    if 'teacher_id' in data:
        subject.teacher_id = data['teacher_id'] or None
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

