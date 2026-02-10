from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, send_from_directory, Response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
# --- ADDED THESE IMPORTS FOR IMAGE HANDLING ---
from werkzeug.utils import secure_filename
import os
# ----------------------------------------------
from models import db, User, ServiceAccount, Job, ChatHistory, Document, DocumentUnlock, Tutor, TutoringSession, Grade, Subject, Feedback, Notification, Subscription
from sqlalchemy import func, or_
import chegg_api
import time
import hashlib
from sqlalchemy import desc
from datetime import datetime
from dotenv import load_dotenv
from flask_apscheduler import APScheduler
import concurrent.futures
from chegg_api import check_if_solved, notify_super_admin

load_dotenv() # Load environment variables from .env

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_default_secret_key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chegg_bot.db'

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
# --------------------------------
scheduler = APScheduler()

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """Serve uploaded files (recordings, etc)"""
    from flask import send_from_directory
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/ads.txt')
def ads_txt():
    return send_from_directory(app.root_path, 'ads.txt')

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

# --- REGISTER PAYMENTS BLUEPRINT ---
from payments import payments_bp
app.register_blueprint(payments_bp)

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
            
        # 2. Check Access (Just check if they CAN afford it, don't deduct yet)
        if not current_user.can_access('unblur') and current_user.credits < 1:
            flash("Upgrade your plan to unlock Unlimited Unblurs, or upload documents to earn credits!", "warning")
            return redirect(url_for('payments.pricing'))

        # 3. Get Super Admin Account (Rotation)
        account = get_super_admin_account()

        if not account:
            flash("System Error: No Unblur Accounts Available. Contact Admin.")
            return redirect(url_for('unblur'))

        # 4. Process
        credit_deducted = False
        if not current_user.can_access('unblur') and current_user.credits >= 1:
             current_user.credits -= 1
             credit_deducted = True
             db.session.commit()

        try:
            result, error = chegg_processor.get_question_data(url, account.cookie_data, account.proxy)
            
            if error:
                # Refund if credit was used
                if credit_deducted:
                    current_user.credits += 1
                    db.session.commit()
                    flash(f"Error: {error}. Credit refunded.")
                else:
                    flash(f"Error: {error}")
                return redirect(url_for('unblur'))
            
            # ... (HTML generation) ...
            final_html = answer_generator.generate_html_string(result['question_data'])

            # Log Job
            job = Job(user_id=current_user.id, subject="Unblur Request", content=url, status="Completed", result_message="Unblurred Successfully")
            db.session.add(job)
            db.session.commit()
            
            return render_template('view_answer.html', html_content=final_html, original_url=url)
            
        except Exception as e:
            if credit_deducted:
                current_user.credits += 1
                db.session.commit()
                flash(f"Processing Failed: {str(e)}. Credit refunded.")
            else:
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
    
    # Check Access (Subscription OR Credits)
    has_plan = current_user.can_access('expert_ask')
    credits_needed = 20 * int(data.get('post_count', 1)) # 20 credits per post
    
    if not has_plan:
        if current_user.credits < credits_needed:
             return jsonify({"error": f"Limit reached. You need a Plan or {credits_needed} Credits to ask an expert."})
        
        # Deduct credits if no plan
        current_user.credits -= credits_needed
        db.session.commit()
    
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
    # Check Access again with count
    # Note: simple check doesn't handle 'count', but for now assume 1 usage per post call or loop
    if not current_user.can_access('expert_ask'):
         return jsonify({"error": "Limit reached."})
    
    # Increment counters later in loop or batch
    # For simplicity in this migration, we will increment in the loop and check continuously or just proceed
    # Since can_access checks current usage, we should be fine.
    
    # Logic change: detailed quota check
    if current_user.role not in ['admin', 'super_admin'] and current_user.active_subscription_id:
        sub = Subscription.query.get(current_user.active_subscription_id)
        # Check if enough quota remains for post_count
        limit = 0
        if sub.plan_type == 'basic_299': limit = 20
        elif sub.plan_type == 'pro_499': limit = 40
        elif sub.plan_type == 'school_1200': limit = 20
        
        if (sub.expert_used + post_count) > limit:
             return jsonify({"error": f"Not enough Expert quota. You have {limit - sub.expert_used} remaining."})
    
    # Deduct credits upfront -> REPLACED by usage tracking
    # current_user.credits -= post_count
    
    # Deduct credits if no plan
        # We already deducted above if needed (logic block has commit)
        pass 
    
    credits_deducted = 0
    if not has_plan:
        credits_deducted = credits_needed

    try:
        success_count = 0
        fail_count = 0
        last_msg = ""
        
        # Post multiple times based on post_count
        for i in range(post_count):
            try:
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
            except Exception as e:
                fail_count += 1
                last_msg = str(e)
            
            # Log each job
            job = Job(
                user_id=current_user.id, 
                subject=f"[Repost] {title}", 
                content=content_html[:200], 
                status="Completed" if success else "Failed",
                result_message=msg if success else last_msg,
                service_account_name=account.name
            )
            db.session.add(job)
        
        # Refund failed posts (If user paid with credits)
        # Each post costs 20 credits. Refund 20 * fail_count
        if credits_deducted > 0 and fail_count > 0:
            refund_amount = 20 * fail_count
            current_user.credits += refund_amount
            db.session.commit()
            last_msg += f" ({refund_amount} credits refunded)"
        else:
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
        # Full Refund on critical error
        if credits_deducted > 0:
            current_user.credits += credits_deducted
            db.session.commit()
        return jsonify({"error": f"Repost failed: {str(e)}. Credits refunded."})

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

    # Fetch pending feedbacks for approval
    pending_feedbacks = Feedback.query.filter_by(is_approved=False).order_by(Feedback.created_at.desc()).all()
    
    # Fetch approved feedbacks for management (limit last 50 to avoid clutter)
    approved_feedbacks = Feedback.query.filter_by(is_approved=True).order_by(Feedback.created_at.desc()).limit(50).all()
    
    # Fetch Pending Verification Users (Disabled Students)
    pending_users = User.query.filter_by(student_type='disabled', is_verified=False).all()

    return render_template('super_admin.html', 
                           admins=all_admins, 
                           users=all_users, 
                           my_accounts=my_accounts,      # Pass my accounts separately
                           other_accounts=other_accounts, # Pass others separately
                           jobs=global_jobs,
                           pending_feedbacks=pending_feedbacks,
                           approved_feedbacks=approved_feedbacks,
                           pending_users=pending_users)

# --- NEW: User Verification Route ---
@app.route('/verify-user/<int:user_id>/<action>', methods=['POST'])
@login_required
def verify_user(user_id, action):
    if current_user.role != 'super_admin':
        flash("Unauthorized access.", "danger")
        return redirect(url_for('dashboard'))
    
    user = User.query.get(user_id)
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for('super_admin_dashboard'))
    
    if action == 'approve':
        user.is_verified = True
        db.session.commit()
        flash(f"User {user.username} has been verified and approved.", "success")
    
    elif action == 'reject':
        # Optional: Delete uploaded certificate if it exists to save space
        if user.disability_certificate_path:
            try:
                full_path = os.path.join(app.config['UPLOAD_FOLDER'], user.disability_certificate_path)
                if os.path.exists(full_path):
                    os.remove(full_path)
            except Exception as e:
                print(f"Error removing certificate: {e}")
        
        db.session.delete(user)
        db.session.commit()
        flash(f"User {user.username} has been rejected and removed.", "warning")
    
    return redirect(url_for('super_admin_dashboard'))

# --- STANDARD ROUTES ---
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    # Fetch stats for landing page
    student_count = User.query.filter_by(role='user').count()
    resource_count = Document.query.count()
    questions_solved = Job.query.filter_by(status='Completed').count() * 5 + 1200 # Fake boost for demo
    
    # Fetch approved feedbacks
    feedbacks = Feedback.query.filter_by(is_approved=True).order_by(Feedback.created_at.desc()).limit(10).all()
    
    return render_template('landing.html', 
                         student_count=student_count,
                         resource_count=resource_count,
                         questions_solved=questions_solved,
                         feedbacks=feedbacks)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            # Check for verification (Disabled Students)
            if user.student_type == 'disabled' and not user.is_verified:
                flash('Your account is pending verification by the admin. Please wait for approval.', 'warning')
                return redirect(url_for('login'))
                
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    # Helper to clean text input
    def clean(val):
        return val.strip() if val else None

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Check if username exists
        if User.query.filter_by(username=username).first():
            flash('Username is already taken. Please choose another one.', 'danger')
            return redirect(url_for('register'))

        # Get Student Type
        student_type = request.form.get('student_type', 'grade') # 'grade', 'higher_ed', 'disabled'
        
        # Base User Data
        email = clean(request.form.get('email'))
        phone = clean(request.form.get('phone'))
        full_name = clean(request.form.get('full_name'))
        grade_id = request.form.get('grade_id') or None
        
        # New Fields
        parent_name = clean(request.form.get('parent_name'))
        parent_phone = clean(request.form.get('parent_phone'))
        address = clean(request.form.get('address'))
        school_name = clean(request.form.get('school_name'))
        
        # Capture class_grade for Higher Ed
        if student_type == 'higher_ed':
             class_grade = clean(request.form.get('class_grade'))
        else:
             class_grade = None

        # Capture grade_id for Disabled if provided via separate select
        if student_type == 'disabled':
             disabled_grade = request.form.get('disabled_grade_id')
             if disabled_grade:
                  grade_id = disabled_grade
        
        # Default verification: True unless disabled
        is_verified = True
        disability_path = None
        
        if student_type == 'disabled':
            is_verified = False # Needs Admin Approval
            
            # Handle Certificate Upload
            if 'certificate' in request.files:
                file = request.files['certificate']
                if file and file.filename != '':
                    filename = secure_filename(f"cert_{int(time.time())}_{file.filename}")
                    cert_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'certificates')
                    os.makedirs(cert_dir, exist_ok=True)
                    
                    file.save(os.path.join(cert_dir, filename))
                    disability_path = f"certificates/{filename}"
        
        # Create User Object
        new_user = User(
            username=username, 
            password=generate_password_hash(password),
            full_name=full_name,
            email=email,
            phone=phone,
            grade_id=grade_id,
            
            # New Fields
            student_type=student_type,
            parent_name=parent_name,
            parent_phone=parent_phone,
            address=address,
            school_name=school_name,
            class_grade=class_grade,
            disability_certificate_path=disability_path,
            is_verified=is_verified
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        if not is_verified:
            flash('Registration successful! Your account is pending verification. You will be notified once approved.', 'info')
            return redirect(url_for('login'))
        else:
            login_user(new_user)
            flash('Account created successfully! Welcome to Students Hub.', 'success')
            return redirect(url_for('dashboard'))

    # Pass grades and unique subjects to template for dropdown
    grades = Grade.query.filter_by(is_active=True).order_by(Grade.display_order).all()
    # Get global subjects for tutor registration
    from school import GlobalSubject
    global_subjects = GlobalSubject.query.filter_by(is_active=True).order_by(GlobalSubject.name).all()
    subject_names = [s.name for s in global_subjects]

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

        # Check Access (Subscription)
        if not current_user.can_access('expert_ask'):
             flash("Expert Questions limit reached for your plan. Please upgrade.")
             return redirect(url_for('dashboard'))
        
        # Check quota for post_count
        if current_user.role not in ['admin', 'super_admin'] and current_user.active_subscription_id:
             sub = Subscription.query.get(current_user.active_subscription_id)
             # Check limits
             limit = 0
             if sub.plan_type == 'basic_299': limit = 20
             elif sub.plan_type == 'pro_499': limit = 40
             elif sub.plan_type == 'school_1200': limit = 20
             
             if (sub.expert_used + post_count) > limit:
                 flash(f"Not enough usage quota! Remaining: {limit - sub.expert_used}")
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
            # current_user.credits -= 1 # Removed credit deduction
            
            # Increment Usage
            if current_user.role not in ['admin', 'super_admin'] and current_user.active_subscription_id:
                sub = Subscription.query.get(current_user.active_subscription_id)
                sub.expert_used += 1
                db.session.commit()
            if current_user.role not in ['admin', 'super_admin'] and current_user.active_subscription_id:
                sub = Subscription.query.get(current_user.active_subscription_id)
                sub.expert_used += 1
                db.session.commit()
            
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
                job.status = "Completed" # Marks it as posted.
                # If msg is a URL, save it to chegg_link for tracking
                if msg.startswith("http"):
                    job.chegg_link = msg
                    job.status = "Pending" # Set to Pending so the checker watches it!
                success_count += 1
            else:
                job.status = "Failed"
                # Refund Usage
                if current_user.role not in ['admin', 'super_admin'] and current_user.active_subscription_id:
                    sub = Subscription.query.get(current_user.active_subscription_id)
                    sub.expert_used = max(0, sub.expert_used - 1)
                    db.session.commit()
                    
                msg = f"{msg} (Quota Refunded)"

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
    
    # Check Access (Subscription)
    if not current_user.can_access('ai_tutor'):
        return jsonify({"error": "Daily/Monthly AI limit reached or no active plan. Please upgrade."})

    # Get responses from BOTH AIs
    chatgpt_response, chatgpt_category, chatgpt_error = get_ai_response('chatgpt', question)
    gemini_response, gemini_category, gemini_error = get_ai_response('gemini', question)
    
    # Use the category from whichever succeeded
    category = chatgpt_category or gemini_category or 'general'
    
    # Increment Usage (if not admin)
    if current_user.role not in ['admin', 'super_admin'] and current_user.active_subscription_id:
        sub = Subscription.query.get(current_user.active_subscription_id)
        sub.ai_used += 1
        db.session.commit()
    
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
        
        # Calculate file hash to prevent duplicates
        file.seek(0)
        file_hash = hashlib.md5(file.read()).hexdigest()
        file.seek(0) # Reset pointer
        
        # Check if hash exists for this user
        existing_doc = Document.query.filter_by(user_id=current_user.id, file_hash=file_hash).first()
        if existing_doc:
             flash('You have already uploaded this document! No credits awarded.', 'warning')
             return redirect(url_for('library'))

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
            file_type=file_type,
            file_hash=file_hash
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

# --- SUPER ADMIN DATA REPORTS & EXPORT ---

@app.route('/api/admin/stats')
@login_required
def api_admin_stats():
    if current_user.role != 'super_admin':
        return jsonify({"error": "Unauthorized"}), 403

    date_str = request.args.get('date')
    if not date_str:
        return jsonify({"error": "Date required"}), 400

    try:
        query_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    # 1. Total Counts
    total_students = User.query.filter(User.role != 'admin', User.role != 'super_admin').count()
    total_tutors = Tutor.query.count()
    
    # 2. Daily Counts
    # SQLite stores datetime, so we filter by range or cast. 
    # Simpler: Filter by >= date and < date + 1 day
    next_day = query_date + timedelta(days=1)
    
    daily_students = User.query.filter(
        User.role != 'admin', 
        User.role != 'super_admin',
        User.created_at >= query_date,
        User.created_at < next_day
    ).count()

    daily_tutors = Tutor.query.filter(
        Tutor.created_at >= query_date,
        Tutor.created_at < next_day
    ).count()
    
    # 3. Active Plans Count
    active_plans = Subscription.query.filter_by(is_active=True).count()

    return jsonify({
        "total": {
            "students": total_students,
            "tutors": total_tutors,
            "active_plans": active_plans
        },
        "daily": {
            "date": date_str,
            "students": daily_students,
            "tutors": daily_tutors
        }
    })

@app.route('/admin/export/students')
@login_required
def admin_export_students():
    try:
        if current_user.role != 'super_admin':
            return redirect(url_for('dashboard'))

        from fpdf import FPDF
        import io

        # Fetch Data
        students = User.query.filter(User.role != 'admin', User.role != 'super_admin').order_by(User.created_at.desc()).all()

        # Create PDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=10)
        
        # Title
        pdf.set_font("Arial", style="B", size=16)
        pdf.cell(0, 10, txt="Students Hub - All Students Report", ln=True, align='C')
        pdf.set_font("Arial", size=10)
        pdf.cell(0, 10, txt=f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align='C')
        pdf.ln(10)

        # Table Header
        pdf.set_font("Arial", style="B", size=9)
        # ID(10), Name(40), Type(20), Parent(30), Phone(25), Plan(30), Joined(30)
        col_widths = [10, 40, 20, 30, 25, 30, 30]
        headers = ["ID", "Name", "Type", "Parent", "Phone", "Active Plan", "Joined"]
        
        for i, h in enumerate(headers):
            pdf.cell(col_widths[i], 10, h, border=1)
        pdf.ln()

        # Table Body
        pdf.set_font("Arial", size=8)
        for s in students:
            # Get Plan Info
            plan_name = "Free"
            if s.active_subscription_id:
                sub = Subscription.query.get(s.active_subscription_id)
                if sub and sub.is_active:
                    plan_name = sub.plan_type.replace('_', ' ').title()

            row = [
                str(s.id),
                s.full_name or s.username,
                s.student_type.capitalize() if s.student_type else "General",
                s.parent_name or "-",
                s.parent_phone or "-",
                plan_name,
                s.created_at.strftime('%Y-%m-%d')
            ]
            
            # Check if row fits, else add page
            if pdf.get_y() > 270:
                pdf.add_page()
                # Reprint Header
                pdf.set_font("Arial", style="B", size=9)
                for i, h in enumerate(headers):
                    pdf.cell(col_widths[i], 10, h, border=1)
                pdf.ln()
                pdf.set_font("Arial", size=8)

            for i, data in enumerate(row):
                # Truncate if too long
                text = str(data)
                if len(text) > 25: text = text[:22] + "..."
                pdf.cell(col_widths[i], 10, text, border=1)
            pdf.ln()

        # Output
        return Response(bytes(pdf.output()), mimetype='application/pdf', 
                        headers={'Content-Disposition': 'attachment;filename=students_report.pdf'})
    except Exception as e:
        print(f"PDF EXPORT ERROR: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/admin/export/tutors')
@login_required
def admin_export_tutors():
    try:
        if current_user.role != 'super_admin':
            return redirect(url_for('dashboard'))

        from fpdf import FPDF

        # Fetch Data
        tutors = Tutor.query.order_by(Tutor.created_at.desc()).all()

        # Create PDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=10)
        
        # Title
        pdf.set_font("Arial", style="B", size=16)
        pdf.cell(0, 10, txt="Students Hub - All Tutors Report", ln=True, align='C')
        pdf.set_font("Arial", size=10)
        pdf.cell(0, 10, txt=f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align='C')
        pdf.ln(10)

        # Table Header
        pdf.set_font("Arial", style="B", size=9)
        # ID(10), Name(40), Subjects(40), Grades(40), Education(30), Status(20)
        col_widths = [10, 40, 40, 40, 30, 20]
        headers = ["ID", "Name", "Subjects", "Grades", "Qualification", "Status"]
        
        for i, h in enumerate(headers):
            pdf.cell(col_widths[i], 10, h, border=1)
        pdf.ln()

        # Table Body
        pdf.set_font("Arial", size=8)
        for t in tutors:
            status = "Active" if t.is_active else "Inactive"
            if not t.is_approved: status = "Pending"

            row = [
                str(t.id),
                t.display_name,
                t.subjects or "-",
                t.teaching_grades or "-",
                t.qualification or "-",
                status
            ]
            
            # Check if row fits
            if pdf.get_y() > 270:
                pdf.add_page()
                # Reprint Header
                pdf.set_font("Arial", style="B", size=9)
                for i, h in enumerate(headers):
                    pdf.cell(col_widths[i], 10, h, border=1)
                pdf.ln()
                pdf.set_font("Arial", size=8)

            for i, data in enumerate(row):
                 # Truncate
                text = str(data)
                if len(text) > 25: text = text[:22] + "..."
                pdf.cell(col_widths[i], 10, text, border=1)
            pdf.ln()

        # Output
        return Response(bytes(pdf.output(dest='S')), mimetype='application/pdf', 
                        headers={'Content-Disposition': 'attachment;filename=tutors_report.pdf'})
    except Exception as e:
        print(f"PDF EXPORT ERROR: {e}")
        return jsonify({"error": str(e)}), 500


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

# --- USER PROFILE ROUTE ---
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        bio = request.form.get('bio')
        
        current_user.full_name = full_name
        current_user.bio = bio
        
        # Profile Picture
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and '.' in file.filename:
                ext = file.filename.rsplit('.', 1)[1].lower()
                if ext in {'png', 'jpg', 'jpeg', 'gif'}:
                    filename = secure_filename(file.filename)
                    # Directory: static/uploads/profiles
                    upload_folder = os.path.join(app.root_path, 'static/uploads/profiles')
                    os.makedirs(upload_folder, exist_ok=True)
                    
                    unique_filename = f"user_{current_user.id}_{int(time.time())}.{ext}"
                    file.save(os.path.join(upload_folder, unique_filename))
                    
                    current_user.profile_picture = f"uploads/profiles/{unique_filename}"
        
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile'))
        
    return render_template('profile.html', user=current_user)

# --- FEEDBACK ROUTES ---
@app.route('/submit_feedback', methods=['POST'])
@login_required
def submit_feedback():
    content = request.form.get('content', '').strip()
    
    word_count = len(content.split())
    if word_count < 10:
        flash(f"Feedback is too short ({word_count} words). Please write at least 10 words.", "warning")
        # Redirect back to referring page
        return redirect(request.referrer or url_for('dashboard'))
        
    feedback = Feedback(user_id=current_user.id, content=content)
    db.session.add(feedback)
    db.session.commit()
    
    flash("Thank you! Your feedback has been submitted for review.")
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/admin/approve_feedback/<int:id>', methods=['POST'])
@login_required
def approve_feedback(id):
    if current_user.role not in ['admin', 'super_admin']:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('dashboard'))
        
    feedback = Feedback.query.get_or_404(id)
    feedback.is_approved = True
    db.session.commit()
    flash("Feedback approved successfully.")
    return redirect(url_for('super_admin_dashboard'))

@app.route('/admin/delete_feedback/<int:id>', methods=['POST'])
@login_required
def delete_feedback(id):
    if current_user.role not in ['admin', 'super_admin']:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('dashboard'))
        
    feedback = Feedback.query.get_or_404(id)
    db.session.delete(feedback)
    db.session.commit()
    flash("Feedback deleted.")
    return redirect(url_for('super_admin_dashboard'))


# --- CHEGG CHECKER BACKGROUND TASK ---

def run_chegg_checker():
    """
    Background task to check status of Pending jobs.
    """
    with app.app_context():
        # 1. 🔍 Get all pending jobs
        pending_jobs = Job.query.filter_by(status='Pending').all()
        if not pending_jobs:
            # print("   (No pending jobs to check)")
            return

        print(f"🕵️ Checker running for {len(pending_jobs)} pending jobs...")
        
        # 2. 🚀 Setup Parallel Execution
        # We use a ThreadPoolExecutor to run multiple checks at once
        results_to_process = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            # Create a dictionary to map futures to jobs
            future_to_job = {
                executor.submit(check_if_solved, job.chegg_link): job 
                for job in pending_jobs
            }
            
            # 3. ⏳ Process Results as they complete
            for future in concurrent.futures.as_completed(future_to_job):
                job = future_to_job[future]
                try:
                    status = future.result()
                    results_to_process.append((job, status))
                except Exception as exc:
                    print(f"   --> JOB #{job.id} generated an exception: {exc}")

        # 4. Update DB in Main Thread (SQLite is sensitive to threads)
        notifications_to_add = []
        
        for job, status in results_to_process:
            if status == 'SOLVED':
                job.status = 'Solved'
                # Create Notification
                notifications_to_add.append(Notification(
                    user_id=job.user_id,
                    message=f"Solution Ready: {job.subject}",
                    link=job.chegg_link
                ))
                print(f"   --> JOB #{job.id} SOLVED! Notification queued.")
                
            elif status == 'CAPTCHA':
                print(f"   --> JOB #{job.id} BLOCKED (Captcha).")
                # notify_super_admin is also db-dependent, careful here. 
                # Ideally, queue this too.
                # notify_super_admin(...) 
                
            elif status == 'UNSOLVED':
                print(f"   --> JOB #{job.id} Unsolved.")
                
            else:
                print(f"   --> JOB #{job.id} Error during check.")

        if notifications_to_add:
            db.session.add_all(notifications_to_add)
            
        try:
            db.session.commit()
            if notifications_to_add:
                print(f"   --> Committed {len(notifications_to_add)} new notifications.")
        except Exception as e:
            db.session.rollback()
            print(f"   --> DB Commit Error: {e}")
        
        # LOGGING TO FILE
        try:
            with open("logs/checker_run.log", "a") as f:
                f.write(f"{datetime.utcnow()} - Checked {len(pending_jobs)} jobs. New Notifications: {len(notifications_to_add)}\n")
        except:
            pass
                
        print("--- Check Complete ---")

# --- NOTIFICATION ROUTES ---

@app.route('/get-notifications')
@login_required
def get_notifications():
    # Fetch latest 20 notifications for the user
    try:
        notifs = Notification.query.filter_by(user_id=current_user.id)\
                                   .order_by(Notification.timestamp.desc())\
                                   .limit(20).all()
        
        data = [{
            'id': n.id,
            'message': n.message,
            'link': n.link,
            'is_read': n.is_read,
            'timestamp': n.timestamp.isoformat()
        } for n in notifs]
        
        return jsonify(data)
    except Exception as e:
        print(f"Error fetching notifications: {e}")
        return jsonify([])

@app.route('/mark-all-read', methods=['POST'])
@login_required
def mark_all_read():
    try:
        Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error marking read: {e}")
        return jsonify({'success': False})

# Initialize Scheduler
scheduler.add_job(id='Scheduled Task', func=run_chegg_checker, trigger="interval", minutes=1)
scheduler.init_app(app)
if __name__ == '__main__':
    scheduler.start()
    with app.app_context():
        db.create_all()
    # Use socketio.run for WebSocket support in video tutoring
    socketio.run(app, debug=True, port=5000)
