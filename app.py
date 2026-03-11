import os
import random
import smtplib
from datetime import datetime, timedelta, UTC
from dotenv import load_dotenv
from flask import Flask, request, session, jsonify, current_app
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

app.config.update(
    SESSION_COOKIE_SECURE=True,    # Only send cookies over HTTPS
    SESSION_COOKIE_HTTPONLY=True,  # Prevent JavaScript from stealing cookies
    SESSION_COOKIE_SAMESITE='None',# Required for Cross-App requests (Android to Web)
)

db = SQLAlchemy(app)
IST = ZoneInfo("Asia/Kolkata")

# ======================
# MODELS
# ======================

class User(db.Model):
    __tablename__ = 'user'
    __table_args__ = {'schema': 'taskcare_schema'}
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    todos = db.relationship('Todo', backref='user', lazy=True)

class Todo(db.Model):
    __tablename__ = 'todo'
    __table_args__ = {'schema': 'taskcare_schema'}
    SNo = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    desc = db.Column(db.String, nullable=False)
    date_created = db.Column(db.Date, nullable=False)
    date_updated = db.Column(db.Date, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('taskcare_schema.user.id'), nullable=False)

# ======================
# AUTH API ENDPOINTS
# ======================

@app.route('/', methods=['GET'])
def default():
    return jsonify({"message": "Welcome to the TaskCare API"}), 200

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
        "tasks": [{"SNo": t.SNo, "title": t.title, "desc": t.desc, "date_created": t.date_created.isoformat(), "date_updated": t.date_updated.isoformat() if t.date_updated else None} for t in all_tasks]
    }), 200

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
    try:
        new_todo = Todo(
            title=data.get('title'),
            desc=data.get('desc'),
            user_id=session['user_id'],
            date_created=datetime.now(IST).date()
        )
        db.session.add(new_todo)
        db.session.commit()
        return jsonify({"status": "success", "message": "Task added!"}), 201
    except Exception as e:
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

import random
import smtplib
import os
from datetime import datetime, timedelta
from flask import session

def send_otp(email):
    # 1. Generate a 6-digit OTP
    otp = random.randint(100000, 999999)
    
    # 2. Get credentials from environment variables
    sender_email = os.getenv('EMAIL_USER')
    sender_password = os.getenv('EMAIL_PASS')

    if not sender_email or not sender_password:
        # Log error for the developer
        print("Error: EMAIL_USER or EMAIL_PASS not set in environment.")
        return False

    # 3. Construct the email message
    subject = "TaskCare360: Password Reset OTP"
    body = f"Your OTP for password reset is: {otp}\n\nThis code is valid for 3 minutes."
    message = f"Subject: {subject}\n\n{body}"

    try:
        # 4. Connect to Gmail SMTP
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()  # Secure the connection
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, email, message)

        # 5. Store OTP and Expiry in session for API verification
        # We store as string to ensure JSON compatibility for the mobile bridge
        session['sent_otp'] = str(otp) 
        session['otp_expiry'] = (datetime.now() + timedelta(minutes=3)).timestamp()
        
        # Force Flask to save the session cookie for the Android client
        session.modified = True 
        
        return True

    except smtplib.SMTPAuthenticationError:
        print("SMTP Authentication failed. Verify your Google App Password.")
    except Exception as e:
        print(f"SMTP Error: {str(e)}")
    
    return False

# 1. Request OTP
@app.route('/api/forgot_password', methods=['POST'])
def api_forgot_password():
    data = request.get_json()
    email = data.get('email', "").strip().lower()
    user = User.query.filter_by(email=email).first()

    if user:
        if send_otp(email):
            session['email'] = email # Store for verification step
            return jsonify({"status": "success", "message": "OTP sent to your email"}), 200
        return jsonify({"status": "error", "message": "Failed to send OTP"}), 500
    
    return jsonify({"status": "error", "message": "Email not found"}), 404

# 2. Verify OTP
@app.route('/api/verify_otp', methods=['POST'])
def api_verify_otp():
    data = request.get_json()
    entered_otp = data.get('otp', '').strip()
    
    sent_otp = session.get('sent_otp')
    otp_expiry = session.get('otp_expiry')
    email = session.get('email')

    if not email or not sent_otp or not otp_expiry:
        return jsonify({"status": "error", "message": "Session invalid. Restart process."}), 400

    if datetime.now().timestamp() > float(otp_expiry):
        return jsonify({"status": "error", "message": "OTP expired"}), 400

    if str(sent_otp) == entered_otp:
        session['verified_email'] = email
        session.pop('sent_otp', None)
        return jsonify({"status": "success", "message": "OTP verified"}), 200
    
    return jsonify({"status": "error", "message": "Invalid OTP"}), 400

# 3. Reset Password
@app.route('/api/reset_password', methods=['POST'])
def api_reset_password():
    email = session.get('verified_email')
    if not email:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.get_json()
    password = data.get('password')
    
    user = User.query.filter_by(email=email).first()
    if user:
        user.password = generate_password_hash(password)
        db.session.commit()
        session.pop('verified_email', None)
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
        db.session.execute(db.text('CREATE SCHEMA IF NOT EXISTS taskcare_schema'))
        db.session.commit()
        db.create_all()

if __name__ == '__main__':
    initialize_database()
    # 0.0.0.0 is critical for the Android emulator to find your laptop
    app.run(host='0.0.0.0', port=5000, debug=True)
