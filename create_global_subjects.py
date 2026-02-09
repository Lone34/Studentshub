from app import app, db
from school import GlobalSubject

with app.app_context():
    db.create_all()
    print("GlobalSubject table created.")
