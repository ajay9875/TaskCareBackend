import os
import random
import smtplib
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask, request, session, jsonify, redirect, abort
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from zoneinfo import ZoneInfo
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import time
import threading
import requests

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import ssl # Added for secure connection
from email.message import EmailMessage
from flask_migrate import Migrate  # 🚀 Import Flask-Migrate
from itsdangerous import BadSignature, URLSafeTimedSerializer

load_dotenv()

app = Flask(__name__)

# Removed the specific IP-based CORS
CORS(app, supports_credentials=True, resources={r"/api/*": {"origins": "*"}})

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SCHEDULER_SECRET'] = os.getenv('SCHEDULER_SECRET')

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
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='None',
    PERMANENT_SESSION_LIFETIME=timedelta(days=210)   # ← uncomment + set to 210
)
 
db = SQLAlchemy(app)

migrate = Migrate(app, db)  # 🚀 Initialize Migrate with your app and db
sync_token_serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

IST = ZoneInfo("Asia/Kolkata")

# ======================
# MODELS
# ======================

# In app.py, add this below your StepSyncEvent model
import secrets

class Team(db.Model):
    __tablename__ = 'team'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    join_code = db.Column(db.String(10), unique=True, nullable=False, default=lambda: secrets.token_hex(4).upper())
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    members = db.relationship('TeamMember', backref='team', lazy=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class TeamMember(db.Model):
    __tablename__ = 'team_member'
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(20), default='member') # 'admin' or 'member'
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('team_id', 'user_id', name='_team_user_uc'),)

class PushToken(db.Model):
    __tablename__ = 'push_token'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    token = db.Column(db.String(200), nullable=False, unique=True)
    platform = db.Column(db.String(20), nullable=True)  # 'android' or 'ios'
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    todos = db.relationship('Todo', backref='user', lazy=True)
    otp = db.Column(db.String(6), nullable=True)
    otp_expiry = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow) # 👈 ADD THIS

    # 🆕 Track last activity for the admin panel
    last_seen = db.Column(db.DateTime, nullable=True)

    # 👇 ADD THESE TWO LINES
    is_signed_in = db.Column(db.Boolean, default=False, nullable=False)
    last_status_change = db.Column(db.DateTime, nullable=True)

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
    # ✅ NEW: Soft delete flag
    is_deleted = db.Column(db.Boolean, default=False, nullable=False) 
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# ======================
# OLD STEP LOG MODEL
# ======================

# StepLog model with separated step buckets for walking and treadmill
class StepLog(db.Model):
    __tablename__ = 'step_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    target_steps = db.Column(db.Integer, default=5000)

    # 🌟 NEW SEPARATED STEP BUCKETS
    walking_steps = db.Column(db.Integer, default=0)
    treadmill_steps = db.Column(db.Integer, default=0)


class StepSyncEvent(db.Model):
    __tablename__ = 'step_sync_event'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(80), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

def now_ist_naive() -> datetime:
    """IST clock time, no tzinfo — safe for MySQL DATETIME columns and delta math."""
    return datetime.now(IST).replace(tzinfo=None)

@app.route('/api/festival', methods=['GET'])
def get_festival():
    # You can hardcode this, or read it from your database
    fest_name = os.getenv("FEST_NAME")
    fest_message = os.getenv("FEST_MESSAGE")
    base_api_url = os.getenv("API_BASE_URL")
    gif_name = os.getenv("GIF_NAME")
    formatted_gif_url = f"{base_api_url}/static/{gif_name}"
    return jsonify({
        "active": True,
        "name": fest_name,
        "message": fest_message,
        # Host the GIF anywhere (S3, Imgur, your server's static folder, etc.)
        "gif_url": formatted_gif_url 
    }), 200

# ======================
# NUMBER FORMATTING HELPERS
# ======================

def format_compact_number(n, decimals=1):
    """
    Abbreviate large integers for display.

    Examples:
        999            -> "999"
        1_500          -> "1.5K"
        32_315         -> "32.3K"
        1_000_000      -> "1M"
        1_100_000      -> "1.1M"
        1_500_000_000  -> "1.5B"
        2_000_000_000_000 -> "2T"

    Returns a string. Negative numbers keep their sign.
    """
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return "0"

    sign = "-" if n < 0 else ""
    n = abs(n)

    for threshold, suffix in (
        (1_000_000_000_000, "T"),
        (1_000_000_000,     "B"),
        (1_000_000,         "M"),
        (1_000,             "K"),
    ):
        if n >= threshold:
            value = n / threshold
            # Trim trailing .0 so 1.0M -> "1M", but keep 1.5M
            formatted = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
            return f"{sign}{formatted}{suffix}"

    return f"{sign}{int(n)}"


def format_metric(n, decimals=1):
    """
    Universal number formatter. Returns raw value, display string, and
    comma-separated full string.

    - Integers (steps, calories, counts)  → abbreviated: "32.3K", "1.5M", "2B"
    - Floats (distances, etc.)            → preserved decimals: "11.43", "24.38"
    """
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        n = 0.0

    # Integers → use compact abbreviation
    if n.is_integer():
        raw = int(n)
        return {
            "value":   raw,
            "display": format_compact_number(raw, decimals=decimals),
            "full":    f"{raw:,}",
        }

    # Floats → preserve the decimals as given
    rounded = round(n, 2)
    return {
        "value":   rounded,
        "display": f"{rounded:.2f}",
        "full":    f"{rounded:.2f}",
    }

@app.before_request
def _touch_last_seen():
    if request.path.startswith('/api/admin/'):
        return
    if request.method == 'OPTIONS':
        return
    uid = session.get('user_id')
    if not uid:
        return
    try:
        u = User.query.get(uid)
        if u:
            u.last_seen = now_ist_naive()   # ← IST
            db.session.commit()
    except Exception:
        db.session.rollback()

def _humanize(delta: timedelta) -> str:
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h"
    days = hrs // 24
    return f"{days}d"

@app.route('/api/admin/verify-pin', methods=['POST'])
def verify_super_admin_pin():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    current = User.query.get(session['user_id'])
    if not _is_admin(current):
        return jsonify({"error": "Forbidden"}), 403

    data = request.get_json()
    entered_pin = str(data.get('pin', '')).strip()
    correct_pin = os.getenv('SUPER_ADMIN_PIN')

    if entered_pin == correct_pin:
        session['super_admin_access'] = True
        return jsonify({"status": "success", "message": "Access Granted"}), 200
    else:
        return jsonify({"error": "Invalid PIN"}), 403

@app.route('/api/superadmin/teams', methods=['GET'])
def superadmin_list_teams():
    if 'user_id' not in session or not session.get('super_admin_access'):
        return jsonify({"error": "Super Admin Access Required"}), 403

    teams = Team.query.order_by(Team.id.desc()).all()
    out = []
    now = datetime.utcnow()

    for t in teams:
        # Get admin name
        admin = User.query.get(t.created_by)
        
        # Calculate age
        delta = now - t.created_at
        if delta.days > 0:
            age = f"{delta.days}d ago"
        elif delta.seconds > 3600:
            age = f"{delta.seconds // 3600}h ago"
        else:
            age = f"{delta.seconds // 60}m ago"

        out.append({
            "id": t.id,
            "name": t.name,
            "join_code": t.join_code,
            "created_by": admin.name if admin else "Unknown",
            "created_at_label": age,
            "member_count": len(t.members)
        })
    return jsonify({"status": "success", "teams": out}), 200

@app.route('/api/superadmin/teams/<int:team_id>', methods=['DELETE'])
def superadmin_delete_team(team_id):
    if 'user_id' not in session or not session.get('super_admin_access'):
        return jsonify({"error": "Super Admin Access Required"}), 403

    team = Team.query.get(team_id)
    if not team:
        return jsonify({"error": "Team not found"}), 404

    try:
        # Cascade: remove memberships, then the team itself.
        TeamMember.query.filter_by(team_id=team.id).delete()
        db.session.delete(team)
        db.session.commit()
        return jsonify({
            "status": "success",
            "message": f"Team #{team_id} deleted"
        }), 200
    except Exception as e:
        db.session.rollback()
        print(f"❌ Delete team failed: {e}")
        return jsonify({"status": "error", "message": "Delete failed"}), 500

# --- TEAM MANAGEMENT ROUTES ---

MAX_TEAMS_PER_USER = 10

@app.route('/api/teams/my-teams', methods=['GET'])
def get_my_team():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get ALL memberships for this user
    memberships = TeamMember.query.filter_by(user_id=session['user_id']).all()
    if not memberships:
        return jsonify({"status": "success", "teams": []}), 200
    
    today = datetime.now(IST).date()
    teams_data = []
    
    for membership in memberships:
        team = Team.query.get(membership.team_id)
        if not team:
            continue
            
        members_data = []
        for m in team.members:
            user = User.query.get(m.user_id)
            log = StepLog.query.filter_by(user_id=user.id, date=today).first()
            steps = (log.walking_steps or 0) + (log.treadmill_steps or 0) if log else 0
            
            members_data.append({
                "user_id": user.id,
                "name": user.name,
                "role": m.role,
                "steps_today": steps,
                "is_signed_in": user.is_signed_in,
                "last_seen": user.last_seen.isoformat() if user.last_seen else None,
            })
            
        teams_data.append({
            "id": team.id,
            "name": team.name,
            "join_code": team.join_code,
            "is_admin": membership.role == 'admin',
            "current_user_id": session['user_id'],
            "members": members_data
        })
        
    return jsonify({"status": "success", "teams": teams_data}), 200

from urllib.parse import quote  # add at top of file

@app.route('/join-team')
def join_team_redirect():
    code = request.args.get('code', '').strip().upper()
    safe_code = quote(code, safe='')
    # Modify to teams (corresponding to app/teams/index.tsx)
    return redirect(f"taskcaremobile://teams?prefill={safe_code}")
 
@app.route('/api/teams/rename', methods=['POST'])
def rename_team():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    new_name = (data.get('name') or '').strip()
    team_id = data.get('team_id')                       # ✅ NEW

    if not team_id:
        return jsonify({"error": "team_id is required"}), 400
    if not new_name:
        return jsonify({"error": "Team name is required"}), 400
    if len(new_name) < 2:
        return jsonify({"error": "Team name must be at least 2 characters"}), 400
    if len(new_name) > 150:
        return jsonify({"error": "Team name must be 150 characters or fewer"}), 400

    membership = TeamMember.query.filter_by(
        user_id=session['user_id'], team_id=team_id
    ).first()                                           # ✅ SPECIFIC team
    if not membership:
        return jsonify({"error": "You are not in this team"}), 404
    if membership.role != 'admin':
        return jsonify({"error": "Only team admins can rename the team"}), 403

    team = Team.query.get(team_id)
    if not team:
        return jsonify({"error": "Team not found"}), 404

    try:
        team.name = new_name
        db.session.commit()
        return jsonify({
            "status": "success",
            "message": "Team renamed successfully",
            "team": {"id": team.id, "name": team.name},
        }), 200
    except Exception as e:
        db.session.rollback()
        print(f"❌ Rename team failed: {e}")
        return jsonify({"error": "Rename failed"}), 500


def _build_user_history_payload(target_user: User):
    """Shared history payload for both admin & team-admin views."""
    now = now_ist_naive()
    ONLINE_WINDOW = timedelta(minutes=15)

    if not target_user.last_seen:
        status_state = "never"
        status_label = "Not active yet"
    else:
        delta = now - target_user.last_seen
        if delta <= ONLINE_WINDOW:
            status_state = "online"
            status_label = "Signed in · Active now"
        else:
            status_state = "offline"
            status_label = f"Last seen {_humanize(delta)} ago"

    if target_user.is_signed_in is False and target_user.last_status_change:
        if (now - target_user.last_status_change) <= ONLINE_WINDOW:
            status_state = "offline"
            status_label = f"Signed out · {_humanize(now - target_user.last_status_change)} ago"

    today = datetime.now(IST).date()
    existing_logs = StepLog.query.filter_by(user_id=target_user.id).all()
    logs_dict = {l.date: l for l in existing_logs}
    all_dates = sorted(logs_dict.keys(), reverse=True)

    history_data = []
    total_walking = 0
    total_treadmill = 0

    for target_date in all_dates:
        row = logs_dict[target_date]
        w = row.walking_steps or 0
        t = row.treadmill_steps or 0
        total_walking += w
        total_treadmill += t
        history_data.append({
            "date": target_date.strftime('%d %b'),
            "date_iso": target_date.isoformat(),
            "date_full": target_date.strftime('%d %b %Y'),
            "year": target_date.year,
            "steps": w + t,
            "walking_steps": w,
            "treadmill_steps": t,
            "target_steps": (
                target_user.target_steps
                if target_date == today
                else (row.target_steps or 5000)
            ),
        })

    combined = total_walking + total_treadmill

    summary = {
        "walking_steps":   format_metric(total_walking),
        "treadmill_steps": format_metric(total_treadmill),
        "walking_km":      format_metric(round(total_walking   * 0.000762, 2)),
        "walking_cal":     format_metric(round(total_walking   * 0.04)),
        "treadmill_km":    format_metric(round(total_treadmill * 0.000762, 2)),
        "treadmill_cal":   format_metric(round(total_treadmill * 0.0575)),
        "combined_steps":  format_metric(combined),
        "combined_km":     format_metric(round(combined * 0.000762, 2)),
        "combined_cal":    format_metric(
            round(total_walking * 0.04) + round(total_treadmill * 0.0575)
        ),
        "days_tracked":    len(all_dates),
    }

    return jsonify({
        "status": "success",
        "server_now": now.isoformat() + "+05:30",
        "user": {
            "id": target_user.id,
            "name": target_user.name,
            "email": target_user.email,
            "last_seen": target_user.last_seen.isoformat() if target_user.last_seen else None,
            "last_status_change": target_user.last_status_change.isoformat() if target_user.last_status_change else None,
            "is_signed_in": bool(target_user.is_signed_in),
            "target_steps": target_user.target_steps or 5000,
            "status_state": status_state,
            "status_label": status_label,
        },
        "history": history_data,
        "summary": summary,
    }), 200

@app.route('/api/admin/users/<int:user_id>/history', methods=['GET'])
def admin_user_history(user_id):
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    current = User.query.get(session['user_id'])
    if not _is_admin(current):
        return jsonify({"status": "error", "message": "Forbidden"}), 403
    target = User.query.get(user_id)
    if not target:
        return jsonify({"status": "error", "message": "User not found"}), 404
    return _build_user_history_payload(target)


@app.route('/api/teams/member/<int:member_id>/history', methods=['GET'])
def team_member_history(member_id):
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    # ✅ Get the team_id passed from the frontend
    team_id = request.args.get('team_id', type=int)
    if not team_id:
        return jsonify({"status": "error", "message": "team_id is required"}), 400

    # ✅ Find the CALLER's membership for THIS SPECIFIC team
    caller = TeamMember.query.filter_by(user_id=session['user_id'], team_id=team_id).first()
    if not caller:
        return jsonify({"status": "error", "message": "You are not in this team"}), 403

    is_self = (member_id == session['user_id'])
    is_admin = (caller.role == 'admin')

    # Admin can view anyone in the team; a member can only view themselves
    if not is_admin and not is_self:
        return jsonify({
            "status": "error",
            "message": "Detailed history is private. Ask the team admin."
        }), 403

    # Ensure the target user is actually in this team
    if not TeamMember.query.filter_by(team_id=team_id, user_id=member_id).first():
        return jsonify({"status": "error", "message": "User is not in your team"}), 404

    target = User.query.get(member_id)
    if not target:
        return jsonify({"status": "error", "message": "User not found"}), 404

    return _build_user_history_payload(target)

@app.route('/api/teams/create', methods=['POST'])
def create_team():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    # ✅ Enforce the 10-team limit
    team_count = TeamMember.query.filter_by(user_id=session['user_id']).count()
    if team_count >= MAX_TEAMS_PER_USER:
        return jsonify({"error": "You can only be in a maximum of 10 teams. Please contact admin."}), 403

    data = request.get_json()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({"error": "Team name is required"}), 400
        
    try:
        new_team = Team(name=name, created_by=session['user_id'])
        db.session.add(new_team)
        db.session.flush()
        
        admin_member = TeamMember(team_id=new_team.id, user_id=session['user_id'], role='admin')
        db.session.add(admin_member)
        
        db.session.commit()
        return jsonify({"status": "success", "message": "Team created!", "join_code": new_team.join_code}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/api/teams/delete', methods=['DELETE'])
def delete_my_team():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    # ✅ Frontend must pass the team_id of the team being deleted
    team_id = request.args.get('team_id', type=int)
    if not team_id:
        return jsonify({"error": "team_id is required"}), 400

    membership = TeamMember.query.filter_by(user_id=session['user_id'], team_id=team_id).first()
    if not membership:
        return jsonify({"error": "You are not in this team"}), 404

    if membership.role != 'admin':
        return jsonify({"error": "Only team admins can delete the team"}), 403

    team = Team.query.get(team_id)
    if not team:
        return jsonify({"error": "Team not found"}), 404

    try:
        TeamMember.query.filter_by(team_id=team.id).delete()
        db.session.delete(team)
        db.session.commit()
        return jsonify({
            "status": "success",
            "message": f"Team '{team.name}' has been deleted",
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Delete failed"}), 500

@app.route('/api/teams/members/<int:member_id>', methods=['DELETE'])
def remove_team_member(member_id):
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    # ✅ Frontend must pass the team_id
    team_id = request.args.get('team_id', type=int)
    if not team_id:
        return jsonify({"error": "team_id is required"}), 400

    # Check requester's admin status IN THIS SPECIFIC TEAM
    current_member = TeamMember.query.filter_by(user_id=session['user_id'], team_id=team_id).first()
    if not current_member or current_member.role != 'admin':
        return jsonify({"error": "Only team admins can remove members"}), 403

    if member_id == session['user_id']:
        return jsonify({"error": "You cannot remove yourself."}), 400

    target_member = TeamMember.query.filter_by(team_id=team_id, user_id=member_id).first()
    if not target_member:
        return jsonify({"error": "Member not found in your team"}), 404

    try:
        db.session.delete(target_member) # ONLY deletes the membership
        db.session.commit()
        return jsonify({"status": "success", "message": "Member removed successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/api/teams/join', methods=['POST'])
def join_team():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.get_json()
    code = data.get('code', '').strip().upper()
    
    if not code:
        return jsonify({"error": "Team code is required"}), 400
        
    team = Team.query.filter_by(join_code=code).first()
    if not team:
        return jsonify({"error": "Invalid team code"}), 404
        
    # Check if already in THIS specific team
    existing = TeamMember.query.filter_by(user_id=session['user_id'], team_id=team.id).first()
    if existing:
        return jsonify({"error": "You are already in this team"}), 400

    # ✅ Enforce the 10-team limit
    team_count = TeamMember.query.filter_by(user_id=session['user_id']).count()
    if team_count >= MAX_TEAMS_PER_USER:
        return jsonify({"error": "You can only be in a maximum of 10 teams. Please contact admin."}), 403
        
    try:
        new_member = TeamMember(team_id=team.id, user_id=session['user_id'], role='member')
        db.session.add(new_member)
        db.session.commit()
        return jsonify({"status": "success", "message": f"Joined {team.name}!"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# ======================
# ADMIN CONFIG & Routes
# ======================
ADMIN_EMAILS = {
    "kumarajay69206@gmail.com",
    "kumar.ajaysah2003@gmail.com",
}

def _is_admin(user) -> bool:
    return bool(user and user.email and user.email.lower() in ADMIN_EMAILS)

@app.route('/api/superadmin/teams/<int:team_id>', methods=['GET'])
def superadmin_get_team(team_id):
    if 'user_id' not in session or not session.get('super_admin_access'):
        return jsonify({"error": "Super Admin Access Required"}), 403

    team = Team.query.get(team_id)
    if not team:
        return jsonify({"error": "Team not found"}), 404

    members_data = []
    for m in team.members:
        u = User.query.get(m.user_id)
        members_data.append({
            "user_id": u.id,
            "name": u.name,
            "email": u.email,
            "role": m.role
        })

    return jsonify({
        "status": "success",
        "team": {
            "id": team.id,
            "name": team.name,
            "join_code": team.join_code,
            "members": members_data
        }
    }), 200

@app.route('/api/admin/users', methods=['GET'])
def admin_list_users():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    current = User.query.get(session['user_id'])
    if not _is_admin(current):
        return jsonify({"status": "error", "message": "Forbidden"}), 403

    now = now_ist_naive()
    ONLINE_WINDOW = timedelta(minutes=15)

    def _derive(u):
        if not u.last_seen:
            return ("never", "Not active yet")
        if u.is_signed_in is False and u.last_status_change:
            change_delta = now - u.last_status_change
            if change_delta <= ONLINE_WINDOW:
                return ("signed_out", f"Signed out · {_humanize(change_delta)} ago")
        delta = now - u.last_seen
        if delta <= ONLINE_WINDOW:
            return ("online", "Signed in · Active now")
        return ("offline", f"Last seen {_humanize(delta)} ago")

    users = User.query.order_by(User.id.asc()).all()
    out = []
    for u in users:
        state, label = _derive(u)

        # Calculate age
        created_delta = now - (u.created_at or now)
        if created_delta.days > 0:
            created_label = f"{created_delta.days}d ago"
        elif created_delta.seconds > 3600:
            created_label = f"{created_delta.seconds // 3600}h ago"
        else:
            created_label = f"{created_delta.seconds // 60}m ago"

        out.append({
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "target_steps": u.target_steps or 5000,
            "is_signed_in": u.is_signed_in,
            "last_status_change": u.last_status_change.isoformat() if u.last_status_change else None,
            "last_seen": u.last_seen.isoformat() if u.last_seen else None,
            "state": state,
            "label": label,
            "created_at_label": created_label  # 👈 ADD THIS
        })

    return jsonify({"status": "success", 
                    "server_now": now.isoformat() + "+05:30", 
                    "users": out}), 200

"""@app.route('/api/admin/users/<int:user_id>/history', methods=['GET'])
def admin_user_history(user_id):
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    current = User.query.get(session['user_id'])
    if not _is_admin(current):
        return jsonify({"status": "error", "message": "Forbidden"}), 403

    target_user = User.query.get(user_id)
    if not target_user:
        return jsonify({"status": "error", "message": "User not found"}), 404

    now = now_ist_naive()             # ← IST (naive)
    ONLINE_WINDOW = timedelta(minutes=15)

    if not target_user.last_seen:
        status_state = "never"
        status_label = "Not active yet"
    else:
        delta = now - target_user.last_seen
        if delta <= ONLINE_WINDOW:
            status_state = "online"
            status_label = "Signed in · Active now"
        else:
            status_state = "offline"
            status_label = f"Last seen {_humanize(delta)} ago"

    if target_user.is_signed_in is False and target_user.last_status_change:
        if (now - target_user.last_status_change) <= ONLINE_WINDOW:
            status_state = "offline"
            status_label = f"Signed out · {_humanize(now - target_user.last_status_change)} ago"

    today = datetime.now(IST).date()
    existing_logs = StepLog.query.filter_by(user_id=target_user.id).all()
    logs_dict = {l.date: l for l in existing_logs}
    all_dates = sorted(logs_dict.keys(), reverse=True)

    history_data = []
    total_walking = 0
    total_treadmill = 0

    for target_date in all_dates:
        row = logs_dict[target_date]
        w = row.walking_steps or 0
        t = row.treadmill_steps or 0
        total_walking += w
        total_treadmill += t
        history_data.append({
            "date": target_date.strftime('%d %b'),
            "date_iso": target_date.isoformat(),
            "date_full": target_date.strftime('%d %b %Y'),
            "year": target_date.year,
            "steps": w + t,
            "walking_steps": w,
            "treadmill_steps": t,
            "target_steps": (
                target_user.target_steps
                if target_date == today
                else (row.target_steps or 5000)
            ),
        })

    combined = total_walking + total_treadmill

    summary = {
        "walking_steps":   format_metric(total_walking),
        "treadmill_steps": format_metric(total_treadmill),
        "walking_km":      format_metric(round(total_walking   * 0.000762, 2)),
        "walking_cal":     format_metric(round(total_walking   * 0.04)),
        "treadmill_km":    format_metric(round(total_treadmill * 0.000762, 2)),
        "treadmill_cal":   format_metric(round(total_treadmill * 0.0575)),
        "combined_steps":  format_metric(combined),
        "combined_km":     format_metric(round(combined * 0.000762, 2)),
        "combined_cal":    format_metric(
            round(total_walking * 0.04) + round(total_treadmill * 0.0575)
        ),
        "days_tracked":    len(all_dates),
    }

    return jsonify({
        "status": "success",
        "server_now": now.isoformat() + "+05:30", # <--- ADD THIS
        "user": {
            "id": target_user.id,
            "name": target_user.name,
            "email": target_user.email,
            # ✅ Match the list endpoint:
            "last_seen": target_user.last_seen.isoformat() if target_user.last_seen else None,
            "last_status_change": target_user.last_status_change.isoformat() if target_user.last_status_change else None,
            "is_signed_in": bool(target_user.is_signed_in),
            "target_steps": target_user.target_steps or 5000,
            "status_state": status_state,
            "status_label": status_label,
        },
        "history": history_data,
        "summary": summary,
    }), 200"""

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
def admin_delete_user(user_id):
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    current = User.query.get(session['user_id'])
    if not _is_admin(current):
        return jsonify({"status": "error", "message": "Forbidden"}), 403

    target = User.query.get(user_id)
    if not target:
        return jsonify({"status": "error", "message": "User not found"}), 404

    # Guard: don't let an admin delete themselves
    if target.id == current.id:
        return jsonify({"status": "error", "message": "You cannot delete your own account"}), 400

    # Guard: don't allow deleting another admin
    if _is_admin(target):
        return jsonify({"status": "error", "message": "Cannot delete another admin"}), 400

    try:
        # Cascade: push tokens, step logs, sync events, todos
        PushToken.query.filter_by(user_id=target.id).delete()
        StepLog.query.filter_by(user_id=target.id).delete()
        StepSyncEvent.query.filter_by(user_id=target.id).delete()
        Todo.query.filter_by(user_id=target.id).delete()
        db.session.delete(target)
        db.session.commit()
        return jsonify({"status": "success", "message": f"User #{user_id} deleted"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"❌ Delete user failed: {e}")
        return jsonify({"status": "error", "message": "Delete failed"}), 500

# ======================
# API ENDPOINTS
# ======================

# This route returns the current day's step data and allows the front-end to specify which step mode (walking or treadmill) to display.
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

@app.route('/api/steps/native-token', methods=['GET'])
def get_native_sync_token():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    token = sync_token_serializer.dumps({"user_id": session['user_id']})
    return jsonify({"status": "success", "token": token}), 200

@app.route('/api/steps/sync/native', methods=['POST'])
def sync_steps_native():
    """
    Called by react-native-step-tracker-pro's WorkManager job.
    Auth: Authorization: Bearer <sync_token> header.
    Payload: {source, sentAt, records: [{date, steps, distance, calories}]}
    Idempotent: Idempotency-Key header from the plugin.
    """
    # 1. Authenticate via Authorization header
    auth = request.headers.get('Authorization', '')

    print(f"🚨 NATIVE SYNC: auth_header='{auth[:30]}...' len={len(auth)}")

    # ✅ ADD THIS LINE
    print(f"🚨 RAW BODY: {request.get_data(as_text=True)}")
    
    if not auth.startswith('Bearer '):
        return jsonify({"error": "Missing or invalid Authorization header"}), 401

    token = auth[7:].strip()
    try:
        payload = sync_token_serializer.loads(token, max_age=180 * 24 * 60 * 60)
        user_id = int(payload['user_id'])
    except (BadSignature, KeyError, TypeError, ValueError):
        return jsonify({"error": "Invalid or expired token"}), 401

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    # 2. Parse the plugin's payload
    body = request.get_json(silent=True) or {}
    records = body.get('records', [])
    if not isinstance(records, list):
        return jsonify({"error": "Invalid payload"}), 400

    idempotency_key = request.headers.get('Idempotency-Key', '')

    # 3. Process each day (cumulative totals — replace, not add)
    applied = 0
    for rec in records:
        try:
            date_str = rec.get('date')
            native_total = int(rec.get('steps', 0))

            if not date_str:
                continue

            try:
                rec_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                continue

            if native_total <= 0:
                continue

            log = StepLog.query.filter_by(user_id=user_id, date=rec_date).first()

            # The plugin sends CUMULATIVE daily totals, not deltas.
            # So we SET (not add) the value, and attribute it all to walking
            # (the plugin doesn't split walking/treadmill).
            if log:
                # Only update if native is HIGHER than what we have —
                # this handles the case where JS path already recorded some steps
                existing_total = (log.walking_steps or 0) + (log.treadmill_steps or 0)
                if native_total > existing_total:
                    # Add the delta to walking
                    log.walking_steps = (log.walking_steps or 0) + (native_total - existing_total)
                    log.target_steps = user.target_steps
                    applied += native_total - existing_total
            else:
                log = StepLog(
                    user_id=user_id,
                    walking_steps=native_total,
                    treadmill_steps=0,
                    date=rec_date,
                    target_steps=user.target_steps,
                )
                db.session.add(log)
                applied += native_total

        except Exception as e:
            print(f"native sync record error: {e}")
            continue

    db.session.commit()
    return jsonify({"status": "success", "applied_steps": applied}), 200

# NEW: This route allows the mobile app to sync step data for the current day, with separate handling for walking and treadmill steps. It checks if the user is authenticated, retrieves the step delta and mode from the request, and updates or creates a StepLog entry for today. It also includes a cleanup mechanism to delete logs older than 15 days.
@app.route('/api/steps/sync', methods=['POST'])
def sync_steps():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    step_delta = data.get('delta', data.get('steps', 0))
    mode = data.get('mode', 'walking')
    event_id = data.get('event_id')

    if not event_id or not isinstance(event_id, str) or not event_id.strip():
        return jsonify({"error": "event_id is required"}), 400
    if not isinstance(step_delta, int) or isinstance(step_delta, bool) or step_delta <= 0:
        return jsonify({"error": "delta must be a positive integer"}), 400
    if mode not in ('walking', 'treadmill'):
        return jsonify({"error": "mode must be walking or treadmill"}), 400

    user_id = session['user_id']
    user = User.query.get(user_id)
    if user is None:
        return jsonify({"error": "Unauthorized"}), 401

    # Retries must be safe: the client keeps an event until it receives a
    # successful response, so a timed-out request can arrive more than once.
    existing_event = StepSyncEvent.query.filter_by(
        event_id=event_id,
        user_id=user_id
    ).first() if event_id else None
    if existing_event:
        log = StepLog.query.filter_by(
            user_id=user_id,
            date=datetime.now(IST).date()
        ).first()
        return jsonify({
            "status": "success",
            "duplicate": True,
            "walking_steps": log.walking_steps if log else 0,
            "treadmill_steps": log.treadmill_steps if log else 0
        }), 200
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
            log.treadmill_steps = (log.treadmill_steps or 0) + step_delta
        else:
            log.walking_steps = (log.walking_steps or 0) + step_delta
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

    if event_id:
        db.session.add(StepSyncEvent(event_id=event_id, user_id=user_id))

    db.session.commit()
    return jsonify({
        "status": "success",
        "walking_steps": log.walking_steps,
        "treadmill_steps": log.treadmill_steps
    }), 200


# NEW:📊 UPDATED Dynamically calculates and returns exactly 15 sequential days with combined step totals
# 📊 FIXED: Dynamically calculates and returns 30 sequential days with fully separated mode tracking data
"""@app.route('/api/steps/performance', methods=['GET'])
def get_performance():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user = User.query.get(session['user_id'])
    today = datetime.now(IST).date()
    existing_logs = StepLog.query.filter_by(user_id=user.id).all()
    logs_dict = {l.date: l for l in existing_logs}

    # ✅ NEW: Fetch all distinct dates from DB, sorted descending
    all_dates = sorted(logs_dict.keys(), reverse=True)
    
    history_data = []
    for target_date in all_dates:
        db_row = logs_dict[target_date]
        w_steps = db_row.walking_steps if db_row.walking_steps is not None else 0
        t_steps = db_row.treadmill_steps if db_row.treadmill_steps is not None else 0
        total_steps = w_steps + t_steps
        current_target = user.target_steps if target_date == today else (db_row.target_steps or 5000)
        
        history_data.append({
            "date": target_date.strftime('%d %b'),
            "steps": total_steps,
            "walking_steps": w_steps,
            "treadmill_steps": t_steps,
            "target_steps": current_target
        })

    return jsonify({"status": "success", "history": history_data}), 200"""

@app.route('/api/steps/performance', methods=['GET'])
def get_performance():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user = User.query.get(session['user_id'])
    today = datetime.now(IST).date()
    existing_logs = StepLog.query.filter_by(user_id=user.id).all()
    logs_dict = {l.date: l for l in existing_logs}

    all_dates = sorted(logs_dict.keys(), reverse=True)

    history_data = []
    total_walking = 0
    total_treadmill = 0

    for target_date in all_dates:
        db_row = logs_dict[target_date]
        w_steps = db_row.walking_steps or 0
        t_steps = db_row.treadmill_steps or 0

        total_walking += w_steps
        total_treadmill += t_steps

        total_steps = w_steps + t_steps
        current_target = user.target_steps if target_date == today else (db_row.target_steps or 5000)

        history_data.append({
            "date": target_date.strftime('%d %b'),
            "date_iso": target_date.isoformat(),            # "2024-11-02"
            "date_full": target_date.strftime('%d %b %Y'),  # "02 Nov 2024"
            "year": target_date.year,
            "steps": total_steps,
            "walking_steps": w_steps,
            "treadmill_steps": t_steps,
            "target_steps": current_target,
        })

    combined = total_walking + total_treadmill

    # ✅ Pre-formatted lifetime summary for the History header card
    # Replace the summary block with:
    summary = {
        "walking_steps":   format_metric(total_walking),
        "treadmill_steps": format_metric(total_treadmill),
        "walking_km":      format_metric(round(total_walking   * 0.000762, 2)),
        "walking_cal":     format_metric(round(total_walking   * 0.04)),
        "treadmill_km":    format_metric(round(total_treadmill * 0.000762, 2)),
        "treadmill_cal":   format_metric(round(total_treadmill * 0.0575)),
        "combined_steps":  format_metric(combined),
        "combined_km":     format_metric(round(combined * 0.000762, 2)),
        "combined_cal":    format_metric(round(total_walking * 0.04) + round(total_treadmill * 0.0575)),
        "days_tracked":    len(all_dates),
    }

    return jsonify({
        "status": "success",
        "history": history_data,
        "summary": summary,
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

# ======================
# PUSH NOTIFICATION REGISTRATION
# ======================
@app.route('/api/push-token', methods=['POST'])
def register_push_token():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    token = data.get('token', '').strip()
    platform = data.get('platform', 'android')

    if not token:
        return jsonify({"status": "error", "message": "Token is required"}), 400

    if len(token) > 200:
        return jsonify({"status": "error", "message": "Token too long"}), 400

    try:
        user_id = session['user_id']
        
        # ✅ FIX: Delete ALL old tokens for this user before adding the new one
        PushToken.query.filter_by(user_id=user_id).delete()
        
        # Add the brand new token
        db.session.add(PushToken(
            user_id=user_id,
            token=token,
            platform=platform,
        ))
        
        db.session.commit()
        return jsonify({"status": "success", "message": "Token registered"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"❌ Push token registration failed: {e}")
        return jsonify({"status": "error", "message": "Registration failed"}), 500

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
    print("Attempting to open the FitWisely Dashboard application. If installed, you will be redirected shortly.")
    return redirect("taskcaremobile://dashboard")

# ======================
# AUTH API ENDPOINTS
# ======================

from flask import render_template  # Make sure this is at the top of your file

@app.route('/', methods=['GET'])
def default():
    # Renders the beautiful HTML page instead of raw JSON
    return render_template('index.html')

# ============================================
# ✅ EMAIL VALIDATION FUNCTION
# ============================================

import re
from email_validator import validate_email, EmailNotValidError

# List of disposable email domains
DISPOSABLE_DOMAINS = {
    'tempmail.com', '10minutemail.com', 'throwaway.com', 'guerrillamail.com',
    'mailinator.com', 'yopmail.com', 'getnada.com', 'temp-mail.org',
    'mailnator.com', 'trashmail.com', 'spambox.us', 'spamgourmet.com',
    'mailexpire.com', 'spambox.fr', 'spambox.info', 'spambox.me',
    'spambox.xyz', 'tempmail.net', 'tempinbox.com'
}

# Role-based emails to reject
ROLE_EMAILS = {
    'admin', 'support', 'info', 'contact', 'noreply', 'no-reply',
    'help', 'sales', 'marketing', 'webmaster', 'postmaster'
}

def validate_email_address(email, check_disposable=True, check_role=True):
    """
    Clean email validation checking syntax, account roles, disposable domains, and DNS/MX deliverability.

    Returns:
        tuple: (is_valid, message, normalized_email)
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

    # 3. CHECK ROLE-BASED EMAILS
    if check_role and local_part in ROLE_EMAILS:
        return False, "Please use a personal email address instead of a role-based one (admin@, info@, etc.)", None

    # 4. CHECK DISPOSABLE EMAILS
    if check_disposable and domain in DISPOSABLE_DOMAINS:
        return False, "Disposable/temporary email addresses are not allowed. Please use a permanent email.", None

    # 5. COMPREHENSIVE EMAIL-VALIDATOR CHECK (Handles MX and deliverability checks internally)
    try:
        valid = validate_email(email, check_deliverability=True)
        return True, "Email is valid", valid.normalized

    except EmailNotValidError as e:
        error_msg = str(e)

        # User-friendly error messages
        if "domain does not exist" in error_msg.lower() or "no mx record" in error_msg.lower():
            return False, f"The domain '{domain}' does not exist or cannot receive emails. Please check for typos.", None
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
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    confirm_email = data.get('cemail', '').strip().lower()
    password = data.get('password')

    # 1. Basic field checks
    if not name:
        return jsonify({"status": "error", "message": "Full name is required"}), 400
    if len(name) < 2:
        return jsonify({"status": "error", "message": "Name must be at least 2 characters long"}), 400
    if not email:
        return jsonify({"status": "error", "message": "Email is required"}), 400
    if not confirm_email:
        return jsonify({"status": "error", "message": "Please confirm your email"}), 400
    if email != confirm_email:
        return jsonify({"status": "error", "message": "Emails do not match"}), 400
    if not password:
        return jsonify({"status": "error", "message": "Password is required"}), 400
    if len(password) < 6:
        return jsonify({"status": "error", "message": "Password must be at least 6 characters long"}), 400

    common_passwords = {'password', '12345678', 'qwerty123', 'admin123', 'password123'}
    if password in common_passwords:
        return jsonify({"status": "error", "message": "Password is too common. Please choose a stronger password"}), 400

    # 2. Email validation
    is_valid, error_msg, normalized_email = validate_email_address(email)
    if not is_valid:
        return jsonify({
            "status": "error",
            "message": error_msg,
            "code": "INVALID_EMAIL"
        }), 400
    email = normalized_email

    # 3. Check if user exists
    if User.query.filter_by(email=email).first():
        return jsonify({
            "status": "error",
            "message": "This email is already registered. Please login or use a different email.",
            "code": "EMAIL_EXISTS"
        }), 400

    # 4. Create user
    try:
        new_user = User(
            name=name,
            email=email,
            password=generate_password_hash(password)
        )
        db.session.add(new_user)
        db.session.commit()

        # ── Fire-and-forget registration emails (non-blocking) ──
        total_users = User.query.count()
        threading.Thread(
            target=send_registration_emails,
            args=(new_user.name, new_user.email, new_user.id, total_users),
            daemon=True,
        ).start()

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
    
# ======================
# 📧 REGISTRATION EMAIL HELPERS
# ======================

def build_welcome_email_html(user_name: str, user_email: str) -> str:
    """Professional welcome email HTML for new users."""
    app_url = "https://TaskCare360.pythonanywhere.com/open-app"

    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                max-width: 600px; margin: 0 auto; padding: 24px; color: #1a1a2e;">
        
        <!-- Header -->
        <div style="background: linear-gradient(135deg, #4ecca3 0%, #2d9970 100%);
                    padding: 32px 24px; border-radius: 20px 20px 0 0; text-align: center;">
            <div style="font-size: 48px; line-height: 1; margin-bottom: 8px;">🎯</div>
            <h1 style="color: #ffffff; font-size: 26px; font-weight: 800;
                       margin: 0; letter-spacing: 0.5px;">
                Welcome to FitWisely!
            </h1>
            <p style="color: #e8fff5; font-size: 14px; margin: 8px 0 0 0; font-weight: 500;">
                Your health & productivity journey starts now 🚀
            </p>
        </div>

        <!-- Body -->
        <div style="background-color: #ffffff; padding: 32px 24px;
                    border: 1px solid #e2e8f0; border-top: none;">
            
            <h2 style="color: #0f172a; font-size: 20px; font-weight: 800;
                       margin: 0 0 8px 0;">
                Hi {user_name} 👋
            </h2>
            <p style="color: #475569; font-size: 15px; line-height: 1.6;
                      margin: 0 0 24px 0;">
                Thanks for joining <strong>FitWisely</strong>! You've just unlocked a smarter way
                to track your fitness, stay productive, and hit your daily goals.
            </p>

            <!-- Feature list -->
            <div style="background-color: #f8fafc; border-radius: 16px;
                        padding: 20px; margin-bottom: 24px;
                        border: 1px solid #e2e8f0;">
                <h3 style="color: #0f172a; font-size: 15px; font-weight: 800;
                           margin: 0 0 14px 0; letter-spacing: 0.3px;">
                    ✨ Here's what you can do:
                </h3>
                
                <table style="width: 100%; border-collapse: collapse;" cellpadding="0" cellspacing="0">
                    <tr>
                        <td style="width: 40px; vertical-align: top; padding: 8px 0;">
                            <span style="font-size: 22px;">👟</span>
                        </td>
                        <td style="padding: 8px 0;">
                            <strong style="color: #0f172a; font-size: 14px;">Track Every Step</strong>
                            <div style="color: #64748b; font-size: 13px; margin-top: 2px;">
                                Auto-count walking & treadmill activity in real time.
                            </div>
                        </td>
                    </tr>
                    <tr>
                        <td style="width: 40px; vertical-align: top; padding: 8px 0;">
                            <span style="font-size: 22px;">📝</span>
                        </td>
                        <td style="padding: 8px 0;">
                            <strong style="color: #0f172a; font-size: 14px;">Manage Daily Tasks</strong>
                            <div style="color: #64748b; font-size: 13px; margin-top: 2px;">
                                Organize, complete and celebrate your wins.
                            </div>
                        </td>
                    </tr>
                    <tr>
                        <td style="width: 40px; vertical-align: top; padding: 8px 0;">
                            <span style="font-size: 22px;">🎯</span>
                        </td>
                        <td style="padding: 8px 0;">
                            <strong style="color: #0f172a; font-size: 14px;">Hit Your Goals</strong>
                            <div style="color: #64748b; font-size: 13px; margin-top: 2px;">
                                Set step targets and get progress reminders.
                            </div>
                        </td>
                    </tr>
                    <tr>
                        <td style="width: 40px; vertical-align: top; padding: 8px 0;">
                            <span style="font-size: 22px;">📊</span>
                        </td>
                        <td style="padding: 8px 0;">
                            <strong style="color: #0f172a; font-size: 14px;">See Your Progress</strong>
                            <div style="color: #64748b; font-size: 13px; margin-top: 2px;">
                                Beautiful history views, distance, calories & more.
                            </div>
                        </td>
                    </tr>
                </table>
            </div>

            <!-- Getting started -->
            <div style="border-left: 4px solid #4ecca3; padding: 4px 0 4px 14px;
                        margin-bottom: 28px;">
                <p style="color: #0f172a; font-size: 14px; font-weight: 700;
                          margin: 0 0 4px 0;">
                    ⚡ Quick start
                </p>
                <p style="color: #475569; font-size: 13px; line-height: 1.6; margin: 0;">
                    1. Install the FitWisely mobile app<br/>
                    2. Log in with your email: <strong>{user_email}</strong><br/>
                    3. Grant step-tracking permissions<br/>
                    4. Hit your first daily goal! 🎉
                </p>
            </div>

            <!-- CTA Button -->
            <div style="text-align: center; margin: 32px 0 20px 0;">
                <a href="{app_url}"
                   style="background-color: #4ecca3; color: #0f172a;
                          padding: 16px 44px; text-decoration: none;
                          border-radius: 12px; font-size: 16px; font-weight: 800;
                          display: inline-block; letter-spacing: 0.4px;
                          box-shadow: 0 6px 20px rgba(78, 204, 163, 0.35);">
                    Open FitWisely →
                </a>
            </div>

            <p style="color: #94a3b8; font-size: 12px; text-align: center;
                      margin: 16px 0 0 0;">
                ⏱️ Takes less than 2 minutes to get started.
            </p>
        </div>

        <!-- Footer -->
        <div style="background-color: #0f172a; padding: 24px;
                    border-radius: 0 0 20px 20px; text-align: center;">
            <p style="color: #94a3b8; font-size: 13px; margin: 0 0 8px 0;">
                Need help? We're here for you.
            </p>
            <p style="color: #64748b; font-size: 11px; margin: 0;">
                Reply to this email or reach us at
                <a href="mailto:info.fitwisely@gmail.com"
                   style="color: #4ecca3; text-decoration: none;">info.fitwisely@gmail.com</a>
            </p>
            <hr style="border: none; border-top: 1px solid #1e293b;
                       margin: 16px 0;" />
            <p style="color: #64748b; font-size: 10px; margin: 0;
                      line-height: 1.5;">
                FitWisely — Your Health & Productivity Partner 🚀<br/>
                You're receiving this because you signed up for FitWisely.
            </p>
        </div>
    </div>
    """


def build_admin_notification_html(user_name: str, user_email: str,
                                   user_id: int, total_users: int) -> str:
    """Internal notification HTML for admin team."""
    now_ist = datetime.now(IST)
    signup_time = now_ist.strftime("%d %b %Y at %I:%M %p IST")

    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                max-width: 600px; margin: 0 auto; padding: 24px; color: #1a1a2e;">
        
        <!-- Header -->
        <div style="background-color: #1e293b; padding: 24px;
                    border-radius: 20px 20px 0 0; text-align: center;">
            <div style="font-size: 36px; margin-bottom: 6px;">🎉</div>
            <h1 style="color: #ffffff; font-size: 22px; font-weight: 800;
                       margin: 0; letter-spacing: 0.3px;">
                New User Registered!
            </h1>
            <p style="color: #94a3b8; font-size: 13px; margin: 6px 0 0 0;">
                FitWisely · Admin Notification
            </p>
        </div>

        <!-- Body -->
        <div style="background-color: #ffffff; padding: 28px 24px;
                    border: 1px solid #e2e8f0; border-top: none;">
            
            <p style="color: #475569; font-size: 14px; line-height: 1.6;
                      margin: 0 0 20px 0;">
                A new user just joined the platform. Here are the details:
            </p>

            <!-- User details card -->
            <div style="background-color: #f8fafc; border-radius: 16px;
                        padding: 20px; border: 1px solid #e2e8f0;
                        margin-bottom: 20px;">
                <table style="width: 100%; border-collapse: collapse;" cellpadding="0" cellspacing="0">
                    <tr>
                        <td style="padding: 8px 0; color: #64748b; font-size: 13px;
                                   font-weight: 600; width: 130px;">👤 Name</td>
                        <td style="padding: 8px 0; color: #0f172a; font-size: 14px;
                                   font-weight: 700;">{user_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; color: #64748b; font-size: 13px;
                                   font-weight: 600; border-top: 1px solid #e2e8f0;">📧 Email</td>
                        <td style="padding: 8px 0; color: #0f172a; font-size: 14px;
                                   font-weight: 700; border-top: 1px solid #e2e8f0;">{user_email}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; color: #64748b; font-size: 13px;
                                   font-weight: 600; border-top: 1px solid #e2e8f0;">🆔 User ID</td>
                        <td style="padding: 8px 0; color: #0f172a; font-size: 14px;
                                   font-weight: 700; border-top: 1px solid #e2e8f0;">#{user_id}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; color: #64748b; font-size: 13px;
                                   font-weight: 600; border-top: 1px solid #e2e8f0;">🕐 Registered</td>
                        <td style="padding: 8px 0; color: #0f172a; font-size: 14px;
                                   font-weight: 700; border-top: 1px solid #e2e8f0;">{signup_time}</td>
                    </tr>
                </table>
            </div>

            <!-- Stats -->
            <div style="display: inline-block; background-color: #ecfdf5;
                        color: #065f46; padding: 10px 18px; border-radius: 10px;
                        font-size: 13px; font-weight: 700; border: 1px solid #a7f3d0;">
                📈 Total registered users: <strong>{total_users}</strong>
            </div>

            <!-- CTA -->
            <div style="text-align: center; margin: 28px 0 12px 0;">
                <a href="https://TaskCare360.pythonanywhere.com/api/admin/users"
                   style="background-color: #0f172a; color: #ffffff;
                          padding: 14px 32px; text-decoration: none;
                          border-radius: 10px; font-size: 14px; font-weight: 700;
                          display: inline-block; letter-spacing: 0.3px;">
                    View in Admin Panel →
                </a>
            </div>
        </div>

        <!-- Footer -->
        <div style="background-color: #f1f5f9; padding: 18px 24px;
                    border-radius: 0 0 20px 20px; text-align: center;">
            <p style="color: #64748b; font-size: 11px; margin: 0;">
                This is an automated notification from FitWisely.
            </p>
        </div>
    </div>
    """


def send_registration_emails(user_name: str, user_email: str,
                              user_id: int, total_users: int):
    """
    Send welcome email to new user + notification to all admins.
    This is fire-and-forget — failures are logged but not raised.
    """
    sender_email = (os.getenv('EMAIL_USER') or '').replace(' ', '')
    sender_password = (os.getenv('EMAIL_PASS') or '').replace(' ', '')

    if not sender_email or not sender_password:
        print("❌ [registration-email] SMTP credentials missing — skipping")
        return

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465,
                               context=ssl.create_default_context(),
                               timeout=20) as server:
            server.login(sender_email, sender_password)

            # ── 1. Welcome email to USER ──
            try:
                welcome_msg = MIMEMultipart("alternative")
                welcome_msg['From'] = f"FitWisely <{sender_email}>"
                welcome_msg['To'] = user_email
                welcome_msg['Subject'] = f"🎯 Welcome to FitWisely, {user_name}!"
                welcome_msg.attach(
                    MIMEText(build_welcome_email_html(user_name, user_email),
                             'html', 'utf-8')
                )
                server.send_message(welcome_msg)
                print(f"✅ [registration-email] Welcome email sent to {user_email}")
            except Exception as e:
                print(f"❌ [registration-email] Welcome email failed for {user_email}: {e}")

            # ── 2. Admin notification ──
            try:
                admin_html = build_admin_notification_html(
                    user_name, user_email, user_id, total_users
                )
                admin_msg = MIMEMultipart("alternative")
                admin_msg['From'] = f"FitWisely Alerts <{sender_email}>"
                admin_msg['To'] = ", ".join(ADMIN_EMAILS)
                admin_msg['Subject'] = f"🎉 New signup: {user_name} ({user_email})"
                admin_msg.attach(MIMEText(admin_html, 'html', 'utf-8'))
                server.send_message(admin_msg)
                print(f"✅ [registration-email] Admin notification sent to {len(ADMIN_EMAILS)} admins")
            except Exception as e:
                print(f"❌ [registration-email] Admin notification failed: {e}")

    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ [registration-email] SMTP auth failed: {e}")
    except (OSError, ssl.SSLError) as e:
        print(f"❌ [registration-email] SMTP network error: {e}")
    except Exception as e:
        print(f"❌ [registration-email] Unexpected error: {e}")

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    user = User.query.filter_by(email=data.get('email', '').lower()).first()

    if user and check_password_hash(user.password, data.get('password')):
        session.clear() # Clear any old/broken sessions
        session.modified = True           # ← add this BEFORE setting values
        session['user_id'] = user.id
        session['username'] = user.name # Add this so dashboard doesn't show 'None'
        session.permanent = True

        # 👇 ADD THESE LINES
        user.is_signed_in = True
        user.last_status_change = now_ist_naive()   # ← IST
        user.last_seen = now_ist_naive()             # ← IST
        db.session.commit()

        return jsonify({
            "status": "success",
            "user": {"id": user.id, "name": user.name},
            "step_sync_token": sync_token_serializer.dumps({"user_id": user.id}),
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

    all_tasks = Todo.query.filter_by(user_id=user_id, is_deleted=False).order_by(Todo.SNo.desc()).all()

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


# Fetch user profile data
@app.route('/api/profile', methods=['GET'])
def get_profile():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    user = User.query.get(user_id)
    if not user:
        session.clear()
        return jsonify({"status": "error", "message": "User not found"}), 401

    return jsonify({
        "status": "success",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "is_admin": _is_admin(user)        # ← ADD THIS ONE LIN
        }
    }), 200

# Update profile details
@app.route('/api/profile/update', methods=['POST'])
def update_profile():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"status": "error", "message": "Session expired"}), 401

    user = User.query.get(user_id)
    if not user:
        session.clear()
        return jsonify({"status": "error", "message": "User not found"}), 401

    data = request.get_json() or {}
    new_name = data.get('name', '').strip()
    new_email = data.get('email', '').strip().lower()

    if not new_name or not new_email:
        return jsonify({"status": "error", "message": "Name and email are required"}), 400

    # Check if the new email is already taken by another account
    existing_user = User.query.filter(User.email == new_email, User.id != user.id).first()
    if existing_user:
        return jsonify({"status": "error", "message": "Email is already in use"}), 400

    user.name = new_name
    user.email = new_email
    session['username'] = new_name  # Keep session username synced

    db.session.commit()

    return jsonify({
        "status": "success",
        "message": "Profile updated successfully",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "is_admin": _is_admin(user),        # ← ADD THIS
        }
    }), 200

# ======================
# LOGOUT API
# ======================

@app.route('/api/logout', methods=['GET', 'POST'])
def logout():
    # 👇 GET USER BEFORE CLEARING SESSION
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        if user:
            user.is_signed_in = False
            user.last_status_change = now_ist_naive()   # ← IST
            db.session.commit()

    session.clear()
    session.modified = True

    response = jsonify({"status": "success", "message": "Logged out successfully"})
    response.delete_cookie('session', path='/', domain=None, secure=True, httponly=True, samesite='None')
    response.delete_cookie('session', path='/', domain=None, secure=False, httponly=True, samesite='Lax')
    return response, 200

# ======================
# TASK API ENDPOINTS
# ======================

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    todos = Todo.query.filter_by(user_id=session['user_id'], is_deleted=False).order_by(Todo.SNo.desc()).all()

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
        # ✅ CHANGE: Soft delete instead of hard delete
        todo.is_deleted = True
        db.session.commit()
        return jsonify({"status": "success", "message": "Deleted"}), 200
    return jsonify({"error": "Not found"}), 404

# ======================
# FORGOT PASSWORD API
# ======================

import traceback   # add this to your imports

def send_otp(email):
    otp = str(random.randint(100000, 999999))
    sender_email = (os.getenv('EMAIL_USER') or '').replace(' ', '')
    sender_password = (os.getenv('EMAIL_PASS') or '').replace(' ', '')

    # 🔎 Sanity-check that credentials are even loaded
    print("=" * 60)
    print("SMTP DEBUG")
    print(f"  EMAIL_USER set      : {bool(sender_email)}  ({sender_email})")
    print(f"  EMAIL_PASS set      : {bool(sender_password)}  (len={len(sender_password) if sender_password else 0})")
    print(f"  recipient           : {email}")
    print("=" * 60)

    if not sender_email or not sender_password:
        print("❌ SMTP Error: EMAIL_USER or EMAIL_PASS environment variable is missing")
        return None

    msg = EmailMessage()
    msg.set_content(f"Your FitWisely OTP is: {otp}\n\nValid for 3 minutes.")
    msg['Subject'] = "FitWisely: Password Reset OTP"
    msg['From'] = sender_email
    msg['To'] = email

    try:
        context = ssl.create_default_context()
        print("→ Connecting to smtp.gmail.com:465 ...")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=15) as server:
            print("→ Connected. Logging in ...")
            server.login(sender_email, sender_password)
            print("→ Logged in. Sending message ...")
            server.send_message(msg)
            print("→ Message sent.")
        return otp

    # ---- FULL, EXACT ERROR REPORTING ----
    except smtplib.SMTPAuthenticationError as e:
        print("❌ SMTPAuthenticationError (bad username/app password)")
        print(f"   smtp_code  : {e.smtp_code}")
        print(f"   smtp_error : {e.smtp_error!r}")
        traceback.print_exc()
        return None

    except smtplib.SMTPException as e:
        print("❌ SMTPException")
        print(f"   type       : {type(e).__name__}")
        print(f"   smtp_code  : {getattr(e, 'smtp_code', 'n/a')}")
        print(f"   smtp_error : {getattr(e, 'smtp_error', 'n/a')!r}")
        traceback.print_exc()
        return None

    except (OSError, ssl.SSLError) as e:
        print("❌ Network / SSL error")
        print(f"   type       : {type(e).__name__}")
        print(f"   errno      : {getattr(e, 'errno', 'n/a')}")
        print(f"   strerror   : {getattr(e, 'strerror', 'n/a')}")
        traceback.print_exc()
        return None

    except Exception as e:
        print("❌ Unexpected SMTP error")
        print(f"   type       : {type(e).__name__}")
        traceback.print_exc()
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

# In your Flask app, e.g. app.py
from sqlalchemy import func

"""@app.route('/api/public/stats', methods=['GET'])
def public_stats():
    try:
        # 1. Total Users
        total_users = db.session.query(User).count()

        # 2. Total Steps (Walking + Treadmill)
        total_steps = db.session.query(
            func.coalesce(func.sum(StepLog.walking_steps), 0) +
            func.coalesce(func.sum(StepLog.treadmill_steps), 0)
        ).scalar() or 0

        # 3. Tasks Handled (Total tasks created, including deleted/completed)
        tasks_handled = db.session.query(Todo).count()

        return jsonify({
            "status": "success",
            "total_users": int(total_users),
            "total_steps": int(total_steps),
            "tasks_handled": int(tasks_handled),
        }), 200

    except Exception as e:
        print(f"❌ Public stats error: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500
"""

@app.route('/api/public/stats', methods=['GET'])
def public_stats():
    try:
        total_users = db.session.query(User).count()
        total_steps = db.session.query(
            func.coalesce(func.sum(StepLog.walking_steps), 0) +
            func.coalesce(func.sum(StepLog.treadmill_steps), 0)
        ).scalar() or 0
        tasks_handled = db.session.query(Todo).count()

        return jsonify({
            "status": "success",
            # Raw values (unchanged — existing clients keep working)
            "total_users": int(total_users),
            "total_steps": int(total_steps),
            "tasks_handled": int(tasks_handled),
            # ✅ Pre-formatted display strings
            "display": {
                "total_users":   format_compact_number(total_users),
                "total_steps":   format_compact_number(total_steps),
                "tasks_handled": format_compact_number(tasks_handled),
            },
        }), 200
    except Exception as e:
        print(f"❌ Public stats error: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

# ======================
# INITIALIZATION
# ======================
# This function compiles the user's daily fitness stats and pending tasks into a beautifully formatted HTML email, and sends it to their registered email address. It handles both the case where the user has no step data for the day (showing 0 steps) and the case where they have pending tasks (listing them in a table). The email also includes a prominent button that deep-links back into the FitWisely app for maximum engagement.
def send_daily_task_reminders():
    sender_email = (os.getenv('EMAIL_USER') or '').replace(' ', '')
    sender_password = (os.getenv('EMAIL_PASS') or '').replace(' ', '')
    login_url = "https://TaskCare360.pythonanywhere.com/open-app"

    # 📋 Tracking lists for the report
    sent_to = []
    skipped = []
    failed = []

    if not sender_email or not sender_password:
        print("❌ Email credentials missing")
        return {
            "error": "Email credentials missing",
            "total_users": 0,
            "emails_sent": 0,
            "sent_to": sent_to,
            "skipped": skipped,
            "failed": failed,
        }

    try:
        users = User.query.all()
        if not users:
            print("No users found")
            return {
                "error": "No users found",
                "total_users": 0,
                "emails_sent": 0,
                "sent_to": sent_to,
                "skipped": skipped,
                "failed": failed,
            }

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)

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
                    tasks = Todo.query.filter_by(user_id=user.id, is_completed=False, is_deleted=False).order_by(Todo.SNo.desc()).all()
                    
                    # 🛑 TOTAL EMPTY DETECTION:
                    # If they have NO steps AND NO pending tasks, send a friendly nudge email instead of skipping.
                    is_empty_user = (walk_steps == 0 and tread_steps == 0 and not tasks)
                    if is_empty_user:
                        print(f"📨 Nudge email for {user.name} ({user.email}): No steps and no pending tasks.")

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
                                    Open FitWisely
                                </a>
                            </div>
                        </div>
                        """
                    elif is_empty_user:
                        # 👋 CASE 3: User HAS NO steps AND NO tasks -> Friendly nudge email
                        fitness_html = f"""
                        <div style="background-color: #16213e; padding: 28px 24px; border-radius: 22px; border: 1.5px solid rgba(255, 255, 255, 0.12); max-width: 460px; margin: 0 auto 20px auto; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; box-shadow: 0 10px 25px rgba(0,0,0,0.35); color: #ffffff; text-align: center;">
                            <div style="font-size: 42px; margin-bottom: 10px;">👋</div>
                            <h3 style="color: #ffffff; font-size: 19px; font-weight: 800; margin: 0 0 10px 0; letter-spacing: 0.2px;">
                                Hi {user.name}, let's get started today!
                            </h3>
                            <p style="color: #a4b0be; font-size: 14px; line-height: 21px; margin: 0 0 18px 0;">
                                You haven't logged any activity or tasks yet today. Open the app to:
                            </p>
                            <div style="text-align: left; display: inline-block; margin: 0 auto 20px auto;">
                                <p style="color: #ffffff; font-size: 14px; margin: 0 0 10px 0;">
                                    📝 <strong>Add a task</strong> to stay productive
                                </p>
                                <p style="color: #ffffff; font-size: 14px; margin: 0 0 10px 0;">
                                    🚶 <strong>Walk</strong> to save your steps
                                </p>
                                <p style="color: #ffffff; font-size: 14px; margin: 0;">
                                    🎯 <strong>Hit your daily goal</strong> of {(user.target_steps if user.target_steps else 5000):,} steps
                                </p>
                            </div>
                            <div style="text-align: center; margin-top: 10px;">
                                <a href="{login_url}" style="background-color: #4ecca3; color: #1a1a2e; padding: 14px 36px; text-decoration: none; border-radius: 12px; font-size: 15px; font-weight: bold; display: inline-block; box-shadow: 0 4px 12px rgba(78, 204, 163, 0.3); letter-spacing: 0.3px;">
                                    Open FitWisely
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
                    if is_empty_user:
                        # Nudge emails already show the CTA card above — no separate task box needed
                        task_content = ""
                    elif not tasks:
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
                            FitWisely — Your health & productivity partner 🚀
                        </p>
                    </div>
                    """

                    # Subject line varies for nudge emails
                    if is_empty_user:
                        subject = f"👋 Let's get started today - {today.strftime('%b %d')}"
                    else:
                        subject = f"📊 Daily Progress - {today.strftime('%b %d')}"

                    # Send email out to active user mailbox
                    msg = MIMEMultipart("alternative")
                    msg['From'] = sender_email
                    msg['To'] = user.email
                    msg['Subject'] = subject
                    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

                    server.send_message(msg)
                    sent_to.append({
                        "email": user.email,
                        "name": user.name,
                        "type": "nudge" if is_empty_user else "report",
                    })
                    print(f"✅ Email sent to {user.email} ({'nudge' if is_empty_user else 'report'})")

                except Exception as e:
                    print(f"❌ Failed to send to {user.email}: {str(e)}")
                    failed.append({"email": user.email, "error": str(e)})
                    continue

            print(
                f"📧 Done — sent: {len(sent_to)} | skipped: {len(skipped)} "
                f"| failed: {len(failed)} | total users: {len(users)}"
            )
            return {
                "error": None,
                "total_users": len(users),
                "emails_sent": len(sent_to),
                "sent_to": sent_to,
                "skipped": skipped,
                "failed": failed,
            }

    except Exception as e:
        print(f"❌ Fatal error in send_daily_task_reminders: {str(e)}")
        return {
            "error": str(e),
            "total_users": 0,
            "emails_sent": 0,
            "sent_to": sent_to,
            "skipped": skipped,
            "failed": failed,
        }
    
# 🧪 TEMPORARY TEST ROUTE: Trigger emails instantly via browser
@app.route('/api/send-daily-email')
def send_daily_email():
    print("🚀 Manual trigger: Executing email sequence...")
    try:
        result = send_daily_task_reminders()

        # If the function itself reported a hard failure (creds missing / fatal error)
        if result.get("error"):
            return jsonify({
                "status": "error",
                "message": result["error"],
                "summary": result,
            }), 500

        # Otherwise — report full breakdown
        return jsonify({
            "status": "success" if result["emails_sent"] > 0 else "info",
            "message": (
                f"Sent {result['emails_sent']} report(s) out of "
                f"{result['total_users']} user(s)."
            ),
            "summary": {
                "total_users":  result["total_users"],
                "emails_sent":  result["emails_sent"],
                "skipped_count": len(result["skipped"]),
                "failed_count":  len(result["failed"]),
                "sent_to":       result["sent_to"],
                "skipped":       result["skipped"],
                "failed":        result["failed"],
            },
        }), 200

    except Exception as err:
        return jsonify({
            "status": "error",
            "message": f"Direct execution crash: {str(err)}",
        }), 500

# ======================
# PUSH NOTIFICATION SENDER
# ======================
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

def send_expo_push(tokens, title, body, data_payload=None):
    """
    Send a push notification to one or more Expo push tokens.
    Returns True if the request was accepted by Expo.
    """
    if not tokens:
        return False

    if isinstance(tokens, str):
        tokens = [tokens]

    messages = []
    for t in tokens:
        if not t or not t.startswith("ExponentPushToken"):
            continue
        messages.append({
            "to": t,
            "sound": "default",
            "title": title,
            "body": body,
            "data": data_payload or {"screen": "steps"},
            "priority": "high",
            "channelId": "default-v2",
        })

    if not messages:
        return False

    try:
        r = requests.post(
            EXPO_PUSH_URL,
            json=messages,
            headers={
                "Accept": "application/json",
                "Accept-encoding": "gzip, deflate",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        if r.status_code == 200:
            print(f"✅ Push sent to {len(messages)} device(s)")
            return True
        print(f"❌ Expo push error {r.status_code}: {r.text}")
        return False
    except Exception as e:
        print(f"❌ Push send exception: {e}")
        return False


def build_step_message(current, target):
    """Build a clear, professional, and highly engaging message for every 5%."""
    if target <= 0:
        return ("🎯 Daily Step Target", "Target step goal is not set.")

    remaining = max(0, target - current)
    percent = min(100, int((current / target) * 100))

    # ✅ Generate a clean visual progress bar (10 blocks)
    filled_blocks = int(percent / 10)
    bar = "▰" * filled_blocks + "▱" * (10 - filled_blocks)
    progress_line = f"[{bar}] {percent}%"

    # Helper to keep format consistent
    def format_body(action_text):
        return (
            f"{progress_line}\n"
            f"{action_text} You've logged {current:,} steps. "
            f"Only {remaining:,} left to hit your {target:,} target."
        )

    # 1. Starting / Zero steps
    if current == 0 or percent < 1:
        return (
            "📍 Ready to begin",
            f"{progress_line}\n"
            f"Lace up and take your first steps toward a {target:,} target!"
        )

    # 2. 1% - 4%
    if percent < 5:
        return ("🌿 Great start", format_body("Keep the momentum going!"))

    # 3. 5% - 9%
    if percent < 10:
        return ("🐣 First 5% down", format_body("You're building a habit—push forward!"))

    # 4. 10% - 14%
    if percent < 15:
        return ("🚶 Finding your stride", format_body("Maintain this steady pace!"))

    # 5. 15% - 19%
    if percent < 20:
        return ("⚡ Picking up speed", format_body("Accelerate your efforts!"))

    # 6. 20% - 24%
    if percent < 25:
        return ("📈 Gaining ground", format_body("Don't stop now—keep pushing!"))

    # 7. 25% - 29%
    if percent < 30:
        return ("⛅ Quarter mark", format_body("Stay focused and drive forward!"))

    # 8. 30% - 34%
    if percent < 35:
        return ("🔥 Warming up", format_body("Your body is finding its flow!"))

    # 9. 35% - 39%
    if percent < 40:
        return ("🏃 In the zone", format_body("Keep this incredible rhythm!"))

    # 10. 40% - 44%
    if percent < 45:
        return ("💪 Strong progress", format_body("Power through the next stretch!"))

    # 11. 45% - 49%
    if percent < 50:
        return ("🎯 Almost halfway", format_body("Eyes on the prize—dig deep!"))

    # 12. 50% - 54%
    if percent < 55:
        return ("🔆 Halfway there", format_body("You've conquered the peak—finish strong!"))

    # 13. 55% - 59%
    if percent < 60:
        return ("🏅 Over the hump", format_body("Double down on your effort!"))

    # 14. 60% - 64%
    if percent < 65:
        return ("👊 More than half", format_body("Build your endurance—keep moving!"))

    # 15. 65% - 69%
    if percent < 70:
        return ("🚀 Cruising", format_body("Don't look back—drive it home!"))

    # 16. 70% - 74%
    if percent < 75:
        return ("🦅 Soaring high", format_body("Make every single step count!"))

    # 17. 75% - 79%
    if percent < 80:
        return ("🌟 Home stretch", format_body("Push to your absolute limit!"))

    # 18. 80% - 84%
    if percent < 85:
        return ("🔥 On fire", format_body("Visualize the finish line—sprint!"))

    # 19. 85% - 89%
    if percent < 90:
        return ("🥇 Going for gold", format_body("Give it everything you've got!"))

    # 20. 90% - 94%
    if percent < 95:
        return ("⚡ Final countdown", format_body("You're so close—empty the tank!"))

    # 21. 95% - 99%
    if percent < 100:
        return ("🏁 Finish line ahead", format_body("Leave nothing behind—secure the win!"))

    # 22. Goal Achieved / Exceeded (100%+)
    extra = current - target
    exceeded_text = f" (+{extra:,} extra)" if extra > 0 else ""

    return (
        "👑 Goal achieved!",
        f"{progress_line}\n"
        f"Target secured! You hit {current:,} steps today{exceeded_text}, conquering your {target:,} target."
    )

# ======================
# 2-HOUR PUSH SCHEDULER
# ======================
import time # Make sure to add this at the top of your file if it's not there

def send_periodic_step_pushes():
    with app.app_context():
        start_time = time.time() # ⏱️ Start the timer
        now_ist = datetime.now(IST)

        # Only run between 4 AM and 10 PM
        if not (4 <= now_ist.hour <= 22):
            print(f"⏸ Outside active window (hour={now_ist.hour}). No pushes sent.")
            return "Message: Outside active window."

        today = now_ist.date()
        sent_count = 0
        all_messages = [] # Collect all messages here
        email_mapping = {} # ✅ Track which message belongs to which email

        users = User.query.all()
        for user in users:
            token_row = PushToken.query.filter_by(user_id=user.id).first()
            if not token_row or not token_row.token.startswith("ExponentPushToken"):
                continue

            log = StepLog.query.filter_by(user_id=user.id, date=today).first()
            current = 0
            if log:
                current = (log.walking_steps or 0) + (log.treadmill_steps or 0)

            target = user.target_steps or 5000
            title, body = build_step_message(current, target)
            
            # ✅ Get user email (Assuming your User model has an 'email' column)
            user_email = getattr(user, 'email', f"User_ID_{user.id}")

            # ✅ Add to the list
            all_messages.append({
                "to": token_row.token,
                "sound": "default",
                "title": title,
                "body": body,
                "data": {"screen": "steps"},
                "priority": "high",
                "channelId": "default-v2",
            })
            
            # ✅ Map the token to the email so we know who succeeded
            email_mapping[token_row.token] = user_email

        successful_emails = [] # List to store emails of successful sends

        # ✅ Now send them in batches of 100
        if all_messages:
            for i in range(0, len(all_messages), 100):
                batch = all_messages[i:i + 100]
                try:
                    r = requests.post(
                        EXPO_PUSH_URL,
                        json=batch,
                        headers={"Accept": "application/json", "Content-Type": "application/json"},
                        timeout=10,
                    )
                    if r.status_code == 200:
                        sent_count += len(batch)
                        # ✅ If the batch succeeds, add all those emails to the success list
                        for msg in batch:
                            token = msg["to"]
                            if token in email_mapping:
                                successful_emails.append(email_mapping[token])
                    else:
                        print(f"❌ Expo push error {r.status_code}: {r.text}")
                except Exception as e:
                    print(f"❌ Push send exception: {e}")

        # ⏱️ Calculate total time taken
        end_time = time.time()
        time_taken = round(end_time - start_time, 2)
        
        # ✅ Prepare the final response
        response_message = f"Sent {sent_count} reminders at {now_ist.strftime('%Y-%m-%d %H:%M')} in {time_taken} seconds."
        
        if successful_emails:
            # Join emails with commas. (If you have 100s of users, this might make the cron-job.org response very long)
            response_message += f" | Emails: {', '.join(successful_emails)}"
        else:
            response_message += " | No emails sent."

        print(f"📲 {response_message}")
        return response_message

@app.route('/api/send-step-push/<secret>')
def send_step_push_now(secret):
    expected = app.config.get('SCHEDULER_SECRET') or ''

    # ✅ Safe debug logging
    print("🔐 Auth check:")
    print(f"   provided = '{secret[:10]}...' (len={len(secret)})")
    print(f"   expected = '{expected[:10]}...' (len={len(expected)})")
    print(f"   match    = {secret == expected}")

    if not expected or secret != expected:
        print(f"❌ Unauthorized attempt from {request.remote_addr}")
        abort(403)

    print("🚀 Manual trigger: sending step pushes...")
    try:
        sent_notifications = send_periodic_step_pushes()
        return jsonify({
            "status": "success",
            "message": sent_notifications
        }), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ Manual push trigger failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def initialize_database():
    with app.app_context():
        # Create newly added tables when the WSGI app starts in production.
        db.create_all()
        print("✅ Database initialized successfully")


# PythonAnywhere loads this module through WSGI instead of __main__.
# Run the idempotent table creation there as well so new sync tables exist
# before the first mobile synchronization request.
initialize_database()

if __name__ == '__main__':
    # 0.0.0.0 is critical for the Android emulator to find your laptop
    debug_mode = os.getenv('DEBUG', 'False').lower() == 'true'

    app.run(host='0.0.0.0', port=5000, debug=debug_mode)