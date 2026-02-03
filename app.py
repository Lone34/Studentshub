from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
# --- ADDED THESE IMPORTS FOR IMAGE HANDLING ---
from werkzeug.utils import secure_filename
import os
# ----------------------------------------------
from models import db, User, ServiceAccount, Job
import chegg_api
import time
import hashlib
from sqlalchemy import desc

app = Flask(__name__)
app.config['SECRET_KEY'] = 'YOUR_SECRET_KEY_HERE'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chegg_bot.db'

# --- ADDED CONFIG FOR UPLOADS ---
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
# --------------------------------

db.init_app(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

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
    return redirect(url_for('login'))

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

        new_user = User(username=username, password=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        flash('Account created. Contact an admin to activate service access.')
        return redirect(url_for('dashboard'))
    return render_template('register.html')

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

    return render_template('dashboard.html',
                           user=current_user,
                           accounts=accounts,
                           jobs=my_jobs)

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

    my_users = User.query.filter_by(manager_id=current_user.id).all()
    my_accounts = ServiceAccount.query.filter_by(owner_id=current_user.id).all()
    
    return render_template('admin.html', users=my_users, accounts=my_accounts)

# Add this route to app.py
@app.route('/tools/chegg', methods=['GET'])
@login_required
def chegg_tools():
    # 1. Fetch Accounts for Posting
    # (Adjust query if you only want specific accounts shown)
    accounts = ServiceAccount.query.all() 
    
    # 2. Fetch User History
    jobs = Job.query.filter_by(user_id=current_user.id).order_by(desc(Job.timestamp)).limit(50).all()
    
    return render_template('chegg_tools.html', accounts=accounts, jobs=jobs)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)


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

    # Call the API
    balance = chegg_api.get_account_balance(account.cookie_data, account.proxy)
    
    return jsonify({"balance": balance})
