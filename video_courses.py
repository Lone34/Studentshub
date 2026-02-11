from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app
from flask_login import login_required, current_user
from models import db, VideoCourse, CourseVideo, CoursePurchase, Subscription
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import stripe

video_courses_bp = Blueprint('video_courses', __name__)

ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'webm', 'mov', 'avi', 'mkv'}
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}


def allowed_video(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS


def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def get_course_dir():
    """Get or create the courses upload directory"""
    course_dir = os.path.join(current_app.config.get('UPLOAD_FOLDER', 'static/uploads'), 'courses')
    os.makedirs(course_dir, exist_ok=True)
    return course_dir


def user_has_access(user, course):
    """Check if a user can access a course"""
    # Admin/Super Admin bypass
    if user.role in ['admin', 'super_admin']:
        return True

    # Check if user purchased this course
    purchase = CoursePurchase.query.filter_by(user_id=user.id, course_id=course.id).first()
    if purchase:
        return True

    # Check if user has active subscription (gets 1 free course)
    if user.active_subscription_id:
        sub = Subscription.query.get(user.active_subscription_id)
        if sub and sub.is_active and sub.end_date >= datetime.utcnow():
            # First course by display_order is free
            first_course = VideoCourse.query.filter_by(is_active=True).order_by(VideoCourse.display_order).first()
            if first_course and first_course.id == course.id:
                return True

    # Free courses (price = 0)
    if course.price == 0:
        return True

    return False


# ============================================
# STUDENT ROUTES
# ============================================

@video_courses_bp.route('/courses/')
@login_required
def browse_courses():
    """Browse all active courses"""
    courses = VideoCourse.query.filter_by(is_active=True).order_by(VideoCourse.display_order).all()

    # Build access map
    access_map = {}
    for course in courses:
        access_map[course.id] = user_has_access(current_user, course)

    return render_template('video_courses/courses.html',
                           courses=courses,
                           access_map=access_map,
                           user=current_user)


@video_courses_bp.route('/courses/<int:course_id>')
@login_required
def course_detail(course_id):
    """View course detail with video list"""
    course = VideoCourse.query.get_or_404(course_id)
    has_access = user_has_access(current_user, course)

    return render_template('video_courses/course_detail.html',
                           course=course,
                           has_access=has_access,
                           user=current_user)


@video_courses_bp.route('/courses/<int:course_id>/watch/<int:video_id>')
@login_required
def watch_video(course_id, video_id):
    """Watch a video"""
    course = VideoCourse.query.get_or_404(course_id)
    video = CourseVideo.query.get_or_404(video_id)

    if video.course_id != course.id:
        flash('Video not found in this course.', 'danger')
        return redirect(url_for('video_courses.course_detail', course_id=course.id))

    if not user_has_access(current_user, course):
        flash('Please purchase this course to watch videos.', 'warning')
        return redirect(url_for('video_courses.course_detail', course_id=course.id))

    # Get previous/next videos
    all_videos = CourseVideo.query.filter_by(course_id=course.id).order_by(CourseVideo.display_order).all()
    current_idx = next((i for i, v in enumerate(all_videos) if v.id == video.id), 0)
    prev_video = all_videos[current_idx - 1] if current_idx > 0 else None
    next_video = all_videos[current_idx + 1] if current_idx < len(all_videos) - 1 else None

    return render_template('video_courses/watch_video.html',
                           course=course,
                           video=video,
                           prev_video=prev_video,
                           next_video=next_video,
                           current_idx=current_idx,
                           total_videos=len(all_videos),
                           user=current_user)


# ============================================
# PURCHASE ROUTES
# ============================================

@video_courses_bp.route('/courses/<int:course_id>/purchase', methods=['POST'])
@login_required
def purchase_course(course_id):
    """Initiate Stripe Checkout for a course"""
    course = VideoCourse.query.get_or_404(course_id)

    if user_has_access(current_user, course):
        flash('You already have access to this course!', 'info')
        return redirect(url_for('video_courses.course_detail', course_id=course.id))

    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'inr',
                    'product_data': {'name': f'Course: {course.title}'},
                    'unit_amount': int(course.price * 100),  # paise
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=url_for('video_courses.purchase_success', course_id=course.id, _external=True) + '&session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('video_courses.course_detail', course_id=course.id, _external=True),
            client_reference_id=str(current_user.id),
        )
        return jsonify({'checkout_url': checkout_session.url})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@video_courses_bp.route('/courses/<int:course_id>/purchase/success')
@login_required
def purchase_success(course_id):
    """Verify Stripe payment and unlock course"""
    course = VideoCourse.query.get_or_404(course_id)

    # Check if already purchased
    existing = CoursePurchase.query.filter_by(user_id=current_user.id, course_id=course.id).first()
    if existing:
        flash('Course already unlocked!', 'info')
        return redirect(url_for('video_courses.course_detail', course_id=course.id))

    payment_id = request.args.get('session_id') or f'stripe_{int(datetime.utcnow().timestamp())}'

    purchase = CoursePurchase(
        user_id=current_user.id,
        course_id=course.id,
        amount_paid=course.price,
        transaction_id=payment_id
    )
    db.session.add(purchase)
    db.session.commit()

    flash(f'Successfully unlocked "{course.title}"!', 'success')
    return redirect(url_for('video_courses.course_detail', course_id=course.id))


# ============================================
# SUPER ADMIN ROUTES
# ============================================

@video_courses_bp.route('/courses/admin/list')
@login_required
def admin_list_courses():
    """API: Get all courses for admin panel"""
    if current_user.role != 'super_admin':
        return jsonify({'error': 'Unauthorized'}), 403

    courses = VideoCourse.query.order_by(VideoCourse.display_order).all()
    return jsonify({
        'courses': [{
            'id': c.id,
            'title': c.title,
            'description': c.description or '',
            'thumbnail': c.thumbnail_path or '',
            'price': c.price,
            'is_active': c.is_active,
            'display_order': c.display_order,
            'video_count': len(c.videos),
            'purchase_count': len(c.purchases),
            'created_at': c.created_at.strftime('%Y-%m-%d')
        } for c in courses]
    })


@video_courses_bp.route('/courses/admin/create', methods=['POST'])
@login_required
def admin_create_course():
    """Create a new course"""
    if current_user.role != 'super_admin':
        return jsonify({'error': 'Unauthorized'}), 403

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    price = float(request.form.get('price', 0))
    display_order = int(request.form.get('display_order', 0))

    if not title:
        return jsonify({'error': 'Title is required'}), 400

    # Handle thumbnail upload
    thumbnail_path = None
    if 'thumbnail' in request.files:
        file = request.files['thumbnail']
        if file and file.filename and allowed_image(file.filename):
            course_dir = get_course_dir()
            filename = secure_filename(f"thumb_{int(datetime.utcnow().timestamp())}_{file.filename}")
            thumb_dir = os.path.join(course_dir, 'thumbnails')
            os.makedirs(thumb_dir, exist_ok=True)
            file.save(os.path.join(thumb_dir, filename))
            thumbnail_path = f"uploads/courses/thumbnails/{filename}"

    course = VideoCourse(
        title=title,
        description=description,
        thumbnail_path=thumbnail_path,
        price=price,
        display_order=display_order,
        created_by=current_user.id
    )
    db.session.add(course)
    db.session.commit()

    return jsonify({'success': True, 'message': f'Course "{title}" created!', 'id': course.id})


@video_courses_bp.route('/courses/admin/<int:course_id>/edit', methods=['POST'])
@login_required
def admin_edit_course(course_id):
    """Edit course details"""
    if current_user.role != 'super_admin':
        return jsonify({'error': 'Unauthorized'}), 403

    course = VideoCourse.query.get_or_404(course_id)
    course.title = request.form.get('title', course.title).strip()
    course.description = request.form.get('description', course.description or '').strip()
    course.price = float(request.form.get('price', course.price))
    course.display_order = int(request.form.get('display_order', course.display_order))
    course.is_active = request.form.get('is_active', '1') == '1'

    # Handle new thumbnail
    if 'thumbnail' in request.files:
        file = request.files['thumbnail']
        if file and file.filename and allowed_image(file.filename):
            course_dir = get_course_dir()
            filename = secure_filename(f"thumb_{int(datetime.utcnow().timestamp())}_{file.filename}")
            thumb_dir = os.path.join(course_dir, 'thumbnails')
            os.makedirs(thumb_dir, exist_ok=True)
            file.save(os.path.join(thumb_dir, filename))
            course.thumbnail_path = f"uploads/courses/thumbnails/{filename}"

    db.session.commit()
    return jsonify({'success': True, 'message': f'Course updated!'})


@video_courses_bp.route('/courses/admin/<int:course_id>/delete', methods=['POST'])
@login_required
def admin_delete_course(course_id):
    """Delete a course and all its videos"""
    if current_user.role != 'super_admin':
        return jsonify({'error': 'Unauthorized'}), 403

    course = VideoCourse.query.get_or_404(course_id)

    # Delete video files from disk
    for video in course.videos:
        try:
            full_path = os.path.join('static', video.file_path)
            if os.path.exists(full_path):
                os.remove(full_path)
        except Exception as e:
            print(f"Error deleting video file: {e}")

    # Delete thumbnail
    if course.thumbnail_path:
        try:
            full_path = os.path.join('static', course.thumbnail_path)
            if os.path.exists(full_path):
                os.remove(full_path)
        except Exception as e:
            print(f"Error deleting thumbnail: {e}")

    db.session.delete(course)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Course deleted!'})


@video_courses_bp.route('/courses/admin/<int:course_id>/add-video', methods=['POST'])
@login_required
def admin_add_video(course_id):
    """Upload a video to a course"""
    if current_user.role != 'super_admin':
        return jsonify({'error': 'Unauthorized'}), 403

    course = VideoCourse.query.get_or_404(course_id)
    title = request.form.get('title', '').strip()

    if not title:
        return jsonify({'error': 'Video title is required'}), 400

    if 'video' not in request.files:
        return jsonify({'error': 'No video file provided'}), 400

    file = request.files['video']
    if not file or not file.filename:
        return jsonify({'error': 'No video file selected'}), 400

    if not allowed_video(file.filename):
        return jsonify({'error': 'Invalid video format. Allowed: mp4, webm, mov, avi, mkv'}), 400

    # Save video file
    course_dir = get_course_dir()
    video_dir = os.path.join(course_dir, f'course_{course.id}')
    os.makedirs(video_dir, exist_ok=True)

    filename = secure_filename(f"vid_{int(datetime.utcnow().timestamp())}_{file.filename}")
    full_path = os.path.join(video_dir, filename)
    file.save(full_path)

    # Get file size
    file_size_mb = round(os.path.getsize(full_path) / (1024 * 1024), 2)

    # Get current max display_order
    max_order = db.session.query(db.func.max(CourseVideo.display_order)).filter_by(course_id=course.id).scalar() or 0

    description = request.form.get('description', '').strip()
    duration = int(request.form.get('duration', 0))

    video = CourseVideo(
        course_id=course.id,
        title=title,
        description=description,
        file_path=f"uploads/courses/course_{course.id}/{filename}",
        file_size_mb=file_size_mb,
        duration_seconds=duration,
        display_order=max_order + 1
    )
    db.session.add(video)
    db.session.commit()

    return jsonify({'success': True, 'message': f'Video "{title}" uploaded! ({file_size_mb}MB)', 'id': video.id})


@video_courses_bp.route('/courses/admin/<int:course_id>/videos')
@login_required
def admin_list_videos(course_id):
    """API: Get all videos for a course"""
    if current_user.role != 'super_admin':
        return jsonify({'error': 'Unauthorized'}), 403

    course = VideoCourse.query.get_or_404(course_id)
    return jsonify({
        'videos': [{
            'id': v.id,
            'title': v.title,
            'description': v.description or '',
            'file_size_mb': v.file_size_mb,
            'duration_seconds': v.duration_seconds,
            'display_order': v.display_order,
            'created_at': v.created_at.strftime('%Y-%m-%d %H:%M')
        } for v in course.videos]
    })


@video_courses_bp.route('/courses/admin/video/<int:video_id>/delete', methods=['POST'])
@login_required
def admin_delete_video(video_id):
    """Delete a specific video"""
    if current_user.role != 'super_admin':
        return jsonify({'error': 'Unauthorized'}), 403

    video = CourseVideo.query.get_or_404(video_id)

    # Delete file from disk
    try:
        full_path = os.path.join('static', video.file_path)
        if os.path.exists(full_path):
            os.remove(full_path)
    except Exception as e:
        print(f"Error deleting video file: {e}")

    db.session.delete(video)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Video deleted!'})
