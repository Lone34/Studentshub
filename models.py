from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(50), default='user')
    credits = db.Column(db.Integer, default=0)
    manager_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    # Student profile fields
    full_name = db.Column(db.String(150), nullable=True)
    email = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    grade_id = db.Column(db.Integer, db.ForeignKey('grade.id'), nullable=True)  # Enrolled grade for school
    
    service_accounts = db.relationship('ServiceAccount', backref='owner', lazy=True, foreign_keys='ServiceAccount.owner_id')

class ServiceAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    cookie_data = db.Column(db.Text, nullable=False) 
    # --- NEW PROXY FIELD ---
    proxy = db.Column(db.String(255), nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='Pending')
    result_message = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    service_account_name = db.Column(db.String(100), nullable=True)

class ChatHistory(db.Model):
    """Stores AI Tutor conversations for history and analytics"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ai_provider = db.Column(db.String(20), nullable=False)  # 'chatgpt' or 'gemini'
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(50), default='general')  # 'questions', 'exams', 'news', 'answers', etc
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('chat_history', lazy=True))

class Document(db.Model):
    """Stores uploaded documents in the library"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    doc_type = db.Column(db.String(50), default='notes')  # 'exam', 'notes', 'paper', 'assignment'
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(20), nullable=False)  # 'pdf', 'image'
    extracted_text = db.Column(db.Text, nullable=True)  # OCR extracted text
    formatted_content = db.Column(db.Text, nullable=True)  # AI-formatted content
    thumbnail_path = db.Column(db.String(500), nullable=True)
    downloads = db.Column(db.Integer, default=0)
    is_approved = db.Column(db.Boolean, default=True)  # For moderation
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('documents', lazy=True))

class DocumentUnlock(db.Model):
    """Tracks which users have unlocked which documents"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('unlocked_docs', lazy=True))
    document = db.relationship('Document', backref=db.backref('unlocks', lazy=True))


# ============================================
# VIDEO TUTORING MODELS
# ============================================

class Tutor(db.Model):
    """Tutor profiles for 1-on-1 video sessions"""
    id = db.Column(db.Integer, primary_key=True)
    
    # Login credentials (separate from User to keep tutors isolated)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    
    # Personal details (for admin verification, not shown to students)
    full_name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    
    # Public profile (shown to students)
    display_name = db.Column(db.String(100), nullable=False)  # Anonymous name
    bio = db.Column(db.Text, nullable=True)
    profile_image = db.Column(db.String(500), nullable=True)
    
    # Qualifications (for admin verification)
    qualification = db.Column(db.String(200), nullable=False)  # e.g., "B.Tech Computer Science"
    experience_years = db.Column(db.Integer, default=0)
    college = db.Column(db.String(200), nullable=True)
    id_proof_path = db.Column(db.String(500), nullable=True)  # Uploaded ID for verification
    
    # Teaching details
    subjects = db.Column(db.String(500), nullable=False)  # Comma-separated: "Math,Physics,Chemistry"
    teaching_grades = db.Column(db.String(500), nullable=True)  # Comma-separated: "Class 9, Class 10"
    languages = db.Column(db.String(200), default="English")  # Languages they can teach in
    
    # Status
    is_approved = db.Column(db.Boolean, default=False)  # Requires admin approval
    is_available = db.Column(db.Boolean, default=False)  # Online/offline toggle
    is_active = db.Column(db.Boolean, default=True)  # Account active
    
    # Stats
    rating = db.Column(db.Float, default=5.0)
    total_sessions = db.Column(db.Integer, default=0)
    total_minutes = db.Column(db.Integer, default=0)
    total_earnings = db.Column(db.Integer, default=0)  # In credits
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)
    last_online = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    sessions = db.relationship('TutoringSession', backref='tutor', lazy=True)


class TutoringSession(db.Model):
    """Tracks video tutoring sessions between students and tutors"""
    id = db.Column(db.Integer, primary_key=True)
    
    # Room identification
    room_id = db.Column(db.String(50), unique=True, nullable=False)  # UUID for video room
    
    # Participants
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tutor_id = db.Column(db.Integer, db.ForeignKey('tutor.id'), nullable=False)
    
    # Session details
    question = db.Column(db.Text, nullable=True)  # Student's doubt/question
    subject = db.Column(db.String(100), nullable=True)
    
    # Billing (pay-per-minute with platform fixed rate)
    rate_per_minute = db.Column(db.Integer, default=2)  # Credits per minute (platform sets this)
    credits_paid = db.Column(db.Integer, default=0)  # Total credits deducted
    
    # Status: pending -> waiting -> active -> completed/cancelled
    status = db.Column(db.String(20), default='pending')
    
    # Timing
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)  # When call actually started
    ended_at = db.Column(db.DateTime, nullable=True)
    duration_minutes = db.Column(db.Integer, default=0)
    
    # Recording & Chat
    recording_path = db.Column(db.String(500), nullable=True)  # Path to video file
    chat_log = db.Column(db.Text, nullable=True)  # JSON string of chat messages
    
    # Feedback
    student_rating = db.Column(db.Integer, nullable=True)  # 1-5 stars
    student_feedback = db.Column(db.Text, nullable=True)
    tutor_notes = db.Column(db.Text, nullable=True)
    
    # Moderation
    is_flagged = db.Column(db.Boolean, default=False)
    flag_reason = db.Column(db.String(200), nullable=True)
    reviewed_by_admin = db.Column(db.Boolean, default=False)
    
    # Relationships
    student = db.relationship('User', backref=db.backref('tutoring_sessions', lazy=True))


# ============================================
# ONLINE SCHOOL MODELS
# ============================================

class Grade(db.Model):
    """School grades from Nursery to 12th"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)  # e.g., "Nursery", "Class 10"
    display_order = db.Column(db.Integer, default=0)  # For sorting
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    subjects = db.relationship('Subject', backref='grade', lazy=True, cascade='all, delete-orphan')
    students = db.relationship('User', backref='enrolled_grade', lazy=True, foreign_keys='User.grade_id')


class Subject(db.Model):
    """Subjects for each grade with schedule times"""
    id = db.Column(db.Integer, primary_key=True)
    grade_id = db.Column(db.Integer, db.ForeignKey('grade.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)  # e.g., "English", "Mathematics"
    description = db.Column(db.Text, nullable=True)
    
    # Schedule (time of day for this subject's class)
    schedule_time = db.Column(db.String(10), nullable=True)  # e.g., "10:00" (24-hour format)
    duration_minutes = db.Column(db.Integer, default=45)
    
    # Days the class runs (comma-separated: "mon,tue,wed,thu,fri")
    schedule_days = db.Column(db.String(50), default="mon,tue,wed,thu,fri")
    
    # Assigned teacher (uses existing Tutor model)
    teacher_id = db.Column(db.Integer, db.ForeignKey('tutor.id'), nullable=True)
    teacher = db.relationship('Tutor', backref=db.backref('teaching_subjects', lazy=True))
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    classes = db.relationship('SchoolClass', backref='subject', lazy=True, cascade='all, delete-orphan')


class SchoolClass(db.Model):
    """Live class sessions for the online school"""
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('tutor.id'), nullable=False)
    
    # Room identification
    room_id = db.Column(db.String(50), unique=True, nullable=False)  # UUID for video room
    
    # Status: scheduled -> live -> ended
    status = db.Column(db.String(20), default='scheduled')
    
    # Timing
    scheduled_date = db.Column(db.Date, nullable=False)  # The date of this class
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    
    # Stats
    peak_attendance = db.Column(db.Integer, default=0)
    
    # Recording
    recording_url = db.Column(db.String(500), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    teacher = db.relationship('Tutor', backref=db.backref('school_classes', lazy=True))
    attendees = db.relationship('ClassAttendance', backref='school_class', lazy=True, cascade='all, delete-orphan')


class ClassAttendance(db.Model):
    """Tracks student attendance in school classes"""
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey('school_class.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Timing
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    left_at = db.Column(db.DateTime, nullable=True)
    duration_minutes = db.Column(db.Integer, default=0)
    
    # Relationships
    student = db.relationship('User', backref=db.backref('class_attendance', lazy=True))

