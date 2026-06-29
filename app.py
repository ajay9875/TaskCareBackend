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

class StepLog(db.Model):
    __tablename__ = 'step_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    steps = db.Column(db.Integer, default=0)
    distance_km = db.Column(db.Float, default=0.0)
    date = db.Column(db.Date, nullable=False)
    # 🔥 Add this column to save the historical daily goal
    target_steps = db.Column(db.Integer, default=5000)

# ======================
# API ENDPOINTS
# ======================

@app.route('/api/steps/data', methods=['GET'])
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
    }), 200

@app.route('/api/steps/sync', methods=['POST'])
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


# 📊 UPDATED: Dynamically calculates and returns exactly 15 sequential days
@app.route('/api/steps/performance', methods=['GET'])
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

# Open app using web route for login page
@app.route('/open-app')
def open_app():
    # Update this to match your app.json scheme!
    # This sends the user from the browser into the Android App
    print("Attempting to open the TaskCare360 application. If installed, you will be redirected shortly.")
    return redirect("taskcaremobile://login")

# ======================
# AUTH API ENDPOINTS
# ======================

@app.route('/', methods=['GET'])
def default():
    return jsonify({"message": "Welcome to the TaskCare API, Backend is working successfully!"}), 200

@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.get_json()
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password')

    if not name or not email or not password:
        return jsonify({"status": "error", "message": "All fields are required"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"status": "error", "message": "Email already registered"}), 400

    try:
        new_user = User(
            name=name,
            email=email,
            password=generate_password_hash(password)
        )
        db.session.add(new_user)
        db.session.commit()
        return jsonify({"status": "success", "message": "Account created!"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": "Database error. Please try again."}), 500

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
    user = User.query.filter_by(email=email).first()

    if user:
        otp_code = send_otp(email) # Capture the returned OTP
        if otp_code:
            # ✅ SAVE TO DATABASE (Required for Mobile)
            user.otp = otp_code
            user.otp_expiry = datetime.now() + timedelta(minutes=5)
            db.session.commit()
            return jsonify({"status": "success", "message": "OTP sent"}), 200
        return jsonify({"status": "error", "message": "Failed to send email"}), 500

    return jsonify({"status": "error", "message": "Email not found"}), 404

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
                    today = date.today()  # This returns date object like date(2026, 5, 13)

                    # Query StepLog for today - works with date objects
                    today_stats = StepLog.query.filter_by(
                        user_id=user.id,
                        date=today
                    ).first()

                    # 🏃‍♂️ Calculate metrics dynamically using the absolute step count formulas
                    steps = today_stats.steps if today_stats else 0
                    
                    # Matches your React Native formula: (steps * 0.000762)
                    distance = round(steps * 0.000762, 2)
                    
                    # Matches your React Native formula: (steps * 0.04)
                    calories = round(steps * 0.04, 1)

                    # Goal progress
                    target = user.target_steps if user.target_steps else 5000
                    progress_percent = round(((steps / target) * 100), 1)

                    visual_progress = min(progress_percent, 100.0)
                    steps_left = max(0, target - steps)

                    # 🎯 Added is_completed=False to filter out finished tasks
                    tasks = Todo.query.filter_by(user_id=user.id, is_completed=False).order_by(Todo.SNo.desc()).all()
                    
                    # ✅ Compute color string safely out-of-line to prevent f-string token conflicts
                    remain_color = "#4ecca3" if steps_left == 0 else "#ffffff"

                    # --- BUILD EMAIL HTML ---
                    fitness_html = f"""
                    <div style="background-color: #16213e; padding: 24px; border-radius: 20px; border: 1px solid rgba(255, 255, 255, 0.08); max-width: 480px; margin: 0 auto 20px auto; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; box-shadow: 0 10px 25px rgba(0,0,0,0.35);">
                        <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                            <tr>
                                <td style="text-align: left;">
                                    <span style="color: #4ecca3; font-size: 11px; font-weight: 800; letter-spacing: 1.5px; text-transform: uppercase; display: block; margin-bottom: 2px;">Activity Report</span>
                                    <h3 style="margin: 0; color: #ffffff; font-size: 20px; font-weight: 800; letter-spacing: -0.5px;">Fitness Progress</h3>
                                </td>
                                <td style="text-align: right; vertical-align: bottom;">
                                    <span style="color: #4ecca3; background-color: rgba(78, 204, 163, 0.1); border: 1px solid rgba(78, 204, 163, 0.2); padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: bold; display: inline-block;">
                                        {visual_progress:.1f}% Done
                                    </span>
                                </td>
                            </tr>
                        </table>
                        <table style="width: 100%; border-collapse: collapse; margin-bottom: 22px;">
                            <tr>
                                <td style="width: 55%; vertical-align: top; padding-right: 12px;">
                                    <div style="background-color: rgba(255, 255, 255, 0.03); border-radius: 14px; padding: 14px; border: 1px solid rgba(255, 255, 255, 0.04); min-height: 120px;">
                                        <span style="color: #4ecca3; font-size: 10px; font-weight: 800; letter-spacing: 1px; display: block; margin-bottom: 6px;">STEPS</span>
                                        <div style="margin-bottom: 8px;">
                                            <span style="color: #ffffff; font-size: 22px; font-weight: bold; line-height: 1;">{steps:,}</span>
                                            <span style="color: #95a5a6; font-size: 10px; font-weight: 700; display: block; margin-top: 1px;">COMPLETED</span>
                                        </div>  
                                        <div style="margin-bottom: 8px;">
                                            { # ✅ Injected safely here as a simple string reference placeholder }
                                            <span style="color: {remain_color}; font-size: 18px; font-weight: bold; line-height: 1;">{steps_left:,}</span>
                                            <span style="color: #95a5a6; font-size: 10px; font-weight: 700; display: block; margin-top: 1px;">REMAIN</span>
                                        </div>
                                        <div>
                                            <span style="color: #ffffff; font-size: 16px; font-weight: bold; line-height: 1; opacity: 0.9;">{target:,}</span>
                                            <span style="color: #95a5a6; font-size: 10px; font-weight: 700; display: block; margin-top: 1px;">DAILY GOAL</span>
                                        </div>
                                    </div>
                                </td>
                                <td style="width: 45%; vertical-align: top;">
                                    <div style="background-color: rgba(255, 255, 255, 0.03); border-radius: 14px; padding: 14px; border: 1px solid rgba(255, 255, 255, 0.04); min-height: 120px; text-align: center;">
                                        <span style="color: #4ecca3; font-size: 10px; font-weight: 800; letter-spacing: 1px; display: block; margin-bottom: 12px; text-align: center;">ACTIVITY</span>
                                        <div style="margin-bottom: 14px;">
                                            <span style="color: #ffffff; font-size: 18px; font-weight: bold;">{distance} <span style="color: #95a5a6; font-size: 10px; font-weight: 600;">KM</span></span>
                                        </div>
                                        <div>
                                            <span style="color: #ff6b35; font-size: 18px; font-weight: bold;">{calories} <span style="color: #95a5a6; font-size: 10px; font-weight: 600;">CAL</span></span>
                                        </div>
                                    </div>
                                </td>
                            </tr>
                        </table>
                        <div style="background-color: rgba(255, 255, 255, 0.08); border-radius: 10px; height: 8px; overflow: hidden; position: relative;">
                            <div style="background-color: #4ecca3; width: {visual_progress}%; height: 8px; border-radius: 10px;"></div>
                        </div>
                        <div style="margin-top: 28px; text-align: center;">
                            <a href="{login_url}" style="background-color: #4ecca3; color: #1a1a2e; padding: 12px 30px; text-decoration: none; border-radius: 12px; font-size: 14px; font-weight: bold; display: inline-block; letter-spacing: 0.3px; transition: all 0.2s ease;">
                                Open TaskCare 360 App
                            </a>
                        </div>
                    </div>
                    """
                    # Tasks section
                    if not tasks:
                        task_content = """
                        <div style="text-align: center; padding: 20px; border: 1px dashed #ddd; border-radius: 8px;">
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
                        <h3 style="color: #333;">📋 Pending Tasks</h3>
                        <table style="border-collapse: collapse; width: 100%;">
                            <thead>
                                <tr style="background-color: #f2f2f2;">
                                    <th style="border:1px solid #ddd;padding:8px;">Title</th>
                                    <th style="border:1px solid #ddd;padding:8px;">Description</th>
                                    <th style="border:1px solid #ddd;padding:8px;">Date</th>
                                </tr>
                            </thead>
                            <tbody>{task_rows}</tbody>
                        </table>
                        <p><strong>Total pending tasks:</strong> {len(tasks)}</p>
                        """

                    # Final HTML
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

                    # Send email
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