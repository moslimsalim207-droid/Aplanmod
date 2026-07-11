import hashlib
import secrets
import string
from datetime import datetime, date
from flask import session, redirect, url_for, flash
from functools import wraps
from database import get_db

def hash_password(password: str) -> str:
    """Hash password with salt"""
    salt = 'dawahi_fixed_salt_v1'
    return hashlib.sha256((salt + password).encode('utf-8')).hexdigest()

def verify_password(stored_hash: str, password: str) -> bool:
    """Verify password against stored hash"""
    return stored_hash == hash_password(password)

def gen_ref_code() -> str:
    """Generate unique reference code"""
    return 'DWH-' + ''.join(
        secrets.choice(string.digits + string.ascii_uppercase)
        for _ in range(8)
    )

def login_required(view):
    """Decorator to require login"""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped

def current_user():
    """Get current user from database"""
    uid = session.get('user_id')
    if not uid:
        return None
    db = get_db()
    return db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()

def validate_signup_input(username, email, phone, country, password1, password2, 
                         passport_issue, passport_expiry):
    """Validate signup form input"""
    from constants import COUNTRIES, TRANSLATIONS
    errors = []
    
    # Username validation
    if not username or len(username) < 3:
        errors.append(TRANSLATIONS['username_short']['ar'])
    
    # Email validation
    if not email or '@' not in email:
        errors.append(TRANSLATIONS['invalid_email']['ar'])
    else:
        db = get_db()
        if db.execute('SELECT id FROM users WHERE email=?', (email.lower(),)).fetchone():
            errors.append(TRANSLATIONS['email_exists']['ar'])
    
    # Phone validation
    if not phone or len(phone) < 8:
        errors.append(TRANSLATIONS['invalid_phone']['ar'])
    
    # Country validation
    if not country or country not in COUNTRIES:
        errors.append(TRANSLATIONS['error_generic']['ar'])
    
    # Password validation
    if not password1 or len(password1) < 6:
        errors.append(TRANSLATIONS['password_short']['ar'])
    
    if password1 != password2:
        errors.append(TRANSLATIONS['passwords_mismatch']['ar'])
    
    # Passport dates validation
    if not passport_issue or not passport_expiry:
        errors.append(TRANSLATIONS['passport_required']['ar'])
    else:
        try:
            issue_dt = date.fromisoformat(passport_issue)
            expiry_dt = date.fromisoformat(passport_expiry)
            
            if expiry_dt < date.today():
                errors.append(TRANSLATIONS['passport_expired']['ar'])
            
            if issue_dt > expiry_dt:
                errors.append(TRANSLATIONS['passport_invalid_dates']['ar'])
        except ValueError:
            errors.append(TRANSLATIONS['invalid_date_format']['ar'])
    
    return errors

def allowed_file(filename: str) -> bool:
    """Check if file is allowed"""
    from config import Config
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS
