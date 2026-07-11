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

@app.route('/airline/<int:airline_id>')
@login_required
def airline_page(airline_id):
    """Airline page with flights and hotels"""
    user = current_user()
    lang = get_language()
    db = get_db()
    
    airline = db.execute(
        'SELECT * FROM airlines WHERE id=?', (airline_id,)
    ).fetchone()
    
    if not airline:
        abort(404)
    
    tab = request.args.get('tab', 'flights')
    content = ''
    
    if tab == 'baggage':
        content = _render_baggage_tab(airline, lang)
    elif tab == 'hotels':
        content = _render_hotels_tab(airline, airline_id, db, lang)
    else:
        content = _render_flights_tab(airline, airline_id, db, lang)
    
    body = f"""
    <h1>{airline['name']}</h1>
    {flashes_html()}
    {_render_airline_tabs(airline_id, tab, lang)}
    {content}
    """
    
    return render_template_string(layout('page_airline', body, user))

def _render_baggage_tab(airline, lang):
    """Render baggage information tab"""
    return f"""
    <div class="card">
      <h3>{t('baggage', lang)} - {airline['name']}</h3>
      <table>
        <tr><th>{t('class', lang)}</th><th>{t('baggage', lang)} (kg)</th><th>Hand carry</th></tr>
        <tr><td>{t('first', lang)}</td><td>40</td><td>2 pcs</td></tr>
        <tr><td>{t('business', lang)}</td><td>30</td><td>2 pcs</td></tr>
        <tr><td>{t('second', lang)}</td><td>25</td><td>1 pc</td></tr>
        <tr><td>{t('economy', lang)}</td><td>20</td><td>1 pc</td></tr>
      </table>
    </div>
    """

def _render_hotels_tab(airline, airline_id, db, lang):
    """Render hotels tab"""
    q_stars = request.args.get('stars', '')
    
    dest_cities = [
        r['to_city'] for r in db.execute(
            'SELECT DISTINCT to_city FROM flights WHERE airline_id=?',
            (airline_id,)
        ).fetchall()
    ]
    
    if not dest_cities:
        return f'<div class="card"><p class="subtitle">{t("no_bookings", lang)}</p></div>'
    
    placeholders = ','.join('?' * len(dest_cities))
    sql = f"SELECT * FROM hotels WHERE city IN ({placeholders})"
    params = list(dest_cities)
    
    if q_stars and q_stars.isdigit():
        sql += ' AND stars=?'
        params.append(int(q_stars))
    
    sql += ' ORDER BY stars DESC, city'
    hotels = db.execute(sql, params).fetchall()
    
    star_filters = ''.join(
        f'<a class="tab {"active" if q_stars==str(s) else ""}" '
        f'href="{url_for("airline_page", airline_id=airline_id, tab="hotels", stars=s)}">{s} ★</a>'
        for s in (5, 4, 3)
    )
    star_filters += f'<a class="tab {"active" if not q_stars else ""}" href="{url_for("airline_page", airline_id=airline_id, tab="hotels")}">{t("back", lang)}</a>'
    
    cards = ''.join(
        f"""<a class="hotel-card" href="{url_for('hotel_rooms', hotel_id=h['id'], airline_id=airline_id)}">
              <div class="emoji-big">🏨</div>
              <h3>{h['name']}</h3>
              <div class="stars">{'★'*h['stars']}{'☆'*(5-h['stars'])}</div>
              <div class="badge">{h['city']} - {h['country']}</div>
            </a>"""
        for h in hotels
    )
    
    return f"""
    <div class="card">
      <h3>{t('hotels', lang)}</h3>
      <div class="tabs">{star_filters}</div>
      <div class="grid">{cards or f'<p class="subtitle">{t("no_bookings", lang)}</p>'}</div>
    </div>
    """

def _render_flights_tab(airline, airline_id, db, lang):
    """Render flights tab"""
    scope = request.args.get('scope', '')
    
    if scope not in ('local', 'intl'):
        return f"""
        <div class="card center">
          <h3>{t('flights', lang)}</h3>
          <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">
            <a class="airline-card" href="{url_for('airline_page', airline_id=airline_id, tab='flights', scope='local')}">
              <div class="emoji-big">🚏</div>
              <h3>{t('local', lang)}</h3>
            </a>
            <a class="airline-card" href="{url_for('airline_page', airline_id=airline_id, tab='flights', scope='intl')}">
              <div class="emoji-big">🌍</div>
              <h3>{t('international', lang)}</h3>
            </a>
          </div>
        </div>
        """
    
    home_country = airline['country']
    from_q = request.args.get('from', '')
    to_q = request.args.get('to', '')
    
    if scope == 'local':
        sql = 'SELECT * FROM flights WHERE airline_id=? AND to_country=?'
        params = [airline_id, home_country]
        scope_label = t('local', lang)
        city_choices = LOCAL_CITIES.get(home_country, [])
    else:
        sql = 'SELECT * FROM flights WHERE airline_id=? AND to_country!=?'
        params = [airline_id, home_country]
        scope_label = t('international', lang)
        city_choices = []
    
    if from_q:
        sql += ' AND from_city LIKE ?'
        params.append(f'%{from_q}%')
    if to_q:
        sql += ' AND to_city LIKE ?'
        params.append(f'%{to_q}%')
    
    sql += ' ORDER BY to_city'
    flights = db.execute(sql, params).fetchall()
    
    city_chips = ''
    if city_choices:
        chips = ''.join(
            f'<a class="tab {"active" if to_q==c else ""}" '
            f'href="{url_for("airline_page", airline_id=airline_id, tab="flights", scope="local", to=c)}">{c}</a>'
            for c in city_choices
        )
        chips += f'<a class="tab {"active" if not to_q else ""}" href="{url_for("airline_page", airline_id=airline_id, tab="flights", scope="local")}">{t("back", lang)}</a>'
        city_chips = f'<p class="subtitle">{t("to_city", lang)}:</p><div class="tabs">{chips}</div>'
    
    rows = ''.join(
        f"""<div class="flight-row">
              <div>
                <div class="route">{f['from_city']} ✈ {f['to_city']}</div>
                <div class="subtitle">{t('departure', lang)} {f['dep_time']} - {t('arrival', lang)} {f['arr_time']} ({f['duration']})</div>
              </div>
              <div class="price">{f['price_economy']} ج.س</div>
              <a class="btn small" href="{url_for('select_class', flight_id=f['id'])}">{t('select_class', lang)}</a>
            </div>"""
        for f in flights
    )
    
    return f"""
    <div class="card">
      <div class="tabs">
        <a class="tab {'active' if scope=='local' else ''}" href="{url_for('airline_page', airline_id=airline_id, tab='flights', scope='local')}">{t('local', lang)}</a>
        <a class="tab {'active' if scope=='intl' else ''}" href="{url_for('airline_page', airline_id=airline_id, tab='flights', scope='intl')}">{t('international', lang)}</a>
      </div>
      <h3>{scope_label}</h3>
      {city_chips}
      <form method="get" class="search-bar">
        <input type="hidden" name="tab" value="flights">
        <input type="hidden" name="scope" value="{scope}">
        <input type="text" name="from" placeholder="{t('from_city', lang)}" value="{from_q}">
        <input type="text" name="to" placeholder="{t('to_city', lang)}" value="{to_q}">
        <button class="btn small" type="submit">{t('search_button', lang)}</button>
      </form>
      {rows or f'<p class="subtitle">{t("no_bookings", lang)}</p>'}
    </div>
    """

def _render_airline_tabs(airline_id, active, lang):
    """Render airline navigation tabs"""
    tabs = [
        ('flights', t('flights', lang)),
        ('baggage', t('baggage', lang)),
        ('hotels', t('hotels', lang))
    ]
    out = '<div class="tabs">'
    for key, label in tabs:
        cls = 'tab active' if key == active else 'tab'
        out += f'<a class="{cls}" href="{url_for("airline_page", airline_id=airline_id, tab=key)}">{label}</a>'
    out += '</div>'
    return out

# ===================================================================
# Flight and Ticket Selection
# ===================================================================

@app.route('/select_class/<int:flight_id>', methods=['GET', 'POST'])
@login_required
def select_class(flight_id):
    """Select ticket class for flight"""
    user = current_user()
    lang = get_language()
    db = get_db()
    
    flight = db.execute(
        'SELECT * FROM flights WHERE id=?', (flight_id,)
    ).fetchone()
    
    if not flight:
        abort(404)
    
    airline = db.execute(
        'SELECT * FROM airlines WHERE id=?', (flight['airline_id'],)
    ).fetchone()
    
    if request.method == 'POST':
        cls = request.form.get('ticket_class')
        if cls not in CLASS_LABELS:
            flash(t('error_generic', lang), 'error')
            return redirect(url_for('select_class', flight_id=flight_id))
        
        session['pending_flight'] = {
            'flight_id': flight_id,
            'ticket_class': cls
        }
        return redirect(url_for('airline_page', airline_id=airline['id'], tab='hotels'))
    
    price_map = {
        'economy': flight['price_economy'],
        'second': flight['price_second'],
        'business': flight['price_business'],
        'first': flight['price_first'],
    }
    
    opts = ''.join(
        f"""<label class="class-opt" style="cursor:pointer">
              <input type="radio" name="ticket_class" value="{key}" required style="width:auto">
              <h3>{t(key, lang)}</h3>
              <div class="price">{price_map[key]} ج.س</div>
            </label>"""
        for key, _label in TICKET_CLASSES
    )
    
    body = f"""
    <h1>{t('select_class', lang)}</h1>
    <div class="card">
      <div class="route">{flight['from_city']} ✈ {flight['to_city']} - {airline['name']}</div>
      <p class="subtitle">{t('departure', lang)} {flight['dep_time']} - {t('arrival', lang)} {flight['arr_time']} ({flight['duration']})</p>
      {flashes_html()}
      <form method="post">
        <div class="class-grid">{opts}</div>
        <div class="center" style="margin-top:20px">
          <button class="btn" type="submit">{t('confirm_booking', lang)}</button>
        </div>
      </form>
    </div>
    """
    
    return render_template_string(layout('page_select_class', body, user))

# ===================================================================
# Hotel Booking
# ===================================================================

@app.route('/hotel/<int:hotel_id>/rooms')
@login_required
def hotel_rooms(hotel_id):
    """View hotel rooms"""
    user = current_user()
    lang = get_language()
    db = get_db()
    
    hotel = db.execute(
        'SELECT * FROM hotels WHERE id=?', (hotel_id,)
    ).fetchone()
    
    if not hotel:
        abort(404)
    
    rooms = db.execute(
        'SELECT * FROM rooms WHERE hotel_id=?', (hotel_id,)
    ).fetchall()
    
    rows = ''.join(
        f"""<tr>
              <td>{r['room_type']}</td><td>{r['capacity']} {t('capacity', lang)}</td>
              <td class="price">{r['price_per_night']} ج.س / {t('price_per_night', lang)}</td>
              <td><a class="btn small" href="{url_for('book_room', room_id=r['id'])}">{t('select_room', lang)}</a></td>
            </tr>"""
        for r in rooms
    )
    
    body = f"""
    <h1>{hotel['name']}</h1>
    <p class="subtitle">{hotel['city']} - {hotel['country']} &nbsp; <span class="stars">{'★'*hotel['stars']}</span></p>
    <div class="card">
      <table>
        <tr><th>{t('room_type', lang)}</th><th>{t('capacity', lang)}</th><th>{t('price_per_night', lang)}</th><th></th></tr>
        {rows}
      </table>
    </div>
    """
    
    return render_template_string(layout('page_hotel_rooms', body, user))

@app.route('/book_room/<int:room_id>', methods=['GET', 'POST'])
@login_required
def book_room(room_id):
    """Book a room"""
    user = current_user()
    lang = get_language()
    db = get_db()
    
    room = db.execute(
        'SELECT * FROM rooms WHERE id=?', (room_id,)
    ).fetchone()
    
    if not room:
        abort(404)
    
    hotel = db.execute(
        'SELECT * FROM hotels WHERE id=?', (room['hotel_id'],)
    ).fetchone()
    
    pending = session.get('pending_flight')
    
    if request.method == 'POST':
        checkin = request.form.get('checkin')
        checkout = request.form.get('checkout')
        
        try:
            d1 = date.fromisoformat(checkin)
            d2 = date.fromisoformat(checkout)
        except (TypeError, ValueError):
            flash(t('invalid_date_format', lang), 'error')
            return redirect(url_for('book_room', room_id=room_id))
        
        if d2 <= d1:
            flash(t('invalid_checkout_date', lang), 'error')
            return redirect(url_for('book_room', room_id=room_id))
        
        if not pending:
            flash(t('error_generic', lang), 'error')
            return redirect(url_for('home'))
        
        flight_id = pending['flight_id']
        ticket_class = pending['ticket_class']
        
        flight = db.execute(
            'SELECT * FROM flights WHERE id=?', (flight_id,)
        ).fetchone()
        
        if not flight:
            flash(t('error_generic', lang), 'error')
            return redirect(url_for('home'))
        
        price_map = {
            'economy': flight['price_economy'],
            'second': flight['price_second'],
            'business': flight['price_business'],
            'first': flight['price_first'],
        }
        flight_price = price_map[ticket_class]
        
        nights = (d2 - d1).days
        hotel_price = nights * room['price_per_night']
        total = flight_price + hotel_price
        
        ref = gen_ref_code()
        
        db.execute(
            """INSERT INTO bookings(
                ref_code, user_id, flight_id, ticket_class, flight_price,
                room_id, checkin, checkout, hotel_price, total_price, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ref, user['id'], flight_id, ticket_class, flight_price,
             room_id, checkin, checkout, hotel_price, total,
             datetime.now().isoformat())
        )
        db.commit()
        
        booking = db.execute(
            'SELECT id FROM bookings WHERE ref_code=?', (ref,)
        ).fetchone()
        
        pdf_name = generate_ticket_pdf(booking['id'])
        db.execute(
            'UPDATE bookings SET pdf_file=? WHERE id=?',
            (pdf_name, booking['id'])
        )
        db.commit()
        
        session.pop('pending_flight', None)
        flash(t('booking_confirmed', lang), 'ok')
        return redirect(url_for('booking_detail', booking_id=booking['id']))
    
    body = f"""
    <h1>{t('book_room', lang)}</h1>
    <div class="card">
      <h3>{hotel['name']} - {room['room_type']}</h3>
      <p class="subtitle">{hotel['city']} - {hotel['country']} &nbsp; {room['price_per_night']} ج.س / {t('price_per_night', lang)}</p>
      {flashes_html()}
      <form method="post">
        <label>{t('checkin', lang)}</label>
        <input type="date" name="checkin" required>
        <label>{t('checkout', lang)}</label>
        <input type="date" name="checkout" required>
        <div class="center" style="margin-top:20px">
          <button class="btn" type="submit">{t('confirm_booking', lang)}</button>
        </div>
      </form>
    </div>
    """
    
    return render_template_string(layout('page_book_room', body, user))

# ===================================================================
# Booking Management
# ===================================================================

@app.route('/booking/<int:booking_id>')
@login_required
def booking_detail(booking_id):
    """View booking details"""
    user = current_user()
    lang = get_language()
    db = get_db()
    
    b = db.execute(
        'SELECT * FROM bookings WHERE id=? AND user_id=?',
        (booking_id, user['id'])
    ).fetchone()
    
    if not b:
        abort(404)
    
    flight = db.execute(
        'SELECT * FROM flights WHERE id=?', (b['flight_id'],)
    ).fetchone()
    
    airline = db.execute(
        'SELECT * FROM airlines WHERE id=?', (flight['airline_id'],)
    ).fetchone()
    
    room = None
    hotel = None
    if b['room_id']:
        room = db.execute(
            'SELECT * FROM rooms WHERE id=?', (b['room_id'],)
        ).fetchone()
        hotel = db.execute(
            'SELECT * FROM hotels WHERE id=?', (room['hotel_id'],)
        ).fetchone()
    
    hotel_html = ''
    if hotel:
        hotel_html = f"""
        <h3>{t('hotel_booking', lang)}</h3>
        <p>{hotel['name']} ({'★'*hotel['stars']}) - {hotel['city']}<br>
        {t('room_type', lang)}: {room['room_type']} — {t('checkin', lang)}: {b['checkin']} / {t('checkout', lang)}: {b['checkout']}<br>
        {t('hotel_price', lang)}: <span class="price">{b['hotel_price']} ج.س</span></p>
        """
    
    status_badge = (
        f'<span class="badge" style="color:#e0645a;border-color:#e0645a">{t("status_cancelled", lang)}</span>'
        if b['status'] == 'cancelled'
        else f'<span class="badge" style="color:#5cc98a;border-color:#5cc98a">{t("status_confirmed", lang)}</span>'
    )
    
    cancel_btn = ''
    if b['status'] != 'cancelled':
        cancel_btn = f"""
        <form method="post" action="{url_for('cancel_booking', booking_id=b['id'])}"
              onsubmit="return confirm('{t('confirm_cancel', lang)}');" style="display:inline">
          <button class="btn danger" type="submit">{t('cancel_booking', lang)}</button>
        </form>
        """
    
    body = f"""
    <h1>{t('booking_detail', lang)} — {b['ref_code']} {status_badge}</h1>
    {flashes_html()}
    <div class="card">
      <h3>{t('flight_details', lang)}</h3>
      <p>{airline['name']}: {flight['from_city']} ✈ {flight['to_city']}<br>
      {t('class', lang)}: {t(b['ticket_class'], lang)}<br>
      {t('flight_price', lang)}: <span class="price">{b['flight_price']} ج.س</span></p>
      {hotel_html}
      <h3>{t('total', lang)}: <span class="price">{b['total_price']} ج.س</span></h3>
      <a class="btn" href="{url_for('download_ticket', booking_id=b['id'])}">{t('download_pdf', lang)}</a>
      <a class="btn secondary" href="{url_for('my_bookings')}">{t('my_bookings', lang)}</a>
      {cancel_btn}
    </div>
    """
    
    return render_template_string(layout('page_booking_detail', body, user))

@app.route('/booking/<int:booking_id>/cancel', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    """Cancel booking"""
    user = current_user()
    lang = get_language()
    db = get_db()
    
    b = db.execute(
        'SELECT * FROM bookings WHERE id=? AND user_id=?',
        (booking_id, user['id'])
    ).fetchone()
    
    if not b:
        abort(404)
    
    if b['status'] == 'cancelled':
        flash(t('error_generic', lang), 'error')
    else:
        db.execute(
            'UPDATE bookings SET status="cancelled" WHERE id=?',
            (booking_id,)
        )
        db.commit()
        flash(t('booking_cancelled', lang), 'ok')
    
    return redirect(url_for('booking_detail', booking_id=booking_id))

@app.route('/ticket/<int:booking_id>/download')
@login_required
def download_ticket(booking_id):
    """Download ticket PDF"""
    user = current_user()
    db = get_db()
    
    b = db.execute(
        'SELECT * FROM bookings WHERE id=? AND user_id=?',
        (booking_id, user['id'])
    ).fetchone()
    
    if not b or not b['pdf_file']:
        abort(404)
    
    return send_from_directory(
        Config.TICKETS_DIR,
        b['pdf_file'],
        as_attachment=True
    )

@app.route('/my_bookings')
@login_required
def my_bookings():
    """View user's bookings"""
    user = current_user()
    lang = get_language()
    db = get_db()
    
    rows = db.execute(
        """SELECT b.*, f.from_city, f.to_city, a.name as airline_name
           FROM bookings b
           JOIN flights f ON f.id=b.flight_id
           JOIN airlines a ON a.id=f.airline_id
           WHERE b.user_id=? ORDER BY b.created_at DESC""",
        (user['id'],)
    ).fetchall()
    
    items = ''.join(
        f"""<div class="flight-row">
              <div>
                <div class="route">{r['from_city']} ✈ {r['to_city']} - {r['airline_name']}</div>
                <div class="subtitle">{r['ref_code']} — {t(r['ticket_class'], lang)}
                  {f'<span class="badge" style="color:#e0645a;border-color:#e0645a">{t("status_cancelled", lang)}</span>' if r['status']=='cancelled' else f'<span class="badge" style="color:#5cc98a;border-color:#5cc98a">{t("status_confirmed", lang)}</span>'}
                </div>
              </div>
              <div class="price">{r['total_price']} ج.س</div>
              <a class="btn small secondary" href="{url_for('booking_detail', booking_id=r['id'])}">{t('details', lang)}</a>
              {f'''<form method="post" action="{url_for('cancel_booking', booking_id=r['id'])}"
                    onsubmit="return confirm('{t('confirm_cancel', lang)}');" style="display:inline">
                    <button class="btn small danger" type="submit">{t('cancel', lang)}</button>
                  </form>''' if r['status'] != 'cancelled' else ''}
            </div>"""
        for r in rows
    )
    
    body = f"""
    <h1>{t('my_bookings', lang)}</h1>
    {flashes_html()}
    <div class="card">{items or f'<p class="subtitle">{t("no_bookings", lang)}</p>'}</div>
    """
    
    return render_template_string(layout('page_my_bookings', body, user))

# ===================================================================
# Error Handlers
# ===================================================================

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    lang = get_language()
    body = f'<h1>404 - {t("error_generic", lang)}</h1><p>الصفحة غير موجودة</p>'
    return render_template_string(layout('error', body)), 404

@app.errorhandler(500)
def server_error(error):
    """Handle 500 errors"""
    lang = get_language()
    body = f'<h1>500 - {t("error_generic", lang)}</h1><p>خطأ في الخادم</p>'
    return render_template_string(layout('error', body)), 500

# ===================================================================
# Run Application
# ===================================================================

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 8080))
    print(f'🌍 وكالة الدواحي للسفر والسياحة تعمل الآن على المنفذ: {port}')
    print(f'📱 الرابط: http://localhost:{port}')
    app.run(host='0.0.0.0', port=port, debug=False)
else:
    init_db()
