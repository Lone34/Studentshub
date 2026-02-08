from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
# --- ADDED THESE IMPORTS FOR IMAGE HANDLING ---
from werkzeug.utils import secure_filename
import os
# ----------------------------------------------
from models import db, User, ServiceAccount, Job, ChatHistory, Document, DocumentUnlock, Tutor, TutoringSession, Grade, Subject
from sqlalchemy import func, or_
import chegg_api
import time
import hashlib
from sqlalchemy import desc

app = Flask(__name__)
app.config['SECRET_KEY'] = 'YOUR_SECRET_KEY_HERE'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chegg_bot.db'

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
# --------------------------------

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """Serve uploaded files (recordings, etc)"""
    from flask import send_from_directory
    return send_from_directory('uploads', filename)

db.init_app(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# --- REGISTER TUTORING BLUEPRINT ---
from tutoring import tutoring_bp
app.register_blueprint(tutoring_bp)

# --- REGISTER SCHOOL BLUEPRINT ---
from school import school_bp
app.register_blueprint(school_bp)

# --- SOCKETIO FOR VIDEO TUTORING ---
from signaling import init_socketio
socketio = init_socketio(app)

# --- DUPLICATE PREVENTION LOCK ---
RECENT_POSTS = {}

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
    
from chegg_processor_web import chegg_processor
from mayank import answer_generator
import random

# --- HELPER: ROTATE SUPER ADMIN ACCOUNTS ---
def get_super_admin_account():
    """Finds a working ServiceAccount owned by a Super Admin."""
    # 1. Find all super admins
    super_admins = User.query.filter_by(role='super_admin').all()
    if not super_admins:
        return None
    
    super_admin_ids = [u.id for u in super_admins]
    
    # 2. Get all accounts owned by these IDs
    accounts = ServiceAccount.query.filter(ServiceAccount.owner_id.in_(super_admin_ids)).all()
    
    if not accounts:
        return None
        
    # 3. Randomly select one (Simple Rotation)
    return random.choice(accounts)

# --- NEW ROUTE: UNBLUR INTERFACE ---
@app.route('/unblur', methods=['GET', 'POST'])
@login_required
def unblur():
    if request.method == 'POST':
        url = request.form.get('chegg_url')
        
        # 1. Validation
        if not url or 'chegg.com' not in url:
            flash("Please enter a valid Chegg URL.")
            return redirect(url_for('unblur'))
            
        # 2. Check Credits
        if current_user.credits < 1:
            flash("Not enough credits! Please recharge.")
            return redirect(url_for('unblur'))

        # 3. Get Super Admin Account (Rotation)
        account = get_super_admin_account()
        if not account:
            flash("System Error: No Unblur Accounts Available. Contact Admin.")
            return redirect(url_for('unblur'))

        # 4. Process
        try:
            result, error = chegg_processor.get_question_data(url, account.cookie_data, account.proxy)
            
            if error:
                # Optional: If error is "Account Cookie Expired", maybe try one more time with a different account
                flash(f"Error: {error}")
                return redirect(url_for('unblur'))
            
            # 5. Generate HTML
            # Note: We added generate_html_string to mayank.py in Step 2
            # If you didn't, use the existing one and read the file content
            final_html = answer_generator.generate_html_string(result['question_data'])
            
            # 6. Deduct Credit
            current_user.credits -= 1
            
            # Log Job (Optional, good for history)
            job = Job(user_id=current_user.id, subject="Unblur Request", content=url, status="Completed", result_message="Unblurred Successfully")
            db.session.add(job)
            db.session.commit()
            
            return render_template('view_answer.html', html_content=final_html, original_url=url)
            
        except Exception as e:
            flash(f"Processing Failed: {str(e)}")
            return redirect(url_for('unblur'))

    return render_template('unblur.html')

# --- NEW: API Route for Image Upload & OCR ---
@app.route('/api/process_image', methods=['POST'])
@login_required
def api_process_image():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    account_id = request.form.get('account_id')
    
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    account = db.session.get(ServiceAccount, account_id)
    if not account:
        return jsonify({"error": "Invalid Account"}), 400
    
    # Permission Check (Matches your logic)
    if current_user.role != 'super_admin':
        allowed_owner_id = current_user.id if current_user.role == 'admin' else current_user.manager_id
        if account.owner_id != allowed_owner_id:
             return jsonify({"error": "Unauthorized Access"}), 403

    # Save temp file
    filename = secure_filename(f"{int(time.time())}_{file.filename}")
    local_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(local_path)

    try:
        # Upload
        chegg_url = chegg_api.upload_image_to_chegg(account.cookie_data, local_path, account.proxy)
        
        if not chegg_url:
            os.remove(local_path)
            return jsonify({"error": "Failed to upload to Chegg."}), 500

        # OCR
        ocr_text = chegg_api.ocr_analyze_image(account.cookie_data, chegg_url, account.proxy)
        os.remove(local_path)

        return jsonify({
            "success": True,
            "image_url": chegg_url,
            "transcribed_text": ocr_text
        })

    except Exception as e:
        if os.path.exists(local_path): os.remove(local_path)
        return jsonify({"error": str(e)}), 500

# --- API Route for Finding Subjects ---
@app.route('/api/get_suggested_subjects', methods=['POST'])
@login_required
def api_get_suggested_subjects():
    data = request.get_json()
    question_text = data.get('question_text', '')
    account_id = data.get('account_id')

    if not question_text or len(question_text) < 5:
        return jsonify({"error": "Question too short"})

    # --- ISOLATION CHECK ---
    account = db.session.get(ServiceAccount, account_id)
    if not account:
        return jsonify({"error": "Invalid Account"})

    # --- SUPER ADMIN BYPASS ---
    if current_user.role != 'super_admin':
        allowed_owner_id = current_user.id if current_user.role == 'admin' else current_user.manager_id

        if account.owner_id != allowed_owner_id:
             return jsonify({"error": "Unauthorized Access to Account"})

    suggestions = chegg_api.get_subjects_from_text(account.cookie_data, question_text, account.proxy)
    return jsonify({"subjects": suggestions})

# --- API: Extract Question from Chegg URL (for Repost) ---
@app.route('/api/chegg/extract-question', methods=['POST'])
@login_required
def api_extract_question():
    """Extract question content from a Chegg URL for reposting."""
    data = request.get_json()
    chegg_url = data.get('url', '').strip()
    
    if not chegg_url or 'chegg.com' not in chegg_url:
        return jsonify({"error": "Please enter a valid Chegg URL"})
    
    # Get super admin account for extraction (doesn't cost credits)
    account = get_super_admin_account()
    if not account:
        return jsonify({"error": "System Error: No accounts available"})
    
    try:
        result, error = chegg_processor.get_question_data(chegg_url, account.cookie_data, account.proxy)
        
        if error:
            return jsonify({"error": error})
        
        question_data = result.get('question_data', {})
        
        # Debug: Print structure to understand the data
        import json as json_module
        print(f"DEBUG question_data keys: {question_data.keys() if question_data else 'None'}")
        if 'content' in question_data:
            print(f"DEBUG content keys: {question_data['content'].keys() if isinstance(question_data.get('content'), dict) else 'Not a dict'}")
        
        # Extract question body - CORRECT PATH: content.body, content.textContent, content.transcribedData
        # This matches the structure used in mayank.py generate_html_string()
        content_html = ""
        plain_text = ""
        images = []
        
        # Primary method: Same as mayank.py
        content_obj = question_data.get('content', {})
        if isinstance(content_obj, dict):
            content_html = (
                content_obj.get('body') or 
                content_obj.get('textContent') or 
                content_obj.get('transcribedData') or
                ""
            )
        
        # Fallback: Try 'body' field directly (older format)
        if not content_html and 'body' in question_data:
            body = question_data['body']
            if isinstance(body, dict):
                content_html = body.get('content', '') or body.get('html', '') or body.get('text', '')
            elif isinstance(body, str):
                content_html = body
        
        # Fallback: Try other field names
        if not content_html:
            for key in ['htmlBody', 'questionBody', 'text', 'questionText', 'rawBody']:
                if key in question_data:
                    val = question_data[key]
                    if isinstance(val, str) and val:
                        content_html = val
                        break
                    elif isinstance(val, dict) and val.get('content'):
                        content_html = val.get('content')
                        break
        
        # Extract images from HTML and from media fields
        import re
        if content_html:
            img_matches = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', content_html)
            images.extend(img_matches)
        
        # Check for media/images field
        if 'media' in question_data and question_data['media']:
            for m in question_data['media']:
                if isinstance(m, dict) and m.get('url'):
                    images.append(m['url'])
                elif isinstance(m, str):
                    images.append(m)
        
        # Check for images field
        if 'images' in question_data and question_data['images']:
            for img in question_data['images']:
                if isinstance(img, dict) and img.get('url'):
                    images.append(img['url'])
                elif isinstance(img, str):
                    images.append(img)
        
        # Remove duplicates
        images = list(dict.fromkeys(images))
        
        # Get plain text from HTML
        from bs4 import BeautifulSoup
        if content_html:
            soup = BeautifulSoup(content_html, 'html.parser')
            plain_text = soup.get_text(separator='\n').strip()
        
        # If still no content, try to get just the question text
        if not plain_text and not content_html:
            # Fallback: check for title or question fields
            plain_text = question_data.get('title', '') or question_data.get('question', '') or question_data.get('text', '')
            content_html = f"<p>{plain_text}</p>" if plain_text else ""
        
        # Extract subject info
        subject_info = None
        if 'subject' in question_data and question_data['subject']:
            subj = question_data['subject']
            print(f"DEBUG subject data: {subj}")
            if isinstance(subj, dict):
                # Try different ID field names
                subj_id = subj.get('id') or subj.get('subjectId') or subj.get('subject_id')
                grp_id = subj.get('groupId') or subj.get('group_id')
                if not grp_id and isinstance(subj.get('group'), dict):
                    grp_id = subj.get('group', {}).get('id')
                
                subject_info = {
                    'title': subj.get('title') or subj.get('name') or subj.get('subjectName', ''),
                    'subjectId': subj_id,
                    'groupId': grp_id
                }
                print(f"DEBUG extracted subject_info: {subject_info}")
            elif isinstance(subj, str):
                subject_info = {'title': subj}
        
        # Also check 'subjects' array
        if not subject_info and 'subjects' in question_data:
            subjects = question_data['subjects']
            if subjects and len(subjects) > 0:
                subj = subjects[0]
                if isinstance(subj, dict):
                    subject_info = {
                        'title': subj.get('title') or subj.get('name', ''),
                        'subjectId': subj.get('id') or subj.get('subjectId'),
                        'groupId': subj.get('groupId')
                    }
        
        # Build final HTML with images
        final_html = content_html
        for img_url in images:
            if img_url not in final_html:
                final_html += f'<div><img src="{img_url}" /></div>'
        
        # OCR: Extract text from images if images are present
        ocr_text = ""
        if images and len(images) > 0:
            print(f"DEBUG: Running OCR on {len(images)} image(s)...")
            for img_url in images:
                try:
                    extracted_text = chegg_api.ocr_analyze_image(account.cookie_data, img_url, account.proxy)
                    if extracted_text:
                        ocr_text += extracted_text + "\n\n"
                        print(f"DEBUG: OCR extracted {len(extracted_text)} chars from image")
                except Exception as e:
                    print(f"DEBUG: OCR failed for image: {e}")
            ocr_text = ocr_text.strip()
        
        return jsonify({
            "success": True,
            "question_id": result.get('question_id'),
            "content_html": final_html,
            "plain_text": plain_text or "Question extracted (see images below)",
            "images": images,
            "ocr_text": ocr_text,  # OCR-extracted text from images
            "subject": subject_info,
            "original_url": chegg_url,
            "raw_keys": list(question_data.keys()) if question_data else []
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Extraction failed: {str(e)}"})

# --- API: Repost Question to Expert ---
@app.route('/api/chegg/repost', methods=['POST'])
@login_required
def api_repost_question():
    """Repost extracted question content to Ask an Expert."""
    data = request.get_json()
    content_html = data.get('content_html', '')
    subject_data = data.get('subject', '')  # "title|subject_id|group_id"
    account_id = data.get('account_id')
    
    if not content_html:
        return jsonify({"error": "No question content to post"})
    
    if not subject_data:
        return jsonify({"error": "Please select a subject"})
    
    # Check credits
    if current_user.credits < 1:
        return jsonify({"error": "Not enough credits! You need 1 credit."})
    
    # Get account
    account = db.session.get(ServiceAccount, account_id)
    if not account:
        return jsonify({"error": "Invalid account selected"})
    
    # Permission check
    if current_user.role != 'super_admin':
        allowed_owner_id = current_user.id if current_user.role == 'admin' else current_user.manager_id
        if account.owner_id != allowed_owner_id:
            return jsonify({"error": "Unauthorized access to account"})
    
    # Parse subject - handle both formats: "title|id|groupId" or just "title"
    try:
        parts = subject_data.split('|')
        if len(parts) >= 3 and parts[1] and parts[2]:
            # Full format with IDs
            title = parts[0]
            subj_id = parts[1]
            grp_id = parts[2]
        else:
            # Only title provided - need to lookup subject ID
            title = parts[0] if parts else subject_data
            print(f"DEBUG: Looking up subject ID for title: {title}")
            
            # Use the question content to find matching subjects
            suggestions = chegg_api.get_subjects_from_text(
                account.cookie_data, 
                title,  # Use subject title as search query
                account.proxy
            )
            
            if suggestions and len(suggestions) > 0:
                # Find best match or use first result
                matched = None
                for s in suggestions:
                    if s.get('title', '').lower() == title.lower():
                        matched = s
                        break
                if not matched:
                    matched = suggestions[0]
                
                subj_id = matched.get('subjectId')
                grp_id = matched.get('groupId')
                title = matched.get('title', title)
                print(f"DEBUG: Found subject - ID: {subj_id}, GroupID: {grp_id}")
            else:
                return jsonify({"error": f"Could not find subject ID for '{title}'. Please use 'Find Related Subjects' button."})
    except Exception as e:
        print(f"Subject parsing error: {e}")
        return jsonify({"error": f"Invalid subject format: {str(e)}"})
    
    # Get post count (how many times to post)
    post_count = data.get('post_count', 1)
    try:
        post_count = int(post_count)
        if post_count < 1:
            post_count = 1
        if post_count > 10:  # Limit to 10 posts max
            post_count = 10
    except:
        post_count = 1
    
    # Check credits
    if current_user.credits < post_count:
        return jsonify({"error": f"Not enough credits! You need {post_count} credit(s), have {current_user.credits}."})
    
    # Deduct credits upfront
    current_user.credits -= post_count
    
    try:
        success_count = 0
        fail_count = 0
        last_msg = ""
        
        # Post multiple times based on post_count
        for i in range(post_count):
            success, msg = chegg_api.post_question_v3(
                account.cookie_data, 
                content_html, 
                int(subj_id), 
                account.proxy
            )
            
            if success:
                success_count += 1
            else:
                fail_count += 1
                last_msg = msg
            
            # Log each job
            job = Job(
                user_id=current_user.id, 
                subject=f"[Repost] {title}", 
                content=content_html[:200], 
                status="Completed" if success else "Failed",
                result_message=msg,
                service_account_name=account.name
            )
            db.session.add(job)
        
        # Refund failed posts
        current_user.credits += fail_count
        db.session.commit()
        
        if success_count == post_count:
            return jsonify({
                "success": True, 
                "message": f"All {post_count} question(s) reposted successfully!", 
                "credits_remaining": current_user.credits
            })
        elif success_count > 0:
            return jsonify({
                "success": True, 
                "message": f"{success_count}/{post_count} questions reposted. {fail_count} failed: {last_msg}", 
                "credits_remaining": current_user.credits
            })
        else:
            return jsonify({"error": f"All reposts failed: {last_msg}"})
            
    except Exception as e:
        current_user.credits += post_count  # Full refund on error
        db.session.commit()
        return jsonify({"error": f"Repost failed: {str(e)}"})

# --- SUPER ADMIN DASHBOARD ---
@app.route('/lone-admin/', methods=['GET', 'POST'])
@login_required
def super_admin_dashboard():
    # STRICT ACCESS CHECK
    if current_user.role != 'super_admin':
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        action = request.form.get('action')

        # --- 1. ADD UNBLUR ACCOUNT (SUPER ADMIN POOL) ---
        if action == 'add_account':
            name = request.form.get('acc_name')
            cookies = request.form.get('cookie_json')
            proxy_val = request.form.get('proxy')
            if proxy_val and proxy_val.strip() == "": proxy_val = None

            # Check if name exists for this admin
            exists = ServiceAccount.query.filter_by(name=name, owner_id=current_user.id).first()
            if exists:
                flash("An account with this name already exists in your pool.")
            else:
                new_acc = ServiceAccount(
                    name=name,
                    cookie_data=cookies,
                    proxy=proxy_val,
                    owner_id=current_user.id  # OWNED BY SUPER ADMIN = UNBLUR POOL
                )
                db.session.add(new_acc)
                db.session.commit()
                flash(f"Success! '{name}' added to Unblur/Super Admin pool.")

        # --- 2. PROMOTE EXISTING USER TO ADMIN ---
        elif action == 'create_admin':
            username = request.form.get('username')
            user_to_promote = User.query.filter_by(username=username).first()
            
            if user_to_promote:
                if user_to_promote.role == 'admin':
                    flash(f"User '{username}' is already an Admin!")
                elif user_to_promote.role == 'super_admin':
                    flash(f"User '{username}' is a Super Admin!")
                else:
                    user_to_promote.role = 'admin'
                    if user_to_promote.credits < 100:
                        user_to_promote.credits = 100
                    user_to_promote.manager_id = current_user.id
                    db.session.commit()
                    flash(f"Success! '{username}' has been promoted to Admin.")
            else:
                flash(f"User '{username}' not found. Please ask them to Register first.")

        # --- 3. DELETE USER/ADMIN ---
        elif action == 'delete_user':
            user_id = request.form.get('user_id')
            if int(user_id) == current_user.id:
                flash("You cannot delete yourself.")
            else:
                u = db.session.get(User, user_id)
                if u:
                    db.session.delete(u)
                    db.session.commit()
                    flash(f"User '{u.username}' deleted permanently.")

        # --- 4. GLOBAL DELETE ACCOUNT ---
        elif action == 'delete_account':
            acc_id = request.form.get('account_id')
            acc = db.session.get(ServiceAccount, acc_id)
            if acc:
                db.session.delete(acc)
                db.session.commit()
                flash("Service Account deleted.")

        return redirect(url_for('super_admin_dashboard'))

    # Data for the dashboard
    all_admins = User.query.filter_by(role='admin').all()
    all_users = User.query.filter(User.role != 'super_admin', User.role != 'admin').all()
    
    # Filter accounts: Separate "Unblur/My Accounts" from "User Accounts"
    my_accounts = ServiceAccount.query.filter_by(owner_id=current_user.id).all()
    other_accounts = ServiceAccount.query.filter(ServiceAccount.owner_id != current_user.id).all()
    
    global_jobs = db.session.query(Job, User).join(User, Job.user_id == User.id).order_by(Job.timestamp.desc()).limit(100).all()

    return render_template('super_admin.html', 
                           admins=all_admins, 
                           users=all_users, 
                           my_accounts=my_accounts,      # Pass my accounts separately
                           other_accounts=other_accounts, # Pass others separately
                           jobs=global_jobs)

# --- STANDARD ROUTES ---
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('landing.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('Username taken')
            return redirect(url_for('register'))

        # Create user with additional profile fields
        new_user = User(
            username=username, 
            password=generate_password_hash(password),
            full_name=request.form.get('full_name'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            grade_id=request.form.get('grade_id') or None
        )
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        flash('Account created. Welcome to Students Hub!')
        return redirect(url_for('dashboard'))
    
    # Pass grades and unique subjects to template for dropdown
    grades = Grade.query.filter_by(is_active=True).order_by(Grade.display_order).all()
    # Get unique subject names
    subjects = db.session.query(Subject.name).distinct().order_by(Subject.name).all()
    subject_names = [s[0] for s in subjects]
    return render_template('register.html', grades=grades, subjects=subject_names)


# --- ONE-TIME DATABASE SETUP ---
@app.route('/setup-database')
def setup_database():
    """One-time setup: creates super_admin and seeds grades. Only works if no admin exists."""
    # Check if admin already exists
    existing_admin = User.query.filter_by(role='super_admin').first()
    if existing_admin:
        return jsonify({"message": "Setup already complete. Admin exists.", "admin_username": existing_admin.username})
    
    # Create super_admin user
    admin = User(
        username='admin',
        password=generate_password_hash('admin123'),
        role='super_admin'
    )
    db.session.add(admin)
    
    # Seed grades from Nursery to 12th
    default_grades = [
        "Nursery", "LKG", "UKG",
        "Class 1", "Class 2", "Class 3", "Class 4", "Class 5",
        "Class 6", "Class 7", "Class 8", "Class 9", "Class 10",
        "Class 11", "Class 12"
    ]
    
    for i, name in enumerate(default_grades):
        grade = Grade(name=name, display_order=i, is_active=True)
        db.session.add(grade)
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "Database initialized!",
        "admin": {"username": "admin", "password": "admin123"},
        "grades_created": len(default_grades)
    })


# --- HELPER: GET TRENDING TOPICS ---
from datetime import timedelta

def get_trending_topics():
    """Get most searched topics for dashboard analytics"""
    from datetime import datetime
    
    # Get category counts
    category_counts = db.session.query(
        ChatHistory.category,
        func.count(ChatHistory.id).label('count')
    ).group_by(ChatHistory.category).order_by(func.count(ChatHistory.id).desc()).limit(5).all()
    
    # Get recent popular questions (last 7 days)
    week_ago = datetime.utcnow() - timedelta(days=7)
    
    popular_questions = db.session.query(
        ChatHistory.question,
        ChatHistory.category,
        func.count(ChatHistory.id).label('count')
    ).filter(
        ChatHistory.timestamp >= week_ago
    ).group_by(ChatHistory.question).order_by(
        func.count(ChatHistory.id).desc()
    ).limit(5).all()
    
    return {
        "categories": [{"name": c[0], "count": c[1]} for c in category_counts],
        "popular_questions": [{"question": q[0][:80], "category": q[1], "count": q[2]} for q in popular_questions]
    }

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    global RECENT_POSTS

    if current_user.role == 'super_admin':
        target_owner_id = None 
        accounts = ServiceAccount.query.all()
    elif current_user.role == 'admin':
        target_owner_id = current_user.id
        accounts = ServiceAccount.query.filter_by(owner_id=target_owner_id).all()
    else:
        target_owner_id = current_user.manager_id
        if target_owner_id:
            accounts = ServiceAccount.query.filter_by(owner_id=target_owner_id).all()
        else:
            accounts = []

    if request.method == 'POST':
        # --- NEW FIELDS FOR IMAGE ---
        post_mode = request.form.get('post_mode', 'text')
        final_image_url = request.form.get('final_image_url')
        # ----------------------------
        
        raw_subject = request.form.get('subject_select')
        content = request.form.get('content')
        account_id = request.form.get('account_id')
        post_count = int(request.form.get('post_count', 1))

        request_signature = f"{current_user.id}-{account_id}-{content[:50]}"
        post_hash = hashlib.sha256(request_signature.encode()).hexdigest()
        current_time = time.time()
        RECENT_POSTS = {k: v for k, v in RECENT_POSTS.items() if current_time - v < 60}
        if post_hash in RECENT_POSTS:
            flash("Duplicate post detected! Please wait.")
            return redirect(url_for('dashboard'))
        RECENT_POSTS[post_hash] = current_time

        if current_user.credits < post_count:
            flash(f"Not enough credits! Needed: {post_count}, Have: {current_user.credits}")
            return redirect(url_for('dashboard'))

        # --- VALIDATION MODIFIED FOR IMAGE MODE ---
        if not raw_subject or not account_id:
            flash("Please fill all fields.")
            return redirect(url_for('dashboard'))
        
        if post_mode == 'text' and not content:
            flash("Please enter question content.")
            return redirect(url_for('dashboard'))
        
        if post_mode == 'image' and not final_image_url:
            flash("Please upload an image.")
            return redirect(url_for('dashboard'))
        # ------------------------------------------

        account = db.session.get(ServiceAccount, account_id)
        if not account:
            flash("Invalid Service Account.")
            return redirect(url_for('dashboard'))

        if current_user.role != 'super_admin':
            if account.owner_id != target_owner_id:
                flash("Unauthorized Service Account.")
                return redirect(url_for('dashboard'))

        try:
            title, subj_id, grp_id = raw_subject.split('|')
        except ValueError:
            flash("Invalid Subject.")
            return redirect(url_for('dashboard'))

        success_count = 0
        for i in range(post_count):
            current_user.credits -= 1
            
            # --- LOGIC TO HANDLE BOTH MODES ---
            if post_mode == 'image':
                job_desc = f"[Image] {content[:100]}"
                html_body = ""
                if content and content.strip():
                    html_body += f"<div><p>{content}</p></div>"
                html_body += f"<div><img src='{final_image_url}' /></div>"
                
                success, msg = chegg_api.post_question_v3(
                    account.cookie_data, html_body, int(subj_id), account.proxy
                )
            else:
                job_desc = content
                success, msg = chegg_api.post_question_to_chegg(
                    account.cookie_data, content, title, int(subj_id), int(grp_id), account.proxy
                )
            # ----------------------------------

            job = Job(user_id=current_user.id, subject=title, content=job_desc, status="Processing", service_account_name=account.name)
            db.session.add(job)
            db.session.commit()

            if success:
                job.status = "Completed"
                success_count += 1
            else:
                job.status = "Failed"
                current_user.credits += 1 
                msg = f"{msg} (Credit Refunded)"

            job.result_message = msg
            db.session.commit()
            if i < post_count - 1: time.sleep(2)

        flash(f"Finished: Posted {success_count}/{post_count} times.")
        return redirect(url_for('dashboard'))

    my_jobs = Job.query.filter_by(user_id=current_user.id).order_by(Job.timestamp.desc()).all()
    
    # Get tutoring sessions for the student
    my_sessions = TutoringSession.query.filter_by(student_id=current_user.id).order_by(TutoringSession.created_at.desc()).all()
    
    # Get trending topics for analytics
    trending = get_trending_topics()

    return render_template('dashboard.html',
                           user=current_user,
                           accounts=accounts,
                           jobs=my_jobs,
                           sessions=my_sessions,
                           trending=trending)

@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        action = request.form.get('action')

        # --- 1. ADD CREDITS (Self or Managed) ---
        if action == 'add_credits':
            username = request.form.get('username')
            amount = int(request.form.get('amount'))

            if username == current_user.username:
                # ADMIN FUNDING THEMSELVES
                current_user.credits += amount
                db.session.commit()
                flash(f"Added {amount} credits to your own account.")
            else:
                # FUNDING MANAGED USER
                u = User.query.filter_by(username=username, manager_id=current_user.id).first()
                if u:
                    u.credits += amount
                    db.session.commit()
                    flash(f"Added {amount} credits to {username}")
                else:
                    flash(f"User {username} not found in your managed list.")

        elif action == 'create_user':
            new_username = request.form.get('new_username')
            new_password = request.form.get('new_password')
            initial_credits = int(request.form.get('initial_credits', 0))

            if User.query.filter_by(username=new_username).first():
                flash(f"Username {new_username} already exists.")
            else:
                new_u = User(
                    username=new_username,
                    password=generate_password_hash(new_password),
                    credits=initial_credits,
                    manager_id=current_user.id
                )
                db.session.add(new_u)
                db.session.commit()
                flash(f"User {new_username} created and assigned to you.")

        elif action == 'add_account':
            name = request.form.get('acc_name')
            cookies = request.form.get('cookie_json')
            proxy_val = request.form.get('proxy')
            if proxy_val and proxy_val.strip() == "": proxy_val = None

            exists = ServiceAccount.query.filter_by(name=name, owner_id=current_user.id).first()
            if exists:
                flash("You already have an account with this name.")
            else:
                new_acc = ServiceAccount(
                    name=name,
                    cookie_data=cookies,
                    proxy=proxy_val,
                    owner_id=current_user.id 
                )
                db.session.add(new_acc)
                db.session.commit()
                flash(f"Account {name} added to your pool.")

        elif action == 'delete_account':
            acc_id = request.form.get('account_id')
            acc = db.session.get(ServiceAccount, acc_id)
            if acc and acc.owner_id == current_user.id:
                db.session.delete(acc)
                db.session.commit()
                flash(f"Account '{acc.name}' deleted.")
            else:
                flash("Account not found or access denied.")

        elif action == 'delete_user':
            user_id = request.form.get('user_id')
            user_to_delete = db.session.get(User, user_id)
            if user_to_delete and user_to_delete.manager_id == current_user.id:
                db.session.delete(user_to_delete)
                db.session.commit()
                flash(f"User '{user_to_delete.username}' deleted.")
            else:
                flash("User not found or you don't have permission.")

        # --- TUTOR APPROVAL ACTIONS ---
        elif action == 'approve_tutor':
            tutor_id = request.form.get('tutor_id')
            tutor = db.session.get(Tutor, tutor_id)
            if tutor:
                tutor.is_approved = True
                db.session.commit()
                flash(f"Tutor '{tutor.display_name}' has been approved!")
            else:
                flash("Tutor not found.")

        elif action == 'reject_tutor':
            tutor_id = request.form.get('tutor_id')
            tutor = db.session.get(Tutor, tutor_id)
            if tutor:
                db.session.delete(tutor)
                db.session.commit()
                flash(f"Tutor application rejected and removed.")
            else:
                flash("Tutor not found.")

        elif action == 'deactivate_tutor':
            tutor_id = request.form.get('tutor_id')
            tutor = db.session.get(Tutor, tutor_id)
            if tutor:
                tutor.is_active = not tutor.is_active
                db.session.commit()
                status = "activated" if tutor.is_active else "deactivated"
                flash(f"Tutor '{tutor.display_name}' has been {status}.")
            else:
                flash("Tutor not found.")

    my_users = User.query.filter_by(manager_id=current_user.id).all()
    my_accounts = ServiceAccount.query.filter_by(owner_id=current_user.id).all()
    
    # Get tutors for admin panel
    pending_tutors = Tutor.query.filter_by(is_approved=False, is_active=True).all()
    approved_tutors = Tutor.query.filter_by(is_approved=True).all()
    
    # Get all sessions for recording review
    sessions = TutoringSession.query.order_by(TutoringSession.created_at.desc()).all()
    
    return render_template('admin.html', 
                         users=my_users, 
                         accounts=my_accounts,
                         pending_tutors=pending_tutors,
                         approved_tutors=approved_tutors,
                         sessions=sessions)

@app.route('/tools/chegg', methods=['GET'])
@login_required
def chegg_tools():
    # 1. Fetch Accounts for Posting
    # (Adjust query if you only want specific accounts shown)
    accounts = ServiceAccount.query.all() 
    
    # 2. Fetch User History
    jobs = Job.query.filter_by(user_id=current_user.id).order_by(desc(Job.timestamp)).limit(50).all()
    
    return render_template('chegg_tools.html', accounts=accounts, jobs=jobs)

# --- AI TUTOR ROUTES ---
from ai_tutor import get_ai_response

@app.route('/ai-tutor')
@login_required
def ai_tutor():
    """Render AI Tutor chat page with dual AI responses"""
    # Get user's recent chat history (combined from both providers)
    history = ChatHistory.query.filter_by(
        user_id=current_user.id
    ).order_by(ChatHistory.timestamp.desc()).limit(10).all()
    
    return render_template('ai_tutor.html', 
                         user=current_user, 
                         history=history[::-1])

@app.route('/api/ai-tutor/chat', methods=['POST'])
@login_required
def api_ai_tutor_chat():
    """Handle AI chat requests - calls BOTH ChatGPT and Gemini, deducts 1 credit"""
    data = request.get_json()
    question = data.get('question', '').strip()
    
    # Validation
    if not question:
        return jsonify({"error": "Please enter a question"})
    
    # Check credits
    if current_user.credits < 1:
        return jsonify({"error": "Not enough credits! You need 1 credit per question."})
    
    # Get responses from BOTH AIs
    chatgpt_response, chatgpt_category, chatgpt_error = get_ai_response('chatgpt', question)
    gemini_response, gemini_category, gemini_error = get_ai_response('gemini', question)
    
    # Use the category from whichever succeeded
    category = chatgpt_category or gemini_category or 'general'
    
    # Deduct only 1 credit for both responses
    current_user.credits -= 1
    
    # Save ChatGPT response to history if successful
    if chatgpt_response:
        chat_gpt = ChatHistory(
            user_id=current_user.id,
            ai_provider='chatgpt',
            question=question,
            answer=chatgpt_response,
            category=category
        )
        db.session.add(chat_gpt)
    
    # Save Gemini response to history if successful
    if gemini_response:
        chat_gemini = ChatHistory(
            user_id=current_user.id,
            ai_provider='gemini',
            question=question,
            answer=gemini_response,
            category=category
        )
        db.session.add(chat_gemini)
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "chatgpt": {
            "answer": chatgpt_response,
            "error": chatgpt_error
        },
        "gemini": {
            "answer": gemini_response,
            "error": gemini_error
        },
        "category": category,
        "credits_remaining": current_user.credits
    })

@app.route('/api/ai-tutor/history/<provider>')
@login_required
def api_ai_tutor_history(provider):
    """Get user's chat history for a provider"""
    history = ChatHistory.query.filter_by(
        user_id=current_user.id,
        ai_provider=provider
    ).order_by(ChatHistory.timestamp.desc()).limit(50).all()
    
    return jsonify({
        "history": [{
            "id": h.id,
            "question": h.question,
            "answer": h.answer,
            "category": h.category,
            "timestamp": h.timestamp.strftime('%Y-%m-%d %H:%M')
        } for h in history]
    })


# --- LIBRARY ROUTES ---
from library import save_uploaded_file, extract_text_with_gemini, format_document_content, search_documents, MAX_FILE_SIZE

@app.route('/library')
@login_required
def library():
    """Browse all documents in the library"""
    doc_type = request.args.get('type', 'all')
    
    query = Document.query.filter_by(is_approved=True)
    if doc_type != 'all':
        query = query.filter_by(doc_type=doc_type)
    
    documents = query.order_by(Document.timestamp.desc()).limit(50).all()
    
    # Get user's unlocked documents
    unlocked_ids = [u.document_id for u in DocumentUnlock.query.filter_by(user_id=current_user.id).all()]
    
    return render_template('library.html', 
                         documents=documents, 
                         unlocked_ids=unlocked_ids,
                         current_type=doc_type,
                         user=current_user)

@app.route('/library/upload', methods=['GET', 'POST'])
@login_required
def library_upload():
    """Upload a new document"""
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        doc_type = request.form.get('doc_type', 'notes')
        file = request.files.get('file')
        
        # Validation
        if not title:
            flash('Please enter a title for your document')
            return redirect(url_for('library_upload'))
        
        if not file or file.filename == '':
            flash('Please select a file to upload')
            return redirect(url_for('library_upload'))
        
        # Check file size
        file.seek(0, 2)  # Seek to end
        size = file.tell()
        file.seek(0)  # Seek back to start
        
        if size > MAX_FILE_SIZE:
            flash('File too large! Maximum size is 20MB')
            return redirect(url_for('library_upload'))
        
        # Save file
        file_path, file_type, error = save_uploaded_file(file, current_user.id)
        if error:
            flash(error)
            return redirect(url_for('library_upload'))
        
        # Create document record
        doc = Document(
            user_id=current_user.id,
            title=title,
            description=description,
            doc_type=doc_type,
            file_path=file_path,
            file_type=file_type
        )
        db.session.add(doc)
        
        # Award credit to uploader
        current_user.credits += 1
        db.session.commit()
        
        # Extract text in background (simplified - doing it synchronously here)
        extracted_text, ocr_error = extract_text_with_gemini(file_path, file_type)
        if extracted_text:
            doc.extracted_text = extracted_text
            
            # Format the document
            formatted_content, format_error = format_document_content(extracted_text, doc_type, title)
            if formatted_content:
                doc.formatted_content = formatted_content
            
            db.session.commit()
        
        flash(f'Document uploaded successfully! You earned 1 credit. Total: {current_user.credits}')
        return redirect(url_for('library'))
    
    return render_template('library_upload.html', user=current_user)

@app.route('/library/document/<int:doc_id>')
@login_required
def library_document(doc_id):
    """View a document (blurred preview or full if unlocked)"""
    doc = Document.query.get_or_404(doc_id)
    
    # Check if user has unlocked this document
    is_owner = doc.user_id == current_user.id
    unlock = DocumentUnlock.query.filter_by(
        user_id=current_user.id, 
        document_id=doc_id
    ).first()
    
    is_unlocked = is_owner or unlock is not None
    
    return render_template('library_document.html', 
                         document=doc, 
                         is_unlocked=is_unlocked,
                         user=current_user)

@app.route('/api/library/unlock/<int:doc_id>', methods=['POST'])
@login_required
def api_library_unlock(doc_id):
    """Unlock a document - costs 1 credit"""
    doc = Document.query.get_or_404(doc_id)
    
    # Check if already unlocked
    existing = DocumentUnlock.query.filter_by(
        user_id=current_user.id, 
        document_id=doc_id
    ).first()
    
    if existing or doc.user_id == current_user.id:
        return jsonify({"success": True, "message": "Already unlocked"})
    
    # Check credits
    if current_user.credits < 1:
        return jsonify({"error": "Not enough credits! You need 1 credit to unlock."})
    
    # Deduct credit and create unlock record
    current_user.credits -= 1
    unlock = DocumentUnlock(user_id=current_user.id, document_id=doc_id)
    doc.downloads += 1
    
    db.session.add(unlock)
    db.session.commit()
    
    return jsonify({
        "success": True, 
        "credits_remaining": current_user.credits,
        "message": "Document unlocked!"
    })

@app.route('/api/library/search')
@login_required
def api_library_search():
    """Search documents"""
    query = request.args.get('q', '').strip()
    
    if not query or len(query) < 2:
        return jsonify({"results": []})
    
    results = search_documents(query)
    
    # Get user's unlocked documents
    unlocked_ids = [u.document_id for u in DocumentUnlock.query.filter_by(user_id=current_user.id).all()]
    
    return jsonify({
        "results": [{
            "id": doc.id,
            "title": doc.title,
            "description": doc.description[:100] if doc.description else "",
            "doc_type": doc.doc_type,
            "uploader": doc.user.username,
            "downloads": doc.downloads,
            "is_unlocked": doc.id in unlocked_ids or doc.user_id == current_user.id
        } for doc in results]
    })


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- API Route for Checking Balance ---
@app.route('/api/check_balance', methods=['POST'])
@login_required
def api_check_balance():
    data = request.get_json()
    account_id = data.get('account_id')
    
    if not account_id:
        return jsonify({"error": "No account selected"})

    # Fetch account
    account = db.session.get(ServiceAccount, account_id)
    if not account:
        return jsonify({"error": "Invalid Account"})

    # Permission check (Standard + Super Admin logic)
    if current_user.role != 'super_admin':
        allowed_owner_id = current_user.id if current_user.role == 'admin' else current_user.manager_id
        if account.owner_id != allowed_owner_id:
            return jsonify({"error": "Unauthorized"})

    # Actually call the Chegg API to get real balance
    try:
        balance_result = chegg_api.get_account_balance(account.cookie_data, account.proxy)
        
        if "error" in balance_result:
            return jsonify({"balance": f"Error: {balance_result['error']}"})
        
        # Return the actual balance data (used/limit or remaining)
        return jsonify({"balance": balance_result})
        
    except Exception as e:
        print(f"[Balance Check Error] {e}")
        return jsonify({"balance": "API Error"})

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # Use socketio.run for WebSocket support in video tutoring
    socketio.run(app, debug=True, port=5000)
