import os
import requests
import random
import string
from flask import session
import hashlib
import time

# Brevo API URL
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"

def generate_otp(length=6):
    """Generates a numeric OTP of given length."""
    return ''.join(random.choices(string.digits, k=length))

def send_otp_email(email, otp):
    """
    Sends an OTP to the specified email using Brevo API.
    Returns (success, message).
    """
    api_key = os.environ.get('BREVO_API_KEY')
    if not api_key:
        print("BREVO_API_KEY not found in environment variables.")
        return False, "Email service configuration missing."

    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json"
    }

    data = {
        "sender": {
            "name": "Students Hub",
            "email": "parveezahmadlone3@gmail.com"
        },
        "to": [{"email": email}],
        "subject": "Your Verification Code - Students Hub",
        "htmlContent": f"""
        <html>
            <body>
                <h1>Your Verification Code</h1>
                <p>Please use the following OTP to verify your email address:</p>
                <h2 style="color: #4F46E5; letter-spacing: 5px;">{otp}</h2>
                <p>This code is valid for 10 minutes.</p>
                <p>If you did not request this code, please ignore this email.</p>
            </body>
        </html>
        """
    }

    try:
        response = requests.post(BREVO_API_URL, headers=headers, json=data)
        if response.status_code == 201:
            return True, "OTP sent successfully."
        else:
            print(f"Brevo API Error: {response.text}")
            return False, "Failed to send OTP via email provider."
    except Exception as e:
        print(f"Exception sending OTP: {str(e)}")
        return False, "An error occurred while sending email."

def store_otp(email, otp):
    """Stores OTP in session with timestamp (hashing OTP for security is better but verify needs raw)."""
    otp_str = str(otp).strip()
    otp_hash = hashlib.sha256(otp_str.encode()).hexdigest()
    print(f"[OTP DEBUG] Storing OTP for {email}. Hash: {otp_hash}") # Debug log
    session['otp_context'] = {
        'email': email,
        'otp_hash': otp_hash,
        'expires': time.time() + 600  # 10 minutes
    }

def verify_otp(email, input_otp):
    """Verifies the input OTP against the stored session OTP."""
    print(f"[OTP DEBUG] Verifying OTP for {email}. Input: {input_otp}") # Debug log
    context = session.get('otp_context')
    
    if not context:
        print("[OTP DEBUG] No OTP context found in session.")
        return False, "No OTP request found. Please request a new code."
    
    print(f"[OTP DEBUG] Context found: {context}")

    if context['email'] != email:
        print(f"[OTP DEBUG] Email mismatch. Session: {context['email']}, Input: {email}")
        return False, "Email does not match the OTP request."
    
    if time.time() > context['expires']:
        print("[OTP DEBUG] OTP expired.")
        session.pop('otp_context', None)
        return False, "OTP has expired. Please request a new code."
    
    input_otp_str = str(input_otp).strip()
    input_hash = hashlib.sha256(input_otp_str.encode()).hexdigest()
    
    print(f"[OTP DEBUG] Input Hash: {input_hash}, Stored Hash: {context['otp_hash']}")
    
    if input_hash == context['otp_hash']:
        print("[OTP DEBUG] Verification Successful.")
        session.pop('otp_context', None) # Clear after usage
        return True, "Verification successful."
    
    print("[OTP DEBUG] Hash mismatch.")
    return False, "Invalid OTP code."
