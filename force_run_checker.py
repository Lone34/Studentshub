from app import app, run_chegg_checker

print("Manually running chegg checker...")
try:
    with app.app_context():
        run_chegg_checker()
    print("Manual run complete.")
except Exception as e:
    print(f"Manual run failed: {e}")
