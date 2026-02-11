"""
Migration script to add video course tables.
Run: python add_video_courses.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from models import VideoCourse, CourseVideo, CoursePurchase

with app.app_context():
    db.create_all()
    print("[OK] Video course tables created successfully!")
    print("   - video_course")
    print("   - course_video")
    print("   - course_purchase")
