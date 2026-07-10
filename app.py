# -*- coding: utf-8 -*-
"""
وكالة الدواحي للسفر والسياحة
تطبيق ويب متكامل (Flask + SQLite) - ملف واحد يعمل على Termux
تسجيل حساب / دخول -> اختيار شركة طيران حسب دولة المستخدم -> رحلات/فنادق/أمتعة
حجز تذكرة + غرفة فندقية -> توليد PDF فيه تفاصيل الحجز + باركود
"""

import os
import sqlite3
import hashlib
import secrets
import string
from datetime import datetime, date
from functools import wraps

from flask import (
    Flask, request, session, redirect, url_for, render_template_string,
    send_from_directory, flash, g, abort, get_flashed_messages
)
from werkzeug.utils import secure_filename

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "dawahi.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
TICKETS_DIR = os.path.join(BASE_DIR, "tickets")
ALLOWED_IMG = {"png", "jpg", "jpeg", "webp"}

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(TICKETS_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = "dawahi-secret-key-change-me"
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8MB لصورة الجواز

# ------------------------------------------------------------------
# قاعدة البيانات
# ------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT NOT NULL,
            country TEXT NOT NULL,
            passport_file TEXT,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS airlines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            country TEXT NOT NULL,
            logo_emoji TEXT DEFAULT '✈️'
        );

        CREATE TABLE IF NOT EXISTS flights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            airline_id INTEGER NOT NULL,
            from_city TEXT NOT NULL,
            to_city TEXT NOT NULL,
            to_country TEXT NOT NULL,
            dep_time TEXT NOT NULL,
            arr_time TEXT NOT NULL,
            duration TEXT NOT NULL,
            price_economy INTEGER NOT NULL,
            price_second INTEGER NOT NULL,
            price_business INTEGER NOT NULL,
            price_first INTEGER NOT NULL,
            FOREIGN KEY(airline_id) REFERENCES airlines(id)
        );

        CREATE TABLE IF NOT EXISTS hotels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL,
            country TEXT NOT NULL,
            name TEXT NOT NULL,
            stars INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hotel_id INTEGER NOT NULL,
            room_type TEXT NOT NULL,
            capacity INTEGER NOT NULL,
            price_per_night INTEGER NOT NULL,
            FOREIGN KEY(hotel_id) REFERENCES hotels(id)
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_code TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            flight_id INTEGER NOT NULL,
            ticket_class TEXT NOT NULL,
            flight_price INTEGER NOT NULL,
            room_id INTEGER,
            checkin TEXT,
            checkout TEXT,
            hotel_price INTEGER DEFAULT 0,
            total_price INTEGER NOT NULL,
            pdf_file TEXT,
            status TEXT NOT NULL DEFAULT 'confirmed',
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(flight_id) REFERENCES flights(id),
            FOREIGN KEY(room_id) REFERENCES rooms(id)
        );
        """
    )
    # ترقية آمنة لقواعد بيانات قديمة لا تحتوي عمود status
    try:
        db.execute("ALTER TABLE bookings ADD COLUMN status TEXT NOT NULL DEFAULT 'confirmed'")
    except sqlite3.OperationalError:
        pass
    db.commit()
    seed_data(db)
    db.close()


# بيانات كل دولة عربية: المدينة الرئيسية (منها تنطلق الرحلات) وشركات الطيران الخاصة بها
COUNTRY_DATA = {
    "السودان":     {"city": "الخرطوم",   "airlines": ["الخطوط الجوية السودانية", "بدر إيرلاينز", "طيران تارجت"]},
    "مصر":         {"city": "القاهرة",   "airlines": ["مصر للطيران", "النيل للطيران", "العربية للطيران - مصر"]},
    "السعودية":    {"city": "الرياض",    "airlines": ["الخطوط السعودية", "طيران ناس", "طيران أديل"]},
    "الإمارات":    {"city": "دبي",       "airlines": ["طيران الإمارات", "الاتحاد للطيران", "فلاي دبي"]},
    "قطر":         {"city": "الدوحة",    "airlines": ["الخطوط الجوية القطرية"]},
    "الكويت":      {"city": "الكويت",    "airlines": ["الخطوط الجوية الكويتية", "جزيرة للطيران"]},
    "البحرين":     {"city": "المنامة",   "airlines": ["طيران الخليج"]},
    "عُمان":       {"city": "مسقط",      "airlines": ["الطيران العماني", "سلام إير"]},
    "الأردن":      {"city": "عمّان",     "airlines": ["الملكية الأردنية", "العربية للطيران - الأردن"]},
    "فلسطين":      {"city": "القدس",     "airlines": ["الخطوط الجوية الفلسطينية"]},
    "لبنان":       {"city": "بيروت",     "airlines": ["طيران الشرق الأوسط"]},
    "سوريا":       {"city": "دمشق",      "airlines": ["الخطوط الجوية السورية", "شام ويngz"]},
    "العراق":      {"city": "بغداد",     "airlines": ["الخطوط الجوية العراقية", "طيران أور"]},
    "اليمن":       {"city": "صنعاء",     "airlines": ["الخطوط الجوية اليمنية", "يمنية فيلكس"]},
    "ليبيا":       {"city": "طرابلس",    "airlines": ["الخطوط الجوية الليبية", "أفريقيا للطيران"]},
    "تونس":        {"city": "تونس",      "airlines": ["الخطوط التونسية", "نوفل إير"]},
    "الجزائر":     {"city": "الجزائر",   "airlines": ["الخطوط الجزائرية", "طيران تسيرة"]},
    "المغرب":      {"city": "الدار البيضاء", "airlines": ["الخطوط الملكية المغربية", "العربية للطيران - المغرب"]},
    "موريتانيا":   {"city": "نواكشوط",   "airlines": ["موريتانيا للطيران"]},
    "الصومال":     {"city": "مقديشو",    "airlines": ["الخطوط الصومالية", "جوبا للطيران"]},
    "جيبوتي":      {"city": "جيبوتي",    "airlines": ["جيبوتي للطيران"]},
    "جزر القمر":   {"city": "موروني",    "airlines": ["القمرية للطيران"]},
    "دولي":        {"city": "إسطنبول",   "airlines": ["الخطوط التركية", "القطرية العالمية", "الاتحاد الدولي"]},
}

# الولايات/المدن الكبرى داخل كل دولة والتي تحتوي على مطارات (للرحلات المحلية)
LOCAL_CITIES = {
    "السودان": ["ود مدني", "بورتسودان", "الأبيض", "نيالا", "كسلا", "عطبرة", "دنقلا"],
    "مصر": ["الإسكندرية", "الأقصر", "أسوان", "شرم الشيخ", "الغردقة", "المنصورة"],
    "السعودية": ["جدة", "الدمام", "المدينة المنورة", "أبها", "تبوك", "الطائف"],
    "الإمارات": ["أبوظبي", "الشارقة", "رأس الخيمة", "العين", "الفجيرة"],
    "قطر": ["الخور", "الوكرة", "الريان"],
    "الكويت": ["الجهراء", "الأحمدي", "الفروانية"],
    "البحرين": ["المحرق", "الرفاع", "مدينة عيسى"],
    "عُمان": ["صلالة", "صحار", "نزوى", "صور"],
    "الأردن": ["العقبة", "إربد", "الزرقاء"],
    "فلسطين": ["غزة", "رام الله", "الخليل", "نابلس"],
    "لبنان": ["طرابلس", "صيدا", "زحلة"],
    "سوريا": ["حلب", "اللاذقية", "حمص"],
    "العراق": ["البصرة", "أربيل", "الموصل", "النجف"],
    "اليمن": ["عدن", "الحديدة", "المكلا", "تعز"],
    "ليبيا": ["بنغازي", "مصراتة", "سبها"],
    "تونس": ["صفاقس", "سوسة", "جربة", "توزر"],
    "الجزائر": ["وهران", "قسنطينة", "عنابة", "ورقلة"],
    "المغرب": ["الرباط", "مراكش", "طنجة", "أكادير", "فاس"],
    "موريتانيا": ["نواذيبو", "كيفة"],
    "الصومال": ["هرجيسا", "بوصاصو", "كسمايو"],
    "جيبوتي": ["علي صبيح", "تاجورة"],
    "جزر القمر": ["موتسامودو", "فومبوني"],
    "دولي": ["أنقرة", "إزمير", "أنطاليا"],
}

HOTEL_NAMES = {
    5: ["فندق النخيل الذهبي", "قصر الواحة الفاخر", "برج اللؤلؤة"],
    4: ["فندق الأفق", "منتجع الشراع", "فندق الياسمين"],
    3: ["فندق المسافر", "بيت الضيافة", "فندق النجمة"],
}
ROOM_TYPES = [("غرفة مفردة", 1), ("غرفة مزدوجة", 2), ("جناح عائلي", 4)]


def seed_data(db):
    if db.execute("SELECT COUNT(*) c FROM airlines").fetchone()["c"] > 0:
        return

    import random
    random.seed(42)
    hours = ["06:15", "09:30", "12:45", "16:20", "20:10", "23:40"]

    # شركات الطيران لكل دولة
    airline_ids = {}  # name -> (id, home_country)
    for country, info in COUNTRY_DATA.items():
        for name in info["airlines"]:
            cur = db.execute("INSERT INTO airlines(name,country) VALUES(?,?)", (name, country))
            airline_ids[name] = (cur.lastrowid, country)

    all_countries = list(COUNTRY_DATA.keys())

    # الرحلات الدولية: كل شركة تربط مدينة دولتها بعدد من المدن في دول أخرى
    for name, (aid, home_country) in airline_ids.items():
        from_city = COUNTRY_DATA[home_country]["city"]
        destinations = [c for c in all_countries if c not in (home_country, "دولي")]
        random.shuffle(destinations)
        for to_country in destinations[:6]:
            to_city = COUNTRY_DATA[to_country]["city"]
            dep = random.choice(hours)
            dur_h = random.randint(1, 6)
            base = random.randint(180, 650) * 10
            db.execute(
                """INSERT INTO flights(airline_id,from_city,to_city,to_country,dep_time,arr_time,
                   duration,price_economy,price_second,price_business,price_first)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    aid, from_city, to_city, to_country, dep,
                    f"{(int(dep[:2])+dur_h)%24:02d}:{dep[3:]}", f"{dur_h} ساعة",
                    base, int(base * 1.3), int(base * 2.1), int(base * 3.2),
                ),
            )

    # الرحلات المحلية: كل شركة تربط عاصمة دولتها بالولايات/المدن الكبرى داخل نفس الدولة
    for name, (aid, home_country) in airline_ids.items():
        from_city = COUNTRY_DATA[home_country]["city"]
        local_cities = LOCAL_CITIES.get(home_country, [])
        for to_city in local_cities:
            dep = random.choice(hours)
            dur_h = random.randint(1, 2)
            base = random.randint(40, 120) * 10
            db.execute(
                """INSERT INTO flights(airline_id,from_city,to_city,to_country,dep_time,arr_time,
                   duration,price_economy,price_second,price_business,price_first)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    aid, from_city, to_city, home_country, dep,
                    f"{(int(dep[:2])+dur_h)%24:02d}:{dep[3:]}", f"{dur_h} ساعة",
                    base, int(base * 1.3), int(base * 2.1), int(base * 3.2),
                ),
            )

    # فنادق 3/4/5 نجوم في مدينة كل دولة
    for country, info in COUNTRY_DATA.items():
        city = info["city"]
        country_label = "تركيا" if country == "دولي" else country
        for stars, names in HOTEL_NAMES.items():
            hname = random.choice(names)
            cur = db.execute(
                "INSERT INTO hotels(city,country,name,stars) VALUES(?,?,?,?)",
                (city, country_label, hname, stars),
            )
            hid = cur.lastrowid
            for rtype, cap in ROOM_TYPES:
                price = (stars * 350) + random.randint(-60, 120) + (cap * 40)
                db.execute(
                    "INSERT INTO rooms(hotel_id,room_type,capacity,price_per_night) VALUES(?,?,?,?)",
                    (hid, rtype, cap, price),
                )
    db.commit()


COUNTRIES = [c for c in COUNTRY_DATA.keys() if c != "دولي"] + ["أخرى"]

TICKET_CLASSES = [
    ("economy", "الدرجة العادية"),
    ("second", "الدرجة الثانية"),
    ("business", "درجة رجال الأعمال والمستثمرين"),
    ("first", "الدرجة الأولى"),
]
CLASS_LABELS = dict(TICKET_CLASSES)

# ------------------------------------------------------------------
# أدوات مساعدة
# ------------------------------------------------------------------

def hash_password(pw: str) -> str:
    salt = "dawahi_fixed_salt_v1"
    return hashlib.sha256((salt + pw).encode("utf-8")).hexdigest()


def gen_ref_code() -> str:
    return "DWH-" + "".join(secrets.choice(string.digits + string.ascii_uppercase) for _ in range(8))


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMG


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*a, **kw)
    return wrapped


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


# ------------------------------------------------------------------
# القوالب المشتركة (الطابع البصري: سماء صحراوية ليلية)
# ------------------------------------------------------------------

BASE_CSS = """
:root{
  --bg1:#0b1220; --bg2:#0f1b30; --gold:#d4af37; --gold-soft:#e8c766;
  --sand:#c9a876; --text:#f2e9d8; --muted:#9fb0c9; --card:#121f38cc;
  --border:#2a3b5c; --danger:#e0645a; --ok:#5cc98a;
}
*{box-sizing:border-box}
body{
  margin:0; font-family:'Cairo','Tahoma',sans-serif; direction:rtl;
  color:var(--text); min-height:100vh;
  background:
    radial-gradient(circle at 15% 15%, rgba(212,175,55,.10), transparent 40%),
    radial-gradient(circle at 85% 10%, rgba(212,175,55,.08), transparent 35%),
    linear-gradient(180deg, var(--bg1) 0%, var(--bg2) 60%, #17233a 100%);
  background-attachment:fixed;
}
a{color:inherit;text-decoration:none}
.navbar{
  display:flex; align-items:center; justify-content:space-between;
  padding:14px 26px; background:rgba(10,16,30,.75); backdrop-filter:blur(6px);
  border-bottom:1px solid var(--border); position:sticky; top:0; z-index:20;
}
.brand{font-size:1.25rem; font-weight:800; color:var(--gold-soft); letter-spacing:.5px}
.brand span{color:var(--sand); font-weight:400; font-size:.85rem; display:block}
.nav-links a{margin-inline-start:16px; color:var(--muted); font-size:.92rem}
.nav-links a:hover{color:var(--gold-soft)}
.wrap{max-width:1080px; margin:0 auto; padding:26px 18px 60px}
.card{
  background:var(--card); border:1px solid var(--border); border-radius:16px;
  padding:22px; margin-bottom:18px; box-shadow:0 10px 30px rgba(0,0,0,.35);
}
h1,h2,h3{color:var(--gold-soft); margin-top:0}
.subtitle{color:var(--muted); font-size:.9rem}
.btn{
  display:inline-block; padding:11px 22px; border-radius:10px; border:none;
  background:linear-gradient(135deg,var(--gold),#b8912b); color:#1a1305; font-weight:800;
  cursor:pointer; font-size:.95rem; transition:.15s;
}
.btn:hover{filter:brightness(1.08); transform:translateY(-1px)}
.btn.secondary{background:transparent; border:1px solid var(--gold); color:var(--gold-soft)}
.btn.danger{background:linear-gradient(135deg,#c94a41,#8f2f29); color:#fff}
.btn.small{padding:7px 14px; font-size:.82rem}
label{display:block; margin:12px 0 6px; font-size:.88rem; color:var(--muted)}
input[type=text],input[type=email],input[type=password],input[type=tel],
input[type=date],input[type=file],select{
  width:100%; padding:11px 13px; border-radius:10px; border:1px solid var(--border);
  background:#0c1526; color:var(--text); font-size:.95rem; font-family:inherit;
}
input:focus,select:focus{outline:1px solid var(--gold)}
.form-box{max-width:420px; margin:40px auto}
.center{text-align:center}
.flash{padding:10px 14px; border-radius:10px; margin-bottom:14px; font-size:.9rem}
.flash.error{background:#3a1616; color:#f3a49c; border:1px solid #6b2a24}
.flash.ok{background:#123a26; color:#8fe0b3; border:1px solid #235c3c}
.grid{display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:16px}
.airline-card,.hotel-card{
  background:var(--card); border:1px solid var(--border); border-radius:14px;
  padding:18px; text-align:center; transition:.15s;
}
.airline-card:hover,.hotel-card:hover{border-color:var(--gold); transform:translateY(-2px)}
.emoji-big{font-size:2.2rem}
.tabs{display:flex; gap:8px; margin-bottom:18px; flex-wrap:wrap}
.tab{
  padding:9px 18px; border-radius:999px; border:1px solid var(--border);
  color:var(--muted); font-size:.88rem; background:#0d1729;
}
.tab.active{background:var(--gold); color:#1a1305; border-color:var(--gold); font-weight:800}
.flight-row{
  display:flex; align-items:center; justify-content:space-between; gap:14px;
  padding:16px; border:1px solid var(--border); border-radius:12px; margin-bottom:12px;
  background:#0d1729; flex-wrap:wrap;
}
.route{font-weight:800; font-size:1.05rem}
.badge{
  display:inline-block; padding:3px 10px; border-radius:999px; font-size:.75rem;
  background:rgba(212,175,55,.15); color:var(--gold-soft); border:1px solid var(--border);
}
.stars{color:var(--gold-soft); letter-spacing:2px}
.price{font-weight:800; color:var(--ok); font-size:1.05rem}
table{width:100%; border-collapse:collapse}
table th,table td{padding:10px; border-bottom:1px solid var(--border); text-align:right; font-size:.9rem}
.search-bar{display:flex; gap:10px; flex-wrap:wrap; margin-bottom:18px}
.search-bar input,.search-bar select{flex:1; min-width:150px}
.class-grid{display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:12px}
.class-opt{
  border:1px solid var(--border); border-radius:12px; padding:16px; text-align:center; background:#0d1729;
}
.class-opt h3{margin:6px 0; font-size:1rem}
.footer-note{color:var(--muted); font-size:.78rem; text-align:center; margin-top:30px}
"""

def layout(title, body, user=None):
    nav_user = ""
    if user:
        nav_user = f'''<a href="{url_for('my_bookings')}">حجوزاتي</a>
        <a href="{url_for('home')}">شركات الطيران</a>
        <span style="color:var(--sand)">{user['username']}</span>
        <a href="{url_for('logout')}" class="btn small danger">خروج</a>'''
    else:
        nav_user = f'<a href="{url_for("login")}" class="btn small">دخول</a>'

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - وكالة الدواحي للسفر والسياحة</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>{BASE_CSS}</style>
</head>
<body>
<div class="navbar">
  <div class="brand">وكالة الدواحي ✦ <span>للسفر والسياحة</span></div>
  <div class="nav-links">{nav_user}</div>
</div>
<div class="wrap">
{body}
</div>
<div class="footer-note">وكالة الدواحي للسفر والسياحة — رحلتك تبدأ من هنا</div>
</body>
</html>"""


def flashes_html():
    """عرض رسائل الفلاش (الأخطاء والنجاح) بشكل صحيح"""
    out = ""
    msgs = get_flashed_messages(with_categories=True)
    for cat, msg in msgs:
        cls = "error" if cat == "error" else "ok"
        out += f'<div class="flash {cls}">{msg}</div>'
    return out


# ------------------------------------------------------------------
# المصادقة: تسجيل الدخول / حساب جديد
# ------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    if session.get("user_id"):
        return redirect(url_for("home"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and user["password_hash"] == hash_password(password):
            session["user_id"] = user["id"]
            flash("تم تسجيل الدخول بنجاح", "ok")
            return redirect(url_for("home"))
        flash("البريد الإلكتروني أو كلمة المرور غير صحيحة", "error")
        return redirect(url_for("login"))

    body = f"""
    <div class="form-box card">
      <h2 class="center">تسجيل الدخول</h2>
      <p class="subtitle center">وكالة الدواحي للسفر والسياحة</p>
      {flashes_html()}
      <form method="post">
        <label>البريد الإلكتروني</label>
        <input type="email" name="email" required>
        <label>كلمة المرور</label>
        <input type="password" name="password" required>
        <div class="center" style="margin-top:20px">
          <button class="btn" type="submit" style="width:100%">تسجيل الدخول</button>
        </div>
      </form>
      <p class="center" style="margin-top:16px">ليس لديك حساب؟ <a href="{url_for('signup')}" style="color:var(--gold-soft)">إنشاء حساب جديد</a></p>
    </div>
    """
    return render_template_string(layout("تسجيل الدخول", body))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        country = request.form.get("country", "").strip()
        code = request.form.get("code", "").strip()  # حقل "اكتب الكود" (رمز الدعوة/التحقق - اختياري)
        pw1 = request.form.get("password1", "")
        pw2 = request.form.get("password2", "")
        passport_file = request.files.get("passport")

        errors = []
        if not username or len(username) < 3:
            errors.append("اسم المستخدم يجب أن يكون 3 أحرف على الأقل")
        if not email or "@" not in email:
            errors.append("البريد الإلكتروني غير صحيح")
        if not phone or len(phone) < 8:
            errors.append("رقم الهاتف غير صحيح")
        if not country:
            errors.append("الرجاء اختيار الدولة")
        if not pw1 or len(pw1) < 6:
            errors.append("كلمة المرور يجب أن تكون 6 أحرف على الأقل")
        if pw1 != pw2:
            errors.append("كلمتا المرور غير متطابقتين")
        if not passport_file or passport_file.filename == "":
            errors.append("الرجاء رفع صورة جواز السفر الساري المفعول")
        elif not allowed_file(passport_file.filename):
            errors.append("صيغة صورة الجواز يجب أن تكون png أو jpg أو jpeg أو webp")

        db = get_db()
        if not errors:
            exists = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if exists:
                errors.append("هذا البريد الإلكتروني مسجل مسبقاً")

        if errors:
            for e in errors:
                flash(e, "error")
            return redirect(url_for("signup"))

        fname = f"{secrets.token_hex(8)}_{secure_filename(passport_file.filename)}"
        passport_file.save(os.path.join(UPLOAD_DIR, fname))

        db.execute(
            """INSERT INTO users(username,email,phone,country,passport_file,password_hash,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (username, email, phone, country, fname, hash_password(pw1), datetime.now().isoformat()),
        )
        db.commit()
        flash("تم إنشاء الحساب بنجاح، الرجاء تسجيل الدخول", "ok")
        return redirect(url_for("login"))

    country_opts = "".join(f'<option value="{c}">{c}</option>' for c in COUNTRIES)
    body = f"""
    <div class="form-box card" style="max-width:520px">
      <h2 class="center">إنشاء حساب جديد</h2>
      {flashes_html()}
      <form method="post" enctype="multipart/form-data">
        <label>اسم المستخدم</label>
        <input type="text" name="username" required>
        <label>البريد الإلكتروني</label>
        <input type="email" name="email" required>
        <label>رقم الهاتف</label>
        <input type="tel" name="phone" required>
        <label>الدولة</label>
        <select name="country" required>
          <option value="">اختر الدولة</option>
          {country_opts}
        </select>
        <label>صورة جواز السفر الساري المفعول</label>
        <input type="file" name="passport" accept="image/*" required>
        <label>كود الدعوة / التحقق (إن وجد)</label>
        <input type="text" name="code" placeholder="اختياري">
        <label>كلمة المرور</label>
        <input type="password" name="password1" required>
        <label>إعادة كتابة كلمة المرور</label>
        <input type="password" name="password2" required>
        <div class="center" style="margin-top:20px">
          <button class="btn" type="submit" style="width:100%">تسجيل الدخول / إنشاء الحساب</button>
        </div>
      </form>
      <p class="center" style="margin-top:16px">لديك حساب بالفعل؟ <a href="{url_for('login')}" style="color:var(--gold-soft)">تسجيل الدخول</a></p>
    </div>
    """
    return render_template_string(layout("إنشاء حساب", body))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------------
# الصفحة الرئيسية: شركات الطيران حسب دولة المستخدم
# ------------------------------------------------------------------

@app.route("/home")
@login_required
def home():
    user = current_user()
    db = get_db()
    airlines = db.execute("SELECT * FROM airlines WHERE country=? ORDER BY name", (user["country"],)).fetchall()
    if not airlines:
        # الدولة غير مدرجة (مثلاً "أخرى") - نعرض شركات الطيران الدولية كبديل
        airlines = db.execute("SELECT * FROM airlines WHERE country='دولي' ORDER BY name").fetchall()

    cards = "".join(
        f"""<a class="airline-card" href="{url_for('airline_page', airline_id=a['id'])}">
              <div class="emoji-big">{a['logo_emoji']}</div>
              <h3>{a['name']}</h3>
              <div class="badge">{a['country']}</div>
            </a>"""
        for a in airlines
    )
    body = f"""
    <h1>شركات الطيران</h1>
    <p class="subtitle">معروضة حسب دولة التسجيل: <b style="color:var(--gold-soft)">{user['country']}</b></p>
    {flashes_html()}
    <div class="grid">{cards}</div>
    """
    return render_template_string(layout("الرئيسية", body, user))


# ------------------------------------------------------------------
# صفحة شركة الطيران: رحلات / أمتعة والتزام / فنادق
# ------------------------------------------------------------------

def airline_tabs(airline_id, active):
    tabs = [("flights", "الرحلات"), ("baggage", "الأمتعة والالتزام"), ("hotels", "الفنادق")]
    out = '<div class="tabs">'
    for key, label in tabs:
        cls = "tab active" if key == active else "tab"
        out += f'<a class="{cls}" href="{url_for("airline_page", airline_id=airline_id, tab=key)}">{label}</a>'
    out += "</div>"
    return out


@app.route("/airline/<int:airline_id>")
@login_required
def airline_page(airline_id):
    user = current_user()
    db = get_db()
    airline = db.execute("SELECT * FROM airlines WHERE id=?", (airline_id,)).fetchone()
    if not airline:
        abort(404)
    tab = request.args.get("tab", "flights")

    if tab == "baggage":
        content = f"""
        <div class="card">
          <h3>سياسة الأمتعة والالتزام - {airline['name']}</h3>
          <table>
            <tr><th>الدرجة</th><th>الأمتعة المسموحة</th><th>حقيبة اليد</th></tr>
            <tr><td>الدرجة الأولى</td><td>40 كجم</td><td>2 قطعة</td></tr>
            <tr><td>درجة رجال الأعمال والمستثمرين</td><td>30 كجم</td><td>2 قطعة</td></tr>
            <tr><td>الدرجة الثانية</td><td>25 كجم</td><td>قطعة واحدة</td></tr>
            <tr><td>الدرجة العادية</td><td>20 كجم</td><td>قطعة واحدة</td></tr>
          </table>
          <p class="subtitle" style="margin-top:10px">يلتزم المسافر بأنظمة الأمتعة الخاصة بالشركة، وأي وزن زائد يُحتسب برسوم إضافي</p>
        </div>
        """
    elif tab == "hotels":
        q_stars = request.args.get("stars", "")
        dest_cities = [r["to_city"] for r in db.execute(
            "SELECT DISTINCT to_city FROM flights WHERE airline_id=?", (airline_id,)
        ).fetchall()]
        placeholders = ",".join("?" * len(dest_cities)) if dest_cities else "''"
        sql = f"SELECT * FROM hotels WHERE city IN ({placeholders})"
        params = list(dest_cities)
        if q_stars:
            sql += " AND stars=?"
            params.append(int(q_stars))
        sql += " ORDER BY stars DESC, city"
        hotels = db.execute(sql, params).fetchall() if dest_cities else []

        star_filters = "".join(
            f'<a class="tab {"active" if q_stars==str(s) else ""}" '
            f'href="{url_for("airline_page", airline_id=airline_id, tab="hotels", stars=s)}">{s} نجوم</a>'
            for s in (5, 4, 3)
        )
        star_filters += f'<a class="tab {"active" if not q_stars else ""}" href="{url_for("airline_page", airline_id=airline_id, tab="hotels")}">الكل</a>'

        cards = "".join(
            f"""<a class="hotel-card" href="{url_for('hotel_rooms', hotel_id=h['id'], airline_id=airline_id)}">
                  <div class="emoji-big">🏨</div>
                  <h3>{h['name']}</h3>
                  <div class="stars">{'★'*h['stars']}{'☆'*(5-h['stars'])}</div>
                  <div class="badge">{h['city']} - {h['country']}</div>
                </a>"""
            for h in hotels
        )
        content = f"""
        <div class="card">
          <h3>الفنادق المتاحة (حسب وجهات {airline['name']})</h3>
          <div class="tabs">{star_filters}</div>
          <div class="grid">{cards or '<p class="subtitle">لا توجد فنادق مطابقة</p>'}</div>
        </div>
        """
    else:
        tab = "flights"
        scope = request.args.get("scope", "")

        if scope not in ("local", "intl"):
            # شاشة اختيار: رحلات محلية أم دولية
            content = f"""
            <div class="card center">
              <h3>اختر نوع الرحلة</h3>
              <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">
                <a class="airline-card" href="{url_for('airline_page', airline_id=airline_id, tab='flights', scope='local')}">
                  <div class="emoji-big">🚏</div>
                  <h3>رحلات محلية</h3>
                  <div class="subtitle">داخل {airline['country']}</div>
                </a>
                <a class="airline-card" href="{url_for('airline_page', airline_id=airline_id, tab='flights', scope='intl')}">
                  <div class="emoji-big">🌍</div>
                  <h3>رحلات دولية</h3>
                  <div class="subtitle">إلى خارج {airline['country']}</div>
                </a>
              </div>
            </div>
            """
        else:
            home_country = airline["country"]
            from_q = request.args.get("from", "")
            to_q = request.args.get("to", "")

            if scope == "local":
                sql = "SELECT * FROM flights WHERE airline_id=? AND to_country=?"
                params = [airline_id, home_country]
                scope_label = "الرحلات المحلية"
                city_choices = LOCAL_CITIES.get(home_country, [])
            else:
                sql = "SELECT * FROM flights WHERE airline_id=? AND to_country!=?"
                params = [airline_id, home_country]
                scope_label = "الرحلات الدولية"
                city_choices = []

            if from_q:
                sql += " AND from_city LIKE ?"
                params.append(f"%{from_q}%")
            if to_q:
                sql += " AND to_city LIKE ?"
                params.append(f"%{to_q}%")
            sql += " ORDER BY to_city"
            flights = db.execute(sql, params).fetchall()

            city_chips = ""
            if city_choices:
                chips = "".join(
                    f'<a class="tab {"active" if to_q==c else ""}" '
                    f'href="{url_for("airline_page", airline_id=airline_id, tab="flights", scope="local", to=c)}">{c}</a>'
                    for c in city_choices
                )
                chips += f'<a class="tab {"active" if not to_q else ""}" href="{url_for("airline_page", airline_id=airline_id, tab="flights", scope="local")}">الكل</a>'
                city_chips = f'<p class="subtitle" style="margin-top:0">اختر الولاية/المدينة:</p><div class="tabs">{chips}</div>'

            rows = "".join(
                f"""<div class="flight-row">
                      <div>
                        <div class="route">{f['from_city']} ✈ {f['to_city']}</div>
                        <div class="subtitle">مغادرة {f['dep_time']} - وصول {f['arr_time']} ({f['duration']})</div>
                      </div>
                      <div class="price">من {f['price_economy']} ج.س</div>
                      <a class="btn small" href="{url_for('select_class', flight_id=f['id'])}">التزاكر</a>
                    </div>"""
                for f in flights
            )
            content = f"""
            <div class="card">
              <div class="tabs">
                <a class="tab {'active' if scope=='local' else ''}" href="{url_for('airline_page', airline_id=airline_id, tab='flights', scope='local')}">محلي</a>
                <a class="tab {'active' if scope=='intl' else ''}" href="{url_for('airline_page', airline_id=airline_id, tab='flights', scope='intl')}">دولي</a>
              </div>
              <h3>{scope_label} - {airline['name']}</h3>
              {city_chips}
              <form method="get" class="search-bar">
                <input type="hidden" name="tab" value="flights">
                <input type="hidden" name="scope" value="{scope}">
                <input type="text" name="from" placeholder="من" value="{from_q}">
                <input type="text" name="to" placeholder="إلى" value="{to_q}">
                <button class="btn small" type="submit">بحث عن الرحلات</button>
              </form>
              {rows or '<p class="subtitle">لا توجد رحلات مطابقة</p>'}
            </div>
            """

    body = f"""
    <h1>{airline['name']}</h1>
    {flashes_html()}
    {airline_tabs(airline_id, tab)}
    {content}
    """
    return render_template_string(layout(airline["name"], body, user))


# ------------------------------------------------------------------
# اختيار درجة التذكرة
# ------------------------------------------------------------------

@app.route("/select_class/<int:flight_id>", methods=["GET", "POST"])
@login_required
def select_class(flight_id):
    user = current_user()
    db = get_db()
    flight = db.execute("SELECT * FROM flights WHERE id=?", (flight_id,)).fetchone()
    if not flight:
        abort(404)
    airline = db.execute("SELECT * FROM airlines WHERE id=?", (flight["airline_id"],)).fetchone()

    if request.method == "POST":
        cls = request.form.get("ticket_class")
        if cls not in CLASS_LABELS:
            flash("الرجاء اختيار درجة التذكرة", "error")
            return redirect(url_for("select_class", flight_id=flight_id))
        session["pending_flight"] = {"flight_id": flight_id, "ticket_class": cls}
        return redirect(url_for("airline_page", airline_id=airline["id"], tab="hotels"))

    price_map = {
        "economy": flight["price_economy"], "second": flight["price_second"],
        "business": flight["price_business"], "first": flight["price_first"],
    }
    opts = "".join(
        f"""<label class="class-opt" style="cursor:pointer">
              <input type="radio" name="ticket_class" value="{key}" required style="width:auto">
              <h3>{label}</h3>
              <div class="price">{price_map[key]} ج.س</div>
            </label>"""
        for key, label in TICKET_CLASSES
    )
    body = f"""
    <h1>اختيار نوع التذكرة</h1>
    <div class="card">
      <div class="route">{flight['from_city']} ✈ {flight['to_city']} - {airline['name']}</div>
      <p class="subtitle">مغادرة {flight['dep_time']} - وصول {flight['arr_time']} ({flight['duration']})</p>
      {flashes_html()}
      <form method="post">
        <div class="class-grid">{opts}</div>
        <div class="center" style="margin-top:20px">
          <button class="btn" type="submit">تأكيد نوع التذكرة والمتابعة للفنادق</button>
        </div>
      </form>
    </div>
    """
    return render_template_string(layout("اختيار الدرجة", body, user))


# ------------------------------------------------------------------
# الفنادق -> الغرف -> تاريخ الحجز والمغادرة -> تأكيد الحجز النهائي
# ------------------------------------------------------------------

@app.route("/hotel/<int:hotel_id>/rooms")
@login_required
def hotel_rooms(hotel_id):
    user = current_user()
    db = get_db()
    hotel = db.execute("SELECT * FROM hotels WHERE id=?", (hotel_id,)).fetchone()
    if not hotel:
        abort(404)
    rooms = db.execute("SELECT * FROM rooms WHERE hotel_id=?", (hotel_id,)).fetchall()

    rows = "".join(
        f"""<tr>
              <td>{r['room_type']}</td><td>{r['capacity']} أشخاص</td>
              <td class="price">{r['price_per_night']} ج.س / الليلة</td>
              <td><a class="btn small" href="{url_for('book_room', room_id=r['id'])}">اختيار</a></td>
            </tr>"""
        for r in rooms
    )
    body = f"""
    <h1>{hotel['name']}</h1>
    <p class="subtitle">{hotel['city']} - {hotel['country']} &nbsp; <span class="stars">{'★'*hotel['stars']}</span></p>
    <div class="card">
      <table>
        <tr><th>نوع الغرفة</th><th>السعة</th><th>السعر</th><th></th></tr>
        {rows}
      </table>
    </div>
    """
    return render_template_string(layout(hotel["name"], body, user))


@app.route("/book_room/<int:room_id>", methods=["GET", "POST"])
@login_required
def book_room(room_id):
    user = current_user()
    db = get_db()
    room = db.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
    if not room:
        abort(404)
    hotel = db.execute("SELECT * FROM hotels WHERE id=?", (room["hotel_id"],)).fetchone()
    pending = session.get("pending_flight")

    if request.method == "POST":
        checkin = request.form.get("checkin")
        checkout = request.form.get("checkout")
        try:
            d1 = date.fromisoformat(checkin)
            d2 = date.fromisoformat(checkout)
        except (TypeError, ValueError):
            flash("الرجاء إدخال تاريخين صحيحين", "error")
            return redirect(url_for("book_room", room_id=room_id))
        if d2 <= d1:
            flash("يجب أن يكون تاريخ المغادرة بعد تاريخ الحجز", "error")
            return redirect(url_for("book_room", room_id=room_id))

        nights = (d2 - d1).days
        hotel_price = nights * room["price_per_night"]

        flight_id = pending["flight_id"] if pending else None
        ticket_class = pending["ticket_class"] if pending else None
        flight_price = 0
        flight = None
        if flight_id:
            flight = db.execute("SELECT * FROM flights WHERE id=?", (flight_id,)).fetchone()
            price_map = {
                "economy": flight["price_economy"], "second": flight["price_second"],
                "business": flight["price_business"], "first": flight["price_first"],
            }
            flight_price = price_map[ticket_class]

        if not flight_id:
            flash("الرجاء اختيار رحلة وتذكرة أولاً قبل حجز الفندق", "error")
            return redirect(url_for("home"))

        total = flight_price + hotel_price
        ref = gen_ref_code()
        db.execute(
            """INSERT INTO bookings(ref_code,user_id,flight_id,ticket_class,flight_price,
               room_id,checkin,checkout,hotel_price,total_price,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (ref, user["id"], flight_id, ticket_class, flight_price, room_id,
             checkin, checkout, hotel_price, total, datetime.now().isoformat()),
        )
        db.commit()
        booking_id = db.execute("SELECT id FROM bookings WHERE ref_code=?", (ref,)).fetchone()["id"]
        pdf_name = generate_ticket_pdf(booking_id)
        db.execute("UPDATE bookings SET pdf_file=? WHERE id=?", (pdf_name, booking_id))
        db.commit()
        session.pop("pending_flight", None)
        flash("تم تأكيد الحجز بنجاح", "ok")
        return redirect(url_for("booking_detail", booking_id=booking_id))

    body = f"""
    <h1>حجز الغرفة</h1>
    <div class="card">
      <h3>{hotel['name']} - {room['room_type']}</h3>
      <p class="subtitle">{hotel['city']} - {hotel['country']} &nbsp; {room['price_per_night']} ج.س / الليلة</p>
      {flashes_html()}
      <form method="post">
        <label>تاريخ الحجز (الوصول)</label>
        <input type="date" name="checkin" required>
        <label>تاريخ المغادرة</label>
        <input type="date" name="checkout" required>
        <div class="center" style="margin-top:20px">
          <button class="btn" type="submit">إتمام الحجز وإصدار التذكرة PDF</button>
        </div>
      </form>
    </div>
    """
    return render_template_string(layout("حجز الغرفة", body, user))


# ------------------------------------------------------------------
# توليد تذكرة PDF مع باركود
# ------------------------------------------------------------------

def generate_ticket_pdf(booking_id):
    db = get_db()
    b = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    user = db.execute("SELECT * FROM users WHERE id=?", (b["user_id"],)).fetchone()
    flight = db.execute("SELECT * FROM flights WHERE id=?", (b["flight_id"],)).fetchone()
    airline = db.execute("SELECT * FROM airlines WHERE id=?", (flight["airline_id"],)).fetchone()
    room = db.execute("SELECT * FROM rooms WHERE id=?", (b["room_id"],)).fetchone() if b["room_id"] else None
    hotel = db.execute("SELECT * FROM hotels WHERE id=?", (room["hotel_id"],)).fetchone() if room else None

    fname = f"ticket_{b['ref_code']}.pdf"
    fpath = os.path.join(TICKETS_DIR, fname)

    c = canvas.Canvas(fpath, pagesize=A4)
    w, h = A4
    gold = colors.HexColor("#b8912b")
    navy = colors.HexColor("#0f1b30")
    muted = colors.HexColor("#555555")

    # ترويسة
    c.setFillColor(navy)
    c.rect(0, h - 90, w, 90, fill=1, stroke=0)
    c.setFillColor(gold)
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(w / 2, h - 45, "DAWAHI TRAVEL & TOURISM AGENCY")
    c.setFont("Helvetica", 11)
    c.setFillColor(colors.white)
    c.drawCentredString(w / 2, h - 65, "E-Ticket / Booking Confirmation")

    y = h - 130
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(40, y, f"Reference: {b['ref_code']}")
    c.setFont("Helvetica", 10)
    c.drawRightString(w - 40, y, f"Issued: {b['created_at'][:19]}")

    y -= 30
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Passenger Information")
    c.setStrokeColor(gold)
    c.line(40, y - 4, w - 40, y - 4)
    y -= 20
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Name: {user['username']}")
    y -= 15
    c.drawString(50, y, f"Email: {user['email']}   Phone: {user['phone']}")
    y -= 15
    c.drawString(50, y, f"Country: {user['country']}")

    y -= 30
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Flight Details")
    c.line(40, y - 4, w - 40, y - 4)
    y -= 20
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Airline: {airline['name']}")
    y -= 15
    c.drawString(50, y, f"Route: {flight['from_city']} -> {flight['to_city']} ({flight['to_country']})")
    y -= 15
    c.drawString(50, y, f"Departure: {flight['dep_time']}   Arrival: {flight['arr_time']}   Duration: {flight['duration']}")
    y -= 15
    c.drawString(50, y, f"Class: {CLASS_LABELS.get(b['ticket_class'], b['ticket_class'])}")
    y -= 15
    c.setFillColor(colors.HexColor("#0a7a3d"))
    c.drawString(50, y, f"Flight Price: {b['flight_price']} SDG")
    c.setFillColor(colors.black)

    if hotel and room:
        y -= 30
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, "Hotel Booking")
        c.line(40, y - 4, w - 40, y - 4)
        y -= 20
        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"Hotel: {hotel['name']} ({'*' * hotel['stars']})")
        y -= 15
        c.drawString(50, y, f"City: {hotel['city']} - {hotel['country']}")
        y -= 15
        c.drawString(50, y, f"Room: {room['room_type']} (Capacity {room['capacity']})")
        y -= 15
        c.drawString(50, y, f"Check-in: {b['checkin']}   Check-out: {b['checkout']}")
        y -= 15
        c.setFillColor(colors.HexColor("#0a7a3d"))
        c.drawString(50, y, f"Hotel Price: {b['hotel_price']} SDG")
        c.setFillColor(colors.black)

    y -= 35
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(navy)
    c.drawString(40, y, f"TOTAL: {b['total_price']} SDG")
    c.setFillColor(colors.black)

    # الباركود
    y -= 50
    barcode_val = code128.Code128(b["ref_code"], barHeight=18 * mm, barWidth=0.5)
    barcode_val.drawOn(c, 40, y - barcode_val.height)
    c.setFont("Helvetica", 9)
    c.setFillColor(muted)
    c.drawString(40, y - barcode_val.height - 12, f"Scan at check-in counter - {b['ref_code']}")

    c.setFont("Helvetica-Oblique", 8)
    c.drawCentredString(w / 2, 30, "Dawahi Travel & Tourism Agency — Thank you for booking with us")
    c.showPage()
    c.save()
    return fname


@app.route("/booking/<int:booking_id>")
@login_required
def booking_detail(booking_id):
    user = current_user()
    db = get_db()
    b = db.execute("SELECT * FROM bookings WHERE id=? AND user_id=?", (booking_id, user["id"])).fetchone()
    if not b:
        abort(404)
    flight = db.execute("SELECT * FROM flights WHERE id=?", (b["flight_id"],)).fetchone()
    airline = db.execute("SELECT * FROM airlines WHERE id=?", (flight["airline_id"],)).fetchone()
    room = db.execute("SELECT * FROM rooms WHERE id=?", (b["room_id"],)).fetchone() if b["room_id"] else None
    hotel = db.execute("SELECT * FROM hotels WHERE id=?", (room["hotel_id"],)).fetchone() if room else None

    hotel_html = ""
    if hotel:
        hotel_html = f"""
        <h3>الفندق</h3>
        <p>{hotel['name']} ({'★'*hotel['stars']}) - {hotel['city']}<br>
        الغرفة: {room['room_type']} — من {b['checkin']} إلى {b['checkout']}<br>
        سعر الفندق: <span class="price">{b['hotel_price']} ج.س</span></p>
        """

    status_badge = (
        '<span class="badge" style="color:#e0645a;border-color:#e0645a">ملغاة</span>'
        if b["status"] == "cancelled"
        else '<span class="badge" style="color:#5cc98a;border-color:#5cc98a">مؤكدة</span>'
    )
    cancel_btn = ""
    if b["status"] != "cancelled":
        cancel_btn = f"""
        <form method="post" action="{url_for('cancel_booking', booking_id=b['id'])}"
              onsubmit="return confirm('هل أنت متأكد من إلغاء هذا الحجز؟ لا يمكن التراجع عن هذا الإجراء.');"
              style="display:inline">
          <button class="btn danger" type="submit">إلغاء الحجز</button>
        </form>
        """

    body = f"""
    <h1>تفاصيل الحجز — {b['ref_code']} {status_badge}</h1>
    {flashes_html()}
    <div class="card">
      <h3>الرحلة</h3>
      <p>{airline['name']}: {flight['from_city']} ✈ {flight['to_city']}<br>
      الدرجة: {CLASS_LABELS.get(b['ticket_class'])}<br>
      سعر التذكرة: <span class="price">{b['flight_price']} ج.س</span></p>
      {hotel_html}
      <h3>الإجمالي: <span class="price">{b['total_price']} ج.س</span></h3>
      <a class="btn" href="{url_for('download_ticket', booking_id=b['id'])}">تحميل التذكرة PDF</a>
      <a class="btn secondary" href="{url_for('my_bookings')}">حجوزاتي</a>
      {cancel_btn}
    </div>
    """
    return render_template_string(layout("تفاصيل الحجز", body, user))


@app.route("/booking/<int:booking_id>/cancel", methods=["POST"])
@login_required
def cancel_booking(booking_id):
    user = current_user()
    db = get_db()
    b = db.execute("SELECT * FROM bookings WHERE id=? AND user_id=?", (booking_id, user["id"])).fetchone()
    if not b:
        abort(404)
    if b["status"] == "cancelled":
        flash("هذا الحجز ملغى بالفعل", "error")
    else:
        db.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
        db.commit()
        flash(f"تم إلغاء الحجز {b['ref_code']} بنجاح", "ok")
    return redirect(url_for("booking_detail", booking_id=booking_id))


@app.route("/ticket/<int:booking_id>/download")
@login_required
def download_ticket(booking_id):
    user = current_user()
    db = get_db()
    b = db.execute("SELECT * FROM bookings WHERE id=? AND user_id=?", (booking_id, user["id"])).fetchone()
    if not b or not b["pdf_file"]:
        abort(404)
    return send_from_directory(TICKETS_DIR, b["pdf_file"], as_attachment=True)


@app.route("/my_bookings")
@login_required
def my_bookings():
    user = current_user()
    db = get_db()
    rows = db.execute(
        """SELECT b.*, f.from_city, f.to_city, a.name as airline_name
           FROM bookings b
           JOIN flights f ON f.id=b.flight_id
           JOIN airlines a ON a.id=f.airline_id
           WHERE b.user_id=? ORDER BY b.created_at DESC""",
        (user["id"],),
    ).fetchall()
    items = "".join(
        f"""<div class="flight-row">
              <div>
                <div class="route">{r['from_city']} ✈ {r['to_city']} - {r['airline_name']}</div>
                <div class="subtitle">{r['ref_code']} — {CLASS_LABELS.get(r['ticket_class'])}
                  {'<span class="badge" style="color:#e0645a;border-color:#e0645a">ملغاة</span>' if r['status']=='cancelled' else '<span class="badge" style="color:#5cc98a;border-color:#5cc98a">مؤكدة</span>'}
                </div>
              </div>
              <div class="price">{r['total_price']} ج.س</div>
              <a class="btn small secondary" href="{url_for('booking_detail', booking_id=r['id'])}">التفاصيل</a>
              {f'''<form method="post" action="{url_for('cancel_booking', booking_id=r['id'])}"
                    onsubmit="return confirm('هل أنت متأكد من إلغاء هذا الحجز؟');" style="display:inline">
                    <button class="btn small danger" type="submit">إلغاء</button>
                  </form>''' if r['status'] != 'cancelled' else ''}
            </div>"""
        for r in rows
    )
    body = f"""
    <h1>حجوزاتي</h1>
    {flashes_html()}
    <div class="card">{items or '<p class="subtitle">لا توجد حجوزات بعد</p>'}</div>
    """
    return render_template_string(layout("حجوزاتي", body, user))


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8080))
    print(f"وكالة الدواحي للسفر والسياحة تعمل الآن على المنفذ: {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
else:
    # عند التشغيل عبر gunicorn في الاستضافة، تأكد من تهيئة قاعدة البيانات
    init_db()
