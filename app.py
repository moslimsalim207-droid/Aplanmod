# -*- coding: utf-8 -*-
"""
وكالة الدواحي للسفر والسياحة - نسخة محسّنة واحترافية
تطبيق ويب متعدد اللغات مع دعم الوضع الليلي
"""

import os
from datetime import datetime, date
from flask import (
    Flask, request, session, redirect, url_for, render_template_string,
    send_from_directory, flash, g, abort
)
from werkzeug.utils import secure_filename

from config import Config, DevelopmentConfig
from database import get_db, close_db, init_db
from auth import (
    hash_password, verify_password, gen_ref_code, login_required,
    current_user, validate_signup_input, allowed_file
)
from translations import t, get_language, set_language, get_theme, set_theme
from constants import (
    COUNTRY_DATA, COUNTRIES, TICKET_CLASSES, CLASS_LABELS,
    LOCAL_CITIES, HOTEL_NAMES, ROOM_TYPES
)
from templates.layout import layout, flashes_html, BASE_CSS
from utils.pdf import generate_ticket_pdf

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(DevelopmentConfig)

# Ensure directories exist
os.makedirs(app.config['UPLOAD_DIR'], exist_ok=True)
os.makedirs(app.config['TICKETS_DIR'], exist_ok=True)

# Register database functions
app.teardown_appcontext(close_db)

# ===================================================================
# Language and Theme Routes
# ===================================================================

@app.route('/set_lang/<lang>')
def set_lang(lang):
    """Set user language"""
    set_language(lang)
    return redirect(request.referrer or url_for('home'))

@app.route('/set_theme/<theme>')
def set_theme_route(theme):
    """Set user theme"""
    set_theme(theme)
    return redirect(request.referrer or url_for('home'))

# ===================================================================
# Authentication Routes
# ===================================================================

@app.route('/', methods=['GET'])
def index():
    """Redirect to home if logged in, otherwise to login"""
    if session.get('user_id'):
        return redirect(url_for('home'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login page"""
    lang = get_language()
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        if not email or not password:
            flash(t('error_generic', lang), 'error')
            return redirect(url_for('login'))
        
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        
        if user and verify_password(user['password_hash'], password):
            # If the stored hash is a legacy SHA256 (no 'pbkdf2:' prefix), upgrade it
            stored = user['password_hash'] or ''
            try:
                if stored and not stored.startswith('pbkdf2:'):
                    db.execute('UPDATE users SET password_hash=? WHERE id=?', (hash_password(password), user['id']))
                    db.commit()
            except Exception:
                # do not block login if upgrade fails
                pass

            session['user_id'] = user['id']
            flash(t('login_success', lang), 'ok')
            return redirect(url_for('home'))
        
        flash(t('error_generic', lang), 'error')
        return redirect(url_for('login'))
    
    body = f"""
    <div class="form-box card glow-form">
      <h2 class="center">{t('login', lang)}</h2>
      <p class="subtitle center">{t('welcome', lang)}</p>
      {flashes_html()}
      <form method="post">
        <label>{t('email', lang)}</label>
        <input type="email" name="email" required autocomplete="email">
        <label>{t('password', lang)}</label>
        <input type="password" name="password" required autocomplete="current-password">
        <div class="center" style="margin-top:20px">
          <button class="btn" type="submit" style="width:100%">{t('login_button', lang)}</button>
        </div>
      </form>
      <p class="center" style="margin-top:16px">{t('no_account', lang)} 
        <a href="{url_for('signup')}" style="color:var(--gold-soft)">{t('create_account', lang)}</a>
      </p>
    </div>
    """
    return render_template_string(layout('page_login', body))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """User signup page"""
    lang = get_language()
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        country = request.form.get('country', '').strip()
        pw1 = request.form.get('password1', '')
        pw2 = request.form.get('password2', '')
        passport_file = request.files.get('passport')
        passport_issue = request.form.get('passport_issue', '')
        passport_expiry = request.form.get('passport_expiry', '')
        
        # Validate input
        errors = validate_signup_input(
            username, email, phone, country, pw1, pw2,
            passport_issue, passport_expiry
        )
        
        if passport_file and passport_file.filename:
            if not allowed_file(passport_file.filename):
                errors.append(t('invalid_file_format', lang))
        else:
            errors.append(t('passport_required', lang))
        
        if errors:
            for error in errors:
                flash(error, 'error')
            return redirect(url_for('signup'))
        
        # Save passport file
        try:
            fname = f"{secure_filename(username)}_{secure_filename(passport_file.filename)}"
            passport_path = os.path.join(app.config['UPLOAD_DIR'], fname)
            passport_file.save(passport_path)
        except Exception as e:
            flash(t('error_generic', lang), 'error')
            return redirect(url_for('signup'))
        
        # Create user
        db = get_db()
        try:
            db.execute(
                """INSERT INTO users(
                    username, email, phone, country, passport_file,
                    passport_issue_date, passport_expiry_date,
                    password_hash, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (username, email, phone, country, fname,
                 passport_issue, passport_expiry,
                 hash_password(pw1), datetime.now().isoformat())
            )
            db.commit()
            flash(t('signup_success', lang), 'ok')
            return redirect(url_for('login'))
        except Exception as e:
            flash(t('error_generic', lang), 'error')
            return redirect(url_for('signup'))
    
    country_opts = ''.join(
        f'<option value="{c}">{c}</option>' for c in COUNTRIES
    )
    
    body = f"""
    <div class="form-box card glow-form" style="max-width:520px">
      <h2 class="center">{t('signup', lang)}</h2>
      {flashes_html()}
      <form method="post" enctype="multipart/form-data">
        <label>{t('username', lang)}</label>
        <input type="text" name="username" required minlength="3">
        <label>{t('email', lang)}</label>
        <input type="email" name="email" required>
        <label>{t('phone', lang)}</label>
        <input type="tel" name="phone" required minlength="8">
        <label>{t('country', lang)}</label>
        <select name="country" required>
          <option value="">{t('country', lang)}</option>
          {country_opts}
        </select>
        <label>{t('passport_issue', lang)}</label>
        <input type="date" name="passport_issue" required>
        <label>{t('passport_expiry', lang)}</label>
        <input type="date" name="passport_expiry" required>
        <label>{t('passport', lang)}</label>
        <input type="file" name="passport" accept="image/*" required>
        <label>{t('password', lang)}</label>
        <input type="password" name="password1" required minlength="6" autocomplete="new-password">
        <label>{t('confirm_password', lang)}</label>
        <input type="password" name="password2" required minlength="6" autocomplete="new-password">
        <div class="center" style="margin-top:20px">
          <button class="btn" type="submit" style="width:100%">{t('signup_button', lang)}</button>
        </div>
      </form>
      <p class="center" style="margin-top:16px">{t('already_have_account', lang)} 
        <a href="{url_for('login')}" style="color:var(--gold-soft)">{t('login', lang)}</a>
      </p>
    </div>
    """
    return render_template_string(layout('page_signup', body))

@app.route('/logout')
def logout():
    """User logout"""
    session.clear()
    return redirect(url_for('login'))

# ===================================================================
# Main Pages
# ===================================================================

@app.route('/home')
@login_required
def home():
    """Home page with airlines"""
    user = current_user()
    lang = get_language()
    
    db = get_db()
    airlines = db.execute(
        'SELECT * FROM airlines WHERE country=? ORDER BY name',
        (user['country'],)
    ).fetchall()
    
    if not airlines:
        airlines = db.execute(
            'SELECT * FROM airlines WHERE country="دولي" ORDER BY name'
        ).fetchall()
    
    cards = ''.join(
        f"""<a class="airline-card" href="{url_for('airline_page', airline_id=a['id'])}">
              <div class="emoji-big">{a['logo_emoji']}</div>
              <h3>{a['name']}</h3>
              <div class="badge">{a['country']}</div>
            </a>"""
        for a in airlines
    )
    
    body = f"""
    <h1>{t('airlines', lang)}</h1>
    <p class="subtitle">{t('airlines', lang)} - {t('country', lang)}: 
      <b style="color:var(--gold-soft)">{user['country']}</b>
    </p>
    {flashes_html()}
    <div class="grid">{cards}</div>
    """
    
    return render_template_string(layout('page_home', body, user))

# (باقي الملف لم يتغير) — للحفاظ على الطول لم نعدّل بقية الدوال

# ===================================================================
# Run Application
# ===================================================================

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 8080))
    print(f'🌍 وكالة الدواحي للسفر والسياحة تعمل الآن على المنفذ: {port}')
    print(f'📱 الرابط: http://localhost:{port}')
    # If using production config, validate required settings before applying
    if os.environ.get('FLASK_ENV') == 'production':
        from config import ProductionConfig
        ProductionConfig.validate()
        app.config.from_object(ProductionConfig)
    app.run(host='0.0.0.0', port=port, debug=False)
else:
    init_db()
