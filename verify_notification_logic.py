from chegg_api import check_if_solved
import requests

# Test URLs
# Replace these with real URLs if you have them, otherwise we just test the function mechanics
unsolved_url = "https://www.chegg.com/homework-help/questions-and-answers/unsolved-question-example-q12345678" 
solved_url = "https://www.chegg.com/homework-help/questions-and-answers/solved-question-example-q87654321"

print("--- Testing Unsolved URL (Simulated/Real) ---")
# Note: Since we don't have a guaranteed unsolved URL handy, this might return 404 or Error, 
# but we want to see the LOGS from check_if_solved.
status = check_if_solved(unsolved_url)
print(f"Result: {status}\n")

print("--- Testing Random Page (Should be Error or Unsolved) ---")
status = check_if_solved("https://google.com")
print(f"Result: {status}\n")
