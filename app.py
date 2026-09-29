import os, sqlite3, hashlib, datetime, json, io, base64, re, functools
from flask import Flask, request, jsonify, send_from_directory, g, send_file, session
from flask_cors import CORS
from werkzeug.utils import secure_filename

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
PHOTO_DIR = os.path.join(DATA_DIR, "photos")
QR_DIR = os.path.join(DATA_DIR, "qrcodes")
DB_PATH = os.path.join(DATA_DIR, "attendance.db")

for d in [DATA_DIR, PHOTO_DIR, QR_DIR]:
    os.makedirs(d, exist_ok=True)

app = Flask(__name__, static_folder='frontend', static_url_path='')
_allowed = [o.strip() for o in os.environ.get('ALLOWED_ORIGINS', '').split(',') if o.strip()]
CORS(app, supports_credentials=True, origins=_allowed if _allowed else None)
app.config['MAX_CONTENT_LENGTH'] = 16*1024*1024
app.secret_key = os.environ.get('ATTENDANCE_SECRET', 'dynamic-attendance-rbac-2026-secret-key')
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(hours=12)
# Secure cookies in production (HTTPS). Local HTTP dev unaffected (Secure=False).
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
if os.environ.get('FLASK_ENV') == 'production':
    app.config['SESSION_COOKIE_SECURE'] = True

def get_db():
    db = getattr(g, '_db', None)
    if db is None:
        db = g._db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
    return db

@app.teardown_appcontext
def close_db(exc):
    db = getattr(g, '_db', None)
    if db is not None:
        db.close()

DEFAULT_SUBJECTS = ["English","Hindi","Mathematics","Science","Social Science","Computer"]
EXAM_TYPES = ["Unit Test 1","Unit Test 2","Mid-Term","Final-Term","Pre-Board"]
DEFAULT_CLASSES = [str(i) for i in range(1,13)]
ROLES = ["admin","teacher","student","parent"]
PERMISSIONS = ["dashboard","student_view","add_students","edit_students","delete_students","attendance_view","attendance_edit","marks","fees","reports","holidays","class_management","user_management","settings","notices","notes","complaints","login_history"]

# ---- RBAC MATRIX (Feature -> allowed roles / actions) ----
RBAC = {
    "dashboard":          {"admin":"full", "teacher":"full", "student":"view", "parent":"view"},
    "students":           {"admin":"full", "teacher":"add_edit_view", "student":"none", "parent":"none"},
    "teachers":           {"admin":"full", "teacher":"none", "student":"none", "parent":"none"},
    "parents":            {"admin":"full", "teacher":"none", "student":"none", "parent":"none"},
    "attendance":         {"admin":"full", "teacher":"add_edit_view", "student":"view_own", "parent":"view_child"},
    "enotes":             {"admin":"full", "teacher":"add_edit_view", "student":"view", "parent":"view"},
    "notices":            {"admin":"full", "teacher":"view", "student":"view", "parent":"view"},
    "messages":           {"admin":"full", "teacher":"yes", "student":"view", "parent":"none"},
    "whatsapp":           {"admin":"full", "teacher":"manage", "student":"view", "parent":"view"},
    "complaints":         {"admin":"full", "teacher":"view", "student":"view", "parent":"view"},
    "datesheet":          {"admin":"full", "teacher":"view", "student":"view", "parent":"view"},
    "examinations":       {"admin":"full", "teacher":"manage", "student":"view_own", "parent":"view_child"},
    "reports":            {"admin":"full", "teacher":"attendance", "student":"own", "parent":"child"},
    "settings":           {"admin":"full", "teacher":"none", "student":"none", "parent":"none"},
    "holidays":           {"admin":"full", "teacher":"view", "student":"view", "parent":"view"},
    "classes":            {"admin":"full", "teacher":"view", "student":"view", "parent":"view"},
}

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY,
        school_name TEXT DEFAULT 'Government School',
        logo_path TEXT,
        branding_color TEXT DEFAULT '#0f766e',
        online_mode INTEGER DEFAULT 1,
        address TEXT DEFAULT '',
        contact TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        UNIQUE(class_id, name),
        FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT UNIQUE NOT NULL,
        roll_no TEXT,
        name TEXT NOT NULL,
        class_id INTEGER,
        section_id INTEGER,
        father_name TEXT,
        mother_name TEXT,
        phone TEXT,
        address TEXT,
        dob TEXT,
        photo TEXT,
        created_at TEXT,
        FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE SET NULL,
        FOREIGN KEY(section_id) REFERENCES sections(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        status TEXT CHECK(status IN ('P','A','L','T')) NOT NULL,
        leave_reason TEXT,
        subject_id INTEGER,
        time TEXT DEFAULT '',
        marked_by INTEGER,
        marked_at TEXT,
        session TEXT DEFAULT '',
        UNIQUE(student_id, date, subject_id),
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS academic_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        start_date TEXT,
        end_date TEXT,
        active INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS attendance_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        date TEXT,
        old_status TEXT,
        new_status TEXT,
        changed_by INTEGER,
        changed_at TEXT,
        note TEXT
    );
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT DEFAULT 'info',
        title TEXT,
        content TEXT,
        date TEXT,
        read INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS timetable (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day TEXT NOT NULL,
        period_time TEXT NOT NULL,
        subject_id INTEGER,
        subject_name TEXT,
        class_id INTEGER,
        section_id INTEGER,
        teacher_id INTEGER,
        room TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS attendance_goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scope TEXT DEFAULT 'student',
        ref_id INTEGER,
        target REAL DEFAULT 90,
        updated_by INTEGER,
        updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS review_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        current_status TEXT,
        reason TEXT,
        status TEXT DEFAULT 'Pending',
        response TEXT DEFAULT '',
        created_at TEXT,
        reviewed_by INTEGER,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS qr_sessions (
        token TEXT PRIMARY KEY,
        class_id INTEGER,
        section_id INTEGER,
        subject_id INTEGER,
        date TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        created_by INTEGER,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS school_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        date TEXT,
        venue TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS holidays (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        type TEXT DEFAULT 'Government'
    );
    CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    );
    CREATE TABLE IF NOT EXISTS marks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        subject_id INTEGER NOT NULL,
        exam_type TEXT NOT NULL,
        max_marks INTEGER DEFAULT 100,
        obtained INTEGER NOT NULL,
        UNIQUE(student_id, subject_id, exam_type),
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
        FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        permissions TEXT,
        linked_student_id INTEGER,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        phone TEXT,
        user_id INTEGER,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT,
        subject TEXT,
        phone TEXT,
        assigned_class TEXT,
        user_id INTEGER,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS parents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT,
        email TEXT,
        student_id INTEGER,
        user_id INTEGER,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE SET NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER,
        receiver_id INTEGER,
        content TEXT NOT NULL,
        date TEXT,
        read INTEGER DEFAULT 0,
        FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS notices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT,
        date TEXT
    );
    CREATE TABLE IF NOT EXISTS enotes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        subject TEXT,
        content TEXT,
        file_url TEXT,
        date TEXT
    );
    CREATE TABLE IF NOT EXISTS midday_meals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        class_id INTEGER,
        count INTEGER,
        menu TEXT,
        FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS scholarships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        scheme TEXT NOT NULL,
        amount REAL,
        status TEXT DEFAULT 'Pending',
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS complaints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        name TEXT,
        text TEXT NOT NULL,
        status TEXT DEFAULT 'Open',
        date TEXT
    );
    CREATE TABLE IF NOT EXISTS datesheets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER,
        exam_type TEXT,
        subject TEXT,
        date TEXT,
        time TEXT,
        FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS whatsapp_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER,
        section_id INTEGER,
        link TEXT,
        UNIQUE(class_id, section_id),
        FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE CASCADE,
        FOREIGN KEY(section_id) REFERENCES sections(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS login_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        time TEXT,
        success INTEGER
    );
    """)
    # seed
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM settings"); 
    if cur.fetchone()[0]==0:
        db.execute("INSERT INTO settings (school_name) VALUES ('Government Senior Secondary School')")
    for c in DEFAULT_CLASSES:
        db.execute("INSERT OR IGNORE INTO classes (name) VALUES (?)", (c,))
    for s in DEFAULT_SUBJECTS:
        db.execute("INSERT OR IGNORE INTO subjects (name) VALUES (?)", (s,))
    # default sections A for each class
    for row in db.execute("SELECT id FROM classes"):
        db.execute("INSERT OR IGNORE INTO sections (class_id, name) VALUES (?, 'A')", (row[0],))
    # default admin
    cur.execute("SELECT COUNT(*) FROM users WHERE username='admin'")
    if cur.fetchone()[0]==0:
        ph = hashlib.sha256("admin123".encode()).hexdigest()
        db.execute("INSERT INTO users (username,password_hash,role,permissions,created_at) VALUES (?,?,?,?,?)",
                   ("admin", ph, "admin", json.dumps(PERMISSIONS), datetime.datetime.now().isoformat()))
        db.execute("INSERT INTO users (username,password_hash,role,permissions,created_at) VALUES (?,?,?,?,?)",
                   ("teacher", hashlib.sha256("teacher123".encode()).hexdigest(), "teacher", json.dumps(["dashboard","student_view","attendance_view","attendance_edit","marks","reports"]), datetime.datetime.now().isoformat()))
    # ensure demo student exists for student/parent linkage
    # create demo student if not exists
    cur.execute("SELECT id FROM students WHERE student_id='STU001'")
    demo_sid = cur.fetchone()
    if not demo_sid:
        # use class 1, section A
        cur.execute("SELECT id FROM classes WHERE name='1'")
        c1 = cur.fetchone()
        cid = c1[0] if c1 else 1
        cur.execute("SELECT id FROM sections WHERE class_id=? AND name='A'", (cid,))
        sec = cur.fetchone()
        sid = sec[0] if sec else 1
        try:
            db.execute("INSERT INTO students (student_id, roll_no, name, class_id, section_id, father_name, mother_name, phone, address, dob, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("STU001","01","Aarav Sharma", cid, sid, "Ramesh Sharma","Sunita Sharma","9876543210","Green Valley","2010-05-12", datetime.datetime.now().isoformat()))
            demo_sid = db.execute("SELECT id FROM students WHERE student_id='STU001'").fetchone()[0]
        except: demo_sid = None
    else:
        demo_sid = demo_sid[0]
        try: demo_sid = db.execute("SELECT id FROM students WHERE student_id='STU001'").fetchone()[0]
        except: pass
    # seed student/parent users linked to STU001
    for uname, pwd, role in [("student","student123","student"), ("parent","parent123","parent")]:
        cur.execute("SELECT id FROM users WHERE username=?", (uname,))
        if not cur.fetchone():
            db.execute("INSERT INTO users (username,password_hash,role,permissions,linked_student_id,created_at) VALUES (?,?,?,?,?,?)",
                       (uname, hashlib.sha256(pwd.encode()).hexdigest(), role, json.dumps([]), demo_sid, datetime.datetime.now().isoformat()))
    # ensure teacher has no link
    # migration: add missing columns for old DB
    for col, typ in [("address","TEXT DEFAULT ''"), ("contact","TEXT DEFAULT ''")]:
        try:
            db.execute(f"ALTER TABLE settings ADD COLUMN {col} {typ}")
        except: pass
    # ensure linked_student_id column exists
    try: db.execute("ALTER TABLE users ADD COLUMN linked_student_id INTEGER")
    except: pass
    # multi-school prep: school_id on core tables (default school '1')
    try: db.execute("CREATE TABLE IF NOT EXISTS schools (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
    except: pass
    try:
        if db.execute("SELECT COUNT(*) FROM schools").fetchone()[0]==0:
            db.execute("INSERT INTO schools (name) VALUES ('Default School')")
    except: pass
    for tbl in ["students","teachers","parents","classes","attendance","notices"]:
        try: db.execute(f"ALTER TABLE {tbl} ADD COLUMN school_id INTEGER DEFAULT 1")
        except: pass
    for col, typ in [("gender","TEXT DEFAULT ''"),("admission_no","TEXT DEFAULT ''"),("email","TEXT DEFAULT ''"),("parent_name","TEXT DEFAULT ''"),("parent_contact","TEXT DEFAULT ''")]:
        try: db.execute(f"ALTER TABLE students ADD COLUMN {col} {typ}")
        except: pass
    for col, typ in [("subject_id","INTEGER"),("time","TEXT DEFAULT ''"),("marked_by","INTEGER"),("marked_at","TEXT"),("session","TEXT DEFAULT ''")]:
        try: db.execute(f"ALTER TABLE attendance ADD COLUMN {col} {typ}")
        except: pass
    # migrate old CHECK constraint (P,A,L) -> allow T : recreate if needed
    try:
        sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='attendance'").fetchone()[0] or ""
        if "'T'" not in sql:
            db.execute("ALTER TABLE attendance RENAME TO attendance_old");
            db.executescript("""
            CREATE TABLE attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                status TEXT CHECK(status IN ('P','A','L','T')) NOT NULL,
                leave_reason TEXT,
                subject_id INTEGER,
                time TEXT DEFAULT '',
                marked_by INTEGER,
                marked_at TEXT,
                session TEXT DEFAULT '',
                UNIQUE(student_id, date, subject_id),
                FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
            );
            INSERT OR IGNORE INTO attendance (id,student_id,date,status,leave_reason,subject_id,time,marked_by,marked_at,session)
              SELECT id,student_id,date,status,leave_reason,NULL,'',NULL,NULL,'' FROM attendance_old;
            DROP TABLE attendance_old;
            """)
    except Exception as e:
        pass
    # seed academic sessions
    try:
        if db.execute("SELECT COUNT(*) FROM academic_sessions").fetchone()[0]==0:
            db.execute("INSERT INTO academic_sessions (name,start_date,end_date,active) VALUES (?,?,?,1)", ("2026-27","2026-04-01","2027-03-31",))
            db.execute("INSERT INTO academic_sessions (name,start_date,end_date,active) VALUES (?,?,?,0)", ("2025-26","2025-04-01","2026-03-31",))
    except: pass
    db.commit()
    db.close()

init_db()

def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()

# ---------- RBAC Helpers ----------
def get_current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    db = get_db()
    row = db.execute("SELECT id, username, role, permissions, linked_student_id FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        return None
    return dict(row)

def require_roles(*roles):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            u = get_current_user()
            if not u:
                return jsonify({"error":"Not authenticated"}), 401
            if u['role'] not in roles:
                return jsonify({"error":"Access denied: requires role "+"/".join(roles)}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def require_auth(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        u = get_current_user()
        if not u:
            return jsonify({"error":"Not authenticated"}), 401
        return fn(*args, **kwargs)
    return wrapper

# per-category in-memory rate limits (failures for auth, hits for APIs)
_LOGIN_ATTEMPTS = {}
_API_HITS = {}
def _rate_limited(key, limit=10, window=300):
    import time
    now = time.time()
    arr = _LOGIN_ATTEMPTS.get(key, [])
    arr = [t for t in arr if now - t < window]
    if len(arr) >= limit:
        _LOGIN_ATTEMPTS[key] = arr
        return True
    arr.append(now)
    _LOGIN_ATTEMPTS[key] = arr
    return False

def _api_limited(category, ident, limit, window=60):
    import time
    now = time.time()
    key = f"{category}:{ident}"
    arr = _API_HITS.get(key, [])
    arr = [t for t in arr if now - t < window]
    if len(arr) >= limit:
        _API_HITS[key] = arr
        return True
    arr.append(now)
    _API_HITS[key] = arr
    return False

def _client_id():
    return request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')

# category limits per minute: auth handled separately; attendance high, reports moderate, public generous, admin strict-auth
RATE_LIMITS = {"attendance": (120, 60), "reports": (30, 60), "public": (200, 60), "default": (120, 60)}

def _check_api_rate(category):
    limit, window = RATE_LIMITS.get(category, RATE_LIMITS["default"])
    if _api_limited(category, _client_id(), limit, window):
        return jsonify({"success": False, "error": {"code": "RATE_LIMITED", "message": "Too many requests. Try again later."}}), 429
    return None

def can(role, feature, action="view"):
    # action: add, edit, delete, view, full
    val = RBAC.get(feature, {}).get(role, "none")
    if val == "full": return True
    if action == "view" and val in ["view","view_own","view_child","add_view","add_edit_view","manage","add","yes","full"]: return True
    if action == "add" and val in ["full","add","add_view","add_edit_view","manage"]: return True
    if action == "edit" and val in ["full","add_edit_view","manage","full"]: return True
    if action == "delete" and val == "full": return True
    if val == "none": return False
    # specific
    if val == "view_own" and action=="view": return True
    if val == "view_child" and action=="view": return True
    return False

# ---------- Helpers ----------
def is_holiday(date_str):
    db=get_db()
    r=db.execute("SELECT * FROM holidays WHERE date=?", (date_str,)).fetchone()
    if r: return True
    # Sunday detection
    try:
        d=datetime.datetime.strptime(date_str, "%Y-%m-%d")
        if d.weekday()==6: return True
    except: pass
    return False

# ---------- Routes: School Settings ----------
@app.route('/')
def index():
    return send_from_directory(os.path.join(APP_DIR, 'frontend'), 'index.html')

@app.route('/api/settings', methods=['GET','POST'])
def settings():
    db=get_db()
    u=get_current_user()
    if request.method=='POST' and (not u or not can(u['role'], "settings", "full")):
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='GET':
        row=db.execute("SELECT * FROM settings LIMIT 1").fetchone()
        return jsonify(dict(row) if row else {})
    data=request.get_json() or request.form or {}
    name=(data.get('school_name') or '').strip()
    color=(data.get('branding_color') or '').strip()
    addr=(data.get('address') or '').strip()
    contact=(data.get('contact') or '').strip()
    # allow updating any provided field - use explicit keys check to allow clearing
    if 'school_name' in data:
        db.execute("UPDATE settings SET school_name=? WHERE id=1", (name,))
    if 'branding_color' in data and color:
        db.execute("UPDATE settings SET branding_color=? WHERE id=1", (color,))
    if 'address' in data:
        db.execute("UPDATE settings SET address=? WHERE id=1", (addr,))
    if 'contact' in data:
        db.execute("UPDATE settings SET contact=? WHERE id=1", (contact,))
    db.commit()
    # return updated
    row=db.execute("SELECT * FROM settings LIMIT 1").fetchone()
    return jsonify({"ok":True, "settings": dict(row) if row else {}})

@app.route('/api/settings/logo', methods=['POST','DELETE'])
def upload_logo():
    u=get_current_user()
    if not u or not can(u['role'], "settings", "full"):
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='DELETE':
        # remove logo
        row=get_db().execute("SELECT logo_path FROM settings WHERE id=1").fetchone()
        if row and row[0]:
            try: os.remove(os.path.join(DATA_DIR, row[0]))
            except: pass
        get_db().execute("UPDATE settings SET logo_path=NULL WHERE id=1")
        get_db().commit()
        return jsonify({"ok":True})
    f=request.files.get('logo')
    if not f: return jsonify({"error":"no file"}),400
    if f.content_length and f.content_length > 2*1024*1024:
        return jsonify({"error":"File too large, max 2MB"}),400
    fn=secure_filename(f.filename)
    # validate extension
    ext=os.path.splitext(fn)[1].lower()
    if ext not in ['.png','.jpg','.jpeg','.webp']:
        return jsonify({"error":"Only PNG/JPG/WebP allowed"}),400
    path=os.path.join(DATA_DIR, fn)
    f.save(path)
    get_db().execute("UPDATE settings SET logo_path=? WHERE id=1", (fn,))
    get_db().commit()
    return jsonify({"ok":True, "logo": fn})

@app.route('/api/logo/<path:fn>')
def serve_logo(fn):
    return send_from_directory(DATA_DIR, fn)

@app.route('/data/<path:fn>')
def serve_data(fn):
    return send_from_directory(DATA_DIR, fn)

# ---------- Classes & Sections ----------
@app.route('/api/classes', methods=['GET','POST','DELETE'])
def classes_api():
    db=get_db()
    u=get_current_user()
    if request.method=='GET':
        rows=db.execute("SELECT * FROM classes ORDER BY CAST(name AS INTEGER), name").fetchall()
        out=[]
        for r in rows:
            secs=db.execute("SELECT * FROM sections WHERE class_id=? ORDER BY name", (r['id'],)).fetchall()
            out.append({"id":r['id'],"name":r['name'],"sections":[dict(s) for s in secs]})
        return jsonify(out)
    # POST/DELETE admin only
    if not u or not can(u['role'], "classes", "full"):
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='POST':
        name=(request.get_json() or {}).get('name','').strip()
        if not name: return jsonify({"error":"name required"}),400
        try:
            db.execute("INSERT INTO classes (name) VALUES (?)", (name,))
            cid=db.execute("SELECT id FROM classes WHERE name=?", (name,)).fetchone()[0]
            db.execute("INSERT OR IGNORE INTO sections (class_id,name) VALUES (?, 'A')", (cid,))
            db.commit()
            return jsonify({"ok":True})
        except sqlite3.IntegrityError:
            return jsonify({"error":"Duplicate class"}),400
    # DELETE ?id=1
    cid=request.args.get('id')
    db.execute("DELETE FROM classes WHERE id=?", (cid,))
    db.commit()
    return jsonify({"ok":True})

@app.route('/api/sections', methods=['POST','DELETE'])
def sections_api():
    db=get_db()
    u=get_current_user()
    if not u or not can(u['role'], "classes", "full"):
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='POST':
        d=request.get_json()
        name=(d.get('name') or '').strip().upper()
        # Enforce A-K only
        if name not in list("ABCDEFGHIJK"):
            return jsonify({"error":"Section must be A-K"}),400
        try:
            db.execute("INSERT INTO sections (class_id,name) VALUES (?,?)", (d['class_id'], name))
            db.commit()
            return jsonify({"ok":True})
        except sqlite3.IntegrityError:
            return jsonify({"error":"Duplicate section"}),400
    sid=request.args.get('id')
    # prevent delete if students assigned
    cnt=db.execute("SELECT COUNT(*) FROM students WHERE section_id=?", (sid,)).fetchone()[0]
    if cnt>0:
        return jsonify({"error": f"Cannot delete: {cnt} student(s) assigned"}),400
    db.execute("DELETE FROM sections WHERE id=?", (sid,))
    db.commit()
    return jsonify({"ok":True})

# ---------- Students ----------
@app.route('/api/students', methods=['GET','POST','PUT','DELETE'])
def students_api():
    db=get_db()
    u = get_current_user()
    # Allow public read for dashboard before login? Prefer require auth, but allow if no session for initial demo
    # Enforce isolation for student/parent
    if request.method=='GET':
        # student/parent isolation: only own/child
        if u and u['role'] in ('student','parent') and u.get('linked_student_id'):
            rows=db.execute("SELECT s.*, c.name as class_name, sec.name as section_name FROM students s LEFT JOIN classes c ON s.class_id=c.id LEFT JOIN sections sec ON sec.id=s.section_id WHERE s.id=?", (u['linked_student_id'],)).fetchall()
            return jsonify([dict(r) for r in rows])
        q=request.args.get('q','')
        class_id=request.args.get('class_id')
        section_id=request.args.get('section_id')
        sql="SELECT s.*, c.name as class_name, sec.name as section_name FROM students s LEFT JOIN classes c ON s.class_id=c.id LEFT JOIN sections sec ON s.section_id=sec.id WHERE 1=1"
        params=[]
        if q:
            sql+=" AND (s.name LIKE ? OR s.student_id LIKE ? OR s.roll_no LIKE ?)"
            params+= [f"%{q}%"]*3
        if class_id:
            sql+=" AND s.class_id=?"
            params.append(class_id)
        if section_id:
            sql+=" AND s.section_id=?"
            params.append(section_id)
        sql+=" ORDER BY s.id DESC"
        # pagination: ?page=1&limit=50 (default 50, max 200)
        try: page=max(1,int(request.args.get('page',1)))
        except: page=1
        try: limit=min(200,max(1,int(request.args.get('limit',50))))
        except: limit=50
        # count total for pagination metadata
        count_sql="SELECT COUNT(*) FROM students s WHERE 1=1"
        count_params=[]
        if q: count_sql+=" AND (s.name LIKE ? OR s.student_id LIKE ? OR s.roll_no LIKE ?)"; count_params+= [f"%{q}%"]*3
        if class_id: count_sql+=" AND s.class_id=?"; count_params.append(class_id)
        if section_id: count_sql+=" AND s.section_id=?"; count_params.append(section_id)
        total=db.execute(count_sql, count_params).fetchone()[0]
        sql+=" LIMIT ? OFFSET ?"
        params+=[limit,(page-1)*limit]
        rows=db.execute(sql, params).fetchall()
        # student/parent with no link should see empty
        if u and u['role'] in ('student','parent') and not u.get('linked_student_id'):
            return jsonify({"success":True,"data":[],"page":page,"limit":limit,"total":0})
        # backward compat: plain list unless ?paged=1
        if request.args.get('paged')=='1':
            return jsonify({"success":True,"data":[dict(r) for r in rows],"page":page,"limit":limit,"total":total})
        return jsonify([dict(r) for r in rows])
    if request.method=='POST':
        if not u or not can(u['role'], "students", "add"):
            return jsonify({"error":"Access denied: cannot add students"}),403
        # multipart or json
        if request.content_type and 'multipart' in request.content_type:
            d=request.form
            photo=request.files.get('photo')
        else:
            d=request.get_json() or {}
            photo=None
        sid=d.get('student_id','').strip()
        if not sid: return jsonify({"error":"Student ID required"}),400
        if db.execute("SELECT id FROM students WHERE student_id=?", (sid,)).fetchone():
            return jsonify({"error":"Duplicate Student ID"}),400
        photo_name=""
        if photo and photo.filename:
            fn=secure_filename(f"{sid}_{photo.filename}")
            photo.save(os.path.join(PHOTO_DIR, fn))
            photo_name=fn
        # also support base64 photo
        elif d.get('photo_base64'):
            try:
                b64=d['photo_base64'].split(',')[-1]
                data=base64.b64decode(b64)
                fn=f"{sid}_photo.jpg"
                open(os.path.join(PHOTO_DIR, fn),'wb').write(data)
                photo_name=fn
            except: pass
        try:
            db.execute("""INSERT INTO students (student_id,roll_no,name,class_id,section_id,father_name,mother_name,phone,address,dob,photo,created_at,gender,admission_no,email,parent_name,parent_contact)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (sid, d.get('roll_no'), d.get('name'), d.get('class_id') or None, d.get('section_id') or None,
                        d.get('father_name'), d.get('mother_name'), d.get('phone'), d.get('address'), d.get('dob'), photo_name, datetime.datetime.now().isoformat(),
                        d.get('gender',''), d.get('admission_no',''), d.get('email',''), d.get('parent_name') or d.get('father_name',''), d.get('parent_contact') or d.get('phone','')))
            db.commit()
        except sqlite3.IntegrityError as e:
            return jsonify({"error": f"Invalid class/section: {e}"}),400
        # generate QR
        try:
            import qrcode
            img=qrcode.make(sid)
            img.save(os.path.join(QR_DIR, f"{sid}.png"))
        except: pass
        return jsonify({"ok":True})
    if request.method=='PUT':
        if not u or not can(u['role'], "students", "edit"):
            return jsonify({"error":"Access denied: cannot edit students"}),403
        # support both JSON and multipart for photo update
        if request.content_type and 'multipart' in request.content_type:
            d=request.form
            photo=request.files.get('photo')
            sid=d.get('id')
            photo_name=None
            if photo and photo.filename:
                # get existing student_id for filename
                row=db.execute("SELECT student_id FROM students WHERE id=?", (sid,)).fetchone()
                if row:
                    fn=secure_filename(f"{row[0]}_{photo.filename}")
                    photo.save(os.path.join(PHOTO_DIR, fn))
                    photo_name=fn
            # update with photo if provided
            if photo_name:
                db.execute("""UPDATE students SET name=?, roll_no=?, class_id=?, section_id=?, father_name=?, mother_name=?, phone=?, address=?, dob=?, photo=? WHERE id=?""",
                           (d.get('name'), d.get('roll_no'), d.get('class_id') or None, d.get('section_id') or None, d.get('father_name'), d.get('mother_name'), d.get('phone'), d.get('address'), d.get('dob'), photo_name, sid))
            else:
                db.execute("""UPDATE students SET name=?, roll_no=?, class_id=?, section_id=?, father_name=?, mother_name=?, phone=?, address=?, dob=? WHERE id=?""",
                           (d.get('name'), d.get('roll_no'), d.get('class_id') or None, d.get('section_id') or None, d.get('father_name'), d.get('mother_name'), d.get('phone'), d.get('address'), d.get('dob'), sid))
            db.commit()
            return jsonify({"ok":True})
        d=request.get_json() or {}
        sid=d.get('id')
        try:
            db.execute("""UPDATE students SET name=?, roll_no=?, class_id=?, section_id=?, father_name=?, mother_name=?, phone=?, address=?, dob=?, gender=?, admission_no=?, email=?, parent_name=?, parent_contact=? WHERE id=?""",
                       (d.get('name'), d.get('roll_no'), d.get('class_id'), d.get('section_id'), d.get('father_name'), d.get('mother_name'), d.get('phone'), d.get('address'), d.get('dob'), d.get('gender',''), d.get('admission_no',''), d.get('email',''), d.get('parent_name',''), d.get('parent_contact',''), sid))
        except Exception:
            db.execute("""UPDATE students SET name=?, roll_no=?, class_id=?, section_id=?, father_name=?, mother_name=?, phone=?, address=?, dob=? WHERE id=?""",
                       (d.get('name'), d.get('roll_no'), d.get('class_id'), d.get('section_id'), d.get('father_name'), d.get('mother_name'), d.get('phone'), d.get('address'), d.get('dob'), sid))
        db.commit()
        return jsonify({"ok":True})
    # DELETE
    if not u or not can(u['role'], "students", "delete"):
        return jsonify({"error":"Access denied: cannot delete students"}),403
    sid=request.args.get('id')
    db.execute("DELETE FROM students WHERE id=?", (sid,))
    db.commit()
    return jsonify({"ok":True})

@app.route('/api/students/<sid>/qr')
def qr_api(sid):
    # sid is student_id string
    path=os.path.join(QR_DIR, f"{sid}.png")
    if not os.path.exists(path):
        try:
            import qrcode
            img=qrcode.make(sid)
            img.save(path)
        except:
            return jsonify({"error":"QR generation failed"}),500
    return send_file(path, mimetype='image/png')

@app.route('/api/photos/<fn>')
def photo_api(fn):
    return send_from_directory(PHOTO_DIR, fn)

# ---------- Attendance ----------
@app.route('/api/attendance', methods=['GET','POST'])
def attendance_api():
    db=get_db()
    if request.method=='GET':
        date=request.args.get('date') or datetime.date.today().isoformat()
        class_id=request.args.get('class_id')
        section_id=request.args.get('section_id')
        # list students + attendance for date
        u=get_current_user()
        if u and u['role'] in ('student','parent') and u.get('linked_student_id'):
            sql="SELECT s.*, a.status, a.leave_reason FROM students s LEFT JOIN attendance a ON a.student_id=s.id AND a.date=? WHERE s.id=?"
            params=[date, u['linked_student_id']]
            rows=db.execute(sql, params).fetchall()
            holiday=is_holiday(date)
            holiday_row=db.execute("SELECT * FROM holidays WHERE date=?", (date,)).fetchone()
            return jsonify({"date":date, "is_holiday": holiday, "holiday": dict(holiday_row) if holiday_row else None, "students":[dict(r) for r in rows]})
        subject_id=request.args.get('subject_id')
        sql="SELECT s.*, a.status, a.leave_reason, a.time, a.subject_id FROM students s LEFT JOIN attendance a ON a.student_id=s.id AND a.date=? "
        if subject_id:
            sql+=" AND (a.subject_id=? OR a.subject_id IS NULL)"
        sql+=" WHERE 1=1"
        params=[date]
        if subject_id:
            params.append(subject_id)
        if class_id:
            sql+=" AND s.class_id=?"
            params.append(class_id)
        if section_id:
            sql+=" AND s.section_id=?"
            params.append(section_id)
        sql+=" ORDER BY CAST(s.roll_no AS INTEGER), s.name"
        # pagination for large class lists
        try: page=max(1,int(request.args.get('page',1)))
        except: page=1
        try: limit=min(200,max(1,int(request.args.get('limit',100))))
        except: limit=100
        if request.args.get('paged')=='1':
            sql+=" LIMIT ? OFFSET ?"
            params+=[limit,(page-1)*limit]
        rows=db.execute(sql, params).fetchall()
        # also check holiday
        holiday=is_holiday(date)
        holiday_row=db.execute("SELECT * FROM holidays WHERE date=?", (date,)).fetchone()
        out={"date":date, "is_holiday": holiday, "holiday": dict(holiday_row) if holiday_row else None, "students":[dict(r) for r in rows]}
        if request.args.get('paged')=='1':
            out.update({"success":True,"page":page,"limit":limit})
        return jsonify(out)
    # POST bulk mark
    hit=_check_api_rate("attendance")
    if hit: return hit
    u=get_current_user()
    if not u or not can(u['role'], "attendance", "add"):
        return jsonify({"success":False,"error":{"code":"FORBIDDEN","message":"Access denied: cannot mark attendance"}}),403
    data=request.get_json() or {}
    date=data.get('date')
    if not date:
        return jsonify({"error":"date required"}),400
    if is_holiday(date):
        return jsonify({"error":"Cannot mark attendance on holiday/Sunday"}),400
    subject_id=data.get('subject_id')
    session_name=data.get('session') or ''
    entries=data.get('entries',[]) # [{student_id, status, leave_reason, time}]
    valid_status=('P','A','L','T')
    now=datetime.datetime.now().isoformat()
    for e in entries:
        sid=e['student_id']
        st=(e.get('status') or 'P').upper()
        if st not in valid_status:
            return jsonify({"error":f"Invalid status {st}. Use P/A/L/T"}),400
        if not db.execute("SELECT id FROM students WHERE id=?", (sid,)).fetchone():
            return jsonify({"error":f"Invalid student_id {sid}"}),400
        tm=e.get('time') or datetime.datetime.now().strftime("%H:%M")
        # audit: capture old
        if subject_id:
            old=db.execute("SELECT status FROM attendance WHERE student_id=? AND date=? AND subject_id=?", (sid,date,subject_id)).fetchone()
        else:
            old=db.execute("SELECT status FROM attendance WHERE student_id=? AND date=? AND (subject_id IS NULL OR subject_id='')", (sid,date)).fetchone()
        old_status=old[0] if old else None
        if subject_id:
            db.execute("INSERT OR REPLACE INTO attendance (student_id,date,status,leave_reason,subject_id,time,marked_by,marked_at,session) VALUES (?,?,?,?,?,?,?,?,?)",
                       (sid, date, st, e.get('leave_reason',''), subject_id, tm, u['id'], now, session_name))
        else:
            db.execute("INSERT OR REPLACE INTO attendance (student_id,date,status,leave_reason,time,marked_by,marked_at,session) VALUES (?,?,?,?,?,?,?,?)",
                       (sid, date, st, e.get('leave_reason',''), tm, u['id'], now, session_name))
        if old_status and old_status!=st:
            db.execute("INSERT INTO attendance_logs (student_id,date,old_status,new_status,changed_by,changed_at,note) VALUES (?,?,?,?,?,?,?)",
                       (sid,date,old_status,st,u['id'],now,f"subject:{subject_id or '-'} session:{session_name}"))
        # absence alert -> notification for linked parent/student
        if st=='A':
            srow=db.execute("SELECT name FROM students WHERE id=?", (sid,)).fetchone()
            sname=srow[0] if srow else f"ID {sid}"
            # find parent/user linked
            for prow in db.execute("SELECT id FROM users WHERE linked_student_id=?", (sid,)).fetchall():
                db.execute("INSERT INTO notifications (user_id,type,title,content,date) VALUES (?,?,?, ?,?)",
                           (prow[0],"alert","Absence Alert",f"Your child {sname} was marked absent on {date}.",now))
    db.commit()
    return jsonify({"ok":True, "saved":len(entries)})

@app.route('/api/attendance/scan', methods=['POST'])
def scan_attendance():
    u=get_current_user()
    if not u or not can(u['role'], "attendance", "add"):
        return jsonify({"error":"Access denied: cannot scan attendance"}),403
    d=request.get_json()
    student_code=d.get('code','').strip() # student_id string
    status=d.get('status','P')
    date=d.get('date') or datetime.date.today().isoformat()
    if is_holiday(date):
        return jsonify({"error":"Holiday - attendance blocked"}),400
    db=get_db()
    row=db.execute("SELECT id FROM students WHERE student_id=?", (student_code,)).fetchone()
    if not row: return jsonify({"error":"Student not found"}),404
    db.execute("INSERT OR REPLACE INTO attendance (student_id,date,status) VALUES (?,?,?)", (row[0], date, status))
    db.commit()
    return jsonify({"ok":True, "student_id": student_code})

@app.route('/api/attendance/dashboard')
def attendance_dashboard():
    db=get_db()
    date=request.args.get('date') or datetime.date.today().isoformat()
    class_id=request.args.get('class_id')
    section_id=request.args.get('section_id')
    subject_id=request.args.get('subject_id')
    # base students
    sql="SELECT COUNT(*) FROM students WHERE 1=1"
    params=[]
    if class_id: sql+=" AND class_id=?"; params.append(class_id)
    if section_id: sql+=" AND section_id=?"; params.append(section_id)
    total=db.execute(sql, params).fetchone()[0]
    # present etc
    sql2="SELECT status, COUNT(*) c FROM attendance a JOIN students s ON s.id=a.student_id WHERE a.date=? "
    params2=[date]
    if class_id: sql2+=" AND s.class_id=?"; params2.append(class_id)
    if section_id: sql2+=" AND s.section_id=?"; params2.append(section_id)
    if subject_id: sql2+=" AND a.subject_id=?"; params2.append(subject_id)
    sql2+=" GROUP BY status"
    rows=db.execute(sql2, params2).fetchall()
    m={r['status']:r['c'] for r in rows}
    present=m.get('P',0); absent=m.get('A',0); leave=m.get('L',0); late=m.get('T',0)
    not_marked= total - present - absent - leave - late
    pct= round(((present+late)/total*100) if total else 0,1)
    # weekday
    try: dow=datetime.datetime.strptime(date, "%Y-%m-%d").strftime("%A")
    except: dow=""
    # active session
    try:
        sess=db.execute("SELECT name FROM academic_sessions WHERE active=1").fetchone()
        session_name=sess[0] if sess else "2026-27"
    except: session_name="2026-27"
    return jsonify({"date":date, "weekday":dow, "total":total, "present":present, "absent":absent, "leave":leave, "late":late, "not_marked": max(not_marked,0), "percentage":pct, "session":session_name})

# ---------- Academic Sessions ----------
@app.route('/api/sessions', methods=['GET','POST','DELETE'])
def sessions_api():
    db=get_db()
    u=get_current_user()
    if request.method=='GET':
        rows=db.execute("SELECT * FROM academic_sessions ORDER BY name DESC").fetchall()
        return jsonify([dict(r) for r in rows])
    if not u or u['role']!='admin':
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='POST':
        d=request.get_json() or {}
        name=(d.get('name') or '').strip()
        if not name: return jsonify({"error":"name required (e.g. 2026-27)"}),400
        try:
            db.execute("INSERT INTO academic_sessions (name,start_date,end_date,active) VALUES (?,?,?,?)",
                       (name, d.get('start_date'), d.get('end_date'), 1 if d.get('active') else 0))
            if d.get('active'):
                db.execute("UPDATE academic_sessions SET active=0 WHERE name!=?", (name,))
            db.commit()
            return jsonify({"ok":True})
        except sqlite3.IntegrityError:
            return jsonify({"error":"Duplicate session"}),400
    sid=request.args.get('id')
    db.execute("DELETE FROM academic_sessions WHERE id=?", (sid,))
    db.commit()
    return jsonify({"ok":True})

# ---------- Attendance Calendar (monthly day-wise) ----------
@app.route('/api/calendar')
def calendar_api():
    db=get_db()
    month=request.args.get('month')  # YYYY-MM
    class_id=request.args.get('class_id')
    section_id=request.args.get('section_id')
    if not month: return jsonify({"error":"month required YYYY-MM"}),400
    import calendar as calmod
    y,m=month.split('-')
    y=int(y); m=int(m)
    days=calmod.monthrange(y,m)[1]
    out=[]
    for d in range(1, days+1):
        ds=f"{y:04d}-{m:02d}-{d:02d}"
        sql="SELECT status, COUNT(*) c FROM attendance a JOIN students s ON s.id=a.student_id WHERE a.date=? "
        params=[ds]
        if class_id: sql+=" AND s.class_id=?"; params.append(class_id)
        if section_id: sql+=" AND s.section_id=?"; params.append(section_id)
        sql+=" GROUP BY status"
        rows=db.execute(sql, params).fetchall()
        mm={r['status']:r['c'] for r in rows}
        total=sum(mm.values())
        pct=round(((mm.get('P',0)+mm.get('T',0))/total*100) if total else 0,1)
        out.append({"date":ds,"weekday":datetime.datetime.strptime(ds,"%Y-%m-%d").strftime("%a"),"present":mm.get('P',0),"absent":mm.get('A',0),"leave":mm.get('L',0),"late":mm.get('T',0),"total":total,"percentage":pct,"is_holiday":is_holiday(ds)})
    return jsonify({"month":month,"days":out})

# ---------- Analytics ----------
@app.route('/api/analytics')
def analytics_api():
    db=get_db()
    class_id=request.args.get('class_id')
    section_id=request.args.get('section_id')
    # weekly last 7 days
    weekly=[]
    for i in range(6,-1,-1):
        d=(datetime.date.today()-datetime.timedelta(days=i)).isoformat()
        sql="SELECT status, COUNT(*) c FROM attendance a JOIN students s ON s.id=a.student_id WHERE a.date=? "
        params=[d]
        if class_id: sql+=" AND s.class_id=?"; params.append(class_id)
        if section_id: sql+=" AND s.section_id=?"; params.append(section_id)
        sql+=" GROUP BY status"
        rows=db.execute(sql, params).fetchall()
        mm={r['status']:r['c'] for r in rows}
        total=sum(mm.values())
        pct=round(((mm.get('P',0)+mm.get('T',0))/total*100) if total else 0,1)
        weekly.append({"date":d,"present":mm.get('P',0),"absent":mm.get('A',0),"late":mm.get('T',0),"leave":mm.get('L',0),"percentage":pct})
    # monthly last 6 months
    monthly=[]
    today=datetime.date.today()
    for k in range(5,-1,-1):
        yy=today.year; mm_=today.month-k
        while mm_<=0: mm_+=12; yy-=1
        mkey=f"{yy:04d}-{mm_:02d}"
        sql="SELECT status, COUNT(*) c FROM attendance a JOIN students s ON s.id=a.student_id WHERE substr(a.date,1,7)=? "
        params=[mkey]
        if class_id: sql+=" AND s.class_id=?"; params.append(class_id)
        if section_id: sql+=" AND s.section_id=?"; params.append(section_id)
        sql+=" GROUP BY status"
        rows=db.execute(sql, params).fetchall()
        mm={r['status']:r['c'] for r in rows}
        total=sum(mm.values())
        pct=round(((mm.get('P',0)+mm.get('T',0))/total*100) if total else 0,1)
        monthly.append({"month":mkey,"percentage":pct,"present":mm.get('P',0),"absent":mm.get('A',0)})
    # class comparison
    comp=[]
    for r in db.execute("SELECT id, name FROM classes ORDER BY CAST(name AS INTEGER) LIMIT 12"):
        sql="SELECT COUNT(*) FROM students WHERE class_id=?"; params=[r['id']]
        total=db.execute(sql, params).fetchone()[0]
        prow=db.execute("SELECT COUNT(*) FROM attendance a JOIN students s ON s.id=a.student_id WHERE s.class_id=? AND a.status IN ('P','T')", (r['id'],)).fetchone()[0]
        arow=db.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='P'", (datetime.date.today().isoformat(),)).fetchone()[0]
        comp.append({"class":r['name'],"total":total,"present_records":prow})
    # low attendance students (<75% this month)
    mkey=today.strftime("%Y-%m")
    holidays_set=set(x[0] for x in db.execute("SELECT date FROM holidays").fetchall())
    import calendar as calmod
    dim=calmod.monthrange(today.year,today.month)[1]
    working=sum(1 for d in range(1,dim+1) if datetime.datetime.strptime(f"{today.year:04d}-{today.month:02d}-{d:02d}","%Y-%m-%d").weekday()!=6 and f"{today.year:04d}-{today.month:02d}-{d:02d}" not in holidays_set)
    sql="SELECT s.id,s.student_id,s.name FROM students s WHERE 1=1"
    params=[]
    if class_id: sql+=" AND s.class_id=?"; params.append(class_id)
    if section_id: sql+=" AND s.section_id=?"; params.append(section_id)
    low=[]; high=[]
    for s in db.execute(sql, params).fetchall():
        p=db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status IN ('P','T') AND substr(date,1,7)=?", (s['id'], mkey)).fetchone()[0]
        pct=round(p/working*100,1) if working else 0
        entry={"student_id":s['student_id'],"name":s['name'],"percentage":pct,"present":p}
        if pct<75 and working>0: low.append(entry)
        if pct>=95 and working>0: high.append(entry)
    low=sorted(low,key=lambda x:x['percentage'])[:10]
    high=sorted(high,key=lambda x:-x['percentage'])[:10]
    return jsonify({"weekly":weekly,"monthly":monthly,"class_comparison":comp,"low_attendance":low,"high_attendance":high,"working_days":working})

# ---------- Notifications ----------
@app.route('/api/notifications', methods=['GET','POST','DELETE'])
def notifications_api():
    db=get_db()
    u=get_current_user()
    if not u: return jsonify({"error":"Not authenticated"}),401
    if request.method=='GET':
        unread_only=request.args.get('unread')=='1'
        sql="SELECT * FROM notifications WHERE user_id=? "
        params=[u['id']]
        if unread_only: sql+=" AND read=0"
        sql+=" ORDER BY id DESC LIMIT 50"
        rows=db.execute(sql, params).fetchall()
        unread=db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0", (u['id'],)).fetchone()[0]
        return jsonify({"notifications":[dict(r) for r in rows],"unread":unread})
    if request.method=='POST':
        # admin can broadcast, others limited
        d=request.get_json() or {}
        if u['role']!='admin':
            return jsonify({"error":"Access denied: Admin only for broadcast"}),403
        # broadcast to all users or specific
        target=d.get('user_id')
        now=datetime.datetime.now().isoformat()
        if target:
            db.execute("INSERT INTO notifications (user_id,type,title,content,date) VALUES (?,?,?,?,?)",(target,d.get('type','info'),d.get('title'),d.get('content'),now))
        else:
            for row in db.execute("SELECT id FROM users"):
                db.execute("INSERT INTO notifications (user_id,type,title,content,date) VALUES (?,?,?,?,?)",(row[0],d.get('type','info'),d.get('title'),d.get('content'),now))
        db.commit()
        return jsonify({"ok":True})
    # DELETE = mark read
    nid=request.args.get('id')
    if nid=='all':
        db.execute("UPDATE notifications SET read=1 WHERE user_id=?", (u['id'],))
    elif nid:
        db.execute("UPDATE notifications SET read=1 WHERE id=? AND user_id=?", (nid,u['id']))
    else:
        return jsonify({"error":"id required"}),400
    db.commit()
    return jsonify({"ok":True})

# ---------- Audit logs ----------
@app.route('/api/audit')
def audit_api():
    db=get_db()
    u=get_current_user()
    if not u or u['role'] not in ('admin','teacher'):
        return jsonify({"error":"Access denied"}),403
    rows=db.execute("SELECT l.*, s.name as student_name, usr.username as changed_by_name FROM attendance_logs l LEFT JOIN students s ON s.id=l.student_id LEFT JOIN users usr ON usr.id=l.changed_by ORDER BY l.id DESC LIMIT 100").fetchall()
    return jsonify([dict(r) for r in rows])

# ---------- Holidays ----------
@app.route('/api/holidays', methods=['GET','POST','DELETE'])
def holidays_api():
    db=get_db()
    u=get_current_user()
    if request.method!='GET' and (not u or not can(u['role'], "holidays", "full")):
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='GET':
        rows=db.execute("SELECT * FROM holidays ORDER BY date").fetchall()
        return jsonify([dict(r) for r in rows])
    if request.method=='POST':
        d=request.get_json()
        db.execute("INSERT OR REPLACE INTO holidays (date,name,type) VALUES (?,?,?)", (d['date'], d['name'], d.get('type','Custom')))
        db.commit()
        return jsonify({"ok":True})
    hid=request.args.get('id')
    if hid:
        db.execute("DELETE FROM holidays WHERE id=?", (hid,))
    else:
        d=request.args.get('date')
        if d: db.execute("DELETE FROM holidays WHERE date=?", (d,))
    db.commit()
    return jsonify({"ok":True})

# ---------- Subjects & Marks ----------
@app.route('/api/subjects', methods=['GET','POST','DELETE'])
def subjects_api():
    db=get_db()
    u=get_current_user()
    if request.method!='GET' and (not u or not can(u['role'], "settings", "full")):
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='GET':
        return jsonify([dict(r) for r in db.execute("SELECT * FROM subjects ORDER BY name").fetchall()])
    if request.method=='POST':
        name=request.get_json().get('name','').strip()
        if not name: return jsonify({"error":"name required"}),400
        try:
            db.execute("INSERT INTO subjects (name) VALUES (?)", (name,))
            db.commit()
            return jsonify({"ok":True})
        except sqlite3.IntegrityError:
            return jsonify({"error":"Duplicate"}),400
    sid=request.args.get('id')
    db.execute("DELETE FROM subjects WHERE id=?", (sid,))
    db.commit()
    return jsonify({"ok":True})

@app.route('/api/marks', methods=['GET','POST'])
def marks_api():
    db=get_db()
    u=get_current_user()
    if request.method=='POST' and (not u or not can(u['role'], "examinations", "add")):
        return jsonify({"error":"Access denied: cannot manage marks"}),403
    if request.method=='GET':
        student_id=request.args.get('student_id')
        exam_type=request.args.get('exam_type')
        sql="SELECT m.*, s.name as subject_name FROM marks m JOIN subjects s ON s.id=m.subject_id WHERE 1=1"
        params=[]
        if student_id: sql+=" AND m.student_id=?"; params.append(student_id)
        if exam_type: sql+=" AND m.exam_type=?"; params.append(exam_type)
        rows=db.execute(sql, params).fetchall()
        return jsonify([dict(r) for r in rows])
    d=request.get_json() or {}
    # bulk save: {student_id, exam_type, marks:[{subject_id, max_marks, obtained}]}
    student_id=d.get('student_id')
    exam_type=d.get('exam_type')
    if not student_id or not exam_type or not d.get('marks'):
        return jsonify({"error":"student_id, exam_type and marks required"}),400
    if not db.execute("SELECT id FROM students WHERE id=?", (student_id,)).fetchone():
        return jsonify({"error":"Invalid student_id"}),400
    for m in d.get('marks',[]) or []:
        if not db.execute("SELECT id FROM subjects WHERE id=?", (m.get('subject_id'),)).fetchone():
            return jsonify({"error":f"Invalid subject_id {m.get('subject_id')}"}),400
        try:
            db.execute("INSERT OR REPLACE INTO marks (student_id, subject_id, exam_type, max_marks, obtained) VALUES (?,?,?,?,?)",
                       (student_id, m['subject_id'], exam_type, m.get('max_marks',100), m['obtained']))
        except sqlite3.IntegrityError as e:
            return jsonify({"error":str(e)}),400
    db.commit()
    return jsonify({"ok":True})

@app.route('/api/marks/report')
def marks_report():
    db=get_db()
    class_id=request.args.get('class_id')
    exam_type=request.args.get('exam_type')
    sql="""SELECT st.id, st.student_id, st.name, st.roll_no, c.name as class_name, sec.name as sec_name
           FROM students st LEFT JOIN classes c ON c.id=st.class_id LEFT JOIN sections sec ON sec.id=st.section_id WHERE 1=1"""
    params=[]
    if class_id: sql+=" AND st.class_id=?"; params.append(class_id)
    rows=db.execute(sql, params).fetchall()
    out=[]
    for r in rows:
        marks=db.execute("SELECT m.*, s.name as subject_name FROM marks m JOIN subjects s ON s.id=m.subject_id WHERE m.student_id=? AND m.exam_type=?", (r['id'], exam_type)).fetchall() if exam_type else []
        total_obt=sum(x['obtained'] for x in marks)
        total_max=sum(x['max_marks'] for x in marks)
        pct= round(total_obt/total_max*100,1) if total_max else 0
        out.append({"student":dict(r), "marks":[dict(x) for x in marks], "total_obt":total_obt, "total_max":total_max, "pct":pct})
    return jsonify(out)

# ---------- Monthly Attendance ----------
@app.route('/api/monthly')
def monthly_api():
    hit=_check_api_rate("reports")
    if hit: return hit
    db=get_db()
    month=request.args.get('month') # YYYY-MM
    class_id=request.args.get('class_id')
    section_id=request.args.get('section_id')
    if not month: return jsonify({"error":"month required YYYY-MM"}),400
    y,m=month.split('-')
    import calendar
    days_in_month=calendar.monthrange(int(y),int(m))[1]
    # working days = exclude holidays + Sundays
    holidays_set=set(r[0] for r in db.execute("SELECT date FROM holidays").fetchall())
    working=[]
    for d in range(1, days_in_month+1):
        ds=f"{y}-{m.zfill(2)}-{str(d).zfill(2)}"
        dow=datetime.datetime.strptime(ds, "%Y-%m-%d").weekday()
        if dow==6: continue
        if ds in holidays_set: continue
        working.append(ds)
    sql="SELECT s.id, s.student_id, s.name, s.roll_no FROM students s WHERE 1=1"
    params=[]
    if class_id: sql+=" AND s.class_id=?"; params.append(class_id)
    if section_id: sql+=" AND s.section_id=?"; params.append(section_id)
    students=db.execute(sql, params).fetchall()
    out=[]
    for s in students:
        # counts
        present=db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='P' AND substr(date,1,7)=?", (s['id'], month)).fetchone()[0]
        absent=db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='A' AND substr(date,1,7)=?", (s['id'], month)).fetchone()[0]
        leave=db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='L' AND substr(date,1,7)=?", (s['id'], month)).fetchone()[0]
        pct= round(present/len(working)*100,1) if working else 0
        out.append({"student":dict(s), "present":present, "absent":absent, "leave":leave, "working_days":len(working), "pct":pct})
    return jsonify({"month":month, "working_days":len(working), "working_dates":working, "students":out})

# ---------- Reports & Exports ----------
@app.route('/api/export/monthly/excel')
def export_monthly_excel():
    hit=_check_api_rate("reports")
    if hit: return hit
    # heavy report -> background-friendly: paginate students (limit 500)
    month=request.args.get('month')
    class_id=request.args.get('class_id')
    section_id=request.args.get('section_id')
    # reuse logic
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    db=get_db()
    y,m=month.split('-')
    import calendar
    days_in_month=calendar.monthrange(int(y),int(m))[1]
    holidays_set=set(r[0] for r in db.execute("SELECT date FROM holidays").fetchall())
    working=[]
    for d in range(1, days_in_month+1):
        ds=f"{y}-{m.zfill(2)}-{str(d).zfill(2)}"
        if datetime.datetime.strptime(ds, "%Y-%m-%d").weekday()==6: continue
        if ds in holidays_set: continue
        working.append(ds)
    sql="SELECT s.id, s.student_id, s.name, s.roll_no FROM students s WHERE 1=1"
    params=[]
    if class_id: sql+=" AND s.class_id=?"; params.append(class_id)
    if section_id: sql+=" AND s.section_id=?"; params.append(section_id)
    students=db.execute(sql, params).fetchall()
    wb=openpyxl.Workbook()
    ws=wb.active
    ws.title=f"Monthly {month}"
    headers=["Roll","Student ID","Name","Present","Absent","Leave","Working Days","%"]
    ws.append(headers)
    for c in ws[1]: c.font=Font(bold=True, color="FFFFFF"); c.fill=PatternFill(start_color="0f766e", end_color="0f766e", fill_type="solid")
    for s in students:
        present=db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='P' AND substr(date,1,7)=?", (s['id'], month)).fetchone()[0]
        absent=db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='A' AND substr(date,1,7)=?", (s['id'], month)).fetchone()[0]
        leave=db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='L' AND substr(date,1,7)=?", (s['id'], month)).fetchone()[0]
        pct= round(present/len(working)*100,1) if working else 0
        ws.append([s['roll_no'], s['student_id'], s['name'], present, absent, leave, len(working), pct])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width=14
    bio=io.BytesIO()
    wb.save(bio); bio.seek(0)
    return send_file(bio, as_attachment=True, download_name=f"monthly_{month}.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route('/api/export/monthly/pdf')
def export_monthly_pdf():
    month=request.args.get('month')
    db=get_db()
    y,m=month.split('-')
    import calendar
    days_in_month=calendar.monthrange(int(y),int(m))[1]
    holidays_set=set(r[0] for r in db.execute("SELECT date FROM holidays").fetchall())
    working=[f"{y}-{m.zfill(2)}-{str(d).zfill(2)}" for d in range(1,days_in_month+1) if datetime.datetime.strptime(f"{y}-{m.zfill(2)}-{str(d).zfill(2)}", "%Y-%m-%d").weekday()!=6 and f"{y}-{m.zfill(2)}-{str(d).zfill(2)}" not in holidays_set]
    students=db.execute("SELECT s.id, s.student_id, s.name, s.roll_no FROM students s").fetchall()
    bio=io.BytesIO()
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet
    doc=SimpleDocTemplate(bio, pagesize=A4)
    styles=getSampleStyleSheet()
    elems=[Paragraph(f"Monthly Attendance Report - {month} (Working Days: {len(working)})", styles['Title'])]
    data=[["Roll","Student ID","Name","P","A","L","%"]]
    for s in students:
        present=db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='P' AND substr(date,1,7)=?", (s['id'], month)).fetchone()[0]
        absent=db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='A' AND substr(date,1,7)=?", (s['id'], month)).fetchone()[0]
        leave=db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status='L' AND substr(date,1,7)=?", (s['id'], month)).fetchone()[0]
        pct= round(present/len(working)*100,1) if working else 0
        data.append([s['roll_no'] or '', s['student_id'], s['name'], str(present), str(absent), str(leave), str(pct)])
    t=Table(data, repeatRows=1)
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor("#0f766e")),('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),('GRID',(0,0),(-1,-1),0.5,colors.grey),('FONTSIZE',(0,0),(-1,-1),8)]))
    elems.append(t)
    doc.build(elems); bio.seek(0)
    return send_file(bio, as_attachment=True, download_name=f"monthly_{month}.pdf", mimetype="application/pdf")

# ---------- Auth & Users ----------
@app.route('/api/auth/login', methods=['POST'])
def login():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
    d=request.get_json() or {}
    u=(d.get('username') or '').strip(); p=d.get('password') or ''
    # role selection from frontend is NOT trusted – we ignore d.get('role')
    row=get_db().execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()
    success=0
    if row and row['password_hash']==hash_pw(p):
        success=1
        get_db().execute("INSERT INTO login_history (username,time,success) VALUES (?,?,?)", (u, datetime.datetime.now().isoformat(), 1))
        get_db().commit()
        _LOGIN_ATTEMPTS.pop(f"login:{ip}", None)
        session.permanent = True
        session['user_id'] = row['id']
        session['role'] = row['role']
        session['username'] = row['username']
        return jsonify({"ok":True, "user":{"id":row['id'],"username":row['username'],"role":row['role'],"permissions":json.loads(row['permissions'] or '[]'),"linked_student_id":row['linked_student_id']}})
    # failed: rate-limit only failures (do not reveal whether username exists)
    if _rate_limited(f"login:{ip}", limit=10, window=300):
        return jsonify({"success": False, "error": {"code": "RATE_LIMITED", "message": "Too many unsuccessful login attempts. Please try again later."}}), 429
    get_db().execute("INSERT INTO login_history (username,time,success) VALUES (?,?,?)", (u, datetime.datetime.now().isoformat(), 0))
    get_db().commit()
    return jsonify({"error":"Invalid credentials"}),401

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"ok":True})

@app.route('/api/auth/me', methods=['GET'])
def me():
    u = get_current_user()
    if not u:
        return jsonify({"user":None}), 200
    # include linked student details if student/parent
    linked = None
    if u.get('linked_student_id'):
        row = get_db().execute("SELECT s.*, c.name as class_name, sec.name as section_name FROM students s LEFT JOIN classes c ON c.id=s.class_id LEFT JOIN sections sec ON sec.id=s.section_id WHERE s.id=?", (u['linked_student_id'],)).fetchone()
        if row: linked = dict(row)
    return jsonify({"user":u, "linked_student": linked})

@app.route('/api/auth/check', methods=['GET'])
def auth_check():
    u = get_current_user()
    if not u:
        return jsonify({"authenticated":False}), 401
    return jsonify({"authenticated":True, "user":u})

@app.route('/api/users', methods=['GET','POST','DELETE'])
def users_api():
    db=get_db()
    u=get_current_user()
    if not u or not can(u['role'], "teachers", "full"):
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='GET':
        rows=db.execute("SELECT id,username,role,permissions,created_at FROM users ORDER BY id").fetchall()
        return jsonify([dict(r) for r in rows])
    if request.method=='POST':
        d=request.get_json()
        try:
            db.execute("INSERT INTO users (username,password_hash,role,permissions,created_at) VALUES (?,?,?,?,?)",
                       (d['username'], hash_pw(d['password']), d['role'], json.dumps(d.get('permissions',[])), datetime.datetime.now().isoformat()))
            db.commit()
            return jsonify({"ok":True})
        except sqlite3.IntegrityError:
            return jsonify({"error":"Duplicate username"}),400
    uid=request.args.get('id')
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    return jsonify({"ok":True})

@app.route('/api/login_history')
def login_history():
    rows=get_db().execute("SELECT * FROM login_history ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify([dict(r) for r in rows])

# ---------- Staff ----------
@app.route('/api/staff', methods=['GET','POST','DELETE'])
def staff_api():
    db=get_db()
    u=get_current_user()
    if request.method!='GET' and (not u or not can(u['role'], "teachers", "full")):
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='GET':
        return jsonify([dict(r) for r in db.execute("SELECT * FROM staff ORDER BY id DESC").fetchall()])
    if request.method=='POST':
        d=request.get_json()
        db.execute("INSERT INTO staff (name,role,phone) VALUES (?,?,?)", (d['name'], d['role'], d.get('phone')))
        db.commit()
        return jsonify({"ok":True})
    sid=request.args.get('id')
    db.execute("DELETE FROM staff WHERE id=?", (sid,))
    db.commit()
    return jsonify({"ok":True})

# ---------- Teachers (RBAC) ----------
@app.route('/api/teachers', methods=['GET','POST','DELETE'])
def teachers_api():
    db=get_db()
    u=get_current_user()
    if request.method=='GET':
        if not u or not can(u['role'], "teachers", "view"):
            # students/parents cannot view teachers list per matrix
            if u and u['role'] in ('student','parent'):
                return jsonify([]), 200
        return jsonify([dict(r) for r in db.execute("SELECT * FROM teachers ORDER BY id DESC").fetchall()])
    if not u or not can(u['role'], "teachers", "full"):
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='POST':
        d=request.get_json()
        db.execute("INSERT INTO teachers (name,email,subject,phone,assigned_class) VALUES (?,?,?,?,?)",
                   (d.get('name'), d.get('email'), d.get('subject'), d.get('phone'), d.get('assigned_class')))
        db.commit()
        return jsonify({"ok":True})
    tid=request.args.get('id')
    db.execute("DELETE FROM teachers WHERE id=?", (tid,))
    db.commit()
    return jsonify({"ok":True})

# ---------- Parents (RBAC) ----------
@app.route('/api/parents', methods=['GET','POST','DELETE'])
def parents_api():
    db=get_db()
    u=get_current_user()
    if request.method=='GET':
        if u and u['role'] in ('student','parent'):
            return jsonify([]), 200
        if not u or not can(u['role'], "parents", "view"):
            # teacher cannot view parents
            if u and u['role']=='teacher':
                return jsonify([]), 200
        return jsonify([dict(r) for r in db.execute("SELECT p.*, s.name as student_name FROM parents p LEFT JOIN students s ON s.id=p.student_id ORDER BY p.id DESC").fetchall()])
    if not u or not can(u['role'], "parents", "full"):
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='POST':
        d=request.get_json()
        # validate student exists if provided
        if d.get('student_id') and not db.execute("SELECT id FROM students WHERE id=?", (d.get('student_id'),)).fetchone():
            return jsonify({"error":"Invalid student_id"}),400
        db.execute("INSERT INTO parents (name,phone,email,student_id) VALUES (?,?,?,?)",
                   (d.get('name'), d.get('phone'), d.get('email'), d.get('student_id')))
        db.commit()
        return jsonify({"ok":True})
    pid=request.args.get('id')
    db.execute("DELETE FROM parents WHERE id=?", (pid,))
    db.commit()
    return jsonify({"ok":True})

# ---------- Messages ----------
@app.route('/api/messages', methods=['GET','POST','DELETE'])
def messages_api():
    db=get_db()
    u=get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}),401
    if request.method=='GET':
        # teacher/admin see all, student sees where they are receiver, parent none
        if u['role']=='admin' or u['role']=='teacher':
            rows=db.execute("SELECT m.*, su.username as sender_name, ru.username as receiver_name FROM messages m LEFT JOIN users su ON su.id=m.sender_id LEFT JOIN users ru ON ru.id=m.receiver_id ORDER BY m.id DESC LIMIT 50").fetchall()
            return jsonify([dict(r) for r in rows])
        elif u['role']=='student':
            rows=db.execute("SELECT m.*, su.username as sender_name FROM messages m LEFT JOIN users su ON su.id=m.sender_id WHERE m.receiver_id=? ORDER BY m.id DESC LIMIT 20", (u['id'],)).fetchall()
            return jsonify([dict(r) for r in rows])
        else:
            return jsonify([])
    # POST - only admin/teacher, student as permitted limited
    if u['role']=='parent':
        return jsonify({"error":"Access denied: cannot send messages"}),403
    if request.method=='POST':
        d=request.get_json()
        if not d.get('content'): return jsonify({"error":"content required"}),400
        # student can only send if permitted (for now allow but limited)
        db.execute("INSERT INTO messages (sender_id, receiver_id, content, date) VALUES (?,?,?,?)",
                   (u['id'], d.get('receiver_id'), d.get('content'), datetime.datetime.now().isoformat()))
        db.commit()
        return jsonify({"ok":True})
    mid=request.args.get('id')
    if u['role']!='admin':
        return jsonify({"error":"Access denied"}),403
    db.execute("DELETE FROM messages WHERE id=?", (mid,))
    db.commit()
    return jsonify({"ok":True})

# ---------- Notices ----------
@app.route('/api/notices', methods=['GET','POST','DELETE'])
def notices_api():
    db=get_db()
    u=get_current_user()
    if request.method!='GET' and (not u or not can(u['role'], "notices", "full")):
        return jsonify({"error":"Access denied: Admin only for notices"}),403
    if request.method=='GET':
        return jsonify([dict(r) for r in db.execute("SELECT * FROM notices ORDER BY id DESC").fetchall()])
    if request.method=='POST':
        d=request.get_json()
        db.execute("INSERT INTO notices (title,content,date) VALUES (?,?,?)", (d['title'], d['content'], datetime.date.today().isoformat()))
        db.commit()
        return jsonify({"ok":True})
    nid=request.args.get('id')
    db.execute("DELETE FROM notices WHERE id=?", (nid,))
    db.commit()
    return jsonify({"ok":True})

# ---------- E-Notes ----------
@app.route('/api/enotes', methods=['GET','POST','DELETE'])
def enotes_api():
    db=get_db()
    u=get_current_user()
    if request.method!='GET' and (not u or not can(u['role'], "enotes", "add")):
        return jsonify({"error":"Access denied: cannot manage notes"}),403
    if request.method=='GET':
        return jsonify([dict(r) for r in db.execute("SELECT * FROM enotes ORDER BY id DESC").fetchall()])
    if request.method=='POST':
        d=request.get_json()
        db.execute("INSERT INTO enotes (title,subject,content,date) VALUES (?,?,?,?)", (d['title'], d.get('subject'), d.get('content'), datetime.date.today().isoformat()))
        db.commit()
        return jsonify({"ok":True})
    nid=request.args.get('id')
    db.execute("DELETE FROM enotes WHERE id=?", (nid,))
    db.commit()
    return jsonify({"ok":True})

# ---------- Mid-Day Meal ----------
@app.route('/api/meals', methods=['GET','POST','DELETE'])
def meals_api():
    db=get_db()
    u=get_current_user()
    if request.method!='GET' and (not u or u['role']!='admin'):
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='GET':
        return jsonify([dict(r) for r in db.execute("SELECT * FROM midday_meals ORDER BY date DESC").fetchall()])
    if request.method=='POST':
        d=request.get_json()
        if d.get('class_id') and not db.execute("SELECT id FROM classes WHERE id=?", (d.get('class_id'),)).fetchone():
            return jsonify({"error":"Invalid class_id"}),400
        try:
            db.execute("INSERT INTO midday_meals (date,class_id,count,menu) VALUES (?,?,?,?)", (d.get('date') or datetime.date.today().isoformat(), d.get('class_id') or None, d.get('count'), d.get('menu')))
            db.commit()
        except sqlite3.IntegrityError as e:
            return jsonify({"error":str(e)}),400
        return jsonify({"ok":True})
    mid=request.args.get('id')
    db.execute("DELETE FROM midday_meals WHERE id=?", (mid,))
    db.commit()
    return jsonify({"ok":True})

# ---------- Scholarships ----------
@app.route('/api/scholarships', methods=['GET','POST','DELETE'])
def scholarships_api():
    db=get_db()
    u=get_current_user()
    if request.method!='GET' and (not u or u['role']!='admin'):
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='GET':
        rows=db.execute("SELECT sch.*, s.name as student_name, s.student_id as sid FROM scholarships sch JOIN students s ON s.id=sch.student_id ORDER BY sch.id DESC").fetchall()
        return jsonify([dict(r) for r in rows])
    if request.method=='POST':
        d=request.get_json()
        if not d.get('student_id') or not d.get('scheme'):
            return jsonify({"error":"student_id and scheme required"}),400
        if not db.execute("SELECT id FROM students WHERE id=?", (d.get('student_id'),)).fetchone():
            return jsonify({"error":"Invalid student_id"}),400
        try:
            db.execute("INSERT INTO scholarships (student_id,scheme,amount,status) VALUES (?,?,?,?)", (d['student_id'], d['scheme'], d.get('amount'), d.get('status','Pending')))
            db.commit()
        except sqlite3.IntegrityError as e:
            return jsonify({"error":str(e)}),400
        return jsonify({"ok":True})
    sid=request.args.get('id')
    db.execute("DELETE FROM scholarships WHERE id=?", (sid,))
    db.commit()
    return jsonify({"ok":True})

# ---------- Complaints ----------
@app.route('/api/complaints', methods=['GET','POST','DELETE'])
def complaints_api():
    db=get_db()
    if request.method=='GET':
        return jsonify([dict(r) for r in db.execute("SELECT * FROM complaints ORDER BY id DESC").fetchall()])
    if request.method=='POST':
        d=request.get_json()
        db.execute("INSERT INTO complaints (student_id,name,text,status,date) VALUES (?,?,?,?,?)", (d.get('student_id'), d.get('name'), d['text'], 'Open', datetime.date.today().isoformat()))
        db.commit()
        return jsonify({"ok":True})
    cid=request.args.get('id')
    # toggle status if provided
    if request.args.get('status'):
        db.execute("UPDATE complaints SET status=? WHERE id=?", (request.args.get('status'), cid))
        db.commit()
        return jsonify({"ok":True})
    db.execute("DELETE FROM complaints WHERE id=?", (cid,))
    db.commit()
    return jsonify({"ok":True})

# ---------- DateSheet ----------
@app.route('/api/datesheets', methods=['GET','POST','DELETE'])
def datesheets_api():
    db=get_db()
    u=get_current_user()
    if request.method!='GET' and (not u or not can(u['role'], "datesheet", "full")):
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='GET':
        return jsonify([dict(r) for r in db.execute("SELECT d.*, c.name as class_name FROM datesheets d LEFT JOIN classes c ON c.id=d.class_id ORDER BY d.date").fetchall()])
    if request.method=='POST':
        d=request.get_json()
        if d.get('class_id') and not db.execute("SELECT id FROM classes WHERE id=?", (d.get('class_id'),)).fetchone():
            return jsonify({"error":"Invalid class_id"}),400
        try:
            db.execute("INSERT INTO datesheets (class_id,exam_type,subject,date,time) VALUES (?,?,?,?,?)", (d.get('class_id') or None, d.get('exam_type'), d.get('subject'), d.get('date'), d.get('time')))
            db.commit()
        except sqlite3.IntegrityError as e:
            return jsonify({"error":str(e)}),400
        return jsonify({"ok":True})
    did=request.args.get('id')
    db.execute("DELETE FROM datesheets WHERE id=?", (did,))
    db.commit()
    return jsonify({"ok":True})

# ---------- WhatsApp / Communication ----------
@app.route('/api/whatsapp', methods=['GET','POST'])
def whatsapp_api():
    db=get_db()
    u=get_current_user()
    if request.method=='POST' and (not u or not can(u['role'], "whatsapp", "add")):
        return jsonify({"error":"Access denied: cannot manage WhatsApp"}),403
    if request.method=='GET':
        rows=db.execute("SELECT w.*, c.name as class_name, s.name as section_name FROM whatsapp_groups w LEFT JOIN classes c ON c.id=w.class_id LEFT JOIN sections s ON s.id=w.section_id").fetchall()
        return jsonify([dict(r) for r in rows])
    d=request.get_json()
    if not d.get('class_id') or not d.get('section_id') or not d.get('link'):
        return jsonify({"error":"class_id, section_id and link required"}),400
    # validate FK exists
    if not db.execute("SELECT id FROM classes WHERE id=?", (d['class_id'],)).fetchone():
        return jsonify({"error":"Invalid class_id"}),400
    if not db.execute("SELECT id FROM sections WHERE id=?", (d['section_id'],)).fetchone():
        return jsonify({"error":"Invalid section_id - section may have been deleted"}),400
    try:
        db.execute("INSERT OR REPLACE INTO whatsapp_groups (class_id,section_id,link) VALUES (?,?,?)", (d['class_id'], d['section_id'], d['link']))
        db.commit()
    except sqlite3.IntegrityError as e:
        return jsonify({"error": str(e)}),400
    return jsonify({"ok":True})

# ---------- Dashboard Summary ----------
@app.route('/api/dashboard/summary')
def dashboard_summary():
    db=get_db()
    total_students=db.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    total_classes=db.execute("SELECT COUNT(*) FROM classes").fetchone()[0]
    today=datetime.date.today().isoformat()
    try: total_teachers=db.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]
    except: total_teachers=db.execute("SELECT COUNT(*) FROM staff").fetchone()[0]
    try: total_parents=db.execute("SELECT COUNT(*) FROM parents").fetchone()[0]
    except: total_parents=0
    if not is_holiday(today):
        present=db.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='P'", (today,)).fetchone()[0]
        absent=db.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='A'", (today,)).fetchone()[0]
        late=db.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='T'", (today,)).fetchone()[0]
        leave=db.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='L'", (today,)).fetchone()[0]
    else:
        present=absent=late=leave=0
    rate=round(((present+late)/total_students*100) if total_students else 0,2)
    holidays_cnt=db.execute("SELECT COUNT(*) FROM holidays").fetchone()[0]
    notices_cnt=db.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
    complaints_open=db.execute("SELECT COUNT(*) FROM complaints WHERE status='Open'").fetchone()[0]
    try:
        sess=db.execute("SELECT name FROM academic_sessions WHERE active=1").fetchone()
        session_name=sess[0] if sess else "2026-27"
    except: session_name="2026-27"
    return jsonify({"total_students":total_students, "total_classes":total_classes, "total_teachers":total_teachers, "total_parents":total_parents, "present_today":present, "absent_today":absent, "late_today":late, "leave_today":leave, "attendance_rate":rate, "holidays":holidays_cnt, "notices":notices_cnt, "complaints_open":complaints_open, "date":today, "is_holiday": is_holiday(today), "session":session_name})

# ---------- Smart Insights (computed from DB, never hardcoded) ----------
@app.route('/api/insights')
def insights_api():
    db=get_db()
    u=get_current_user()
    class_id=request.args.get('class_id')
    out=[]
    today=datetime.date.today()
    this_m=today.strftime("%Y-%m")
    # prev month
    py=today.year; pm=today.month-1
    if pm<=0: pm+=12; py-=1
    prev_m=f"{py:04d}-{pm:02d}"
    def pct_for(month, cid=None):
        sql="SELECT COUNT(*) FROM attendance a JOIN students s ON s.id=a.student_id WHERE substr(a.date,1,7)=? AND a.status IN ('P','T') "
        params=[month]
        if cid: sql+=" AND s.class_id=?"; params.append(cid)
        p=db.execute(sql, params).fetchone()[0]
        sql2="SELECT COUNT(*) FROM attendance a JOIN students s ON s.id=a.student_id WHERE substr(a.date,1,7)=? "
        params2=[month]
        if cid: sql2+=" AND s.class_id=?"; params2.append(cid)
        t=db.execute(sql2, params2).fetchone()[0]
        return round(p/t*100,1) if t else None
    # class improvement: compare this vs prev month per class
    for r in db.execute("SELECT id, name FROM classes ORDER BY CAST(name AS INTEGER) LIMIT 12"):
        if class_id and str(r['id'])!=str(class_id): continue
        cur=pct_for(this_m, r['id']); prev=pct_for(prev_m, r['id'])
        if cur is not None and prev is not None and cur>prev:
            out.append({"icon":"🏅","title":"Attendance Improvement","text":f"Class {r['name']} improved from {prev}% to {cur}% vs last month.","class":r['name']})
    # best class this month
    best=None; bestv=-1
    for r in db.execute("SELECT id, name FROM classes"):
        v=pct_for(this_m, r['id'])
        if v is not None and v>bestv: bestv=v; best=r['name']
    if best: out.append({"icon":"🏆","title":"Highest Attendance","text":f"Class {best} has the highest attendance this month ({bestv}%).","class":best})
    # weekday pattern: lowest weekday
    wd={0:0,1:0,2:0,3:0,4:0,5:0,6:0}; wdt={0:0,1:0,2:0,3:0,4:0,5:0,6:0}
    for row in db.execute("SELECT date, status FROM attendance WHERE substr(date,1,7)=?", (this_m,)):
        try: w=datetime.datetime.strptime(row['date'],"%Y-%m-%d").weekday()
        except: continue
        wdt[w]+=1
        if row['status'] in ('P','T'): wd[w]+=1
    if sum(wdt.values())>0:
        rates={k: round(wd[k]/wdt[k]*100,1) if wdt[k] else 100 for k in wdt}
        lowday=min(rates, key=lambda k: rates[k])
        names=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        if wdt[lowday]>=3:
            out.append({"icon":"📉","title":"Weekday Pattern","text":f"Attendance is lower than usual on {names[lowday]} ({rates[lowday]}%).","weekday":names[lowday]})
    # late trend this week
    week_ago=(today-datetime.timedelta(days=7)).isoformat()
    late_now=db.execute("SELECT COUNT(*) FROM attendance WHERE date>=? AND status='T'", (week_ago,)).fetchone()[0]
    late_prev=db.execute("SELECT COUNT(*) FROM attendance WHERE date<? AND date>=? AND status='T'", (week_ago,(today-datetime.timedelta(days=14)).isoformat())).fetchone()[0]
    if late_now>late_prev and late_now>0:
        out.append({"icon":"🟡","title":"Late Arrivals","text":f"Late arrivals increased this week ({late_prev} → {late_now})."})
    # low attendance count
    import calendar as calmod
    dim=calmod.monthrange(today.year,today.month)[1]
    hset=set(x[0] for x in db.execute("SELECT date FROM holidays").fetchall())
    working=sum(1 for d in range(1,dim+1) if datetime.datetime.strptime(f"{today.year:04d}-{today.month:02d}-{d:02d}","%Y-%m-%d").weekday()!=6 and f"{today.year:04d}-{today.month:02d}-{d:02d}" not in hset)
    low_n=0
    if working>0:
        for s in db.execute("SELECT id FROM students"):
            p=db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status IN ('P','T') AND substr(date,1,7)=?", (s['id'], this_m)).fetchone()[0]
            if round(p/working*100,1)<75: low_n+=1
    out.append({"icon":"⚠️","title":"Low Attendance Watch","text":f"{low_n} students below 75% this month (working days {working})."})
    return jsonify(out)

# ---------- Heatmap (date x class) ----------
@app.route('/api/heatmap')
def heatmap_api():
    db=get_db()
    month=request.args.get('month') or datetime.date.today().strftime("%Y-%m")
    section_id=request.args.get('section_id')
    import calendar as calmod
    y,m=map(int, month.split('-'))
    dim=calmod.monthrange(y,m)[1]
    classes=list(db.execute("SELECT id, name FROM classes ORDER BY CAST(name AS INTEGER) LIMIT 12"))
    grid=[]
    for r in classes:
        row={"class":r['name'],"class_id":r['id'],"days":[]}
        for d in range(1, dim+1):
            ds=f"{y:04d}-{m:02d}-{d:02d}"
            sql="SELECT status, COUNT(*) c FROM attendance a JOIN students s ON s.id=a.student_id WHERE a.date=? AND s.class_id=? "
            params=[ds, r['id']]
            if section_id: sql+=" AND s.section_id=?"; params.append(section_id)
            sql+=" GROUP BY status"
            rows=db.execute(sql, params).fetchall()
            mm={x['status']:x['c'] for x in rows}
            tot=sum(mm.values())
            pct=round(((mm.get('P',0)+mm.get('T',0))/tot*100) if tot else -1,1)
            level="none" if pct<0 else ("high" if pct>=90 else ("medium" if pct>=75 else "low"))
            row["days"].append({"date":ds,"percentage":pct,"level":level,"total":tot})
        grid.append(row)
    return jsonify({"month":month,"grid":grid})

# ---------- Goals ----------
@app.route('/api/goals', methods=['GET','POST'])
def goals_api():
    db=get_db()
    u=get_current_user()
    if request.method=='GET':
        student_id=request.args.get('student_id')
        # student/parent see own/child only
        if u and u['role'] in ('student','parent') and u.get('linked_student_id'):
            student_id=str(u['linked_student_id'])
        if not student_id:
            return jsonify({"error":"student_id required"}),400
        g=db.execute("SELECT * FROM attendance_goals WHERE scope='student' AND ref_id=?", (student_id,)).fetchone()
        target=(g['target'] if g else 90)
        # current month pct
        today=datetime.date.today(); mkey=today.strftime("%Y-%m")
        import calendar as calmod
        dim=calmod.monthrange(today.year,today.month)[1]
        hset=set(x[0] for x in db.execute("SELECT date FROM holidays").fetchall())
        working=sum(1 for d in range(1,dim+1) if datetime.datetime.strptime(f"{today.year:04d}-{today.month:02d}-{d:02d}","%Y-%m-%d").weekday()!=6 and f"{today.year:04d}-{today.month:02d}-{d:02d}" not in hset)
        p=db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status IN ('P','T') AND substr(date,1,7)=?", (student_id, mkey)).fetchone()[0]
        cur=round(p/working*100,1) if working else 0
        remaining=round(max(0,target-cur),1)
        return jsonify({"student_id":student_id,"current":cur,"target":target,"remaining":remaining,"working_days":working,"present":p})
    # POST: admin/teacher set target
    if not u or u['role'] not in ('admin','teacher'):
        return jsonify({"error":"Access denied"}),403
    d=request.get_json() or {}
    try:
        db.execute("INSERT OR REPLACE INTO attendance_goals (scope,ref_id,target,updated_by,updated_at) VALUES ('student',?,?,?,?)",
                   (d.get('student_id'), float(d.get('target',90)), u['id'], datetime.datetime.now().isoformat()))
        db.commit()
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"error":str(e)}),400

# ---------- Achievements (badges, class-level only) ----------
@app.route('/api/achievements')
def achievements_api():
    db=get_db()
    today=datetime.date.today(); this_m=today.strftime("%Y-%m")
    py=today.year; pm=today.month-1
    if pm<=0: pm+=12; py-=1
    prev_m=f"{py:04d}-{pm:02d}"
    def pct(month, cid):
        p=db.execute("SELECT COUNT(*) FROM attendance a JOIN students s ON s.id=a.student_id WHERE substr(a.date,1,7)=? AND s.class_id=? AND a.status IN ('P','T')", (month,cid)).fetchone()[0]
        t=db.execute("SELECT COUNT(*) FROM attendance a JOIN students s ON s.id=a.student_id WHERE substr(a.date,1,7)=? AND s.class_id=?", (month,cid)).fetchone()[0]
        return round(p/t*100,1) if t else None
    badges=[]
    for r in db.execute("SELECT id, name FROM classes"):
        cur=pct(this_m, r['id']); prev=pct(prev_m, r['id'])
        if cur is not None and prev is not None and cur>prev:
            badges.append({"badge":"🏅 Attendance Improvement","class":r['name'],"text":f"Class {r['name']} improved {prev}% → {cur}%."})
        if cur is not None and cur>=95:
            badges.append({"badge":"✅ Consistent Attendance","class":r['name'],"text":f"Class {r['name']} at {cur}% this month."})
    return jsonify(badges[:12])

# ---------- Alert Center ----------
@app.route('/api/alerts')
def alerts_api():
    db=get_db()
    u=get_current_user()
    if not u: return jsonify({"error":"Not authenticated"}),401
    today=datetime.date.today().isoformat()
    abs_today=db.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='A'", (today,)).fetchone()[0]
    late_today=db.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='T'", (today,)).fetchone()[0]
    # low attendance count
    tm=datetime.date.today().strftime("%Y-%m")
    import calendar as calmod
    t=datetime.date.today(); dim=calmod.monthrange(t.year,t.month)[1]
    hset=set(x[0] for x in db.execute("SELECT date FROM holidays").fetchall())
    working=sum(1 for d in range(1,dim+1) if datetime.datetime.strptime(f"{t.year:04d}-{t.month:02d}-{d:02d}","%Y-%m-%d").weekday()!=6 and f"{t.year:04d}-{t.month:02d}-{d:02d}" not in hset)
    low=0
    if working:
        for s in db.execute("SELECT id FROM students"):
            p=db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status IN ('P','T') AND substr(date,1,7)=?", (s['id'], tm)).fetchone()[0]
            if round(p/working*100,1)<75: low+=1
    pending_review=db.execute("SELECT COUNT(*) FROM review_requests WHERE status='Pending'").fetchone()[0]
    notices=db.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
    unread=db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0", (u['id'],)).fetchone()[0] if u else 0
    alerts=[
        {"type":"absence","icon":"🔴","text":f"{abs_today} students absent today","count":abs_today},
        {"type":"late","icon":"🟡","text":f"{late_today} late arrivals today","count":late_today},
        {"type":"low","icon":"⚠️","text":f"{low} students have low attendance","count":low},
        {"type":"review","icon":"🔵","text":f"{pending_review} attendance records require review","count":pending_review},
        {"type":"notice","icon":"📢","text":f"{notices} school notices","count":notices},
        {"type":"unread","icon":"🔔","text":f"{unread} unread notifications","count":unread},
    ]
    return jsonify(alerts)

# ---------- Timetable ----------
@app.route('/api/timetable', methods=['GET','POST','DELETE'])
def timetable_api():
    db=get_db()
    u=get_current_user()
    if request.method=='GET':
        day=request.args.get('day') or datetime.datetime.now().strftime("%A")
        sql="SELECT t.*, c.name as class_name, s.name as section_name FROM timetable t LEFT JOIN classes c ON c.id=t.class_id LEFT JOIN sections s ON s.id=t.section_id WHERE 1=1 "
        params=[]
        if request.args.get('day'): sql+=" AND t.day=?"; params.append(request.args.get('day'))
        if request.args.get('class_id'): sql+=" AND t.class_id=?"; params.append(request.args.get('class_id'))
        sql+=" ORDER BY t.period_time"
        rows=db.execute(sql, params).fetchall()
        # mark completed if attendance exists for that class today
        today=datetime.date.today().isoformat()
        out=[]
        for r in rows:
            d=dict(r)
            cnt=0
            if r['class_id']:
                cnt=db.execute("SELECT COUNT(*) FROM attendance a JOIN students st ON st.id=a.student_id WHERE a.date=? AND st.class_id=?", (today, r['class_id'])).fetchone()[0]
            d['completed']=cnt>0
            out.append(d)
        return jsonify(out)
    if not u or u['role']!='admin':
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='POST':
        d=request.get_json() or {}
        db.execute("INSERT INTO timetable (day,period_time,subject_id,subject_name,class_id,section_id,teacher_id,room) VALUES (?,?,?,?,?,?,?,?)",
                   (d.get('day'), d.get('period_time'), d.get('subject_id'), d.get('subject_name'), d.get('class_id'), d.get('section_id'), d.get('teacher_id'), d.get('room','')))
        db.commit()
        return jsonify({"ok":True})
    tid=request.args.get('id')
    db.execute("DELETE FROM timetable WHERE id=?", (tid,))
    db.commit()
    return jsonify({"ok":True})

# ---------- Parent Snapshot ----------
@app.route('/api/snapshot')
def snapshot_api():
    db=get_db()
    u=get_current_user()
    if not u or u['role'] not in ('parent','student','admin','teacher'):
        return jsonify({"error":"Not authenticated"}),401
    sid=request.args.get('student_id') or (u.get('linked_student_id') if u['role'] in ('student','parent') else None)
    if not sid: return jsonify({"error":"student_id required"}),400
    # isolation
    if u['role'] in ('student','parent') and str(u.get('linked_student_id'))!=str(sid):
        return jsonify({"error":"Access denied"}),403
    s=db.execute("SELECT s.*, c.name as class_name, sec.name as section_name FROM students s LEFT JOIN classes c ON c.id=s.class_id LEFT JOIN sections sec ON sec.id=s.section_id WHERE s.id=?", (sid,)).fetchone()
    if not s: return jsonify({"error":"Not found"}),404
    today=datetime.date.today().isoformat()
    trow=db.execute("SELECT status FROM attendance WHERE student_id=? AND date=? ORDER BY rowid DESC LIMIT 1", (sid,today)).fetchone()
    mkey=datetime.date.today().strftime("%Y-%m")
    import calendar as calmod
    t=datetime.date.today(); dim=calmod.monthrange(t.year,t.month)[1]
    hset=set(x[0] for x in db.execute("SELECT date FROM holidays").fetchall())
    working=sum(1 for d in range(1,dim+1) if datetime.datetime.strptime(f"{t.year:04d}-{t.month:02d}-{d:02d}","%Y-%m-%d").weekday()!=6 and f"{t.year:04d}-{t.month:02d}-{d:02d}" not in hset)
    p=db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=? AND status IN ('P','T') AND substr(date,1,7)=?", (sid,mkey)).fetchone()[0]
    pct=round(p/working*100,1) if working else 0
    recent=[dict(r) for r in db.execute("SELECT date,status,time FROM attendance WHERE student_id=? ORDER BY date DESC LIMIT 7", (sid,)).fetchall()]
    upcoming=[dict(r) for r in db.execute("SELECT * FROM datesheets ORDER BY date LIMIT 3")]
    notices=[dict(r) for r in db.execute("SELECT * FROM notices ORDER BY id DESC LIMIT 3")]
    return jsonify({"student":dict(s),"today":trow[0] if trow else None,"percentage":pct,"recent":recent,"upcoming":upcoming,"notices":notices})

# ---------- Digital Student ID ----------
@app.route('/api/student_id_card')
def id_card_api():
    db=get_db()
    u=get_current_user()
    sid=request.args.get('student_id') or (u.get('linked_student_id') if u and u['role'] in ('student','parent') else None)
    if not sid: return jsonify({"error":"student_id required"}),400
    if u and u['role'] in ('student','parent') and str(u.get('linked_student_id'))!=str(sid):
        return jsonify({"error":"Access denied"}),403
    s=db.execute("SELECT s.student_id,s.name,s.roll_no,c.name as class_name,sec.name as section_name,s.photo FROM students s LEFT JOIN classes c ON c.id=s.class_id LEFT JOIN sections sec ON sec.id=s.section_id WHERE s.id=?", (sid,)).fetchone()
    if not s: return jsonify({"error":"Not found"}),404
    sch=db.execute("SELECT school_name, logo_path FROM settings WHERE id=1").fetchone()
    # QR must not expose sensitive info: only student_id code
    return jsonify({"school":sch['school_name'] if sch else '',"logo":sch['logo_path'] if sch else None,"student_id":s['student_id'],"name":s['name'],"class":s['class_name'],"section":s['section_name'],"roll":s['roll_no'],"photo":s['photo'],"qr_url":f"/api/students/{s['student_id']}/qr"})

# ---------- Timeline ----------
@app.route('/api/timeline')
def timeline_api():
    db=get_db()
    u=get_current_user()
    sid=request.args.get('student_id') or (u.get('linked_student_id') if u and u['role'] in ('student','parent') else None)
    if not sid: return jsonify({"error":"student_id required"}),400
    if u and u['role'] in ('student','parent') and str(u.get('linked_student_id'))!=str(sid):
        return jsonify({"error":"Access denied"}),403
    month=request.args.get('month'); status=request.args.get('status'); subject_id=request.args.get('subject_id')
    sql="SELECT date,status,time,leave_reason,subject_id FROM attendance WHERE student_id=? "
    params=[sid]
    if month: sql+=" AND substr(date,1,7)=?"; params.append(month)
    if status: sql+=" AND status=?"; params.append(status)
    if subject_id: sql+=" AND subject_id=?"; params.append(subject_id)
    sql+=" ORDER BY date DESC LIMIT 60"
    rows=db.execute(sql, params).fetchall()
    return jsonify([dict(r) for r in rows])

# ---------- Review Requests ----------
@app.route('/api/reviews', methods=['GET','POST','DELETE'])
def reviews_api():
    db=get_db()
    u=get_current_user()
    if not u: return jsonify({"error":"Not authenticated"}),401
    if request.method=='GET':
        if u['role'] in ('student','parent'):
            rows=db.execute("SELECT r.*, s.name as student_name FROM review_requests r JOIN students s ON s.id=r.student_id WHERE r.student_id=? ORDER BY r.id DESC", (u.get('linked_student_id'),)).fetchall()
            return jsonify([dict(r) for r in rows])
        rows=db.execute("SELECT r.*, s.name as student_name FROM review_requests r JOIN students s ON s.id=r.student_id ORDER BY r.id DESC LIMIT 100").fetchall()
        return jsonify([dict(r) for r in rows])
    if request.method=='POST':
        d=request.get_json() or {}
        # student/parent create for own/child only
        sid=d.get('student_id') or u.get('linked_student_id')
        if u['role'] in ('student','parent') and str(sid)!=str(u.get('linked_student_id')):
            return jsonify({"error":"Access denied"}),403
        if not sid or not d.get('date'):
            return jsonify({"error":"student_id and date required"}),400
        cur=db.execute("SELECT status FROM attendance WHERE student_id=? AND date=? ORDER BY rowid DESC LIMIT 1", (sid, d.get('date'))).fetchone()
        db.execute("INSERT INTO review_requests (student_id,date,current_status,reason,status,created_at) VALUES (?,?,?,?,?,?)",
                   (sid, d.get('date'), cur[0] if cur else None, d.get('reason',''), 'Pending', datetime.datetime.now().isoformat()))
        db.commit()
        # notify admin (user 1)
        try:
            db.execute("INSERT INTO notifications (user_id,type,title,content,date) VALUES (1,'review','Review Request',?,?)",
                       (f"Review requested for student {sid} on {d.get('date')}", datetime.datetime.now().isoformat()))
            db.commit()
        except: pass
        return jsonify({"ok":True})
    # DELETE = approve/reject (teacher/admin)
    if u['role'] not in ('admin','teacher'):
        return jsonify({"error":"Access denied"}),403
    rid=request.args.get('id'); action=request.args.get('action')  # approve/reject
    row=db.execute("SELECT * FROM review_requests WHERE id=?", (rid,)).fetchone()
    if not row: return jsonify({"error":"Not found"}),404
    if action=='approve' and request.args.get('new_status'):
        ns=request.args.get('new_status')
        db.execute("INSERT OR REPLACE INTO attendance (student_id,date,status) VALUES (?,?,?)", (row['student_id'], row['date'], ns))
        db.execute("INSERT INTO attendance_logs (student_id,date,old_status,new_status,changed_by,changed_at,note) VALUES (?,?,?,?,?,?,?)",
                   (row['student_id'], row['date'], row['current_status'], ns, u['id'], datetime.datetime.now().isoformat(), 'via review '+str(rid)))
        db.execute("UPDATE review_requests SET status='Approved', response=?, reviewed_by=? WHERE id=?", (request.args.get('response',''), u['id'], rid))
    else:
        db.execute("UPDATE review_requests SET status=?, response=?, reviewed_by=? WHERE id=?", ('Rejected' if action=='reject' else 'Pending', request.args.get('response',''), u['id'], rid))
    db.commit()
    return jsonify({"ok":True})

# ---------- Health (public, no sensitive data) ----------
@app.route('/api/health')
def health():
    try:
        get_db().execute("SELECT 1").fetchone()
        db_status = "connected"
    except Exception:
        db_status = "error"
    return jsonify({"success": True, "status": "ok", "database": db_status})

# ---------- Public website (no private data) ----------
@app.route('/public')
def public_site():
    return send_from_directory(os.path.join(APP_DIR, 'frontend'), 'public.html')

@app.route('/api/public/info')
def public_info():
    row = get_db().execute("SELECT school_name, branding_color, logo_path, address, contact FROM settings WHERE id=1").fetchone()
    d = dict(row) if row else {}
    # only public fields
    return jsonify({"school_name": d.get('school_name'), "address": d.get('address'), "contact": d.get('contact'), "logo_url": f"/api/logo/{d.get('logo_path')}" if d.get('logo_path') else None})

@app.route('/api/public/notices')
def public_notices():
    hit=_check_api_rate("public")
    if hit: return hit
    rows = get_db().execute("SELECT id, title, content, date FROM notices ORDER BY id DESC LIMIT 10").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/public/events')
def public_events():
    hit=_check_api_rate("public")
    if hit: return hit
    db = get_db()
    holidays = [dict(r) for r in db.execute("SELECT date as date, name as title, type FROM holidays ORDER BY date LIMIT 10").fetchall()]
    datesheets = [dict(r) for r in db.execute("SELECT date, subject as title, exam_type FROM datesheets ORDER BY date LIMIT 10").fetchall()]
    try:
        events = [dict(r) for r in db.execute("SELECT * FROM school_events ORDER BY date LIMIT 10").fetchall()]
    except: events = []
    return jsonify({"holidays": holidays, "exams": datesheets, "events": events})

@app.route('/api/public/contact', methods=['POST'])
def public_contact():
    d = request.get_json() or {}
    if not d.get('name') or not d.get('message'):
        return jsonify({"error": "name and message required"}), 400
    # store as complaint (public-safe, no student link)
    get_db().execute("INSERT INTO complaints (name,text,status,date) VALUES (?,?,?,?)",
                     (d.get('name')[:80], f"Contact from {d.get('email','')}: {d.get('message')[:500]}", 'Open', datetime.date.today().isoformat()))
    get_db().commit()
    return jsonify({"ok": True})

# ---------- Temporary QR sessions (expire, server-validated) ----------
@app.route('/api/qr/session', methods=['POST'])
def qr_session_create():
    u = get_current_user()
    if not u or not can(u['role'], "attendance", "add"):
        return jsonify({"error": "Access denied"}), 403
    d = request.get_json() or {}
    import secrets
    token = secrets.token_urlsafe(16)
    exp = (datetime.datetime.now() + datetime.timedelta(minutes=int(d.get('ttl_minutes', 5)))).isoformat()
    get_db().execute("INSERT INTO qr_sessions (token,class_id,section_id,subject_id,date,expires_at,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)",
                     (token, d.get('class_id'), d.get('section_id'), d.get('subject_id'), d.get('date') or datetime.date.today().isoformat(), exp, u['id'], datetime.datetime.now().isoformat()))
    get_db().commit()
    return jsonify({"ok": True, "token": token, "expires_at": exp})

@app.route('/api/qr/scan-temp', methods=['POST'])
def qr_scan_temp():
    u = get_current_user()
    if not u: return jsonify({"error": "Not authenticated"}), 401
    d = request.get_json() or {}
    token = (d.get('token') or '').strip()
    student_code = (d.get('code') or '').strip()
    # students/parents may only mark own/child attendance
    if u['role'] in ('student', 'parent') and u.get('linked_student_id'):
        own = get_db().execute("SELECT student_id FROM students WHERE id=?", (u['linked_student_id'],)).fetchone()
        if own and student_code and student_code != own[0]:
            return jsonify({"error": "You can only mark your own attendance"}), 403
    row = get_db().execute("SELECT * FROM qr_sessions WHERE token=?", (token,)).fetchone()
    if not row: return jsonify({"error": "Invalid QR"}), 400
    if row['expires_at'] < datetime.datetime.now().isoformat():
        return jsonify({"error": "QR expired"}), 400
    db = get_db()
    srow = db.execute("SELECT id, class_id, section_id FROM students WHERE student_id=?", (student_code,)).fetchone()
    if not srow: return jsonify({"error": "Student not found"}), 404
    # verify class/session match if session scoped
    if row['class_id'] and srow['class_id'] != row['class_id']:
        return jsonify({"error": "Wrong class for this QR"}), 400
    if row['section_id'] and srow['section_id'] != row['section_id']:
        return jsonify({"error": "Wrong section for this QR"}), 400
    # prevent duplicate: if already marked today for same subject, return ok (idempotent, no duplicate)
    if row['subject_id']:
        ex = db.execute("SELECT id FROM attendance WHERE student_id=? AND date=? AND subject_id=?", (srow['id'], row['date'], row['subject_id'])).fetchone()
    else:
        ex = db.execute("SELECT id FROM attendance WHERE student_id=? AND date=?", (srow['id'], row['date'])).fetchone()
    if ex:
        return jsonify({"ok": True, "duplicate": True})
    if is_holiday(row['date']):
        return jsonify({"error": "Holiday - blocked"}), 400
    if row['subject_id']:
        db.execute("INSERT INTO attendance (student_id,date,status,subject_id,time,marked_by,marked_at) VALUES (?,?,?,?,?,?,?)",
                   (srow['id'], row['date'], 'P', row['subject_id'], datetime.datetime.now().strftime("%H:%M"), u['id'], datetime.datetime.now().isoformat()))
    else:
        db.execute("INSERT INTO attendance (student_id,date,status,time,marked_by,marked_at) VALUES (?,?,?,?,?,?)",
                   (srow['id'], row['date'], 'P', datetime.datetime.now().strftime("%H:%M"), u['id'], datetime.datetime.now().isoformat()))
    db.commit()
    return jsonify({"ok": True})

@app.route('/api/qr/image/<token>')
def qr_image(token):
    row = get_db().execute("SELECT * FROM qr_sessions WHERE token=?", (token,)).fetchone()
    if not row: return jsonify({"error": "Invalid"}), 404
    import qrcode
    bio = io.BytesIO()
    qrcode.make(f"ATTEND:{token}").save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype='image/png')

@app.route('/api/permissions')
def permissions_api():
    return jsonify(PERMISSIONS)

@app.route('/api/roles')
def roles_api():
    return jsonify(ROLES)

@app.route('/api/exam_types')
def exam_types_api():
    return jsonify(EXAM_TYPES)

# ---------- Static fallback ----------
@app.route('/manifest.json')
def manifest():
    return send_from_directory(APP_DIR, 'manifest.json')

if __name__=='__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
