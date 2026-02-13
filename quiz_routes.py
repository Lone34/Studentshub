from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, QuizSession, QuizAttempt, Subject
from ai_tutor import generate_quiz
import json
import datetime

quiz_bp = Blueprint('quiz_bp', __name__)

@quiz_bp.route('/quiz')
@login_required
def quiz_home():
    # Only show subjects that the student is enrolled in (via their grade)
    # Assuming user.grade_id or similiar logic. 
    # For now, let's fetch all subjects for the user's enrolled grade.
    if not current_user.grade_id:
        flash("Please update your profile with your Grade to access quizzes.", "warning")
        return redirect(url_for('profile'))
        
    subjects = Subject.query.filter_by(grade_id=current_user.grade_id).all()
    return render_template('quiz/home.html', subjects=subjects)

@quiz_bp.route('/quiz/start/<int:subject_id>', methods=['POST'])
@login_required
def start_quiz(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    
    # 1. Generate Quiz via AI
    quiz_data = generate_quiz(subject.name, subject.grade.name, difficulty='hard')
    
    if not quiz_data:
        flash("AI is busy building your difficult quiz! Please try again in a moment.", "error")
        return redirect(url_for('quiz_bp.quiz_home'))
        
    # 2. Store in DB
    new_session = QuizSession(
        user_id=current_user.id,
        subject=subject.name,
        grade=subject.grade.name,
        questions_json=json.dumps(quiz_data),
        start_time=datetime.datetime.utcnow()
    )
    db.session.add(new_session)
    db.session.commit()
    
    return redirect(url_for('quiz_bp.take_quiz', session_id=new_session.id))

@quiz_bp.route('/quiz/take/<int:session_id>')
@login_required
def take_quiz(session_id):
    quiz_session = QuizSession.query.get_or_404(session_id)
    
    if quiz_session.user_id != current_user.id:
        return "Unauthorized", 403
        
    if quiz_session.is_completed:
        flash("You have already completed this quiz.", "info")
        return redirect(url_for('quiz_bp.quiz_home'))
        
    questions = json.loads(quiz_session.questions_json)
    
    return render_template('quiz/active_quiz.html', 
                           quiz_session=quiz_session, 
                           questions=questions,
                           total_questions=len(questions))

@quiz_bp.route('/quiz/submit/<int:session_id>', methods=['POST'])
@login_required
def submit_quiz(session_id):
    quiz_session = QuizSession.query.get_or_404(session_id)
    
    if quiz_session.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
        
    if quiz_session.is_completed:
        return jsonify({'error': 'Quiz already submitted'}), 400
        
    data = request.get_json()
    answers = data.get('answers', {}) # { "0": "A", "1": "C", ... }
    
    questions = json.loads(quiz_session.questions_json)
    score = 0
    results_details = []
    
    for idx, q in enumerate(questions):
        user_ans = answers.get(str(idx))
        correct_ans = q.get('answer')
        is_correct = (user_ans == correct_ans)
        
        if is_correct:
            score += 1
            
        results_details.append({
            'question': q['question'],
            'user_ans': user_ans,
            'correct_ans': correct_ans,
            'is_correct': is_correct,
            'explanation': q.get('explanation', 'No explanation provided.')
        })
        
    # Save Attempt
    attempt = QuizAttempt(
        user_id=current_user.id,
        subject=quiz_session.subject,
        score=score,
        total_questions=len(questions),
        details_json=json.dumps(results_details)
    )
    
    # Mark session completed
    quiz_session.is_completed = True
    
    db.session.add(attempt)
    db.session.commit()
    
    return jsonify({'redirect_url': url_for('quiz_bp.quiz_result', attempt_id=attempt.id)})

@quiz_bp.route('/quiz/result/<int:attempt_id>')
@login_required
def quiz_result(attempt_id):
    attempt = QuizAttempt.query.get_or_404(attempt_id)
    if attempt.user_id != current_user.id:
        return "Unauthorized", 403
        
    details = json.loads(attempt.details_json)
    return render_template('quiz/result.html', attempt=attempt, details=details)
