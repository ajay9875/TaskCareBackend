import os
import random
import smtplib
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask, request, session, jsonify, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from zoneinfo import ZoneInfo
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import time
import threading

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import ssl # Added for secure connection
from email.message import EmailMessage
from flask_migrate import Migrate  # 🚀 Import Flask-Migrate

load_dotenv()      

app = Flask(__name__)

# Removed the specific IP-based CORS
CORS(app, supports_credentials=True, resources={r"/api/*": {"origins": "*"}})

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ✅ FIX: Prevents "Lost connection to MySQL server" crashes on the main app and background threads
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_recycle': 280,
    'pool_pre_ping': True
}

"""
# At development 
app.config.update(
    SESSION_COOKIE_SECURE=False,    # Only send cookies over HTTPS
    SESSION_COOKIE_HTTPONLY=True,  # Prevent JavaScript from stealing cookies
    SESSION_COOKIE_SAMESITE='Lax',# Required for Cross-App requests (Android to Web)
    PERMANENT_SESSION_LIFETIME=timedelta(days=14)
)
"""

# At production
app.config.update(
    SESSION_COOKIE_SECURE=True,    # Only send cookies over HTTPS
    SESSION_COOKIE_HTTPONLY=True,  # Prevent JavaScript from stealing cookies
    SESSION_COOKIE_SAMESITE='None',# Required for Cross-App requests (Android to Web)
    #PERMANENT_SESSION_LIFETIME=timedelta(days=14)
)

db = SQLAlchemy(app)

migrate = Migrate(app, db)  # 🚀 Initialize Migrate with your app and db

IST = ZoneInfo("Asia/Kolkata")

# ======================
# MODELS
# ======================

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    todos = db.relationship('Todo', backref='user', lazy=True)
    otp = db.Column(db.String(6), nullable=True)
    otp_expiry = db.Column(db.DateTime, nullable=True)
    
    # Fitness Data
    target_steps = db.Column(db.Integer, default=5000) 
    step_logs = db.relationship('StepLog', backref='user', lazy=True)

class Todo(db.Model):
    __tablename__ = 'todo'
    SNo = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    desc = db.Column(db.String, nullable=False)
    date_created = db.Column(db.Date, nullable=False)
    date_updated = db.Column(db.Date, nullable=True)
    is_completed = db.Column(db.Boolean, default=False, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# ======================
# OLD STEP LOG MODEL
"""class StepLog(db.Model):
    __tablename__ = 'step_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    steps = db.Column(db.Integer, default=0)
    distance_km = db.Column(db.Float, default=0.0)
    date = db.Column(db.Date, nullable=False)
    # 🔥 Add this column to save the historical daily goal
    target_steps = db.Column(db.Integer, default=5000)"""

# New StepLog model with separated step buckets for walking and treadmill
class StepLog(db.Model):
    __tablename__ = 'step_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    target_steps = db.Column(db.Integer, default=5000)
    
    # 🌟 NEW SEPARATED STEP BUCKETS
    walking_steps = db.Column(db.Integer, default=0)
    treadmill_steps = db.Column(db.Integer, default=0)

# ======================
# API ENDPOINTS
# ======================
# OLD: This route returns the current day's step data for the logged-in user, including their target steps, current steps, and distance in kilometers. It checks if the user is authenticated via session and retrieves the relevant data from the database.
"""@app.route('/api/steps/data', methods=['GET'])
def get_steps_data():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user = User.query.get(session['user_id'])
    today = datetime.now(IST).date()
    log = StepLog.query.filter_by(user_id=user.id, date=today).first()
    
    return jsonify({
        "status": "success",
        "target_steps": user.target_steps, # Pulls your current live target setting
        "current_steps": log.steps if log else 0,
        "distance_km": log.distance_km if log else 0.0
    }), 200"""

# NEW: This route returns the current day's step data and allows the front-end to specify which step mode (walking or treadmill) to display.
@app.route('/api/steps/data', methods=['GET'])
def get_steps_data():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user = User.query.get(session['user_id'])
    today = datetime.now(IST).date()
    log = StepLog.query.filter_by(user_id=user.id, date=today).first()
    
    # Extract values safely or default to 0
    w_steps = log.walking_steps if log else 0
    t_steps = log.treadmill_steps if log else 0
    
    # Read what active view mode the user is toggled into from front-end query param
    mode = request.args.get('mode', 'walking')
    
    if mode == 'treadmill':
        display_steps = t_steps
        distance_km = t_steps * 0.000762
    else:
        display_steps = w_steps
        distance_km = w_steps * 0.000762

    return jsonify({
        "status": "success",
        "target_steps": user.target_steps,
        "current_steps": display_steps,     # Isolated steps for current view mode
        "distance_km": round(distance_km, 2),
        "walking_steps": w_steps,
        "treadmill_steps": t_steps
    }), 200

# OLD: This route allows the mobile app to sync step data for the current day. It checks if the user is authenticated, retrieves the new step count and distance from the request, and updates or creates a StepLog entry for today. It also includes a cleanup mechanism to delete logs older than 15 days.
"""@app.route('/api/steps/sync', methods=['POST'])
def sync_steps():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json()
    new_steps = data.get('steps', 0)
    new_distance = data.get('distance', 0.0)
    is_absolute = data.get('is_absolute', True) 
    
    user_id = session['user_id']
    user = User.query.get(user_id)

    # 1. Get the exact current time in IST
    now_ist = datetime.now(IST)
    today = now_ist.date()
    
    # 🛡️ GHOST JUMP PROTECTION BLOCK
    if now_ist.hour == 0 and now_ist.minute < 15:
        today_log = StepLog.query.filter_by(user_id=user_id, date=today).first()
        if not today_log or today_log.steps == 0:
            today = today - timedelta(days=1)
            print(f"🌙 Late night sync caught: Redirecting {new_steps} steps to yesterday ({today})")

    # Fetch the row based on our corrected target date variable
    log = StepLog.query.filter_by(user_id=user_id, date=today).first()
    
    if log:
        if is_absolute:
            log.steps = new_steps 
            log.distance_km = new_distance
        else:
            log.steps += new_steps 
            log.distance_km += new_distance
            
        log.target_steps = user.target_steps
    else:
        log = StepLog(
            user_id=user_id, 
            steps=new_steps, 
            distance_km=new_distance, 
            date=today,
            target_steps=user.target_steps 
        )
        db.session.add(log)
    
    # --- 🔄 FIXED 15-DAY ROLLING CLEANUP ---
    # Since we generate exactly the last 15 calendar days, we clean anything 
    # strictly older than 15 days back from literal today.
    cleanup_today = now_ist.date()
    cutoff_date = cleanup_today - timedelta(days=15)
    StepLog.query.filter(
        StepLog.user_id == user_id, 
        StepLog.date < cutoff_date
    ).delete()

    db.session.commit()
    return jsonify({"status": "success", "message": "Synced and history cleaned", "date_applied": str(today)}), 200
"""

# NEW: This route allows the mobile app to sync step data for the current day, with separate handling for walking and treadmill steps. It checks if the user is authenticated, retrieves the step delta and mode from the request, and updates or creates a StepLog entry for today. It also includes a cleanup mechanism to delete logs older than 15 days.
@app.route('/api/steps/sync', methods=['POST'])
def sync_steps():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json()
    step_delta = data.get('delta', 0)  # Switch layout to accept step increments cleanly
    mode = data.get('mode', 'walking') # "walking" or "treadmill"
    
    user_id = session['user_id']
    user = User.query.get(user_id)
    now_ist = datetime.now(IST)
    today = now_ist.date()
    
    # Ghost jump midnight layout wrapper check
    if now_ist.hour == 0 and now_ist.minute < 15:
        today_log = StepLog.query.filter_by(user_id=user_id, date=today).first()
        if not today_log or (today_log.walking_steps == 0 and today_log.treadmill_steps == 0):
            today = today - timedelta(days=1)

    log = StepLog.query.filter_by(user_id=user_id, date=today).first()
    
    if log:
        if mode == 'treadmill':
            log.treadmill_steps += step_delta
        else:
            log.walking_steps += step_delta
        log.target_steps = user.target_steps
    else:
        # Create fresh row configuration
        w_init = step_delta if mode == 'walking' else 0
        t_init = step_delta if mode == 'treadmill' else 0
        log = StepLog(
            user_id=user_id,
            walking_steps=w_init,
            treadmill_steps=t_init,
            date=today,
            target_steps=user.target_steps
        )
        db.session.add(log)
    
    # 15-Day rolling cleanup loop execution
    cutoff_date = now_ist.date() - timedelta(days=15)
    StepLog.query.filter(StepLog.user_id == user_id, StepLog.date < cutoff_date).delete()
    
    db.session.commit()
    return jsonify({
        "status": "success", 
        "walking_steps": log.walking_steps, 
        "treadmill_steps": log.treadmill_steps
    }), 200

# OLD:📊 UPDATED Dynamically calculates and returns exactly 15 sequential days
"""@app.route('/api/steps/performance', methods=['GET'])
def get_performance():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user = User.query.get(session['user_id'])
    today = datetime.now(IST).date()
    
    # 1. Fetch whatever logs exist for this user
    existing_logs = StepLog.query.filter_by(user_id=user.id).all()
    # Create a fast lookup dictionary mapping {date: log_object}
    logs_dict = {l.date: l for l in existing_logs}
    
    history_data = []
    
    # 2. Loop EXACTLY 15 times, calculating dates from 14 days ago up to today
    for i in range(14, -1, -1):
        target_date = today - timedelta(days=i)
        
        # Check if we have this date in our database lookup dictionary
        if target_date in logs_dict:
            db_row = logs_dict[target_date]
            steps = db_row.steps
            # Use current live target if evaluating today, otherwise use saved snapshot
            current_target = user.target_steps if target_date == today else db_row.target_steps
        else:
            # 💡 Injection point: Day missing from DB! Generate a clean 0 step entry placeholder
            steps = 0
            current_target = user.target_steps if target_date == today else 1000  # Fallback goal
            
        history_data.append({
            "date": target_date.strftime('%d %b'), 
            "steps": steps,
            "target_steps": current_target if current_target else 5000
        })
        
    return jsonify({
        "status": "success",
        "history": history_data
    }), 200
"""

# NEW:📊 UPDATED Dynamically calculates and returns exactly 15 sequential days with combined step totals
# 📊 FIXED: Dynamically calculates and returns 30 sequential days with fully separated mode tracking data
@app.route('/api/steps/performance', methods=['GET'])
def get_performance():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user = User.query.get(session['user_id'])
    today = datetime.now(IST).date()
    existing_logs = StepLog.query.filter_by(user_id=user.id).all()
    logs_dict = {l.date: l for l in existing_logs}
    
    history_data = []
    for i in range(30, -1, -1):
        target_date = today - timedelta(days=i)
        if target_date in logs_dict:
            db_row = logs_dict[target_date]
            w_steps = db_row.walking_steps if db_row.walking_steps is not None else 0
            t_steps = db_row.treadmill_steps if db_row.treadmill_steps is not None else 0
            total_steps = w_steps + t_steps
            current_target = user.target_steps if target_date == today else (db_row.target_steps or 5000)
        else:
            w_steps = 0
            t_steps = 0
            total_steps = 0
            current_target = user.target_steps if target_date == today else 5000
            
        history_data.append({
            "date": target_date.strftime('%d %b'), 
            "steps": total_steps,
            "walking_steps": w_steps,      # ✅ FIXED: Now passed cleanly to support left column layout
            "treadmill_steps": t_steps,    # ✅ FIXED: Now passed cleanly to support right column layout
            "target_steps": current_target
        })
        
    return jsonify({"status": "success", "history": history_data}), 200

# Update target steps by user (This allows users to set their own goals from the mobile app)
@app.route('/api/steps/update-target', methods=['POST'])
def update_target():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json()
    new_target = data.get('target', 5000)
    
    user = User.query.get(session['user_id'])
    user.target_steps = new_target
    db.session.commit()
    return jsonify({"status": "success", "message": "Target updated"}), 200

# Open app using web route for email app
@app.route('/contact-support')
def contact_support():
    # Redirects to the support section of your app
    print("Attempting to open the Eamil application.")
    return redirect("taskcaremobile://support")

# Open app using web route for dashboard redirection
@app.route('/open-app')
def open_app():
    # ✅ Updated scheme path from 'login' to 'dashboard' to target the home file directly
    print("Attempting to open the TaskCare360 Dashboard application. If installed, you will be redirected shortly.")
    return redirect("taskcaremobile://dashboard")

# ======================
# AUTH API ENDPOINTS
# ======================

@app.route('/', methods=['GET'])
def default():
    return jsonify({"message": "Welcome to the TaskCare API, Backend is working successfully!"}), 200

# ============================================
# ✅ EMAIL VALIDATION FUNCTION
# ============================================

import re
import dns.resolver
from email_validator import validate_email, EmailNotValidError

# List of disposable email domains (partial list)
DISPOSABLE_DOMAINS = {
    'tempmail.com', '10minutemail.com', 'throwaway.com', 'guerrillamail.com',
    'mailinator.com', 'yopmail.com', 'getnada.com', 'temp-mail.org',
    'mailnator.com', 'trashmail.com', 'spambox.us', 'spamgourmet.com',
    'mailexpire.com', 'spambox.fr', 'spambox.info', 'spambox.me',
    'spambox.us', 'spambox.xyz', 'tempmail.net', 'tempinbox.com'
}

# Common typos to correct
COMMON_TYPOS = {
    'gmail.con': 'gmail.com',
    'gmal.com': 'gmail.com',
    'gmial.com': 'gmail.com',
    'gmil.com': 'gmail.com',
    'yaho.com': 'yahoo.com',
    'yhoo.com': 'yahoo.com',
    'yohoo.com': 'yahoo.com',
    'hotmal.com': 'hotmail.com',
    'hotmil.com': 'hotmail.com',
    'outlok.com': 'outlook.com',
    'outloook.com': 'outlook.com',
}

# Role-based emails to reject
ROLE_EMAILS = {
    'admin', 'support', 'info', 'contact', 'noreply', 'no-reply',
    'help', 'sales', 'marketing', 'webmaster', 'postmaster'
}

def validate_email_address(email, check_disposable=True, check_role=True, auto_correct_typos=True):
    """
    Complete email validation with all checks
    
    Args:
        email: Email address to validate
        check_disposable: Check against disposable email domains
        check_role: Reject role-based emails
        auto_correct_typos: Auto-correct common typos
    
    Returns:
        tuple: (is_valid, message, corrected_email)
    """
    if not email:
        return False, "Email is required", None
    
    # Clean and lower case
    email = email.strip().lower()
    
    # 1. BASIC FORMAT VALIDATION
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        return False, "Invalid email format. Please enter a valid email address.", None
    
    # Extract local part and domain
    try:
        local_part, domain = email.split('@')
    except ValueError:
        return False, "Invalid email format", None
    
    # 2. LENGTH CHECKS
    if len(local_part) > 64:
        return False, "Email local part is too long (max 64 characters)", None
    
    if len(domain) > 255:
        return False, "Email domain is too long (max 255 characters)", None
    
    # 3. AUTO-CORRECT COMMON TYPOS
    original_domain = domain
    if auto_correct_typos and domain in COMMON_TYPOS:
        domain = COMMON_TYPOS[domain]
        corrected_email = f"{local_part}@{domain}"
        email = corrected_email
        print(f"🔄 Auto-corrected email: {original_domain} → {domain}")
    
    # 4. CHECK ROLE-BASED EMAILS
    if check_role and local_part in ROLE_EMAILS:
        return False, "Please use a personal email address instead of a role-based one (admin@, info@, etc.)", None
    
    # 5. CHECK DISPOSABLE EMAILS
    if check_disposable and domain in DISPOSABLE_DOMAINS:
        return False, "Disposable/temporary email addresses are not allowed. Please use a permanent email.", None
    
    # 6. DOMAIN EXISTENCE CHECK (MX Records)
    try:
        # Quick DNS check without requiring dnspython in some environments
        import socket
        # Check if domain has MX record
        try:
            dns.resolver.resolve(domain, 'MX')
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            return False, f"Domain '{domain}' does not appear to be valid", None
        except Exception as e:
            # If DNS lookup fails, still continue with email-validator
            print(f"⚠️ DNS lookup warning: {str(e)}")
    except ImportError:
        # dnspython not installed - skip MX check
        print("ℹ️ dnspython not installed, skipping MX validation")
    except Exception as e:
        print(f"⚠️ Domain validation warning: {str(e)}")
    
    # 7. COMPREHENSIVE EMAIL-VALIDATOR CHECK
    try:
        # With deliverability check
        valid = validate_email(email, check_deliverability=True)
        return True, "Email is valid", valid.normalized
    except EmailNotValidError as e:
        # Specific error from email-validator
        error_msg = str(e)
        
        # Provide user-friendly error messages
        if "domain does not exist" in error_msg.lower():
            return False, f"The domain '{domain}' does not exist. Please check for typos.", None
        elif "disposable email address" in error_msg.lower():
            return False, "Please use a permanent email address, not a temporary one.", None
        elif "mailbox does not exist" in error_msg.lower():
            return False, "This email address does not appear to be valid.", None
        else:
            return False, f"Invalid email: {error_msg}", None
    except Exception as e:
        return False, f"Email validation failed: {str(e)}", None

# ============================================
# UPDATED SIGNUP ROUTE WITH COMPLETE VALIDATION
# ============================================

@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.get_json()
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password')

    # 1. Basic field validation
    if not name:
        return jsonify({"status": "error", "message": "Full name is required"}), 400
    
    if not email:
        return jsonify({"status": "error", "message": "Email is required"}), 400
    
    if not password:
        return jsonify({"status": "error", "message": "Password is required"}), 400

    # 2. Name validation (minimum length)
    if len(name) < 2:
        return jsonify({"status": "error", "message": "Name must be at least 2 characters long"}), 400

    # 3. Password strength validation
    if len(password) < 8:
        return jsonify({"status": "error", "message": "Password must be at least 8 characters long"}), 400
    
    # Check if password is too common
    common_passwords = {'password', '12345678', 'qwerty123', 'admin123', 'password123'}
    if password in common_passwords:
        return jsonify({"status": "error", "message": "Password is too common. Please choose a stronger password"}), 400

    # 4. COMPLETE EMAIL VALIDATION
    is_valid, error_msg, corrected_email = validate_email_address(email)
    
    if not is_valid:
        return jsonify({
            "status": "error",
            "message": error_msg,
            "code": "INVALID_EMAIL"
        }), 400

    # Use corrected email if auto-correction happened
    if corrected_email and corrected_email != email:
        email = corrected_email

    # 5. Check if email already registered
    if User.query.filter_by(email=email).first():
        return jsonify({
            "status": "error", 
            "message": "This email is already registered. Please login or use a different email.",
            "code": "EMAIL_EXISTS"
        }), 400

    # 6. Create user
    try:
        new_user = User(
            name=name,
            email=email,
            password=generate_password_hash(password)
        )
        db.session.add(new_user)
        db.session.commit()
        
        return jsonify({
            "status": "success", 
            "message": "Account created successfully! Please login.",
            "user": {
                "id": new_user.id,
                "name": new_user.name,
                "email": new_user.email
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Database error during signup: {str(e)}")
        return jsonify({
            "status": "error", 
            "message": "An error occurred during registration. Please try again.",
            "code": "DATABASE_ERROR"
        }), 500

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    user = User.query.filter_by(email=data.get('email', '').lower()).first()

    if user and check_password_hash(user.password, data.get('password')):
        session.clear() # Clear any old/broken sessions
        session['user_id'] = user.id
        session['username'] = user.name # Add this so dashboard doesn't show 'None'
        session.permanent = True

        return jsonify({
            "status": "success",
            "user": {"id": user.id, "name": user.name}
        }), 200

    return jsonify({"status": "error", "message": "Invalid email or password"}), 401

# Dashboard route for testing session persistence
@app.route('/api/dashboard', methods=['GET'])
def get_dashboard_data():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    # Get the tasks for the logged-in user
    user_id = session['user_id']
    all_tasks = Todo.query.filter_by(user_id=user_id).order_by(Todo.SNo.desc()).all()

    # Send JSON back to the Android App
    return jsonify({
        "status": "success",
        "username": session.get('username'),
        "tasks": [{"SNo": t.SNo,
        "title": t.title, 
        "desc": t.desc,
        "is_completed": t.is_completed, # ✅ FIXED: Sent boolean mapping to mobile 
        "date_created": t.date_created.isoformat(), 
        "date_updated": t.date_updated.isoformat() if t.date_updated else None} for t in all_tasks]
    }), 200

# ======================
# LOGOUT API
# ======================
@app.route('/api/logout', methods=['GET', 'POST']) # Support both for flexibility
def logout():
    session.clear() # This wipes the user_id and username from the session
    return jsonify({"status": "success", "message": "Logged out successfully"}), 200

# ======================
# TASK API ENDPOINTS
# ======================

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    todos = Todo.query.filter_by(user_id=session['user_id']).order_by(Todo.SNo.desc()).all()
    return jsonify([{
        "SNo": t.SNo, "title": t.title, "desc": t.desc,
        "date_created": t.date_created.isoformat()
    } for t in todos])

@app.route('/api/addTodo', methods=['POST'])
def add_todo():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No data provided"}), 400

    # 1. Extract and Sanitize (Store in variables)
    title = data.get('title', '').strip()
    desc = data.get('desc', '').strip()

    # 2. Strict Validation (Check the clean variables)
    if not title:
        return jsonify({"status": "error", "message": "Title is required!"}), 400
    if not desc:
        return jsonify({"status": "error", "message": "Description is required!"}), 400
    
    try:
        new_todo = Todo(
            title=title,  # FIXED: Use the 'title' variable you just stripped
            desc=desc,    # FIXED: Use the 'desc' variable you just stripped
            user_id=session['user_id'],
            date_created=datetime.now(IST).date()
        )
        db.session.add(new_todo)
        db.session.commit()
        return jsonify({"status": "success", "message": "Task added!"}), 201
    except Exception as e:
        db.session.rollback() # Important for keeping the DB healthy
        return jsonify({"status": "error", "message": str(e)}), 500
    
# 🔥 NEW SEPARATE API ROUTE FOR TOGGLING STATE ONLY
@app.route('/api/tasks/toggle/<int:SNo>', methods=['POST'])
def api_toggle_task_complete(SNo):
    try:
        if 'user_id' not in session:
            return jsonify({"status": "error", "message": "Unauthorized access"}), 401

        todo = Todo.query.filter_by(SNo=SNo, user_id=session['user_id']).first()
        if not todo:
            return jsonify({"status": "error", "message": "Task not found"}), 404

        # Simply invert the current boolean flag
        todo.is_completed = not todo.is_completed
        todo.date_updated = datetime.now(IST).date()

        db.session.commit()
        return jsonify({
            "status": "success", 
            "message": "Status updated successfully", 
            "is_completed": todo.is_completed
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/delete/<int:sno>', methods=['DELETE'])
def delete_todo(sno):
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    todo = Todo.query.filter_by(SNo=sno, user_id=session['user_id']).first()
    if todo:
        db.session.delete(todo)
        db.session.commit()
        return jsonify({"status": "success", "message": "Deleted"}), 200
    return jsonify({"error": "Not found"}), 404

# ======================
# FORGOT PASSWORD API
# ======================

def send_otp(email):
    otp = str(random.randint(100000, 999999)) # Generate as string
    sender_email = os.getenv('EMAIL_USER')
    sender_password = os.getenv('EMAIL_PASS')

    msg = EmailMessage()
    msg.set_content(f"Your TaskCare360 OTP is: {otp}\n\nValid for 3 minutes.")
    msg['Subject'] = "TaskCare360: Password Reset OTP"
    msg['From'] = sender_email
    msg['To'] = email

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(sender_email, sender_password) # type: ignore
            server.send_message(msg)
        return otp  # ✅ Return the OTP so the route can save it to the DB
    except Exception as e:
        print(f"SMTP Error: {str(e)}")
        return None

# 1. Request OTP
@app.route('/api/forgot_password', methods=['POST'])
def api_forgot_password():
    data = request.get_json()
    email = data.get('email', "").strip().lower()

    if not email:
        return jsonify({"status": "error", "message": "Email is required"}), 400

    # ✅ Use the same validation
    is_valid, error_msg, corrected_email = validate_email_address(email)
    
    if not is_valid:
        return jsonify({"status": "error", "message": error_msg}), 400

    if corrected_email and corrected_email != email:
        email = corrected_email

    user = User.query.filter_by(email=email).first()
    
    if not user:
        # Don't reveal if email exists or not (security)
        return jsonify({"status": "success", "message": "If the email exists, an OTP has been sent"}), 200

    otp_code = send_otp(email)
    if otp_code:
        user.otp = otp_code
        user.otp_expiry = datetime.now() + timedelta(minutes=5)
        db.session.commit()
        return jsonify({"status": "success", "message": "OTP sent successfully"}), 200
    
    return jsonify({"status": "error", "message": "Failed to send OTP"}), 500

# 2. Verify OTP (As you wrote it, it's perfect once the DB is populated)
@app.route('/api/verify_otp', methods=['POST'])
def api_verify_otp():
    data = request.get_json()
    email = data.get('email')
    entered_otp = data.get('otp', '').strip()

    user = User.query.filter_by(email=email).first()

    if not user or not user.otp:
        return jsonify({"status": "error", "message": "The OTP has expired or does not exist. Please request a new verification code."}), 400

    if datetime.now() > user.otp_expiry:
        return jsonify({"status": "error", "message": "OTP expired"}), 400

    if user.otp == entered_otp:
        return jsonify({"status": "success", "message": "OTP verified"}), 200

    return jsonify({"status": "error", "message": "Invalid OTP"}), 400

# 3. Reset Password
@app.route('/api/reset_password', methods=['POST'])
def api_reset_password():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    user = User.query.filter_by(email=email).first()
    if user:
        user.password = generate_password_hash(password)
        user.otp = None # ✅ Clean up
        user.otp_expiry = None
        db.session.commit()
        return jsonify({"status": "success", "message": "Password updated"}), 200

    return jsonify({"status": "error", "message": "User not found"}), 404

# ======================
# UPDATE TODO API
# ======================
# Synchronized API Route for Mobile Update
@app.route('/api/update/<int:SNo>', methods=['POST'])
def api_update_todo(SNo):
    try:
        # 1. Authentication check (Mirroring your web logic)
        if 'user_id' not in session:
            return jsonify({"status": "error", "message": "Please log in to update tasks!"}), 401

        # 2. Get the todo item with ownership check
        todo = Todo.query.filter_by(SNo=SNo, user_id=session['user_id']).first()
        if not todo:
            return jsonify({"status": "error", "message": "Task not found!"}), 404

        # 3. Get JSON data from mobile request
        data = request.get_json()
        title = data.get('title', '').strip()
        desc = data.get('desc', '').strip()

        # 4. Input validation (Mirroring your web logic)
        if not title:
            return jsonify({"status": "error", "message": "Title cannot be empty!"}), 400

        # 5. Timezone logic (Fixing the 'ist' not defined error)
        # Ensure 'ist' is defined at the top of your app.py: ist = pytz.timezone('Asia/Kolkata')
        global IST
        current_ist_date = datetime.now(IST).date()

        # 6. Update fields
        todo.title = title
        todo.desc = desc
        todo.date_updated = current_ist_date

        db.session.commit()
        return jsonify({"status": "success", "message": "Task updated successfully!"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

# ======================
# INITIALIZATION
# ======================
# This function compiles the user's daily fitness stats and pending tasks into a beautifully formatted HTML email, and sends it to their registered email address. It handles both the case where the user has no step data for the day (showing 0 steps) and the case where they have pending tasks (listing them in a table). The email also includes a prominent button that deep-links back into the TaskCare360 app for maximum engagement.
def send_daily_task_reminders():
    sender_email = os.getenv('EMAIL_USER')
    sender_password = os.getenv('EMAIL_PASS')
    login_url = "https://TaskCare360.pythonanywhere.com/open-app"

    if not sender_email or not sender_password:
        print("❌ Email credentials missing")
        return False

    try:
        users = User.query.all()
        if not users:
            print("No users found")
            return False

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            emails_sent = 0

            for user in users:
                try:
                    # --- GET TODAY'S DATE PROPERLY ---
                    today = datetime.now(IST).date()
                    
                    # Query StepLog for today
                    today_stats = StepLog.query.filter_by(
                        user_id=user.id,
                        date=today
                    ).first()

                    # 🏃‍♂️ Extract separated tracking data variables securely
                    walk_steps = today_stats.walking_steps if today_stats else 0
                    tread_steps = today_stats.treadmill_steps if today_stats else 0
                    
                    # Pull tasks early to determine if we should skip the email entirely
                    tasks = Todo.query.filter_by(user_id=user.id, is_completed=False).order_by(Todo.SNo.desc()).all()

                    # 🛑 TOTAL EMPTY GATING ACTION:
                    # If they have NO steps AND NO pending tasks, skip the email completely.
                    if walk_steps == 0 and tread_steps == 0 and not tasks:
                        print(f"Skip email for {user.name}: No active steps and no tasks pending today.")
                        continue

                    # 📊 CASE 1: User HAS step data today -> Render full premium report card
                    if walk_steps > 0 or tread_steps > 0:
                        walk_km = round(walk_steps * 0.000762, 2)
                        walk_cal = int(walk_steps * 0.04)

                        tread_km = round(tread_steps * 0.000762, 2)
                        tread_cal = int(tread_steps * 0.05)

                        combined_steps = walk_steps + tread_steps
                        combined_km = round(combined_steps * 0.000762, 2)
                        combined_cal = walk_cal + tread_cal

                        target = user.target_steps if user.target_steps else 5000
                        steps_left = max(0, target - combined_steps)
                        progress_percent = min(int((combined_steps / target) * 100), 100) if target > 0 else 0

                        fitness_html = f"""
                        <div style="background-color: #16213e; padding: 24px; border-radius: 22px; border: 1.5px solid rgba(255, 255, 255, 0.12); max-width: 460px; margin: 0 auto 20px auto; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; box-shadow: 0 10px 25px rgba(0,0,0,0.35); color: #ffffff;">
                            <div style="font-size: 16px; color: #ffffff; font-weight: 800; margin-bottom: 20px; letter-spacing: 0.3px;">
                                📆 {today.strftime('%d %b')} Report
                            </div>
                            <table style="width: 100%; border-collapse: collapse; margin-bottom: 4px;" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td style="width: 48%; vertical-align: top;">
                                        <div style="margin-bottom: 12px; padding-left: 4px;">
                                            <span style="color: #4ecca3; font-size: 13px; font-weight: 800; letter-spacing: 0.8px;">🚶 WALKING</span>
                                        </div>
                                        <div style="background-color: rgba(255, 255, 255, 0.04); padding: 16px 14px; border-radius: 14px; border: 1px solid rgba(255, 255, 255, 0.08); min-height: 150px;">
                                            <div style="font-size: 19px; font-weight: bold; color: #ffffff; margin-top: 2px;">{walk_steps:,}</div>
                                            <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; margin-bottom: 12px;">STEPS</div>                                        
                                            <div style="font-size: 19px; font-weight: bold; color: #ffffff; margin-top: 2px;">{walk_km:.2f} <span style="font-size: 11px; color: #a4b0be; font-weight: 500;">KM</span></div>
                                            <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; margin-bottom: 12px;">DISTANCE</div>             
                                            <div style="font-size: 19px; font-weight: bold; color: #ff6b35; margin-top: 2px;">{walk_cal} <span style="font-size: 11px; color: #a4b0be; font-weight: 500;">CAL</span></div>
                                            <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.5px;">ENERGY</div>
                                        </div>
                                    </td>
                                    <td style="width: 4%;"></td>                                              
                                    <td style="width: 48%; vertical-align: top;">
                                        <div style="margin-bottom: 12px; padding-left: 4px;">
                                            <span style="color: #4ecca3; font-size: 13px; font-weight: 800; letter-spacing: 0.8px;">⚡ TREADMILL</span>
                                        </div>
                                        <div style="background-color: rgba(255, 255, 255, 0.04); padding: 16px 14px; border-radius: 14px; border: 1px solid rgba(255, 255, 255, 0.08); min-height: 150px;">
                                            <div style="font-size: 19px; font-weight: bold; color: #ffffff; margin-top: 2px;">{tread_steps:,}</div>
                                            <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; margin-bottom: 12px;">STEPS</div>                                      
                                            <div style="font-size: 19px; font-weight: bold; color: #ffffff; margin-top: 2px;">{tread_km:.2f} <span style="font-size: 11px; color: #a4b0be; font-weight: 500;">KM</span></div>
                                            <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; margin-bottom: 12px;">DISTANCE</div>             
                                            <div style="font-size: 19px; font-weight: bold; color: #ff6b35; margin-top: 2px;">{tread_cal} <span style="font-size: 11px; color: #a4b0be; font-weight: 500;">CAL</span></div>
                                            <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.5px;">ENERGY</div>
                                        </div>
                                    </td>
                                </tr>
                            </table>
                            <div style="height: 1.5px; background-color: rgba(255, 255, 255, 0.15); margin: 24px 0 16px 0;"></div>                       
                            <h4 style="color: #4ecca3; font-size: 13px; font-weight: 800; letter-spacing: 1.2px; margin: 0 0 16px 0; text-align: left;">COMBINED PERFORMANCE</h4>                        
                            <table style="width: 100%; border-collapse: collapse;" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td style="width: 55%; vertical-align: middle;">
                                        <table style="width: 100%; border-collapse: collapse;">
                                            <tr>
                                                <td style="padding-bottom: 14px;">
                                                    <div style="font-size: 20px; font-weight: 800; color: #ffffff; line-height: 24px;">{combined_steps:,}</div>
                                                    <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.6px; margin-top: 2px;">TOTAL STEPS</div>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td style="padding-bottom: 14px;">
                                                    {f'<div style="font-size: 20px; font-weight: 800; color: #4ecca3; line-height: 24px;">{steps_left:,}</div>' if steps_left == 0 else f'<div style="font-size: 20px; font-weight: 800; color: #ffffff; line-height: 24px;">{steps_left:,}</div>'}
                                                    <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.6px; margin-top: 2px;">STEPS REMAINING</div>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td>
                                                    <div style="font-size: 20px; font-weight: 800; color: #ffffff; line-height: 24px;">{target:,}</div>
                                                    <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.6px; margin-top: 2px;">DAILY GOAL</div>
                                                </td>
                                            </tr>
                                        </table>
                                    </td> 
                                    <td style="width: 45%; vertical-align: middle; text-align: center; padding-left: 12px;">
                                        <div style="display: inline-block; padding: 12px 20px; background-color: rgba(255, 255, 255, 0.05); border-radius: 30px; border: 2px solid #4ecca3; margin-bottom: 12px;">
                                            <strong style="color: #ffffff; font-size: 18px; font-weight: 800;">{progress_percent}%</strong>
                                        </div>          
                                        <div style="width: 70%; height: 1px; background-color: rgba(255, 255, 255, 0.15); margin: 0 auto 12px auto;"></div>                   
                                        <div style="text-align: center;">
                                            <div style="color: #ffffff; font-size: 18px; font-weight: 700; margin-bottom: 4px; line-height: 20px;">
                                                {combined_km:.2f} <span style="color: #a4b0be; font-size: 14px; font-weight: 600;">KM</span>
                                            </div>
                                            <div style="color: #ff6b35; font-size: 18px; font-weight: 700; line-height: 20px;">
                                                {combined_cal} <span style="color: #a4b0be; font-size: 14px; font-weight: 600;">CAL</span>
                                            </div>
                                        </div>
                                    </td>
                                </tr>
                            </table>
                            <div style="background-color: rgba(255, 255, 255, 0.1); border-radius: 10px; height: 8px; overflow: hidden; margin: 24px 0 14px 0;">
                                <div style="background-color: #4ecca3; width: {progress_percent}%; height: 8px; border-radius: 10px;"></div>
                            </div>               
                            <div style="text-align: center; margin-top: 28px;">
                                <a href="{login_url}" style="background-color: #4ecca3; color: #1a1a2e; padding: 14px 36px; text-decoration: none; border-radius: 12px; font-size: 15px; font-weight: bold; display: inline-block; box-shadow: 0 4px 12px rgba(78, 204, 163, 0.3); letter-spacing: 0.3px;">
                                    Open TaskCare 360
                                </a>
                            </div>
                        </div>
                        """
                    else:
                        # 🚫 CASE 2: User HAS NO step data today -> Render the premium dashed empty block placeholder
                        fitness_html = f"""
                        <div style="background-color: #16213e; padding: 24px; border-radius: 22px; border: 1.5px dashed rgba(255, 255, 255, 0.15); max-width: 460px; margin: 0 auto 20px auto; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; text-align: center; color: #a4b0be;">
                            <div style="font-size: 16px; color: #ffffff; font-weight: 800; margin-bottom: 14px; text-align: left;">
                                📆 {today.strftime('%d %b')} Report
                            </div>
                            <p style="font-size: 14px; color: rgba(255,255,255,0.4); margin: 20px 0;">
                                💤 No fitness tracking activity or step records logged for today yet.
                            </p>
                            <div style="text-align: center; margin-top: 14px;">
                                <a href="{login_url}" style="background-color: rgba(255,255,255,0.08); color: #ffffff; padding: 10px 24px; text-decoration: none; border-radius: 10px; font-size: 13px; font-weight: bold; display: inline-block; border: 1px solid rgba(255,255,255,0.15);">
                                    Sync Steps Now
                                </a>
                            </div>
                        </div>
                        """

                    # Tasks section rendering framework
                    if not tasks:
                        task_content = """
                        <div style="text-align: center; padding: 20px; border: 1px dashed #ddd; border-radius: 8px; font-family: Arial, sans-serif;">
                            🎉 Great job! No pending tasks. Keep it up!
                        </div>
                        """
                    else:
                        task_rows = ""
                        for task in tasks:
                            task_rows += f"""
                            <tr>
                                <td style="border:1px solid #ddd;padding:8px;">{task.title}</td>
                                <td style="border:1px solid #ddd;padding:8px;">{task.desc or 'No description'}</td>
                                <td style="border:1px solid #ddd;padding:8px;">{task.date_created.strftime('%Y-%m-%d')}</td>
                            </tr>
                            """

                        task_content = f"""
                        <h3 style="color: #333; font-family: Arial, sans-serif;">📋 Pending Tasks</h3>
                        <table style="border-collapse: collapse; width: 100%; font-family: Arial, sans-serif;">
                            <thead>
                                <tr style="background-color: #f2f2f2;">
                                    <th style="border:1px solid #ddd;padding:8px;text-align:left;">Title</th>
                                    <th style="border:1px solid #ddd;padding:8px;text-align:left;">Description</th>
                                    <th style="border:1px solid #ddd;padding:8px;text-align:left;">Date</th>
                                </tr>
                            </thead>
                            <tbody>{task_rows}</tbody>
                        </table>
                        <p style="font-family: Arial, sans-serif;"><strong>Total pending tasks:</strong> {len(tasks)}</p>
                        """

                    # Final HTML Assembly
                    html_body = f"""
                    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; color: #333;">
                        <h2>Hello, {user.name}! 👋</h2>
                        <p>Here's your daily progress report:</p>

                        {fitness_html}

                        {task_content}

                        <hr style="margin: 30px 0;">
                        <p style="font-size: 12px; color: #888; text-align: center;">
                            TaskCare360 — Your health & productivity partner 🚀
                        </p>
                    </div>
                    """

                    # Send email out to active user mailbox
                    subject = f"📊 Daily Progress - {today.strftime('%b %d')}"
                    msg = MIMEMultipart("alternative")
                    msg['From'] = sender_email
                    msg['To'] = user.email
                    msg['Subject'] = subject
                    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

                    server.send_message(msg)
                    emails_sent += 1
                    print(f"✅ Email sent to {user.email}")

                except Exception as e:
                    print(f"❌ Failed to send to {user.email}: {str(e)}")
                    continue

            print(f"📧 Sent {emails_sent} out of {len(users)} emails")
            return emails_sent > 0

    except Exception as e:
        print(f"❌ Fatal error in send_daily_task_reminders: {str(e)}")
        return False
    
# 🧪 TEMPORARY TEST ROUTE: Trigger emails instantly via browser
@app.route('/api/send-daily-email')
def send_daily_email():
    print("🚀 Manual trigger: Executing email sequence...")
    try:
        # We call the function directly inside the main web process
        emails_sent = send_daily_task_reminders()
        if emails_sent:
            return jsonify({"status": "success", "message": f"Successfully sent daily digest emails!"}), 200
        else:
            return jsonify({"status": "info", "message": "No emails sent. Check server terminal console logs."}), 200
    except Exception as err:
        return jsonify({"status": "error", "message": f"Direct execution crash: {str(err)}"}), 500

def initialize_database():
    with app.app_context():
        # Cleaned up the empty raw SQL try/except block. 
        # Flask-Migrate completely replaces manual query checks!
        db.create_all()
        print("✅ Database initialized successfully")

if __name__ == '__main__':
    initialize_database()
    # 0.0.0.0 is critical for the Android emulator to find your laptop
    debug_mode = os.getenv('DEBUG', 'False').lower() == 'true'

    app.run(host='0.0.0.0', port=5000, debug=debug_mode)