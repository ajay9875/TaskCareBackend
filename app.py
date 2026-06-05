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

load_dotenv()      

app = Flask(__name__)

# Removed the specific IP-based CORS
CORS(app, supports_credentials=True, resources={r"/api/*": {"origins": "*"}})

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

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
        "target_steps": user.target_steps,
        "current_steps": log.steps if log else 0,
        "distance_km": log.distance_km if log else 0.0
    }), 200

# This is the critical endpoint that the mobile app will call to sync steps. It handles both foreground (absolute) and background (delta) updates, and also performs the 15-day cleanup of old step logs.
@app.route('/api/steps/sync', methods=['POST'])
def sync_steps():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json()
    new_steps = data.get('steps', 0)
    new_distance = data.get('distance', 0.0)
    # This flag is critical! 
    # True = From Foreground (Total) | False = From Background (Delta)
    is_absolute = data.get('is_absolute', True) 
    
    today = datetime.now(IST).date()
    user_id = session['user_id']

    log = StepLog.query.filter_by(user_id=user_id, date=today).first()
    
    if log:
        if is_absolute:
            # Foreground: The App sends the absolute total for today
            log.steps = new_steps 
            log.distance_km = new_distance
        else:
            # Background: TaskManager sends ONLY the steps found in the last 15m
            log.steps += new_steps 
            log.distance_km += new_distance
    else:
        # First steps of the day: Create a new record
        log = StepLog(
            user_id=user_id, 
            steps=new_steps, 
            distance_km=new_distance, 
            date=today
        )
        db.session.add(log)
    
    # --- 15-DAY CLEANUP ---
    cutoff_date = today - timedelta(days=15)
    StepLog.query.filter(
        StepLog.user_id == user_id, 
        StepLog.date < cutoff_date
    ).delete()

    db.session.commit()
    return jsonify({"status": "success", "message": "Synced and history cleaned"}), 200

# Endpoint to fetch step history for the last 15 days
@app.route('/api/steps/performance', methods=['GET'])
def get_performance():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Fetch the 15-day history in chronological order
    logs = StepLog.query.filter_by(user_id=session['user_id'])\
                         .order_by(StepLog.date.asc()).all()
    
    return jsonify({
        "status": "success",
        "history": [{
            "date": l.date.strftime('%d %b'), 
            "steps": l.steps
        } for l in logs]
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

# To send daily reminder using email to each users with their tasks
from zoneinfo import ZoneInfo
import time
import threading

from flask import current_app
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# This function runs in a separate thread and checks every minute if it's time to send the daily reminders. It calculates the next target time (3:30 PM IST) and sleeps until then. When the time comes, it calls the send_daily_task_reminders function to send out the emails. It also keeps track of the last run time to avoid sending multiple emails if the scheduler runs multiple times within the same minute.
def notification_scheduler():
    target_times = [
        (22, 15)    # 10:15 PM
    ]

    last_run_times = {}  # Track last run for each target

    while True:
        now = datetime.now(IST)

        # Find the next target time
        next_target = None
        for hour, minute in target_times:
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # If target is in the past today, schedule for next day
            if now >= target:
                target += timedelta(days=1)

            # Find the earliest upcoming target
            if next_target is None or target < next_target:
                next_target = target

        sleep_seconds = (next_target - now).total_seconds()

        if sleep_seconds > 1:
            print(f"⏳ Next run at {next_target.strftime('%I:%M %p')} IST (in {int(sleep_seconds)}s)")
            time.sleep(sleep_seconds)

        # Verify we're at the exact target time
        while datetime.now(IST) < next_target:
            time.sleep(0.1)

        # Check if we already ran for this specific time today
        current_target = next_target.replace(tzinfo=None)
        if last_run_times.get(current_target.date()) == current_target.time():
            print(f"⏭ Already ran at {current_target.strftime('%I:%M %p')} today")
            continue

        try:
            with app.app_context():
                print(f"⏰ Executing scheduler for {current_target.strftime('%I:%M %p')} IST")
                sent_msg = send_daily_task_reminders()

                if sent_msg:
                    print("✅ Reminders sent successfully")
                    last_run_times[current_target.date()] = current_target.time()
                else:
                    print("ℹ️ No users needed reminders")

        except Exception as e:
            print(f"❌ Error sending notifications: {str(e)}")

# This function compiles the user's daily fitness stats and pending tasks into a beautifully formatted HTML email, and sends it to their registered email address. It handles both the case where the user has no step data for the day (showing 0 steps) and the case where they have pending tasks (listing them in a table). The email also includes a prominent button that deep-links back into the TaskCare360 app for maximum engagement.
from datetime import date
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

                    steps = today_stats.steps if today_stats else 0
                    distance = today_stats.distance_km if today_stats else 0.0
                    calories = round(steps * 0.04, 2)

                    # Goal progress
                    target = user.target_steps if user.target_steps else 5000
                    progress_percent = min(round((steps / target) * 100), 100)

                    # Get tasks
                    tasks = Todo.query.filter_by(user_id=user.id).order_by(Todo.SNo.desc()).all()

                    # --- BUILD EMAIL HTML ---
                    fitness_html = f"""
                    <div style="background-color: #f0f7ff; padding: 15px; border-radius: 10px; border: 1px solid #d1e3ff; margin-bottom: 20px;">
                        <h3 style="margin: 0 0 10px 0; color: #0056b3;">🏃 Today's Fitness Progress</h3>
                        <table style="width: 100%; text-align: center;">
                            <tr>
                                <td><span style="color: #666; font-size: 12px;">Steps</span><br><strong>{steps:,} / {target:,}</strong></td>
                                <td><span style="color: #666; font-size: 12px;">Distance</span><br><strong>{distance} km</strong></td>
                                <td><span style="color: #666; font-size: 12px;">Calories</span><br><strong>{calories} kcal</strong></td>
                            </tr>
                        </table>
                        <div style="background-color: #e0e0e0; border-radius: 5px; height: 12px; margin-top: 15px; overflow: hidden;">
                            <div style="background-color: #28a745; width: {progress_percent}%; height: 12px;"></div>
                        </div>
                        <p style="font-size: 12px; color: #666; margin-top: 5px; text-align: center;">
                            ✅ Achieved <strong>{progress_percent}%</strong> of daily goal!
                        </p>
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

                        <p style="text-align: center; margin: 30px 0;">
                            <a href="{login_url}" style="background-color: #007bff; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                                Open TaskCare 360
                            </a>
                        </p>

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
    
# ✅ Start scheduler only once in production (and local dev)
def start_scheduler():
    if os.environ.get("RUN_MAIN") != "true":  # Avoid running twice in development
        scheduler_thread = threading.Thread(target=notification_scheduler, daemon=True)
        scheduler_thread.start()

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


import os
import ssl # Added for secure connection
from email.message import EmailMessage

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

def initialize_database():
    with app.app_context():
        #db.session.execute(db.text('CREATE SCHEMA IF NOT EXISTS taskcare_schema'))
        db.session.commit()
        db.create_all()
        print("✅ Database initialized successfully")
        start_scheduler()   # 🔥 This kicks off your 10:15 PM background thread

if __name__ == '__main__':
    initialize_database()
    # 0.0.0.0 is critical for the Android emulator to find your laptop
    debug_mode = os.getenv('DEBUG', 'False').lower() == 'true'

    app.run(host='0.0.0.0', port=5000, debug=debug_mode)