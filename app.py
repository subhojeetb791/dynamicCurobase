import os, sqlite3, hashlib, hmac, secrets, datetime, json, io, base64, re, functools, unicodedata
from flask import Flask, request, jsonify, send_from_directory, g, send_file, session, abort
from flask_cors import CORS
from werkzeug.utils import secure_filename

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
PHOTO_DIR = os.path.join(DATA_DIR, "photos")
QR_DIR = os.path.join(DATA_DIR, "qrcodes")
DB_PATH = os.path.join(DATA_DIR, "attendance.db")
# Profile images are permanent user data, so on a platform with an ephemeral
# filesystem (Render's root disk is wiped on every deploy) point
# PROFILE_UPLOAD_DIR at a mounted persistent disk. Defaults to data/photos so
# local dev and existing student photos behave exactly as before.
PROFILE_UPLOAD_DIR = os.environ.get('PROFILE_UPLOAD_DIR') or PHOTO_DIR

for d in [DATA_DIR, PHOTO_DIR, QR_DIR]:
    os.makedirs(d, exist_ok=True)
# The upload dir may be a persistent disk that only exists once mounted on the
# hosting platform, so a failure here is tolerated and retried on first upload.
try:
    os.makedirs(PROFILE_UPLOAD_DIR, exist_ok=True)
except OSError:
    pass

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
    # Everyone may READ the schedule that concerns them; only admins may shape it.
    "timetable":          {"admin":"full", "teacher":"view", "student":"view", "parent":"view"},
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
    -- ================= Timetable Management =================
    -- A timetable_version is a complete week of one class+section that becomes
    -- live on `effective_from`. Editing a live version means forking a new draft,
    -- so published history is never overwritten and change history stays honest.
    CREATE TABLE IF NOT EXISTS timetable_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL DEFAULT 1,
        class_id INTEGER NOT NULL,
        section_id INTEGER NOT NULL,
        name TEXT DEFAULT '',
        status TEXT DEFAULT 'draft' CHECK(status IN ('draft','published','archived')),
        effective_from TEXT NOT NULL,
        parent_id INTEGER,
        created_by INTEGER,
        created_at TEXT,
        published_at TEXT,
        published_by INTEGER,
        publish_note TEXT DEFAULT '',
        FOREIGN KEY(session_id) REFERENCES academic_sessions(id) ON DELETE CASCADE,
        FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE CASCADE,
        FOREIGN KEY(section_id) REFERENCES sections(id) ON DELETE CASCADE,
        FOREIGN KEY(parent_id) REFERENCES timetable_versions(id) ON DELETE SET NULL
    );
    -- One row per grid cell. Breaks/lunch are rows too (kind<>'period') so the
    -- editor and the reader share a single source of truth for the day shape.
    CREATE TABLE IF NOT EXISTS timetable_slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        name TEXT DEFAULT '',
        kind TEXT DEFAULT 'period' CHECK(kind IN ('period','break','lunch','assembly')),
        subject_id INTEGER,
        teacher_id INTEGER,
        substitute_teacher_id INTEGER,
        room TEXT DEFAULT '',
        status TEXT DEFAULT 'active' CHECK(status IN ('active','cancelled')),
        cancel_reason TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        FOREIGN KEY(version_id) REFERENCES timetable_versions(id) ON DELETE CASCADE,
        FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE SET NULL,
        FOREIGN KEY(teacher_id) REFERENCES teachers(id) ON DELETE SET NULL,
        FOREIGN KEY(substitute_teacher_id) REFERENCES teachers(id) ON DELETE SET NULL
    );
    -- School-day shape. class_id/section_id NULL = school-wide default; a row for
    -- a specific class+section overrides it.
    CREATE TABLE IF NOT EXISTS timetable_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL DEFAULT 1,
        class_id INTEGER,
        section_id INTEGER,
        open_time TEXT DEFAULT '08:00',
        close_time TEXT DEFAULT '15:00',
        timezone TEXT DEFAULT 'Asia/Kolkata',
        working_days TEXT DEFAULT 'Monday,Tuesday,Wednesday,Thursday,Friday,Saturday',
        period_minutes INTEGER DEFAULT 45,
        updated_by INTEGER,
        updated_at TEXT
    );
    -- Append-only audit trail. Never stores credentials or personal data.
    CREATE TABLE IF NOT EXISTS timetable_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version_id INTEGER,
        class_id INTEGER,
        section_id INTEGER,
        action TEXT NOT NULL,
        summary TEXT DEFAULT '',
        detail TEXT DEFAULT '{}',
        changed_by INTEGER,
        changed_at TEXT
    );
    -- A substitution applies to one concrete DATE (a teacher is away that day),
    -- while the slot itself is a weekday pattern.
    CREATE TABLE IF NOT EXISTS timetable_substitutions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slot_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        original_teacher_id INTEGER,
        substitute_teacher_id INTEGER,
        reason TEXT DEFAULT '',
        status TEXT DEFAULT 'approved' CHECK(status IN ('pending','approved','rejected')),
        requested_by INTEGER,
        approved_by INTEGER,
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY(slot_id) REFERENCES timetable_slots(id) ON DELETE CASCADE,
        FOREIGN KEY(original_teacher_id) REFERENCES teachers(id) ON DELETE SET NULL,
        FOREIGN KEY(substitute_teacher_id) REFERENCES teachers(id) ON DELETE SET NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ux_ttslot ON timetable_slots(version_id, day, start_time);
    CREATE INDEX IF NOT EXISTS ix_ttslot_day ON timetable_slots(day, start_time);
    CREATE INDEX IF NOT EXISTS ix_ttslot_teacher ON timetable_slots(teacher_id, day);
    CREATE INDEX IF NOT EXISTS ix_ttslot_sub ON timetable_slots(substitute_teacher_id, day);
    CREATE INDEX IF NOT EXISTS ix_ttver_class ON timetable_versions(class_id, section_id, session_id, status, effective_from);
    -- COALESCE because SQLite treats NULLs as distinct in UNIQUE constraints
    -- (the same trap that produced duplicate attendance rows).
    CREATE UNIQUE INDEX IF NOT EXISTS ux_ttset
        ON timetable_settings(session_id, COALESCE(class_id,-1), COALESCE(section_id,-1));
    CREATE UNIQUE INDEX IF NOT EXISTS ux_ttsub ON timetable_substitutions(slot_id, date);
    CREATE INDEX IF NOT EXISTS ix_ttchg ON timetable_changes(class_id, section_id, changed_at);
    -- At most one PUBLISHED version per effective date (drafts stay unconstrained).
    CREATE UNIQUE INDEX IF NOT EXISTS ux_ttver_pub
        ON timetable_versions(session_id, class_id, section_id, effective_from)
        WHERE status='published';
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
    # One-time repair: rows written before the idempotent-save fix could stack
    # up (SQLite treats NULL as distinct in UNIQUE()). Keep only the newest
    # mark per student/date/subject so report maths stays honest.
    try:
        db.execute("""
            DELETE FROM attendance
             WHERE id NOT IN (
                 SELECT MAX(id) FROM attendance
                  GROUP BY student_id, date, COALESCE(subject_id, -1)
             )
        """)
        db.commit()
    except Exception:
        pass
    # seed academic sessions
    try:
        if db.execute("SELECT COUNT(*) FROM academic_sessions").fetchone()[0]==0:
            db.execute("INSERT INTO academic_sessions (name,start_date,end_date,active) VALUES (?,?,?,1)", ("2026-27","2026-04-01","2027-03-31",))
            db.execute("INSERT INTO academic_sessions (name,start_date,end_date,active) VALUES (?,?,?,0)", ("2025-26","2025-04-01","2026-03-31",))
    except: pass

    # =================================================================
    #  Student & Parent portal migrations
    # =================================================================
    try:
        db.execute("""
        CREATE TABLE IF NOT EXISTS homework (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER,
            section_id INTEGER,
            subject TEXT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            due_date TEXT,
            assigned_by INTEGER,
            school_id INTEGER DEFAULT 1,
            created_at TEXT,
            FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE CASCADE,
            FOREIGN KEY(section_id) REFERENCES sections(id) ON DELETE CASCADE
        )""")
    except Exception: pass

    # parents: parent_id (PAR-xxxx) + password hash for PIN-style login
    for col, typ in [("parent_id","TEXT"), ("password_hash","TEXT")]:
        try: db.execute(f"ALTER TABLE parents ADD COLUMN {col} {typ}")
        except Exception: pass

    # parent <-> student link table (one parent, many children)
    try:
        db.execute("""
        CREATE TABLE IF NOT EXISTS parent_students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            UNIQUE(user_id, student_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        )""")
    except Exception: pass

    # backfill parent_students from existing single-link data so nothing breaks
    try:
        db.execute("""
        INSERT OR IGNORE INTO parent_students (user_id, student_id)
        SELECT u.id, u.linked_student_id FROM users u
        WHERE u.role='parent' AND u.linked_student_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM students s WHERE s.id=u.linked_student_id)""")
        db.execute("""
        INSERT OR IGNORE INTO parent_students (user_id, student_id)
        SELECT p.user_id, p.student_id FROM parents p
        WHERE p.user_id IS NOT NULL AND p.student_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM students s WHERE s.id=p.student_id)""")
        # drop links that point at deleted students
        db.execute("""DELETE FROM parent_students
                      WHERE student_id NOT IN (SELECT id FROM students)""")
        db.execute("""DELETE FROM parent_students
                      WHERE user_id NOT IN (SELECT id FROM users)""")
    except Exception: pass

    # give every parent user a stable Parent ID (PAR-5001...) if missing
    def _new_parent_id(used):
        n = 5001
        while (f"PAR-{n}" in used) or f"PAR-{n}" == "PAR-5012":   # PAR-5012 reserved for the demo parent
            n += 1
        used.add(f"PAR-{n}")
        return f"PAR-{n}"
    try:
        used = set(r[0] for r in db.execute(
            "SELECT parent_id FROM parents WHERE parent_id IS NOT NULL AND parent_id<>''").fetchall())
        rows = db.execute("SELECT id FROM parents WHERE parent_id IS NULL OR parent_id=''").fetchall()
        for r in rows:
            db.execute("UPDATE parents SET parent_id=? WHERE id=?", (_new_parent_id(used), r[0]))
        # parent users that have no parents row yet -> create one
        prows = db.execute("""
            SELECT u.id, u.username, u.password_hash FROM users u
            WHERE u.role='parent'
              AND NOT EXISTS (SELECT 1 FROM parents p WHERE p.user_id=u.id)""").fetchall()
        for r in prows:
            db.execute("""INSERT INTO parents (name, phone, email, student_id, user_id, parent_id, password_hash, school_id)
                          VALUES (?,?,?,?,?,?,?,1)""",
                       (r[1], '', '', None, r[0], _new_parent_id(used), r[2]))
    except Exception: pass

    # ---- demo student + parent portal accounts -------------------
    # NOTE: the original INSERT listed 11 columns but had 12 placeholders, so it
    # always failed silently (the except swallowed it) and left
    # users.linked_student_id pointing at a student row that no longer existed.
    # This block runs AFTER the migrations so parent_id / parent_students exist.
    def _class_sec(class_name, sec_name="A"):
        c = db.execute("SELECT id FROM classes WHERE name=?", (class_name,)).fetchone()
        cid = c[0] if c else None
        if cid is None:
            return None, None
        s = db.execute("SELECT id FROM sections WHERE class_id=? AND name=?", (cid, sec_name)).fetchone()
        return cid, (s[0] if s else None)

    def _ensure_student(sid_label, roll, name, cls, sec, father, mother, dob, adm):
        row = db.execute("SELECT id FROM students WHERE student_id=?", (sid_label,)).fetchone()
        if row:
            return row[0]
        cid, secid = _class_sec(cls, sec)
        db.execute("""INSERT INTO students (student_id, roll_no, name, class_id, section_id,
                      father_name, mother_name, phone, address, dob, admission_no, created_at)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (sid_label, roll, name, cid, secid, father, mother, "9876543210",
                    "Green Valley", dob, adm, datetime.datetime.now().isoformat()))
        return db.execute("SELECT id FROM students WHERE student_id=?", (sid_label,)).fetchone()[0]

    try:
        demo_sid  = _ensure_student("STU001", "01", "Aarav Sharma", "1", "A",
                                    "Ramesh Sharma", "Sunita Sharma", "2010-05-12", "ADM-2010-0001")
        # second child of the same family -> makes multi-child parent login testable
        demo_sid2 = _ensure_student("STU009", "09", "Kiara Sharma", "3", "A",
                                    "Ramesh Sharma", "Sunita Sharma", "2013-02-18", "ADM-2013-0009")

        for uname, pwd, role in [("student", "student123", "student"), ("parent", "parent123", "parent")]:
            row = db.execute("SELECT id, linked_student_id FROM users WHERE username=?", (uname,)).fetchone()
            if not row:
                db.execute("INSERT INTO users (username,password_hash,role,permissions,linked_student_id,created_at) VALUES (?,?,?,?,?,?)",
                           (uname, hashlib.sha256(pwd.encode()).hexdigest(), role, json.dumps([]),
                            demo_sid, datetime.datetime.now().isoformat()))
            elif row[1] and not db.execute("SELECT 1 FROM students WHERE id=?", (row[1],)).fetchone():
                # repair a dangling link left behind by a deleted student row
                db.execute("UPDATE users SET linked_student_id=? WHERE id=?", (demo_sid, row[0]))

        # demo parent: stable Parent ID PAR-5012, password, links to BOTH children
        pur = db.execute("SELECT id, linked_student_id FROM users WHERE username='parent'").fetchone()
        if pur:
            puid = pur[0]
            if not db.execute("SELECT 1 FROM parents WHERE user_id=?", (puid,)).fetchone():
                db.execute("""INSERT INTO parents (name, phone, email, student_id, user_id, parent_id, password_hash, school_id)
                              VALUES (?,?,?,?,?,?,?,1)""",
                           ("Ramesh Sharma", "9876543210", "ramesh.sharma@example.com",
                            demo_sid, puid, "PAR-5012",
                            hashlib.sha256("parent123".encode()).hexdigest()))
            else:
                db.execute("""UPDATE parents SET name=?, phone=?, email=?, parent_id=?, password_hash=?
                              WHERE user_id=?""",
                           ("Ramesh Sharma", "9876543210", "ramesh.sharma@example.com", "PAR-5012",
                            hashlib.sha256("parent123".encode()).hexdigest(), puid))
            for c in (demo_sid, demo_sid2):
                db.execute("INSERT OR IGNORE INTO parent_students (user_id, student_id) VALUES (?,?)", (puid, c))
            if not db.execute("SELECT 1 FROM students WHERE id=?", (pur[1] or -1,)).fetchone():
                db.execute("UPDATE users SET linked_student_id=? WHERE id=?", (demo_sid, puid))
        db.execute("""DELETE FROM parent_students
                      WHERE student_id NOT IN (SELECT id FROM students)""")
    except Exception: pass

    # ---- demo homework for the two demo children (class 1-A and class 3-A) ----
    try:
        if db.execute("SELECT COUNT(*) FROM homework").fetchone()[0] == 0:
            samples = {
                "1": [("Mathematics", "Worksheet: Addition up to 100",
                       "Solve questions 1-20 from page 42.", 2),
                      ("English", "Read chapter 3 and write a summary",
                       "Write 10 lines in your notebook.", 3),
                      ("Science", "Leaf identification activity",
                       "Collect 5 different leaves and label them.", 5)],
                "3": [("Mathematics", "Tables 2 to 5",
                       "Write each table three times.", 1),
                      ("Hindi", "पाठ 4 - सारे दिन चलो",
                       "प्रश्न 1 से 5 हल करें।", 4)],
            }
            for cls, items in samples.items():
                cid, secid = _class_sec(cls, "A")
                for subj, title, desc, days in items:
                    db.execute("""INSERT INTO homework (class_id, section_id, subject, title, description, due_date,
                                  assigned_by, school_id, created_at)
                                  VALUES (?,?,?,?,?,?,?,1,?)""",
                               (cid, secid, subj, title, desc,
                                (datetime.date.today() + datetime.timedelta(days=days)).isoformat(),
                                None, datetime.datetime.now().isoformat()))
    except Exception: pass

    # ---- demo attendance + marks so the student/parent dashboards are not empty ----
    try:
        hset0 = set(x[0] for x in db.execute("SELECT date FROM holidays").fetchall())
        seq = ['P','P','A','P','P','T','P','L','P','P','P','A','P','P','P',
               'P','L','P','P','P','P','A','P','P','P','P','P','T','P','P']
        exam_names = ["Unit Test 1", "Mid-Term"]
        for sid_label, bump in (('STU001', 8), ('STU009', 3)):
            srow = db.execute("SELECT id FROM students WHERE student_id=?", (sid_label,)).fetchone()
            if not srow:
                continue
            spk = srow[0]
            if db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=?", (spk,)).fetchone()[0] == 0:
                today = datetime.date.today()
                for i in range(30):
                    d = today - datetime.timedelta(days=i)
                    ds = d.isoformat()
                    if d.weekday() == 6 or ds in hset0:
                        continue
                    db.execute("""INSERT INTO attendance (student_id, date, status, time, marked_by, marked_at)
                                  VALUES (?,?,?,?,?,?)""",
                               (spk, ds, seq[i % len(seq)], "09:00", 1,
                                datetime.datetime.now().isoformat()))
            if db.execute("SELECT COUNT(*) FROM marks WHERE student_id=?", (spk,)).fetchone()[0] == 0:
                subs = [r[0] for r in db.execute("SELECT id FROM subjects ORDER BY id").fetchall()]
                for ei, exam in enumerate(exam_names):
                    for i, subid in enumerate(subs):
                        obtained = 58 + ((i * 9 + bump + ei * 5) % 38)
                        db.execute("""INSERT INTO marks (student_id, subject_id, exam_type, max_marks, obtained)
                                      VALUES (?,?,?,?,?)""",
                                   (spk, subid, exam, 100, obtained))
    except Exception: pass

    # ---- academic year: timetable_versions.session_id has a real FK to this ----
    # A database created before academic_sessions existed could be empty, which
    # would make every timetable insert fail. Seed one only when there is none.
    try:
        if db.execute("SELECT COUNT(*) FROM academic_sessions").fetchone()[0] == 0:
            y = datetime.date.today().year
            db.execute("""INSERT INTO academic_sessions (name,start_date,end_date,active)
                          VALUES (?,?,?,1)""", (f"{y}-{str(y+1)[2:]}", f"{y}-04-01", f"{y+1}-03-31"))
    except Exception: pass

    # ---- one-time import of the legacy flat `timetable` table ---------------
    # Legacy rows were free-text (`day` + `period_time` like "09:00-10:00") with
    # no versioning. Copy them into a draft version so no production data is
    # silently abandoned. Guarded: runs only when legacy rows exist AND the new
    # table is still empty, so it can never duplicate on later restarts.
    try:
        legacy_n = db.execute("SELECT COUNT(*) FROM timetable").fetchone()[0]
        new_n = db.execute("SELECT COUNT(*) FROM timetable_versions").fetchone()[0]
        if legacy_n and new_n == 0:
            def _norm_t(v):
                v = str(v).strip()
                m = re.fullmatch(r'(\d{1,2}):(\d{2})', v)
                if not m: return None
                h, mi = int(m.group(1)), int(m.group(2))
                if h > 23 or mi > 59: return None
                return '%02d:%02d' % (h, mi)
            def _plus45(t):
                h, mi = [int(x) for x in t.split(':')]
                tot = h * 60 + mi + 45
                return '%02d:%02d' % (tot // 60, tot % 60)
            now_iso = datetime.datetime.now().isoformat()
            sid_row = db.execute("SELECT id FROM academic_sessions WHERE active=1 ORDER BY id LIMIT 1").fetchone()
            sid = sid_row[0] if sid_row else 1
            imported = skipped = 0
            for r in db.execute("SELECT * FROM timetable ORDER BY id").fetchall():
                if not r['class_id'] or not r['day']:
                    skipped += 1; continue
                pt = str(r['period_time'] or '').strip()
                st = en = None
                m = re.match(r'^(\d{1,2}:\d{2})\s*[-\u2013\u2014]\s*(\d{1,2}:\d{2})$', pt)
                if m:
                    st, en = _norm_t(m.group(1)), _norm_t(m.group(2))
                else:
                    st = _norm_t(pt)
                    en = _plus45(st) if st else None
                if not st or not en or st >= en:
                    skipped += 1; continue
                sec = r['section_id']
                if not sec:
                    sr = db.execute("SELECT id FROM sections WHERE class_id=? ORDER BY id LIMIT 1", (r['class_id'],)).fetchone()
                    sec = sr[0] if sr else None
                if not sec:
                    skipped += 1; continue
                ver = db.execute("""SELECT id FROM timetable_versions
                                    WHERE session_id=? AND class_id=? AND section_id=?
                                      AND status='draft' AND name='Imported (legacy)'""",
                                 (sid, r['class_id'], sec)).fetchone()
                if not ver:
                    cur = db.execute("""INSERT INTO timetable_versions
                        (session_id,class_id,section_id,name,status,effective_from,created_by,created_at)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (sid, r['class_id'], sec, 'Imported (legacy)', 'draft',
                         datetime.date.today().isoformat(), None, now_iso))
                    ver_id = cur.lastrowid
                else:
                    ver_id = ver[0]
                dup = db.execute("SELECT 1 FROM timetable_slots WHERE version_id=? AND day=? AND start_time=?",
                                 (ver_id, r['day'], st)).fetchone()
                if dup:
                    skipped += 1; continue
                db.execute("""INSERT INTO timetable_slots
                    (version_id,day,start_time,end_time,name,kind,subject_id,teacher_id,room)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (ver_id, r['day'], st, en, r['subject_name'] or 'Period',
                     'period', r['subject_id'], r['teacher_id'], r['room'] or ''))
                imported += 1
            db.execute("""INSERT INTO timetable_changes
                (version_id,class_id,section_id,action,summary,detail,changed_at)
                VALUES (NULL,NULL,NULL,'migrate','Imported legacy timetable rows',?,?)""",
                (json.dumps({"imported": imported, "skipped": skipped, "source": "timetable"}), now_iso))
    except Exception: pass

    # ---- profile system: extend users + add the 1:1 profile table ----------
    # Additive only. Existing user rows keep their values; new columns get
    # safe defaults so nothing else in the app has to change.
    for col, typ in [("email","TEXT DEFAULT ''"), ("phone","TEXT DEFAULT ''"),
                     ("status","TEXT DEFAULT 'active'"),
                     ("email_verified","INTEGER DEFAULT 0"),
                     ("updated_at","TEXT"),
                     # bumped to invalidate every other signed-in device at once
                     ("auth_epoch","INTEGER DEFAULT 0")]:
        try: db.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
        except Exception: pass
    # usernames are already UNIQUE; email must be too, but only for real
    # addresses (legacy rows all hold '' so a plain UNIQUE would collide).
    try:
        db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email
                      ON users(email) WHERE email <> ''""")
    except Exception: pass
    try:
        db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS ux_users_phone
                      ON users(phone) WHERE phone <> ''""")
    except Exception: pass
    db.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            display_name TEXT DEFAULT '',
            bio TEXT DEFAULT '',
            photo TEXT DEFAULT '',
            cover_photo TEXT DEFAULT '',
            dob TEXT DEFAULT '',
            gender TEXT DEFAULT '',
            pronouns TEXT DEFAULT '',
            country TEXT DEFAULT '',
            city TEXT DEFAULT '',
            language TEXT DEFAULT 'English',
            interests TEXT DEFAULT '',
            theme TEXT DEFAULT 'light',
            socials TEXT DEFAULT '{}',
            notify_email INTEGER DEFAULT 1,
            notify_app INTEGER DEFAULT 1,
            notify_attendance INTEGER DEFAULT 1,
            notify_notices INTEGER DEFAULT 1,
            a11y_large_text INTEGER DEFAULT 0,
            a11y_reduced_motion INTEGER DEFAULT 0,
            visibility TEXT DEFAULT 'private',
            show_email INTEGER DEFAULT 0,
            show_phone INTEGER DEFAULT 0,
            show_dob INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    # reset tokens: only a hash is stored, never the token itself
    db.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL,
            kind TEXT DEFAULT 'reset',
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    try: db.execute("ALTER TABLE password_reset_tokens ADD COLUMN kind TEXT DEFAULT 'reset'")
    except Exception: pass
    # every profile row the account may need; created lazily on first read too
    try:
        db.execute("""
            INSERT OR IGNORE INTO user_profiles (user_id, created_at, updated_at)
            SELECT id, ?, ? FROM users
             WHERE NOT EXISTS (SELECT 1 FROM user_profiles p WHERE p.user_id = users.id)
        """, (datetime.datetime.now().isoformat(), datetime.datetime.now().isoformat()))
    except Exception: pass
    # --- Profile system (additive, safe to re-run, never drops anything) ---
    # display_name is the optional "how I appear" name; this is the real one.
    try:
        db.execute("ALTER TABLE user_profiles ADD COLUMN full_name TEXT DEFAULT ''")
    except Exception: pass
    # Account deletion is a *request*, never an instant self-serve wipe: an admin
    # still has to decide it, and attendance/school records are never deleted here.
    db.execute("""
        CREATE TABLE IF NOT EXISTS account_deletion_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reason TEXT DEFAULT '',
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
            created_at TEXT,
            decided_by INTEGER,
            decided_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS ix_prt_hash ON password_reset_tokens(token_hash)")
    # Only one *live* token per user per kind: issuing a new link retires the old one.
    # Retire any pre-existing duplicates first so the index always builds.
    try:
        db.execute("""UPDATE password_reset_tokens SET used=1
                        WHERE used=0 AND id NOT IN
                              (SELECT MAX(id) FROM password_reset_tokens
                                WHERE used=0 GROUP BY user_id, kind)""")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_prt_live"
                   " ON password_reset_tokens(user_id, kind) WHERE used=0")
    except Exception:
        pass

    db.commit()
    db.close()

init_db()

"""Password hashing.

Historically this app stored a bare SHA-256 digest (unsalted, unslowed), which is
not an acceptable password hash. We now use PBKDF2-HMAC-SHA256 with a per-user
random salt and a high iteration count, using only the standard library.

Existing accounts keep working: verify_pw() detects the legacy format and still
accepts it, and _upgrade_password_hash() transparently re-hashes to PBKDF2 the
next time the user logs in successfully. No user is locked out and no password
is ever reset or written to a log.
"""
PW_ALGO = 'pbkdf2:sha256'
PW_ITERATIONS = int(os.environ.get('PW_ITERATIONS', '390000'))
PW_SALT_BYTES = 16

def hash_pw(p):
    """Hash a password with PBKDF2-HMAC-SHA256. Format: algo:iters$salt$hash."""
    salt = secrets.token_hex(PW_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac('sha256', (p or '').encode('utf-8'),
                                 bytes.fromhex(salt), PW_ITERATIONS).hex()
    return '%s:%d$%s$%s' % (PW_ALGO, PW_ITERATIONS, salt, digest)

def _legacy_hash(p):
    """The pre-upgrade digest, kept only so old accounts can still sign in."""
    return hashlib.sha256((p or '').encode('utf-8')).hexdigest()

def is_legacy_hash(stored):
    """True when the stored value is the old bare-SHA-256 format."""
    if not stored:
        return False
    # legacy = 64 lowercase hex chars with no algo/iterations prefix
    return len(stored) == 64 and '$' not in stored and re.fullmatch(r'[0-9a-f]{64}', stored) is not None

def verify_pw(stored, p):
    """Constant-time password check that understands both formats."""
    if not stored:
        return False
    if is_legacy_hash(stored):
        return hmac.compare_digest(stored, _legacy_hash(p))
    try:
        head, salt, digest = stored.split('$')
        algo, iters = head.rsplit(':', 1)
        if algo != 'pbkdf2:sha256':
            return False
        computed = hashlib.pbkdf2_hmac('sha256', (p or '').encode('utf-8'),
                                       bytes.fromhex(salt), int(iters)).hex()
        return hmac.compare_digest(computed, digest)
    except (ValueError, TypeError):
        return False

def _upgrade_password_hash(db, user_id, stored, p):
    """Re-hash a legacy digest in place. Best effort — never blocks a login."""
    try:
        if is_legacy_hash(stored):
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_pw(p), user_id))
            db.commit()
    except Exception:
        pass

# Human-readable reasons an account that *authenticated* still cannot start a
# session. Shown only after a correct password, so nothing leaks publicly.
_PENDING_STATUS_MSG = {
    'pending':   "Your account is awaiting approval from the school office.",
    'rejected':  "This registration was not approved. Please contact the school office.",
    'suspended': "This account has been suspended. Please contact the school office.",
}

# ---------- RBAC Helpers ----------
def get_current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    db = get_db()
    row = db.execute("SELECT id, username, role, permissions, linked_student_id, "
                     "status, auth_epoch FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        return None
    d = dict(row)
    # A pending / rejected / suspended account may never hold a live session.
    if (d.get('status') or 'active') != 'active':
        session.clear()
        return None
    # auth_epoch lets "sign out everywhere else" invalidate other devices: the
    # value is baked into each cookie at login, so bumping it on the row makes
    # every older cookie fail this check on its next request.
    if int(session.get('epoch') or 0) != int(d.get('auth_epoch') or 0):
        session.clear()
        return None
    return d

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

# ---------- Ownership guards (Student / Parent isolation) ----------
def readable_student_ids(u):
    """Set of students.id this user may read, or None when unrestricted (admin/teacher).

    A student may only ever read their own row. A parent may only read the rows
    explicitly linked to their account via parent_students / parents.
    """
    if not u:
        return set()
    if u['role'] in ('admin', 'teacher'):
        return None                      # unrestricted (feature-level RBAC still applies)
    db = get_db()
    ids = set()
    if u.get('linked_student_id'):
        ids.add(int(u['linked_student_id']))
    try:
        for r in db.execute("SELECT student_id FROM parent_students WHERE user_id=?", (u['id'],)).fetchall():
            if r[0]: ids.add(int(r[0]))
        for r in db.execute("SELECT student_id FROM parents WHERE user_id=? AND student_id IS NOT NULL",
                            (u['id'],)).fetchall():
            ids.add(int(r[0]))
    except Exception:
        pass
    return ids

def student_scope(u, requested=None, must_have_link=False):
    """Resolve the students.id the caller is allowed to read.

    Returns an int            -> allowed, use it
    Returns a (body, status)  -> return it straight from the route (401/403/400)
    """
    if not u:
        return (jsonify({"error":"Not authenticated"}), 401)
    allowed = readable_student_ids(u)
    if allowed is None:                       # admin / teacher
        if requested in (None, ''):
            return (jsonify({"error":"student id required"}), 400)
        try:
            return int(requested)
        except (TypeError, ValueError):
            return (jsonify({"error":"Invalid student id"}), 400)
    if requested in (None, ''):
        if not allowed:
            if must_have_link:
                return (jsonify({"error":"No student linked to this account"}), 403)
            return None                       # caller wants "all readable" (a list)
        return sorted(allowed)[0] if must_have_link else None
    try:
        pk = int(requested)
    except (TypeError, ValueError):
        return (jsonify({"error":"Invalid student id"}), 400)
    if pk in allowed:
        return pk
    # Never reveal whether the other student exists.
    return (jsonify({"error":"Access denied: you are not authorised to view this record"}), 403)

def readable_filter_sql(u, column="student_id"):
    """(sql_fragment, params) that restricts a query to the caller's readable rows."""
    allowed = readable_student_ids(u)
    if allowed is None:
        return ("", [])
    if not allowed:
        return (" AND 1=0", [])
    marks = ",".join("?" for _ in allowed)
    return (f" AND {column} IN ({marks})", sorted(allowed))

# ---------- Default-deny for the API ----------
# Anything under /api/ requires a session unless it is explicitly public.
# Individual routes still do their own role + ownership checks; this guard only
# guarantees that a route can never accidentally expose data anonymously.
PUBLIC_API_ANY = (
    '/api/auth/login',
    '/api/auth/student-login',
    '/api/auth/parent-login',
    '/api/auth/check',
    '/api/auth/logout',
    # Self-service account creation + email verification + password recovery.
    # These are deliberately unauthenticated, but each one is rate-limited by IP
    # and none of them ever returns whether an address is registered.
    '/api/auth/register',
    '/api/auth/verify-email',
    '/api/auth/forgot-password',
    '/api/auth/reset-password',
    # The public site's contact form (frontend/public.html) posts here before
    # any session exists. It only ever writes an anonymous row into complaints
    # and answers {"ok":true}, and it is rate-limited per IP below.
    '/api/public/',
)
PUBLIC_API_GET = (
    '/api/settings',      # school name + logo shown on the login screens
    '/api/logo',          # logo image for the login screens
    '/api/photos',        # avatars
    '/api/public',        # public school info / notice board
    '/api/permissions',
    '/api/roles',
    '/api/exam_types',
    '/api/qr/image',
    '/api/health',        # render.yaml healthCheckPath: must answer without a
                          # session or the hosting platform can never pass it.
                          # Returns only ok/status + database connectivity.
    # A single, exact-username lookup that only ever answers for profiles the
    # owner explicitly set to 'public'. There is no directory, listing or search
    # endpoint, so student profiles are not publicly discoverable.
    '/api/profile/public',
)

@app.before_request
def _guard_api():
    path = request.path
    if not path.startswith('/api/'):
        return None
    if request.method == 'OPTIONS':
        return None
    if any(path.startswith(p) for p in PUBLIC_API_ANY):
        return None
    if request.method == 'GET' and any(path.startswith(p) for p in PUBLIC_API_GET):
        return None
    if get_current_user() is None:
        return jsonify({"error": "Not authenticated"}), 401
    return None

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

# --- public image files ---------------------------------------------------
# send_from_directory() blocks '../' traversal, but that alone is NOT enough
# here: the live SQLite database physically lives inside DATA_DIR, the very
# directory these routes serve. send_from_directory does not filter filenames,
# so GET /data/attendance.db used to hand the entire school database to any
# anonymous visitor - every PBKDF2 password hash, every student's personal
# record, every attendance mark, every reset-token hash. /api/logo/attendance.db
# served it too, because that route sits in PUBLIC_API_GET for the login screen.
# An explicit allowlist of what may be public is therefore checked BEFORE
# anything touches disk: only plainly-named image files, at the top level.
_PUBLIC_FILE_RE = re.compile(
    r'^[A-Za-z0-9][A-Za-z0-9._-]*\.(?:png|jpe?g|webp|gif|ico|svg)$', re.I)

def _public_image(directory, fn):
    """Serve one image file from *directory*, or 404.

    The basename is taken first so no path separator - forward or backward,
    and on Windows os.path.join() treats '\\' as a separator too - can ever
    reach the filesystem. Anything that is not a plainly-named image (the
    database, .env, backups, Python sources, anything inside a
    sub-directory such as qrcodes/) is a 404. QR codes are deliberately
    excluded: they carry live attendance-scanning tokens and must stay
    behind authentication.
    """
    fn = os.path.basename((fn or '').replace('\\', '/'))
    if not fn or not _PUBLIC_FILE_RE.match(fn):
        abort(404)
    full = os.path.join(directory, fn)
    if not os.path.isfile(full):
        abort(404)
    return send_file(full, conditional=True)

_SAFE_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')

def _safe_id_for_file(sid):
    """Validate a student_id before it is used to build a file path.

    Photo and QR file names are built as ``f"{sid}..."`` and then handed to
    ``os.path.join()``. Werkzeug's default ``<sid>`` converter excludes '/'
    but not '\\', and on Windows ``os.path.join()`` treats '\\' as a
    separator - so ``..%5Cschool_logo`` escaped ``data/qrcodes`` and read
    ``data/school_logo.png`` (confirmed: HTTP 200 with real PNG bytes). The
    same value was also used to *write* newly generated QR codes outside the
    directory. Returns the cleaned id, or None when it is not a plain
    identifier - callers must treat None as a 400/404.
    """
    s = (sid or '').strip()
    if not _SAFE_ID_RE.match(s) or '..' in s:
        return None
    return s

@app.route('/api/logo/<path:fn>')
def serve_logo(fn):
    # School logo only - shown on the login screens before any session exists.
    return _public_image(DATA_DIR, fn)

@app.route('/data/<path:fn>')
def serve_data(fn):
    # Legacy path kept so old links still resolve. Nothing in this codebase
    # references it any more; it is narrowed to the same image allowlist so it
    # can never serve the database again.
    return _public_image(DATA_DIR, fn)

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
        d=request.get_json() or {}
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
    # Authenticated reads only; student/parent rows are filtered to their own records.
    if request.method=='GET':
        if not u:
            return jsonify({"error":"Not authenticated"}), 401
        # student/parent isolation: only own / linked children (never the roster)
        allowed = readable_student_ids(u)
        if allowed is not None:
            if not allowed:
                return jsonify([])
            marks_list = ",".join("?" for _ in allowed)
            rows=db.execute(f"SELECT s.*, c.name as class_name, sec.name as section_name FROM students s LEFT JOIN classes c ON s.class_id=c.id LEFT JOIN sections sec ON sec.id=s.section_id WHERE s.id IN ({marks_list}) ORDER BY s.name", sorted(allowed)).fetchall()
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
        sid=(d.get('student_id') or '').strip()
        if not sid: return jsonify({"error":"Student ID required"}),400
        # sid becomes the photo file name AND the QR file name below, both
        # joined straight onto a directory - so a value containing a path
        # separator (Werkzeug's JSON body has no such restriction, and on
        # Windows '\\' is a separator to os.path.join) would write outside
        # data/photos and data/qrcodes. Require a plain identifier.
        if not _safe_id_for_file(sid):
            return jsonify({"error":"Invalid Student ID: use letters, digits, dot, dash or underscore only"}),400
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
    # sid is student_id string. It is used verbatim to build a filesystem
    # path, so it must be a plain identifier - see _safe_id_for_file().
    sid = _safe_id_for_file(sid)
    if not sid:
        abort(404)
    path=os.path.join(QR_DIR, f"{sid}.png")
    if not os.path.exists(path):
        try:
            import qrcode
            img=qrcode.make(sid)
            img.save(path)
        except Exception:
            # a bare `except:` hid the real failure; surface it in the log
            app.logger.exception("QR generation failed for %s", sid)
            return jsonify({"error":"QR generation failed"}),500
    return send_file(path, mimetype='image/png')

@app.route('/api/photos/<fn>')
def photo_api(fn):
    # Profile photos may sit on a persistent disk (PROFILE_UPLOAD_DIR) while
    # student photos stay in data/photos; serve whichever directory holds it.
    # _public_image() takes the basename first: Werkzeug's <fn> converter only
    # excludes '/', so on Windows a '%5C' (backslash) in the URL used to reach
    # os.path.join() as a separator and escape the directory.
    fn = os.path.basename((fn or '').replace('\\', '/'))
    if not fn or not _PUBLIC_FILE_RE.match(fn):
        abort(404)
    if PROFILE_UPLOAD_DIR != PHOTO_DIR:
        alt = os.path.join(PROFILE_UPLOAD_DIR, fn)
        if os.path.isfile(alt):
            return send_file(alt, conditional=True)
    full = os.path.join(PHOTO_DIR, fn)
    if not os.path.isfile(full):
        abort(404)
    return send_file(full, conditional=True)

# ---------- Attendance ----------
@app.route('/api/attendance', methods=['GET','POST'])
def attendance_api():
    db=get_db()
    if request.method=='GET':
        date=request.args.get('date') or datetime.date.today().isoformat()
        class_id=request.args.get('class_id')
        section_id=request.args.get('section_id')
        u=get_current_user()
        if not u:
            return jsonify({"error":"Not authenticated"}), 401
        allowed = readable_student_ids(u)
        holiday=is_holiday(date)
        holiday_row=db.execute("SELECT * FROM holidays WHERE date=?", (date,)).fetchone()
        if allowed is not None:
            # student / parent: never the class list — only rows they are linked to
            ids = sorted(allowed)
            want = request.args.get('student_id')
            if want:
                res = student_scope(u, want)
                if isinstance(res, tuple):
                    return res
                ids = [res]
            if not ids:
                return jsonify({"date":date, "is_holiday": holiday,
                                "holiday": dict(holiday_row) if holiday_row else None, "students":[]})
            marks_list = ",".join("?" for _ in ids)
            sql=("SELECT s.*, a.status, a.leave_reason FROM students s "
                 "LEFT JOIN attendance a ON a.student_id=s.id AND a.date=? "
                 f"WHERE s.id IN ({marks_list})")
            rows=db.execute(sql, [date]+ids).fetchall()
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
        # Idempotent write: SQLite treats NULL as distinct inside UNIQUE(), so
        # INSERT OR REPLACE kept stacking duplicate rows for the daily
        # (subject-less) slot. Clear the slot first, then insert one row.
        if subject_id:
            db.execute("DELETE FROM attendance WHERE student_id=? AND date=? AND subject_id=?",
                       (sid, date, subject_id))
            db.execute("INSERT INTO attendance (student_id,date,status,leave_reason,subject_id,time,marked_by,marked_at,session) VALUES (?,?,?,?,?,?,?,?,?)",
                       (sid, date, st, e.get('leave_reason',''), subject_id, tm, u['id'], now, session_name))
        else:
            db.execute("DELETE FROM attendance WHERE student_id=? AND date=? AND (subject_id IS NULL OR subject_id='')",
                       (sid, date))
            db.execute("INSERT INTO attendance (student_id,date,status,leave_reason,time,marked_by,marked_at,session) VALUES (?,?,?,?,?,?,?,?)",
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
    d=request.get_json() or {}
    student_code=(d.get('code') or '').strip() # student_id string
    status=(d.get('status') or 'P').upper()
    date=d.get('date') or datetime.date.today().isoformat()
    if status not in ('P','A','L','T'):
        return jsonify({"error":f"Invalid status {status}. Use P/A/L/T"}),400
    if is_holiday(date):
        return jsonify({"error":"Holiday - attendance blocked"}),400
    db=get_db()
    row=db.execute("SELECT id FROM students WHERE student_id=?", (student_code,)).fetchone()
    if not row: return jsonify({"error":"Student not found"}),404
    # Idempotent write (same pattern as the bulk endpoint above): the daily
    # slot has subject_id NULL, and SQLite treats NULL as distinct inside
    # UNIQUE(student_id,date,subject_id), so INSERT OR REPLACE never replaced
    # anything - scanning the same student twice stacked duplicate rows with
    # conflicting statuses that the roster then listed twice. Clear the slot
    # first so a repeat scan updates rather than duplicates.
    db.execute("DELETE FROM attendance WHERE student_id=? AND date=? AND (subject_id IS NULL OR subject_id='')",
               (row[0], date))
    db.execute("INSERT INTO attendance (student_id,date,status) VALUES (?,?,?)", (row[0], date, status))
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
    # present etc — newest mark per student (never raw rows)
    mm=status_counts(db, date=date, class_id=class_id, section_id=section_id, subject_id=subject_id)
    present=mm.get('P',0); absent=mm.get('A',0); leave=mm.get('L',0); late=mm.get('T',0)
    not_marked= total - present - absent - leave - late
    pct= round(min(((present+late)/total*100) if total else 0, 100.0),1)
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

# ---------- Attendance maths helper ----------
def status_counts(db, date=None, month=None, class_id=None, section_id=None,
                  subject_id=None, scope_sql="", scope_params=()):
    """Status -> number of *students* for a date (or a whole month).

    A student can legitimately be marked once per subject, and rows written
    before the idempotent-save fix could repeat, so counting raw rows would
    double-count people and push percentages past 100. We keep only the newest
    mark per student per date instead.
    """
    where = "a.date=?" if date else "substr(a.date,1,7)=?"
    head_params = []
    slot = "1=1"
    if subject_id:
        slot = "x.subject_id=?"
        head_params.append(subject_id)
    tail = " WHERE " + where
    tail_params = [date or month]
    if class_id:
        tail += " AND s.class_id=?"; tail_params.append(class_id)
    if section_id:
        tail += " AND s.section_id=?"; tail_params.append(section_id)
    if scope_sql:
        tail += scope_sql; tail_params.extend(scope_params)
    if subject_id:
        tail += " AND a.subject_id=?"; tail_params.append(subject_id)
    sql = (
        "SELECT status, COUNT(*) c FROM ("
        "  SELECT a.date AS d, ("
        "    SELECT x.status FROM attendance x"
        "     WHERE x.student_id=a.student_id AND x.date=a.date AND " + slot +
        "     ORDER BY x.id DESC LIMIT 1) AS status"
        "  FROM attendance a JOIN students s ON s.id=a.student_id" + tail +
        "  GROUP BY a.student_id, a.date"
        ") WHERE status IS NOT NULL GROUP BY status"
    )
    rows = db.execute(sql, head_params + tail_params).fetchall()
    return {r['status']: r['c'] for r in rows}

def _valid_month(month, default=None):
    """Validate a user-supplied 'YYYY-MM' query parameter.

    Returns the normalised string, *default* when the parameter is absent, or
    None when it is malformed. Every caller previously did
    ``y,m = month.split('-')`` straight off ``request.args``: '2026' unpacks to
    one value, '2026-10-11' to three, '2026-13' fails ``monthrange`` and 'abc'
    fails ``int()`` - each an uncaught ValueError that surfaced as HTTP 500
    instead of a 400.
    """
    if not month:
        return default
    p = str(month).split('-')
    if len(p) != 2:
        return None
    try:
        y, m = int(p[0]), int(p[1])
    except ValueError:
        return None
    if not (1 <= m <= 12 and 1 <= y <= 9999):
        return None
    return "%04d-%02d" % (y, m)

# ---------- Attendance Calendar (monthly day-wise) ----------
@app.route('/api/calendar')
def calendar_api():
    db=get_db()
    month=_valid_month(request.args.get('month'))  # YYYY-MM
    class_id=request.args.get('class_id')
    section_id=request.args.get('section_id')
    if not month: return jsonify({"error":"month required YYYY-MM"}),400
    import calendar as calmod
    y,m=month.split('-')
    y=int(y); m=int(m)
    days=calmod.monthrange(y,m)[1]
    # RBAC: aggregate calendar is school-wide, but students/parents only get
    # the rows they are allowed to read.
    allowed = readable_student_ids(get_current_user())
    scope_sql = "" if allowed is None else (
        " AND s.id IN (%s)" % (",".join("?" * len(allowed)) if allowed else "-1")
    )
    out=[]
    for d in range(1, days+1):
        ds=f"{y:04d}-{m:02d}-{d:02d}"
        mm = status_counts(db, date=ds, class_id=class_id, section_id=section_id,
                           scope_sql=scope_sql,
                           scope_params=(sorted(allowed) if allowed is not None else []))
        total=sum(mm.values())
        pct=round(min(((mm.get('P',0)+mm.get('T',0))/total*100) if total else 0, 100.0),1)
        out.append({"date":ds,"weekday":datetime.datetime.strptime(ds,"%Y-%m-%d").strftime("%a"),"present":mm.get('P',0),"absent":mm.get('A',0),"leave":mm.get('L',0),"late":mm.get('T',0),"total":total,"percentage":pct,"is_holiday":is_holiday(ds)})
    return jsonify({"month":month,"days":out})

# ---------- Analytics ----------
@app.route('/api/analytics')
def analytics_api():
    db=get_db()
    class_id=request.args.get('class_id')
    section_id=request.args.get('section_id')
    # RBAC: students/parents may only ever read their own (or their linked
    # children's) rows. None == unrestricted for admin/teacher.
    allowed = readable_student_ids(get_current_user())
    restricted = allowed is not None
    # weekly last 7 days
    weekly=[]
    for i in range(6,-1,-1):
        d=(datetime.date.today()-datetime.timedelta(days=i)).isoformat()
        mm = status_counts(db, date=d, class_id=class_id, section_id=section_id)
        total=sum(mm.values())
        pct=round(min(((mm.get('P',0)+mm.get('T',0))/total*100) if total else 0, 100.0),1)
        weekly.append({"date":d,"present":mm.get('P',0),"absent":mm.get('A',0),"late":mm.get('T',0),"leave":mm.get('L',0),"percentage":pct})
    # monthly last 6 months
    monthly=[]
    today=datetime.date.today()
    for k in range(5,-1,-1):
        yy=today.year; mm_=today.month-k
        while mm_<=0: mm_+=12; yy-=1
        mkey=f"{yy:04d}-{mm_:02d}"
        mm = status_counts(db, month=mkey, class_id=class_id, section_id=section_id)
        total=sum(mm.values())
        pct=round(min(((mm.get('P',0)+mm.get('T',0))/total*100) if total else 0, 100.0),1)
        monthly.append({"month":mkey,"percentage":pct,"present":mm.get('P',0),"absent":mm.get('A',0)})
    # class comparison
    comp=[]
    if not restricted:
        for r in db.execute("SELECT id, name FROM classes ORDER BY CAST(name AS INTEGER) LIMIT 12"):
            sql="SELECT COUNT(*) FROM students WHERE class_id=?"; params=[r['id']]
            total=db.execute(sql, params).fetchone()[0]
            prow=db.execute("SELECT COUNT(*) FROM attendance a JOIN students s ON s.id=a.student_id WHERE s.class_id=? AND a.status IN ('P','T')", (r['id'],)).fetchone()[0]
            arow=db.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='P'", (datetime.date.today().isoformat(),)).fetchone()[0]
            comp.append({"class": r["name"], "total": total, "present_records": prow})
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
        if restricted and (allowed is None or int(s['id']) not in allowed):
            continue
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
        d=request.get_json() or {}
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
        name=(request.get_json() or {}).get('name','').strip()
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
        u = get_current_user()
        if not u:
            return jsonify({"error":"Not authenticated"}), 401
        student_id=request.args.get('student_id')
        exam_type=request.args.get('exam_type')
        sql="SELECT m.*, s.name as subject_name FROM marks m JOIN subjects s ON s.id=m.subject_id WHERE 1=1"
        params=[]
        allowed = readable_student_ids(u)
        if allowed is not None:
            # student / parent: hard-restrict to their own readable rows
            if not allowed:
                return jsonify([])
            if student_id:
                res = student_scope(u, student_id)
                if isinstance(res, tuple):
                    return res
            marks_list = ",".join("?" for _ in allowed)
            sql += f" AND m.student_id IN ({marks_list})"
            params.extend(sorted(allowed))
        elif student_id:
            sql += " AND m.student_id=?"; params.append(student_id)
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
    u=get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}), 401
    class_id=request.args.get('class_id')
    exam_type=request.args.get('exam_type')
    sql="""SELECT st.id, st.student_id, st.name, st.roll_no, c.name as class_name, sec.name as sec_name
           FROM students st LEFT JOIN classes c ON c.id=st.class_id LEFT JOIN sections sec ON sec.id=st.section_id WHERE 1=1"""
    params=[]
    if class_id: sql+=" AND st.class_id=?"; params.append(class_id)
    allowed = readable_student_ids(u)
    if allowed is not None:
        # a student/parent only ever sees their own report card, never the class list
        if not allowed:
            return jsonify([])
        marks_list = ",".join("?" for _ in allowed)
        sql += f" AND st.id IN ({marks_list})"
        params.extend(sorted(allowed))
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
    u = get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}), 401
    db=get_db()
    month=_valid_month(request.args.get('month')) # YYYY-MM
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
    allowed = readable_student_ids(u)
    if allowed is not None:
        # a student/parent only ever gets their own row out of the monthly report
        if not allowed:
            return jsonify({"month":month, "working_days":len(working), "working_dates":working, "students":[]})
        marks_list = ",".join("?" for _ in allowed)
        sql += f" AND s.id IN ({marks_list})"
        params.extend(sorted(allowed))
    students=db.execute(sql, params).fetchall()
    out=[]
    for s in students:
        # one mark per date — a student can appear once per subject, and raw
        # row counts would let "present" exceed the number of working days.
        mc={row[0]: row[1] for row in db.execute(
            "SELECT status, COUNT(*) c FROM ("
            "  SELECT date, (SELECT x.status FROM attendance x"
            "                 WHERE x.student_id=a.student_id AND x.date=a.date"
            "                 ORDER BY x.id DESC LIMIT 1) AS status"
            "    FROM attendance a WHERE a.student_id=? AND substr(a.date,1,7)=?"
            "   GROUP BY date"
            ") WHERE status IS NOT NULL GROUP BY status",
            (s['id'], month)).fetchall()}
        present=mc.get('P',0); absent=mc.get('A',0); leave=mc.get('L',0)
        pct= round(min(present/len(working)*100, 100.0),1) if working else 0
        out.append({"student":dict(s), "present":present, "absent":absent, "leave":leave, "working_days":len(working), "pct":pct})
    return jsonify({"month":month, "working_days":len(working), "working_dates":working, "students":out})

# ---------- Reports & Exports ----------
@app.route('/api/export/monthly/excel')
def export_monthly_excel():
    hit=_check_api_rate("reports")
    if hit: return hit
    # heavy report -> background-friendly: paginate students (limit 500)
    month=_valid_month(request.args.get('month'))
    if not month:
        # month may be absent entirely; the old code called None.split('-'),
        # which was an AttributeError -> HTTP 500 rather than a 400.
        return jsonify({"error":"month required YYYY-MM"}),400
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
    month=_valid_month(request.args.get('month'))
    if not month:
        # month may be absent entirely; the old code called None.split('-'),
        # which was an AttributeError -> HTTP 500 rather than a 400.
        return jsonify({"error":"month required YYYY-MM"}),400
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
    if row and verify_pw(row['password_hash'], p):
        # Credentials are right, but the account may still be awaiting approval.
        # This message is only ever shown to someone who already proved they
        # own the password, so it leaks nothing to an attacker.
        st = row['status'] or 'active'
        if st != 'active':
            get_db().execute("INSERT INTO login_history (username,time,success) VALUES (?,?,?)", (u, datetime.datetime.now().isoformat(), 0))
            get_db().commit()
            return jsonify({"error": _PENDING_STATUS_MSG.get(
                st, "This account is not active. Please contact the school office.")}), 403
        success=1
        _upgrade_password_hash(get_db(), row['id'], row['password_hash'], p)
        get_db().execute("INSERT INTO login_history (username,time,success) VALUES (?,?,?)", (u, datetime.datetime.now().isoformat(), 1))
        get_db().commit()
        _LOGIN_ATTEMPTS.pop(f"login:{ip}", None)
        session.permanent = True
        session['user_id'] = row['id']
        session['role'] = row['role']
        session['username'] = row['username']
        session['epoch'] = int(row['auth_epoch'] or 0)
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

def _student_detail(pk):
    row = get_db().execute(
        """SELECT s.*, c.name as class_name, sec.name as section_name
           FROM students s
           LEFT JOIN classes c ON c.id=s.class_id
           LEFT JOIN sections sec ON sec.id=s.section_id
           WHERE s.id=?""", (pk,)).fetchone()
    return dict(row) if row else None

@app.route('/api/auth/me', methods=['GET'])
def me():
    u = get_current_user()
    if not u:
        return jsonify({"user":None}), 200
    # include linked student details if student/parent
    linked = _student_detail(u['linked_student_id']) if u.get('linked_student_id') else None
    # every student row this account is allowed to read (1 for a student, 1..n for a parent)
    children = []
    allowed = readable_student_ids(u)
    if allowed:
        for pk in sorted(allowed):
            d = _student_detail(pk)
            if d: children.append(d)
    parent_row = None
    if u['role'] == 'parent':
        pr = get_db().execute("SELECT parent_id, name, phone, email FROM parents WHERE user_id=?", (u['id'],)).fetchone()
        parent_row = dict(pr) if pr else None
    if not linked and children:
        linked = children[0]
    return jsonify({"user":u, "linked_student": linked, "children": children, "parent": parent_row})

@app.route('/api/auth/check', methods=['GET'])
def auth_check():
    u = get_current_user()
    if not u:
        return jsonify({"authenticated":False}), 401
    return jsonify({"authenticated":True, "user":u})

def _finish_login(row):
    """Create the session for an authenticated users row and return the JSON payload."""
    st = (row['status'] or 'active') if 'status' in row.keys() else 'active'
    if st != 'active':
        # Correct password but the registration has not been approved yet.
        return jsonify({"error": _PENDING_STATUS_MSG.get(
            st, "This account is not active. Please contact the school office.")}), 403
    db = get_db()
    db.execute("INSERT INTO login_history (username,time,success) VALUES (?,?,?)",
               (row['username'], datetime.datetime.now().isoformat(), 1))
    db.commit()
    session.permanent = True
    session['user_id'] = row['id']
    session['role'] = row['role']
    session['username'] = row['username']
    session['epoch'] = int(row['auth_epoch'] or 0) if 'auth_epoch' in row.keys() else 0
    return jsonify({"ok":True, "user":{
        "id":row['id'], "username":row['username'], "role":row['role'],
        "permissions": json.loads(row['permissions'] or '[]'),
        "linked_student_id": row['linked_student_id']}})

def _login_fail(u, ip):
    """Uniform failure: log it, rate-limit it, never reveal which half was wrong."""
    db = get_db()
    db.execute("INSERT INTO login_history (username,time,success) VALUES (?,?,?)",
               (u or '', datetime.datetime.now().isoformat(), 0))
    db.commit()
    if _rate_limited(f"login:{ip}", limit=10, window=300):
        return jsonify({"success": False, "error": {
            "code": "RATE_LIMITED",
            "message": "Too many unsuccessful login attempts. Please try again later."}}), 429
    return jsonify({"error":"Invalid credentials"}), 401

@app.route('/api/auth/student-login', methods=['POST'])
def student_login():
    """Student sign-in by Student ID **or** Admission Number + password.

    The identifier is only ever used to *locate* the account; the session is bound
    to the users row, and every later read goes through student_scope().
    """
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
    d = request.get_json() or {}
    ident = (d.get('identifier') or '').strip()
    pw = d.get('password') or ''
    if not ident or not pw:
        return jsonify({"error":"Student ID and password are required"}), 400
    db = get_db()
    st = db.execute(
        "SELECT id FROM students WHERE lower(student_id)=lower(?) OR lower(admission_no)=lower(?)",
        (ident, ident)).fetchone()
    user = None
    if st:
        user = db.execute("SELECT * FROM users WHERE role='student' AND linked_student_id=?",
                          (st['id'],)).fetchone()
    if not user:
        user = db.execute("SELECT * FROM users WHERE role='student' AND lower(username)=lower(?)",
                          (ident,)).fetchone()
    if user and verify_pw(user['password_hash'], pw):
        _upgrade_password_hash(db, user['id'], user['password_hash'], pw)
        return _finish_login(user)
    return _login_fail(ident, ip)

@app.route('/api/auth/parent-login', methods=['POST'])
def parent_login():
    """Parent sign-in by Parent ID / registered mobile / username + password or PIN."""
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
    d = request.get_json() or {}
    ident = (d.get('identifier') or '').strip()
    pw = d.get('password') or ''
    if not ident or not pw:
        return jsonify({"error":"Parent ID / mobile number and password are required"}), 400
    db = get_db()
    user = None
    prow = db.execute(
        "SELECT user_id FROM parents WHERE (lower(parent_id)=lower(?) OR phone=?) AND user_id IS NOT NULL "
        "ORDER BY id LIMIT 1",
        (ident, ident)).fetchone()
    if prow and prow['user_id']:
        user = db.execute("SELECT * FROM users WHERE id=? AND role='parent'", (prow['user_id'],)).fetchone()
    if not user:
        user = db.execute("SELECT * FROM users WHERE role='parent' AND lower(username)=lower(?)",
                          (ident,)).fetchone()
    if user and verify_pw(user['password_hash'], pw):
        _upgrade_password_hash(db, user['id'], user['password_hash'], pw)
        return _finish_login(user)
    return _login_fail(ident, ip)

@app.route('/api/auth/change-password', methods=['POST'])
def change_password():
    u = get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}), 401
    d = request.get_json() or {}
    cur = d.get('current_password') or ''
    new = d.get('new_password') or ''
    db = get_db()
    row = db.execute("SELECT password_hash FROM users WHERE id=?", (u['id'],)).fetchone()
    if not row or not verify_pw(row['password_hash'], cur):
        return jsonify({"error":"Current password is incorrect"}), 403
    # The policy is only evaluated once the caller has proved they own the
    # account, so someone who cannot change the password never gets told the
    # rules. auth_epoch is deliberately left alone here: the user already has
    # an explicit "sign out other devices" control, and the unauthenticated
    # reset flow below is what bumps it.
    msg = _pw_policy(new)
    if msg:
        return jsonify({"error": msg}), 400
    if new == cur:
        return jsonify({"error":"New password must be different from the current one"}), 400
    db.execute("UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
               (hash_pw(new), now_iso(), u['id']))
    if u['role'] == 'parent':
        try: db.execute("UPDATE parents SET password_hash=? WHERE user_id=?", (hash_pw(new), u['id']))
        except Exception: pass
    db.commit()
    return jsonify({"ok":True, "message":"Password updated"})

# ===================== Sign-up, profiles & recovery =====================
#
# Rules everything below obeys:
#   * a password is only ever hashed (hash_pw/verify_pw) and is never logged,
#     echoed back, or included in any error message
#   * tokens are stored as SHA-256 of the token, so a database dump cannot be
#     replayed as a reset/verify link
#   * every write goes through an explicit allowlist -> no mass assignment
#   * a self-registered account starts 'pending' and can never open a session,
#     so public sign-up cannot mint an admin/teacher/parent/student account

_UPLOAD_PREFIX = 'pf'
_IMG_MAX = 2 * 1024 * 1024          # 2 MB, same ceiling the school logo uses
_IMG_EXTS = ('.jpg', '.png', '.webp')

# --- Password policy (applied only when a NEW password is chosen) ----------
_PW_MIN = 8
_PW_COMMON = {'password1', 'qwerty123', 'letmein123', 'welcome123',
              'abc12345', 'iloveyou1', 'password12'}

def pw_problems(p):
    """The requirements `p` fails. An empty list means acceptable."""
    p = p or ''
    bad = []
    if len(p) < _PW_MIN:
        bad.append("at least %d characters" % _PW_MIN)
    if not re.search(r'[A-Za-z]', p):
        bad.append("a letter")
    if not re.search(r'\d', p):
        bad.append("a number")
    if p.lower() in _PW_COMMON:
        bad.append("a less common phrase")
    return bad

def _pw_policy(p):
    bad = pw_problems(p)
    return ("Password must have " + ", ".join(bad) + ".") if bad else None

_USERNAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{2,29}$')
_EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}$')

def _clean_text(v, limit):
    return str(v or '').strip()[:limit]

def _valid_dob(s):
    s = str(s or '').strip()
    if not s:
        return True
    try:
        d = datetime.date.fromisoformat(s)
    except ValueError:
        return False
    today = datetime.date.today()
    return d <= today and d.year >= today.year - 120

def _valid_language(v):
    """Is this a plausible language name, in any script?

    A regex of \\w cannot do this: Python's \\w is built from str.isalnum(), and
    Devanagari/Bengali/Arabic are assembled from *combining marks* (the vowel
    signs and viramas) that are category Mn, not alnum. `\\w+` therefore rejects
    the perfectly ordinary language name "हिन्दी". Classifying each character
    explicitly accepts every real script while still refusing control
    characters and markup.
    """
    v = str(v or '')
    if not (1 <= len(v) <= 40):
        return False
    for ch in v:
        if ch in " .'-()":                 # "English (US)", "Portuguese-Brazil"
            continue
        if unicodedata.category(ch)[0] in ('L', 'M', 'N'):
            continue                       # letters, combining marks, digits
        return False
    return True

# --- Single-use tokens ------------------------------------------------------
def _issue_token(db, user_id, kind, minutes):
    """Mint a token; only its SHA-256 is persisted. Returns the raw token."""
    raw = secrets.token_urlsafe(32)
    h = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    now = datetime.datetime.now()
    # Retire any previous live token of this kind first (one active link at a
    # time) - also keeps the ux_prt_live unique index satisfied.
    db.execute("UPDATE password_reset_tokens SET used=1 "
               "WHERE user_id=? AND kind=? AND used=0", (user_id, kind))
    db.execute("INSERT INTO password_reset_tokens "
               "(user_id,token_hash,kind,expires_at,used,created_at) "
               "VALUES (?,?,?,?,0,?)",
               (user_id, h, kind,
                (now + datetime.timedelta(minutes=minutes)).isoformat(),
                now.isoformat()))
    db.commit()
    return raw

def _consume_token(db, raw, kind):
    """Validate and burn a token. Returns the user id, or None."""
    if not raw:
        return None
    h = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    row = db.execute("SELECT * FROM password_reset_tokens "
                     "WHERE token_hash=? AND kind=? AND used=0",
                     (h, kind)).fetchone()
    if not row:
        return None
    try:
        if datetime.datetime.fromisoformat(row['expires_at']) < datetime.datetime.now():
            db.execute("UPDATE password_reset_tokens SET used=1 WHERE id=?", (row['id'],))
            db.commit()
            return None
    except ValueError:
        return None
    db.execute("UPDATE password_reset_tokens SET used=1 WHERE id=?", (row['id'],))
    db.commit()
    return row['user_id']

def _dev_tokens():
    """Should a freshly issued token be returned in the HTTP response?

    There is no SMTP/SMS gateway in this app, so without this the link could
    never reach a human - the school office mints links manually instead
    (POST /api/users/<id>/token). Default is **off**: a default of "on unless
    production" would mean one missing env var silently exposes every reset
    link in production. Set PROFILE_DEV_TOKENS=1 for local development/tests.
    """
    v = os.environ.get('PROFILE_DEV_TOKENS')
    if v is None:
        return False
    return v.strip().lower() in ('1', 'true', 'yes', 'on')

# --- Profile row + completion ---------------------------------------------
def _profile_row(db, user_id):
    row = db.execute("SELECT * FROM user_profiles WHERE user_id=?",
                     (user_id,)).fetchone()
    if row:
        return row
    now = datetime.datetime.now().isoformat()
    db.execute("INSERT INTO user_profiles (user_id, created_at, updated_at) "
               "VALUES (?,?,?)", (user_id, now, now))
    db.commit()
    return db.execute("SELECT * FROM user_profiles WHERE user_id=?",
                      (user_id,)).fetchone()

def _socials_of(p):
    try:
        v = json.loads(p['socials'] or '{}')
    except (ValueError, TypeError):
        v = {}
    return v if isinstance(v, dict) else {}

def profile_completion(p):
    """Five non-sensitive, genuinely optional signals, 20% each.

    Deliberately nothing here is personal data (no name, contact, DOB, gender
    or location), so nobody is pushed to hand over information they would
    rather keep private.
    """
    socials = _socials_of(p)
    items = [
        ("photo",     "Profile photo", bool((p['photo'] or '').strip())),
        ("display",   "Display name",  bool((p['display_name'] or '').strip())),
        ("bio",       "Bio",           bool((p['bio'] or '').strip())),
        ("interests", "Interests",     bool((p['interests'] or '').strip())),
        ("social",    "A social link", any((v or '').strip() for v in socials.values())),
    ]
    return {"percent": sum(1 for _, _, ok in items if ok) * 20,
            "items": [{"key": k, "label": lab, "done": ok} for k, lab, ok in items]}

# --- Images ----------------------------------------------------------------
def _upload_dir():
    # Retried per upload: on Render the persistent disk may mount after boot.
    try:
        os.makedirs(PROFILE_UPLOAD_DIR, exist_ok=True)
    except OSError:
        pass
    return PROFILE_UPLOAD_DIR

def _sniff_image(data):
    """Real container type from the first bytes.

    The filename extension and the Content-Type header are both attacker
    controlled; these bytes are not. An uploaded .exe renamed to .png never
    matches, so it is rejected before it can reach disk or a browser.
    """
    if data[:3] == b'\xff\xd8\xff':
        return '.jpg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return '.png'
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp'
    return None

def store_profile_image(f, user_id):
    """Validate, re-encode and save an uploaded image.

    Re-encoding through Pillow does three things: proves the bytes really are
    the image type we sniffed, drops EXIF (which can carry GPS coordinates),
    and enforces a sane pixel ceiling so a decompression bomb cannot be
    served back later. The filename is generated entirely server-side from an
    integer user id plus random hex, so it can never contain a path separator.
    Returns (filename, None) or (None, error_message).
    """
    if not f or not getattr(f, 'filename', ''):
        return None, "No file selected."
    f.stream.seek(0)
    data = f.stream.read(_IMG_MAX + 1)
    if len(data) > _IMG_MAX:
        return None, "Image is too large - the limit is 2 MB."
    ext = _sniff_image(data)
    if not ext:
        return None, "Only JPEG, PNG or WebP images are allowed."
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = 40_000_000   # decompression-bomb guard
        im = Image.open(io.BytesIO(data))
        im.load()
        im.thumbnail((1024, 1024))
        if ext == '.jpg':
            im = im.convert('RGB')
        else:
            rgba = im.convert('RGBA')
            # keep transparency only when it is actually used
            if rgba.getchannel('A').getextrema()[1] == 255:
                rgba = rgba.convert('RGB')
            im = rgba
        buf = io.BytesIO()
        if ext == '.png':
            im.save(buf, 'PNG', optimize=True)
        elif ext == '.webp':
            im.save(buf, 'WEBP', quality=85)
        else:
            im.save(buf, 'JPEG', quality=86, optimize=True)
        data = buf.getvalue()
        if len(data) > _IMG_MAX:
            return None, "Image is too large after processing - please use a smaller photo."
    except Exception:
        # Message stays generic: never echo a traceback or Pillow internals.
        return None, "That file could not be read as an image. Please upload a valid JPEG, PNG or WebP."
    d = _upload_dir()
    # Built only from an integer id plus random hex - the caller never
    # influences it, so there is no separator or '..' to escape with.
    name = "%s%d_%s%s" % (_UPLOAD_PREFIX, int(user_id),
                          secrets.token_hex(6), ext)
    try:
        with open(os.path.join(d, name), 'wb') as fh:
            fh.write(data)
    except OSError:
        return None, "Could not save the image. Please try again."
    return name, None

def _delete_stored_image(fn):
    """Best-effort removal of our own generated file name."""
    if not fn:
        return
    if not re.fullmatch(r'pf\d+_[0-9a-f]{12}\.(jpg|png|webp)', fn):
        return
    for d in (PROFILE_UPLOAD_DIR, PHOTO_DIR):
        try:
            os.remove(os.path.join(d, fn))
            return
        except OSError:
            continue

# --- Explicit update allowlist --------------------------------------------
_PROFILE_TEXT = {'full_name': 80, 'display_name': 60, 'bio': 280,
                 'gender': 24, 'pronouns': 32, 'country': 56, 'city': 56,
                 'language': 40, 'interests': 300}
_PROFILE_ENUM = {'theme': ('light', 'dark', 'system'),
                 'visibility': ('private', 'public')}
_PROFILE_FLAGS = ('notify_email', 'notify_app', 'notify_attendance', 'notify_notices',
                  'a11y_large_text', 'a11y_reduced_motion',
                  'show_email', 'show_phone', 'show_dob')
_SOCIAL_KEYS = ('instagram', 'facebook', 'youtube', 'linkedin', 'website', 'other')

def _clean_socials(v):
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise ValueError("Social links must be sent as an object.")
    out = {}
    for k in _SOCIAL_KEYS:
        url = str(v.get(k) or '').strip()
        if not url:
            continue
        if len(url) > 200:
            raise ValueError("That social link is too long.")
        # javascript:, data: etc. would execute if ever rendered as an href.
        if not re.match(r'^https?://', url, re.I):
            raise ValueError("Social links must start with http:// or https://")
        out[k] = url
    return out

def _att_pct(db, sid):
    """Attendance percentage for one student, month to date.

    Formula mirrors the portal's own figure (present + late over the working
    days of the current month) so the profile never shows a number that
    disagrees with My Attendance / Monthly Report.
    """
    today = datetime.date.today()
    import calendar as _cal
    dim = _cal.monthrange(today.year, today.month)[1]
    hols = set(r[0] for r in db.execute("SELECT date FROM holidays").fetchall())
    working = 0
    for d in range(1, dim + 1):
        ds = "%04d-%02d-%02d" % (today.year, today.month, d)
        if datetime.datetime.strptime(ds, "%Y-%m-%d").weekday() == 6:
            continue
        if ds in hols:
            continue
        working += 1
    p = db.execute("SELECT COUNT(*) FROM attendance "
                   "WHERE student_id=? AND status IN ('P','T') AND substr(date,1,7)=?",
                   (sid, today.strftime("%Y-%m"))).fetchone()[0]
    return round(p / working * 100, 1) if working else 0.0

def _profile_context(db, u):
    """Role-appropriate facts drawn from the existing tables.

    Nothing here invents a new permission: a student only ever sees the row
    linked to their account, a parent only their own children, and a teacher
    only the classes they are actually scheduled in.
    """
    out = {}
    role = u['role']
    if role == 'student':
        sid = u.get('linked_student_id')
        if sid:
            row = db.execute("""SELECT s.id, s.student_id, s.name, s.class_id, s.section_id,
                                       c.name AS class_name, sec.name AS section_name
                                  FROM students s
                                  LEFT JOIN classes c ON c.id=s.class_id
                                  LEFT JOIN sections sec ON sec.id=s.section_id
                                 WHERE s.id=?""", (sid,)).fetchone()
            if row:
                out['student'] = dict(row)
                out['attendance_percent'] = _att_pct(db, sid)
                out['attendance_view'] = 'attcal'
    elif role == 'parent':
        allowed = sorted(readable_student_ids(u) or [])
        kids = []
        for pk in allowed:
            row = db.execute("""SELECT s.id, s.student_id, s.name, s.class_id, s.section_id,
                                       c.name AS class_name, sec.name AS section_name
                                  FROM students s
                                  LEFT JOIN classes c ON c.id=s.class_id
                                  LEFT JOIN sections sec ON sec.id=s.section_id
                                 WHERE s.id=?""", (pk,)).fetchone()
            if row:
                d = dict(row)
                d['attendance_percent'] = _att_pct(db, pk)
                kids.append(d)
        if kids:
            out['children'] = kids
    elif role == 'teacher':
        t = db.execute("SELECT id, name, email, subject, assigned_class FROM teachers "
                       "WHERE user_id=?", (u['id'],)).fetchone()
        if t:
            out['staff_record'] = dict(t)
        # Only classes this teacher is actually scheduled in - never a guess.
        out['assigned_classes'] = []
        if t and t['id']:
            out['assigned_classes'] = [dict(r) for r in db.execute("""
                SELECT DISTINCT c.id, c.name AS class_name, sec.name AS section_name
                  FROM timetable_slots sl
                  JOIN timetable_versions v ON v.id=sl.version_id
                  JOIN classes c ON c.id=v.class_id
                  JOIN sections sec ON sec.id=v.section_id
                 WHERE sl.teacher_id=?
                 ORDER BY c.name, sec.name""", (t['id'],)).fetchall()]
    elif role == 'admin':
        s = db.execute("SELECT school_name FROM settings WHERE id=1").fetchone()
        out['school_name'] = s['school_name'] if s else ''
        out['users_total'] = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        out['users_pending'] = db.execute(
            "SELECT COUNT(*) FROM users WHERE status='pending'").fetchone()[0]
    return out


@app.route('/api/auth/register', methods=['POST'])
def auth_register():
    """Public sign-up.

    Creates a **pending** account: it cannot authenticate until an admin
    approves it and assigns the role, which is what stops sign-up from being a
    privilege-escalation path.
    """
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
    if _rate_limited("register:%s" % ip, limit=5, window=900):
        return jsonify({"error": "Too many sign-up attempts. Please try again later."}), 429
    d = request.get_json(silent=True) or {}

    full_name = _clean_text(d.get('full_name'), 80)
    username = _clean_text(d.get('username'), 30)
    email = _clean_text(d.get('email'), 254).lower()
    phone = re.sub(r'[\s()-]', '', _clean_text(d.get('phone'), 20))
    dob = _clean_text(d.get('dob'), 10)
    language = _clean_text(d.get('language'), 40) or 'English'
    country = _clean_text(d.get('country'), 56)
    pw = d.get('password') or ''
    pw2 = d.get('confirm_password') or ''

    fields = {}
    if len(full_name) < 2:
        fields['full_name'] = "Please enter your full name."
    if not _USERNAME_RE.match(username):
        fields['username'] = "3-30 characters: letters, numbers, dot, dash or underscore."
    if not _EMAIL_RE.match(email) or len(email) > 254:
        fields['email'] = "Please enter a valid email address."
    if phone and not re.fullmatch(r'\+?\d{7,15}', phone):
        fields['phone'] = "Enter 7-15 digits, optionally starting with +."
    if dob and not _valid_dob(dob):
        fields['dob'] = "Please enter a valid date of birth."
    # Any real script: हिन्दी, বাংলা, English (US), اردو ... see _valid_language.
    if not _valid_language(language):
        fields['language'] = "Please choose a language name."
    msg = _pw_policy(pw)
    if msg:
        fields['password'] = msg
    elif pw != pw2:
        fields['confirm_password'] = "The two passwords do not match."
    if not d.get('accept_terms'):
        fields['accept_terms'] = "You must accept the Terms of Service and Privacy Policy."

    db = get_db()
    # Uniqueness is checked case-insensitively on both, because SQLite's
    # default TEXT comparison is case sensitive and Admin/admin would collide.
    if not fields.get('username') and db.execute(
            "SELECT 1 FROM users WHERE lower(username)=lower(?)", (username,)).fetchone():
        fields['username'] = "That username is already taken."
    if not fields.get('email') and db.execute(
            "SELECT 1 FROM users WHERE email<>'' AND lower(email)=lower(?)",
            (email,)).fetchone():
        fields['email'] = "That email address is already registered."
    # users.phone carries a unique index (one mobile per account, and parents
    # sign in with it), so check it here rather than letting the INSERT fail
    # and blame the wrong field.
    if phone and db.execute(
            "SELECT 1 FROM users WHERE phone=? AND phone<>''",
            (phone,)).fetchone():
        fields['phone'] = "That mobile number is already registered to another account."

    if fields:
        return jsonify({"error": "Please fix the highlighted fields.",
                        "fields": fields}), 400

    now = datetime.datetime.now().isoformat()
    try:
        cur = db.execute(
            "INSERT INTO users (username, password_hash, role, permissions, "
            "linked_student_id, created_at, email, phone, status, email_verified, "
            "updated_at, auth_epoch) VALUES (?,?,?,?,?,?,?,?,?,?,?,0)",
            (username, hash_pw(pw), 'student', json.dumps([]), None, now,
             email, phone, 'pending', 0, now))
        uid = cur.lastrowid
        db.execute("INSERT INTO user_profiles "
                   "(user_id, full_name, language, country, dob, created_at, updated_at) "
                   "VALUES (?,?,?,?,?,?,?)",
                   (uid, full_name, language, country, dob, now, now))
        db.commit()
    except sqlite3.IntegrityError as e:
        # Lost a race with a concurrent sign-up. Name the column that actually
        # collided instead of always blaming the username.
        msg = str(e)
        if 'email' in msg:
            field, text = 'email', "That email address is already registered."
        elif 'phone' in msg:
            field, text = 'phone', "That mobile number is already registered."
        else:
            field, text = 'username', "That username is already taken."
        return jsonify({"error": "Please fix the highlighted fields.",
                        "fields": {field: text}}), 400

    token = _issue_token(db, uid, 'verify', 60 * 24)
    resp = {"ok": True, "status": "pending", "username": username,
            "message": "Your account has been created and is awaiting approval "
                       "from the school office. You will be able to sign in once "
                       "it has been approved."}
    if _dev_tokens():
        # No mail gateway exists, so without this nobody could ever verify.
        # Only ever emitted outside production (see _dev_tokens).
        resp["verification_token"] = token
    return jsonify(resp), 201


@app.route('/api/auth/verify-email', methods=['POST'])
def auth_verify_email():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
    if _rate_limited("verify:%s" % ip, limit=15, window=900):
        return jsonify({"error": "Too many attempts. Please try again later."}), 429
    d = request.get_json(silent=True) or {}
    db = get_db()
    uid = _consume_token(db, d.get('token') or '', 'verify')
    if not uid:
        return jsonify({"error": "That verification link is invalid or has expired."}), 400
    db.execute("UPDATE users SET email_verified=1, updated_at=? WHERE id=?",
               (datetime.datetime.now().isoformat(), uid))
    db.commit()
    return jsonify({"ok": True, "message": "Email address verified."})


@app.route('/api/auth/forgot-password', methods=['POST'])
def auth_forgot_password():
    """Always answers the same way, whether or not the address exists."""
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
    if _rate_limited("forgot:%s" % ip, limit=5, window=900):
        return jsonify({"error": "Too many attempts. Please try again later."}), 429
    d = request.get_json(silent=True) or {}
    ident = _clean_text(d.get('identifier'), 254)
    generic = {"ok": True,
               "message": "If an account matches that username or email, a "
                          "password reset link has been created."}
    if ident:
        db = get_db()
        row = db.execute("SELECT id FROM users WHERE lower(username)=lower(?) "
                         "OR (email<>'' AND lower(email)=lower(?)) "
                         "ORDER BY id LIMIT 1", (ident, ident)).fetchone()
        if row:
            token = _issue_token(db, row['id'], 'reset', 60)
            if _dev_tokens():
                generic["dev_token"] = token
    return jsonify(generic)


@app.route('/api/auth/reset-password', methods=['POST'])
def auth_reset_password():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
    if _rate_limited("reset:%s" % ip, limit=10, window=900):
        return jsonify({"error": "Too many attempts. Please try again later."}), 429
    d = request.get_json(silent=True) or {}
    pw = d.get('new_password') or ''
    msg = _pw_policy(pw)
    if msg:
        return jsonify({"error": msg}), 400
    if pw != (d.get('confirm_password') or ''):
        return jsonify({"error": "The two passwords do not match."}), 400
    db = get_db()
    uid = _consume_token(db, d.get('token') or '', 'reset')
    if not uid:
        return jsonify({"error": "That reset link is invalid or has expired."}), 400
    row = db.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    db.execute("UPDATE users SET password_hash=?, updated_at=?, "
               "auth_epoch=COALESCE(auth_epoch,0)+1 WHERE id=?", (hash_pw(pw), now_iso(), uid))
    if row and row['role'] == 'parent':
        try:
            db.execute("UPDATE parents SET password_hash=? WHERE user_id=?", (hash_pw(pw), uid))
        except Exception:
            pass
    db.commit()
    # Bumping auth_epoch invalidates every session that existed before the
    # reset, so an attacker holding an old cookie is signed out on next request.
    return jsonify({"ok": True, "message": "Password updated. Please sign in again."})


def now_iso():
    return datetime.datetime.now().isoformat()


@app.route('/api/profile', methods=['GET', 'PUT'])
def profile_api():
    u = get_current_user()
    if not u:
        return jsonify({"error": "Not authenticated"}), 401
    db = get_db()
    acc = db.execute("SELECT id, username, role, email, phone, status, "
                     "email_verified, created_at, linked_student_id "
                     "FROM users WHERE id=?", (u['id'],)).fetchone()
    if not acc:
        return jsonify({"error": "Account not found"}), 404

    if request.method == 'GET':
        p = _profile_row(db, u['id'])
        prof = dict(p)
        prof['socials'] = _socials_of(p)
        return jsonify({
            "account": dict(acc),
            "profile": prof,
            "completion": profile_completion(p),
            "context": _profile_context(db, u),
            "can": {"edit_profile": True,
                    "manage_users": can(u['role'], "teachers", "full"),
                    "public_profile_url": "/api/profile/public/%s" % acc['username']},
        })

    # ---- UPDATE (explicit allowlist; role/permissions/status are unreachable) ----
    d = request.get_json(silent=True) or {}
    errors = {}
    updates = {}
    for col, limit in _PROFILE_TEXT.items():
        if col in d:
            updates[col] = _clean_text(d.get(col), limit)
    if 'bio' in updates and len(updates['bio']) > 280:
        errors['bio'] = "Keep your bio under 280 characters."
    if 'full_name' in updates and len(updates['full_name']) < 2:
        errors['full_name'] = "Please enter your full name."
    if 'language' in updates and updates['language'] \
            and not _valid_language(updates['language']):
        errors['language'] = "Please choose a language name."
    for col, allowed in _PROFILE_ENUM.items():
        if col in d:
            v = str(d.get(col) or '')
            if v not in allowed:
                errors[col] = "Allowed values: " + ", ".join(allowed)
            else:
                updates[col] = v
    for col in _PROFILE_FLAGS:
        if col in d:
            updates[col] = 1 if str(d.get(col)).lower() in ('1', 'true', 'yes', 'on') else 0
    if 'dob' in d:
        v = _clean_text(d.get('dob'), 10)
        if not _valid_dob(v):
            errors['dob'] = "Please enter a valid date of birth."
        else:
            updates['dob'] = v
    if 'socials' in d:
        try:
            updates['socials'] = json.dumps(_clean_socials(d['socials']))
        except ValueError as e:
            errors['socials'] = str(e)

    # Account columns the user may genuinely edit on their own account.
    if 'username' in d:
        username = _clean_text(d.get('username'), 30)
        if not _USERNAME_RE.match(username):
            errors['username'] = "3-30 characters: letters, numbers, dot, dash or underscore."
        elif db.execute("SELECT 1 FROM users WHERE lower(username)=lower(?) AND id<>?",
                        (username, u['id'])).fetchone():
            errors['username'] = "That username is already taken."
        else:
            updates['username'] = username
    if 'email' in d:
        email = _clean_text(d.get('email'), 254).lower()
        if not _EMAIL_RE.match(email):
            errors['email'] = "Please enter a valid email address."
        elif db.execute("SELECT 1 FROM users WHERE email<>'' AND lower(email)=lower(?) AND id<>?",
                        (email, u['id'])).fetchone():
            errors['email'] = "That email address is already registered."
        else:
            updates['email'] = email
            # Re-verify only when the address actually changes, so re-saving an
            # unchanged profile never silently un-verifies the account.
            if email != (acc['email'] or '').lower():
                updates['email_verified'] = 0
    if 'phone' in d:
        phone = re.sub(r'[\s()-]', '', _clean_text(d.get('phone'), 20))
        if phone and not re.fullmatch(r'\+?\d{7,15}', phone):
            errors['phone'] = "Enter 7-15 digits, optionally starting with +."
        elif phone and db.execute("SELECT 1 FROM users WHERE phone=? AND id<>?",
                                  (phone, u['id'])).fetchone():
            errors['phone'] = "That mobile number is already in use."
        else:
            updates['phone'] = phone

    if errors:
        return jsonify({"error": "Please fix the highlighted fields.",
                        "fields": errors}), 400

    profile_cols = [c for c in updates if c in _PROFILE_TEXT or c in _PROFILE_ENUM
                    or c in _PROFILE_FLAGS or c in ('dob', 'socials')]
    user_cols = [c for c in updates if c in ('username', 'email', 'phone', 'email_verified')]
    ts = now_iso()
    try:
        if profile_cols:
            sql = "UPDATE user_profiles SET " + ",".join("%s=?" % c for c in profile_cols) + \
                  ", updated_at=? WHERE user_id=?"
            db.execute(sql, [updates[c] for c in profile_cols] + [ts, u['id']])
        if user_cols:
            sql = "UPDATE users SET " + ",".join("%s=?" % c for c in user_cols) + \
                  ", updated_at=? WHERE id=?"
            db.execute(sql, [updates[c] for c in user_cols] + [ts, u['id']])
        db.commit()
    except sqlite3.IntegrityError as e:
        # A unique index (email/phone) is the only thing that can fire here.
        col = 'phone' if 'phone' in str(e) else 'email'
        return jsonify({"error": "Please fix the highlighted fields.",
                        "fields": {col: "That value is already in use."}}), 400

    p = _profile_row(db, u['id'])
    prof = dict(p)
    prof['socials'] = _socials_of(p)
    return jsonify({"ok": True, "message": "Profile saved.",
                    "profile": prof, "completion": profile_completion(p)})


@app.route('/api/profile/photo', methods=['POST', 'DELETE'])
@app.route('/api/profile/cover', methods=['POST', 'DELETE'])
def profile_photo_api():
    u = get_current_user()
    if not u:
        return jsonify({"error": "Not authenticated"}), 401
    db = get_db()
    col = 'cover_photo' if request.path.endswith('/cover') else 'photo'
    p = _profile_row(db, u['id'])
    if request.method == 'DELETE':
        _delete_stored_image(p[col])
        db.execute("UPDATE user_profiles SET %s='', updated_at=? WHERE user_id=?" % col,
                   (now_iso(), u['id']))
        db.commit()
        return jsonify({"ok": True, "message": "Image removed."})
    f = request.files.get('image') or request.files.get('photo')
    if f is None:
        return jsonify({"error": "No file selected."}), 400
    # Size, magic-byte and Pillow re-encode checks all live in one place, so
    # the avatar and cover paths can never drift apart.
    name, err = store_profile_image(f, u['id'])
    if err:
        return jsonify({"error": err}), 400
    old = p[col]
    db.execute("UPDATE user_profiles SET %s=?, updated_at=? WHERE user_id=?" % col,
               (name, now_iso(), u['id']))
    db.commit()
    if old and old != name:
        _delete_stored_image(old)
    pp = _profile_row(db, u['id'])
    return jsonify({"ok": True, "message": "Photo updated.",
                    col: name, "completion": profile_completion(pp)})


@app.route('/api/profile/sessions', methods=['GET'])
def profile_sessions():
    u = get_current_user()
    if not u:
        return jsonify({"error": "Not authenticated"}), 401
    rows = get_db().execute("SELECT id, time, success FROM login_history "
                            "WHERE username=? ORDER BY id DESC LIMIT 20",
                            (u['username'],)).fetchall()
    ep = get_db().execute("SELECT auth_epoch FROM users WHERE id=?",
                          (u['id'],)).fetchone()
    return jsonify({"sessions": [dict(r) for r in rows],
                    "auth_epoch": int((ep and ep['auth_epoch']) or 0),
                    "note": "Sign-in history for your username."})


@app.route('/api/profile/logout-others', methods=['POST'])
def profile_logout_others():
    """Sign out every other device by bumping auth_epoch.

    get_current_user() compares the epoch baked into the session cookie
    against the row, so every older cookie fails on its next request while
    this one is refreshed to the new value.
    """
    u = get_current_user()
    if not u:
        return jsonify({"error": "Not authenticated"}), 401
    db = get_db()
    db.execute("UPDATE users SET auth_epoch=COALESCE(auth_epoch,0)+1, updated_at=? "
               "WHERE id=?", (now_iso(), u['id']))
    db.commit()
    row = db.execute("SELECT auth_epoch FROM users WHERE id=?", (u['id'],)).fetchone()
    session['epoch'] = int(row['auth_epoch'] or 0)
    return jsonify({"ok": True,
                    "message": "All other devices have been signed out."})


@app.route('/api/profile/delete-request', methods=['GET', 'POST'])
def profile_delete_request():
    """Request account removal - never an instant self-serve deletion.

    An admin must decide it, and closing a login account never touches
    attendance, marks or any other school record.
    """
    u = get_current_user()
    if not u:
        return jsonify({"error": "Not authenticated"}), 401
    db = get_db()
    if request.method == 'GET':
        row = db.execute("SELECT * FROM account_deletion_requests WHERE user_id=? "
                         "AND status='pending' ORDER BY id DESC LIMIT 1",
                         (u['id'],)).fetchone()
        return jsonify({"request": dict(row) if row else None})
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
    if _rate_limited("delreq:%s" % ip, limit=5, window=900):
        return jsonify({"error": "Too many attempts. Please try again later."}), 429
    existing = db.execute("SELECT id FROM account_deletion_requests "
                          "WHERE user_id=? AND status='pending'", (u['id'],)).fetchone()
    if existing:
        return jsonify({"error": "You already have a pending deletion request."}), 409
    d = request.get_json(silent=True) or {}
    if not str(d.get('confirm') or '').strip():
        return jsonify({"error": "Please type DELETE to confirm."}), 400
    db.execute("INSERT INTO account_deletion_requests (user_id, reason, status, created_at) "
               "VALUES (?,?, 'pending', ?)",
               (u['id'], _clean_text(d.get('reason'), 300), now_iso()))
    admins = db.execute("SELECT id FROM users WHERE role='admin'").fetchall()
    for a in admins:
        db.execute("INSERT INTO notifications (user_id, type, title, content, date, read) "
                   "VALUES (?,?,?,?,?,0)",
                   (a['id'], 'account',
                    'Account deletion request',
                    "%s requested account deletion." % u['username'], now_iso()))
    db.commit()
    return jsonify({"ok": True,
                    "message": "Your request has been sent to the school office."})


@app.route('/api/profile/public/<username>', methods=['GET'])
def profile_public(username):
    """Exact-username lookup for profiles the owner made public.

    There is deliberately no listing or search endpoint, and the response is a
    fixed allowlist: no role, no email/phone/DOB unless explicitly opted in,
    and never any attendance, class or other student data.
    """
    db = get_db()
    row = db.execute("SELECT u.username, p.* FROM users u "
                     "JOIN user_profiles p ON p.user_id=u.id "
                     "WHERE lower(u.username)=lower(?)", (str(username)[:30],)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    if (row['visibility'] or 'private') != 'public':
        # Same answer as a missing profile: existence itself is not leaked.
        return jsonify({"error": "Not found"}), 404
    out = {"username": row['username'],
           "display_name": row['display_name'], "bio": row['bio'],
           "photo": row['photo'], "cover_photo": row['cover_photo'],
           "city": row['city'], "country": row['country'],
           "language": row['language'], "interests": row['interests'],
           "socials": _socials_of(row)}
    if row['show_email']:
        out['email'] = db.execute("SELECT email FROM users WHERE username=?",
                                  (row['username'],)).fetchone()[0]
    if row['show_phone']:
        out['phone'] = db.execute("SELECT phone FROM users WHERE username=?",
                                  (row['username'],)).fetchone()[0]
    if row['show_dob']:
        out['dob'] = row['dob']
    return jsonify(out)


@app.route('/api/users', methods=['GET','POST','PUT','DELETE'])
def users_api():
    db=get_db()
    u=get_current_user()
    if not u or not can(u['role'], "teachers", "full"):
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='GET':
        rows=db.execute("""SELECT id,username,role,permissions,created_at,status,email,
                                  phone,email_verified
                             FROM users ORDER BY id""").fetchall()
        return jsonify([dict(r) for r in rows])
    if request.method=='POST':
        d=request.get_json() or {}
        uname = _clean_text(d.get('username'), 30)
        role = str(d.get('role') or '')
        if not _USERNAME_RE.match(uname):
            return jsonify({"error":"Username must be 3-30 characters: letters, numbers, dot, dash or underscore."}),400
        if role not in ROLES:
            return jsonify({"error":"role must be one of: "+", ".join(ROLES)}),400
        # Same policy as self-service sign-up: an admin account must not be
        # created with a weaker password than a public one could use.
        msg = _pw_policy(d.get('password') or '')
        if msg:
            return jsonify({"error": msg}),400
        try:
            db.execute("INSERT INTO users (username,password_hash,role,permissions,created_at,email,phone,status) VALUES (?,?,?,?,?,?,?,?)",
                       (uname, hash_pw(d['password']), role, json.dumps(d.get('permissions',[])),
                        datetime.datetime.now().isoformat(),
                        _clean_text(d.get('email'), 254).lower(),
                        re.sub(r'[\s()-]', '', _clean_text(d.get('phone'), 20)),
                        'active'))
            db.commit()
            return jsonify({"ok":True})
        except sqlite3.IntegrityError:
            return jsonify({"error":"Duplicate username"}),400
    if request.method=='PUT':
        # The trusted workflow that approves self-registered accounts and is
        # the ONLY place a role may be assigned.
        uid=request.args.get('id')
        d=request.get_json(silent=True) or {}
        row=db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not row: return jsonify({"error":"User not found"}),404
        updates={}
        if 'status' in d:
            st=str(d.get('status') or '')
            if st not in ('active','pending','rejected','suspended'):
                return jsonify({"error":"status must be active, pending, rejected or suspended"}),400
            updates['status']=st
        if 'role' in d:
            role=str(d.get('role') or '')
            if role not in ROLES:
                return jsonify({"error":"role must be one of: "+", ".join(ROLES)}),400
            updates['role']=role
        if 'permissions' in d:
            perms=d.get('permissions')
            if not isinstance(perms,list) or any(p not in PERMISSIONS for p in perms):
                return jsonify({"error":"Unknown permission in list"}),400
            updates['permissions']=json.dumps(perms)
        if 'email_verified' in d:
            updates['email_verified']=1 if str(d.get('email_verified')).lower() in ('1','true','yes') else 0
        if not updates:
            return jsonify({"error":"Nothing to update"}),400
        updates['updated_at']=now_iso()
        db.execute("UPDATE users SET "+",".join("%s=?"%c for c in updates)+" WHERE id=?",
                   [updates[c] for c in updates]+[int(uid)])
        db.commit()
        return jsonify({"ok":True,"user":dict(db.execute(
            "SELECT id,username,role,status,email_verified FROM users WHERE id=?",
            (uid,)).fetchone())})
    uid=request.args.get('id')
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()
    return jsonify({"ok":True})


@app.route('/api/users/<int:uid>/token', methods=['POST'])
def user_issue_token(uid):
    """Issue a fresh verify/reset link for another account (admin only).

    Because only the token hash is stored, the school office cannot read an
    existing link - they can only mint a new one and pass it on out of band.
    """
    u=get_current_user()
    if not u or not can(u['role'], "teachers", "full"):
        return jsonify({"error":"Access denied: Admin only"}),403
    db=get_db()
    if not db.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
        return jsonify({"error":"User not found"}),404
    d=request.get_json(silent=True) or {}
    kind=str(d.get('kind') or 'verify')
    if kind not in ('verify','reset'):
        return jsonify({"error":"kind must be verify or reset"}),400
    raw=_issue_token(db, uid, kind, 60*24 if kind=='verify' else 60)
    return jsonify({"ok":True,"kind":kind,"token":raw,
                    "hint": ("Hand this to the user, then POST it to "
                             "/api/auth/verify-email"
                             if kind=='verify' else
                             "Hand this to the user, then POST it to "
                             "/api/auth/reset-password")})


@app.route('/api/account-deletions', methods=['GET','POST'])
def account_deletions():
    u=get_current_user()
    if not u or not can(u['role'], "teachers", "full"):
        return jsonify({"error":"Access denied: Admin only"}),403
    db=get_db()
    if request.method=='GET':
        rows=db.execute("""SELECT r.*, us.username, us.role
                             FROM account_deletion_requests r
                             JOIN users us ON us.id=r.user_id
                            ORDER BY r.id DESC LIMIT 100""").fetchall()
        return jsonify([dict(r) for r in rows])
    d=request.get_json(silent=True) or {}
    rid=d.get('id')
    decision=str(d.get('decision') or '')
    if decision not in ('approved','rejected'):
        return jsonify({"error":"decision must be approved or rejected"}),400
    row=db.execute("SELECT * FROM account_deletion_requests WHERE id=?", (rid,)).fetchone()
    if not row: return jsonify({"error":"Request not found"}),404
    db.execute("UPDATE account_deletion_requests SET status=?, decided_by=?, decided_at=? WHERE id=?",
               (decision, u['id'], now_iso(), rid))
    if decision=='approved':
        # Close the login only. Attendance, marks and every other school record
        # are left untouched - those belong to the school, not to the login.
        db.execute("UPDATE users SET status='suspended', auth_epoch=COALESCE(auth_epoch,0)+1, "
                   "updated_at=? WHERE id=?", (now_iso(), row['user_id']))
    db.commit()
    return jsonify({"ok":True,"status":decision})


@app.route('/api/login_history')
def login_history():
    u = get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}), 401
    if u['role'] != 'admin':
        return jsonify({"error":"Access denied: Admin only"}), 403
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
        d=request.get_json() or {}
        db.execute("INSERT INTO staff (name,role,phone) VALUES (?,?,?)", (d['name'], d['role'], d.get('phone')))
        db.commit()
        return jsonify({"ok":True})
    sid=request.args.get('id')
    db.execute("DELETE FROM staff WHERE id=?", (sid,))
    db.commit()
    return jsonify({"ok":True})

# ---------- Teachers (RBAC) ----------
@app.route('/api/teachers', methods=['GET','POST','PUT','DELETE'])
def teachers_api():
    db=get_db()
    u=get_current_user()
    if request.method=='GET':
        if not u or not can(u['role'], "teachers", "view"):
            # RBAC["teachers"] is {"admin":"full", "teacher":"none",
            # "student":"none", "parent":"none"} and can() returns False for
            # "none". This guard only returned [] for student/parent, so a
            # TEACHER satisfied the outer condition but not the inner one and
            # fell straight through to the SELECT - receiving the entire
            # staff table (phone, email, user_id) the matrix denies them.
            # Students/parents keep the empty list the portal expects.
            if u and u['role'] in ('student','parent'):
                return jsonify([]), 200
            return jsonify({"error":"Access denied"}),403
        return jsonify([dict(r) for r in db.execute("SELECT * FROM teachers ORDER BY id DESC").fetchall()])
    if not u or not can(u['role'], "teachers", "full"):
        return jsonify({"error":"Access denied: Admin only"}),403

    def _link_user(payload):
        """Resolve an optional teacher-account link.

        teachers.user_id is what lets the teacher dashboard find "my periods".
        Only an existing user with role='teacher' may be linked, and one user
        cannot be attached to two staff records.
        """
        if 'user_id' not in payload:
            return None, None
        uid = payload.get('user_id')
        if uid in (None, '', 0, '0'):
            return None, None
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            return None, "user_id must be an integer."
        row = db.execute("SELECT id, role FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            return None, "That user account does not exist."
        if row['role'] != 'teacher':
            return None, "Only accounts with the teacher role can be linked."
        taken = db.execute("SELECT id FROM teachers WHERE user_id=? ", (uid,)).fetchone()
        if taken:
            return None, "That account is already linked to another staff record."
        return uid, None

    if request.method == 'POST':
        d = request.get_json() or {}
        if not (d.get('name') or '').strip():
            return jsonify({"error":"Name is required."}), 400
        uid, err = _link_user(d)
        if err: return jsonify({"error": err}), 400
        db.execute("INSERT INTO teachers (name,email,subject,phone,assigned_class,user_id) VALUES (?,?,?,?,?,?)",
                   (d.get('name'), d.get('email'), d.get('subject'), d.get('phone'), d.get('assigned_class'), uid))
        db.commit()
        return jsonify({"ok":True})

    if request.method == 'PUT':
        d = request.get_json() or {}
        tid = _tt_int(request.args.get('id'))
        if not tid: return jsonify({"error":"id is required."}), 400
        row = db.execute("SELECT * FROM teachers WHERE id=?", (tid,)).fetchone()
        if not row: return jsonify({"error":"Staff record not found."}), 404
        uid, err = _link_user(d)
        if err: return jsonify({"error": err}), 400
        fields, params = [], []
        for col in ("name", "email", "subject", "phone", "assigned_class"):
            if col in d:
                fields.append(f"{col}=?"); params.append(d.get(col))
        if 'user_id' in d:
            fields.append("user_id=?"); params.append(uid)
        if not fields:
            return jsonify({"error":"Nothing to update."}), 400
        params.append(tid)
        db.execute(f"UPDATE teachers SET {','.join(fields)} WHERE id=?", params)
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
        # Explicit column list rather than p.*: the table gained a
        # password_hash column, which SELECT p.* was serialising straight into
        # the JSON response. No endpoint should ever return a password hash,
        # even to an admin.
        return jsonify([dict(r) for r in db.execute("SELECT p.id,p.name,p.phone,p.email,p.student_id,p.user_id,p.school_id,p.parent_id,s.name as student_name FROM parents p LEFT JOIN students s ON s.id=p.student_id ORDER BY p.id DESC").fetchall()])
    if not u or not can(u['role'], "parents", "full"):
        return jsonify({"error":"Access denied: Admin only"}),403
    if request.method=='POST':
        d=request.get_json() or {}
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
        d=request.get_json() or {}
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
        d=request.get_json() or {}
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
        d=request.get_json() or {}
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
        d=request.get_json() or {}
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
        d=request.get_json() or {}
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
    u=get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}), 401
    if request.method=='GET':
        allowed = readable_student_ids(u)
        if allowed is None:
            rows = db.execute("SELECT * FROM complaints ORDER BY id DESC").fetchall()
        elif not allowed:
            rows = []
        else:
            marks_list = ",".join("?" for _ in allowed)
            rows = db.execute(f"SELECT * FROM complaints WHERE student_id IN ({marks_list}) OR student_id IS NULL ORDER BY id DESC",
                              sorted(allowed)).fetchall()
        return jsonify([dict(r) for r in rows])
    if request.method=='POST':
        d=request.get_json() or {}
        if not (d.get('text') or '').strip():
            return jsonify({"error":"Please describe your concern"}), 400
        sid = d.get('student_id')
        name = d.get('name') or ''
        if u['role'] in ('student','parent'):
            res = student_scope(u, sid, must_have_link=True)
            if isinstance(res, tuple):
                return res
            sid = res
            detail = _student_detail(sid)
            name = (d.get('name') or '').strip() or (detail['name'] if detail else u['username'])
        db.execute("INSERT INTO complaints (student_id,name,text,status,date) VALUES (?,?,?,?,?)",
                   (sid, name, d['text'], 'Open', datetime.date.today().isoformat()))
        db.commit()
        return jsonify({"ok":True})
    # status toggle / delete: staff only
    if not can(u['role'], "complaints", "edit"):
        return jsonify({"error":"Access denied"}), 403
    cid=request.args.get('id')
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
        d=request.get_json() or {}
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
    d=request.get_json() or {}
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
    month=_valid_month(request.args.get('month'),
                       default=datetime.date.today().strftime("%Y-%m"))
    if month is None:
        return jsonify({"error":"month must be YYYY-MM"}),400
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
        # Ownership must not rest on users.linked_student_id alone. That column
        # is NULL for every self-registered account and no admin path can set
        # it, so the old guard was skipped entirely and the caller-supplied
        # student_id was trusted - any student could read any classmate's goal
        # and attendance percentage with ?student_id=7. student_scope() also
        # consults parent_students / parents and refuses anything outside the
        # caller's own set.
        req_sid = request.args.get('student_id')
        if not req_sid and u and u.get('linked_student_id'):
            req_sid = str(u['linked_student_id'])   # keep the old default
        scoped = student_scope(u, req_sid, must_have_link=True)
        if isinstance(scoped, tuple):
            return scoped
        student_id=str(scoped)
        # ORDER BY id DESC: this table historically had no unique constraint on
        # (scope, ref_id), so INSERT OR REPLACE inserted a fresh row on every
        # save and fetchone() returned the FIRST (oldest) one - a target set
        # weeks ago shadowed every later edit. Prefer the newest row so legacy
        # duplicates resolve to what the office most recently saved.
        g=db.execute("SELECT * FROM attendance_goals WHERE scope='student' AND ref_id=? ORDER BY id DESC LIMIT 1", (student_id,)).fetchone()
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
    if not d.get('student_id'):
        return jsonify({"error":"student_id required"}),400
    try:
        target=float(d.get('target',90))
    except (TypeError, ValueError):
        return jsonify({"error":"target must be a number"}),400
    now=datetime.datetime.now().isoformat()
    # attendance_goals has no UNIQUE(scope, ref_id), so INSERT OR REPLACE had
    # nothing to conflict against: every save inserted a brand-new row (which
    # the read then ignored, returning the oldest). Update the existing row
    # and only insert when this student has no goal yet.
    n=db.execute("UPDATE attendance_goals SET target=?, updated_by=?, updated_at=? WHERE scope='student' AND ref_id=?",
                 (target, u['id'], now, d.get('student_id'))).rowcount
    if not n:
        db.execute("INSERT INTO attendance_goals (scope,ref_id,target,updated_by,updated_at) VALUES ('student',?,?,?,?)",
                   (d.get('student_id'), target, u['id'], now))
    db.commit()
    return jsonify({"ok":True, "student_id":d.get('student_id'), "target":target, "updated":bool(n)})

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

# ---------- Timetable (legacy endpoint, kept for the dashboard) ----------
def _tt_working_draft(db, u, class_id, section_id, session_id):
    """Get a draft the admin can safely edit, forking the published one if needed.

    Published timetables are never edited in place — that is what keeps the
    change history truthful (spec A). Returns (version_id, error_tuple).
    """
    now_iso = datetime.datetime.now().isoformat()
    d = db.execute("""SELECT id FROM timetable_versions
                       WHERE class_id=? AND section_id=? AND session_id=? AND status='draft'
                       ORDER BY effective_from DESC, id DESC LIMIT 1""",
                   (class_id, section_id, session_id)).fetchone()
    if d: return d['id'], None
    live = _live_version(db, class_id, section_id, session_id)
    if live:
        try:
            cur = db.execute("""INSERT INTO timetable_versions
                  (session_id,class_id,section_id,name,status,effective_from,parent_id,created_by,created_at)
                  VALUES (?,?,?,?,?,?,?,?,?)""",
                  (session_id, class_id, section_id, "Draft of #%d" % live['id'], 'draft',
                   datetime.date.today().isoformat(), live['id'], u['id'], now_iso))
        except sqlite3.IntegrityError:
            return None, ({"error":"Could not create a draft timetable."}, 409)
        _tt_write_slots(db, cur.lastrowid,
                        [dict(r) for r in db.execute("SELECT * FROM timetable_slots WHERE version_id=?",
                                                     (live['id'],)).fetchall()])
        _tt_log(db, cur.lastrowid, class_id, section_id, 'create',
                f"Forked draft from published version #{live['id']}", {"from": live['id']}, u['id'])
        db.commit()
        return cur.lastrowid, None
    cur = db.execute("""INSERT INTO timetable_versions
          (session_id,class_id,section_id,name,status,effective_from,created_by,created_at)
          VALUES (?,?,?,?,?,?,?,?)""",
          (session_id, class_id, section_id, '', 'draft',
           datetime.date.today().isoformat(), u['id'], now_iso))
    _tt_log(db, cur.lastrowid, class_id, section_id, 'create', "Created draft timetable",
            {"session_id": session_id}, u['id'])
    db.commit()
    return cur.lastrowid, None

@app.route('/api/timetable', methods=['GET','POST','DELETE'])
def timetable_api():
    db = get_db()
    u = get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}), 401
    if request.method == 'GET':
        if not can(u['role'], 'timetable', 'view'):
            return jsonify({"error":"Access denied"}), 403
        day = request.args.get('day') or datetime.datetime.now().strftime("%A")
        if day not in TT_DAYS:
            day = datetime.datetime.now().strftime("%A")
        class_id = _tt_int(request.args.get('class_id'))
        section_id = _tt_int(request.args.get('section_id'))
        student_id = _tt_int(request.args.get('student_id'))
        session_id = _tt_active_session_id(db)
        today = datetime.date.today().isoformat()
        subjects, teachers = _tt_names(db)

        rows = []
        allowed = readable_student_ids(u)
        if allowed is not None:
            # students/parents only ever see their own class (spec H) — the class
            # is derived from the database link, never trusted from the query string
            class_id, section_id, _, err = _tt_scope(db, u, class_id, section_id, student_id, '')
            if err: return jsonify(err[0]), err[1]
            ver = _live_version(db, class_id, section_id, session_id, today)
            if ver:
                rows = db.execute("""SELECT sl.*, v.class_id, v.section_id,
                                            c.name AS class_name, s.name AS section_name
                                       FROM timetable_slots sl
                                       JOIN timetable_versions v ON v.id=sl.version_id
                                       LEFT JOIN classes c ON c.id=v.class_id
                                       LEFT JOIN sections s ON s.id=v.section_id
                                      WHERE sl.version_id=? AND sl.day=? ORDER BY sl.start_time""",
                                  (ver['id'], day)).fetchall()
        elif u['role'] == 'teacher':
            tids = _teacher_ids_for_user(db, u)
            if class_id is None and section_id is None and tids:
                q = ",".join("?" * len(tids))
                rows = db.execute(f"""SELECT sl.*, v.class_id, v.section_id,
                                             c.name AS class_name, s.name AS section_name
                                        FROM timetable_slots sl
                                        JOIN timetable_versions v ON v.id=sl.version_id
                                        LEFT JOIN classes c ON c.id=v.class_id
                                        LEFT JOIN sections s ON s.id=v.section_id
                                       WHERE v.status='published' AND v.effective_from<=?
                                         AND sl.day=? AND sl.teacher_id IN ({q})
                                       ORDER BY sl.start_time""",
                                  [today, day] + tids).fetchall()
            elif class_id is not None:
                if section_id is None:
                    sec = db.execute("SELECT id FROM sections WHERE class_id=? ORDER BY id LIMIT 1",
                                     (class_id,)).fetchone()
                    section_id = sec[0] if sec else None
                if not _teacher_teaches(db, tids, class_id, section_id):
                    return jsonify({"error":"You are not assigned to this class."}), 403
                ver = _live_version(db, class_id, section_id, session_id, today)
                if ver:
                    rows = db.execute("""SELECT sl.*, v.class_id, v.section_id,
                                                c.name AS class_name, s.name AS section_name
                                           FROM timetable_slots sl
                                           JOIN timetable_versions v ON v.id=sl.version_id
                                           LEFT JOIN classes c ON c.id=v.class_id
                                           LEFT JOIN sections s ON s.id=v.section_id
                                          WHERE sl.version_id=? AND sl.day=? ORDER BY sl.start_time""",
                                      (ver['id'], day)).fetchall()
        else:
            # admin: every published class, or one class when explicitly requested
            if class_id is not None and section_id is not None:
                vers = [v['id'] for v in db.execute(
                    "SELECT id FROM timetable_versions WHERE class_id=? AND section_id=? AND status='published' AND effective_from<=?",
                    (class_id, section_id, today)).fetchall()]
                if vers:
                    rows = db.execute("""SELECT sl.*, v.class_id, v.section_id,
                                                c.name AS class_name, s.name AS section_name
                                           FROM timetable_slots sl
                                           JOIN timetable_versions v ON v.id=sl.version_id
                                           LEFT JOIN classes c ON c.id=v.class_id
                                           LEFT JOIN sections s ON s.id=v.section_id
                                          WHERE sl.version_id=? AND sl.day=? ORDER BY sl.start_time""",
                                      (vers[0], day)).fetchall()
            else:
                rows = db.execute("""SELECT sl.*, v.class_id, v.section_id,
                                            c.name AS class_name, s.name AS section_name
                                       FROM timetable_slots sl
                                       JOIN timetable_versions v ON v.id=sl.version_id
                                       LEFT JOIN classes c ON c.id=v.class_id
                                       LEFT JOIN sections s ON s.id=v.section_id
                                      WHERE v.status='published' AND v.effective_from<=?
                                        AND sl.day=?
                                      ORDER BY v.class_id, v.section_id, sl.start_time""",
                                  (today, day)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d['period_time'] = "%s-%s" % (r['start_time'], r['end_time'])
            d['subject_id'] = r['subject_id']
            d['subject_name'] = subjects.get(r['subject_id']) or r['name'] or ''
            d['teacher_name'] = teachers.get(r['teacher_id']) or ''
            d['kind'] = r['kind']
            d['status'] = r['status']
            cnt = 0
            if r['class_id']:
                cnt = db.execute("""SELECT COUNT(*) FROM attendance a
                                      JOIN students st ON st.id=a.student_id
                                     WHERE a.date=? AND st.class_id=? AND st.section_id=?""",
                                 (today, r['class_id'], r['section_id'])).fetchone()[0]
            d['completed'] = cnt > 0
            out.append(d)
        return jsonify(out)

    # ---- writes: administrators only (spec H) ----
    if not can(u['role'], 'timetable', 'full'):
        return jsonify({"error":"Access denied: Admin only"}), 403

    if request.method == 'POST':
        d = request.get_json(silent=True) or {}
        class_id, section_id = _tt_int(d.get('class_id')), _tt_int(d.get('section_id'))
        if not class_id or not section_id:
            return jsonify({"error":"class_id and section_id are required."}), 400
        day = str(d.get('day') or '')
        if day not in TT_DAYS:
            return jsonify({"error":"day must be a full weekday name."}), 400
        session_id = _tt_active_session_id(db)
        settings = _tt_settings(db, session_id, class_id, section_id)
        start = str(d.get('period_time') or '').strip()
        if _tt_minutes(start) is None:
            return jsonify({"error":"period_time must be a clock time in HH:MM format."}), 400
        mins = _tt_minutes(start) + int(settings['period_minutes'])
        if mins >= 24 * 60:
            return jsonify({"error":"That start time leaves no room for a period."}), 400
        end = _tt_hhmm(mins)
        subj_id = _tt_int(d.get('subject_id'))
        if not subj_id and d.get('subject_name'):
            srow = db.execute("SELECT id FROM subjects WHERE lower(name)=lower(?)",
                              (str(d.get('subject_name')).strip(),)).fetchone()
            if srow: subj_id = srow[0]
        vid, err = _tt_working_draft(db, u, class_id, section_id, session_id)
        if err: return jsonify(err[0]), err[1]
        cur_ver = db.execute("SELECT * FROM timetable_versions WHERE id=?", (vid,)).fetchone()
        existing = [dict(r) for r in db.execute("SELECT * FROM timetable_slots WHERE version_id=?",
                                                (vid,)).fetchall()]
        existing = [s for s in existing if not (s['day'] == day and s['start_time'] == start)]
        new_cell = {"day": day, "start_time": start, "end_time": end,
                    "name": str(d.get('subject_name') or 'Period')[:80], "kind": "period",
                    "subject_id": subj_id, "teacher_id": _tt_int(d.get('teacher_id')),
                    "room": str(d.get('room') or '')[:40], "status": "active"}
        candidate = existing + [new_cell]
        errors = _tt_validate_or_409(db, dict(cur_ver), candidate, settings)
        if errors:
            db.rollback()
            return jsonify({"error":"That period conflicts with the existing timetable.",
                            "errors":errors, "saved":False}), 409
        try:
            _tt_write_slots(db, vid, candidate)
            _tt_log(db, vid, class_id, section_id, 'edit',
                    f"Added {day} {start} via quick add", {"day": day, "start": start}, u['id'])
            db.commit()
        except Exception as e:
            db.rollback()
            return jsonify({"error":"Could not save the period.","detail":str(e)[:200]}), 500
        return jsonify({"ok":True, "version_id":vid})

    tid = _tt_int(request.args.get('id'))
    if not tid:
        return jsonify({"error":"id is required."}), 400
    # prefer the new model, fall back to the legacy flat table
    # NOTE: sl.* and v.status would both be called "status", and sqlite3.Row
    # resolves a duplicate name to the FIRST column (the slot's 'active'), which
    # would silently defeat this published-version guard. Alias both.
    slot = db.execute("""SELECT sl.*, v.class_id, v.section_id,
                                v.status AS version_status, sl.status AS slot_status
                           FROM timetable_slots sl
                           JOIN timetable_versions v ON v.id=sl.version_id
                          WHERE sl.id=?""", (tid,)).fetchone()
    if slot:
        if slot['version_status'] == 'published':
            return jsonify({"error":"This timetable is published — duplicate it into a draft to make changes."}), 409
        db.execute("DELETE FROM timetable_slots WHERE id=?", (tid,))
        _tt_log(db, slot['version_id'], slot['class_id'], slot['section_id'], 'edit',
                "Removed a period", {"slot_id": tid}, u['id'])
        db.commit()
        return jsonify({"ok":True})
    db.execute("DELETE FROM timetable WHERE id=?", (tid,))
    db.commit()
    return jsonify({"ok":True})

# ---------- Parent Snapshot ----------
@app.route('/api/snapshot')
def snapshot_api():
    db=get_db()
    u=get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}),401
    res = student_scope(u, request.args.get('student_id'),
                        must_have_link=(u['role'] in ('student','parent')))
    if isinstance(res, tuple):
        return res
    sid = res
    if not sid: return jsonify({"error":"student_id required"}),400
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
    res = student_scope(u, request.args.get('student_id'),
                        must_have_link=(bool(u) and u['role'] in ('student','parent')))
    if isinstance(res, tuple):
        return res
    sid = res
    if not sid: return jsonify({"error":"student_id required"}),400
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
    res = student_scope(u, request.args.get('student_id'),
                        must_have_link=(bool(u) and u['role'] in ('student','parent')))
    if isinstance(res, tuple):
        return res
    sid = res
    if not sid: return jsonify({"error":"student_id required"}),400
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
        allowed = readable_student_ids(u)
        if allowed is not None:
            if not allowed:
                return jsonify([])
            marks_list = ",".join("?" for _ in allowed)
            rows=db.execute(f"SELECT r.*, s.name as student_name FROM review_requests r JOIN students s ON s.id=r.student_id WHERE r.student_id IN ({marks_list}) ORDER BY r.id DESC", sorted(allowed)).fetchall()
            return jsonify([dict(r) for r in rows])
        rows=db.execute("SELECT r.*, s.name as student_name FROM review_requests r JOIN students s ON s.id=r.student_id ORDER BY r.id DESC LIMIT 100").fetchall()
        return jsonify([dict(r) for r in rows])
    if request.method=='POST':
        d=request.get_json() or {}
        # student/parent create for own / linked child only
        sid=d.get('student_id') or u.get('linked_student_id')
        if u['role'] in ('student','parent'):
            res = student_scope(u, sid)
            if isinstance(res, tuple):
                return res
            sid = res
        if not sid or not d.get('date'):
            return jsonify({"error":"student_id and date required"}),400
        # review_requests.student_id is a foreign key and PRAGMA foreign_keys
        # is ON, so a stale id (e.g. a student deleted in another tab) raised
        # an unhandled IntegrityError -> HTTP 500. Validate it is a real
        # student first. student/parent are already constrained above by
        # student_scope(), which returns 403 for anyone else's id.
        if u['role'] in ('admin','teacher') and not db.execute("SELECT id FROM students WHERE id=?", (sid,)).fetchone():
            return jsonify({"error":"Invalid student_id"}),400
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
        ns=(request.args.get('new_status') or '').strip().upper()
        # attendance.status carries CHECK(status IN ('P','A','L','T')), so an
        # unvalidated value (the UI prompts for free text) raised an
        # unhandled IntegrityError -> HTTP 500.
        if ns not in ('P','A','L','T'):
            return jsonify({"error":f"Invalid status {ns}. Use P/A/L/T"}),400
        # Idempotent write: the daily slot has subject_id NULL and SQLite
        # treats NULL as distinct inside UNIQUE(student_id,date,subject_id),
        # so INSERT OR REPLACE inserted a second row instead of replacing -
        # approving a review for an already-marked date duplicated the mark.
        db.execute("DELETE FROM attendance WHERE student_id=? AND date=? AND (subject_id IS NULL OR subject_id='')",
                   (row['student_id'], row['date']))
        db.execute("INSERT INTO attendance (student_id,date,status) VALUES (?,?,?)", (row['student_id'], row['date'], ns))
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
    # Now genuinely reachable: it is a POST, so the GET allowlist never
    # covered it and _guard_api returned 401 before this handler ran - the
    # public site's contact form was silently dead. With the route public it
    # needs a limit of its own so it cannot be used to flood `complaints`.
    hit = _api_limited("contact", _client_id(), 5, 300)
    if hit:
        return jsonify({"error": "Too many messages. Please try again later."}), 429
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
    # int() on user input: "ttl_minutes":"abc" raised ValueError and
    # "ttl_minutes":null raised TypeError - both uncaught -> HTTP 500.
    try:
        ttl = int(d.get('ttl_minutes') or 5)
    except (TypeError, ValueError):
        return jsonify({"error":"ttl_minutes must be a whole number of minutes"}),400
    if ttl < 1 or ttl > 1440:
        # an unbounded TTL minted a scanning token that stayed live
        # indefinitely, which defeats the point of an expiring QR.
        return jsonify({"error":"ttl_minutes must be between 1 and 1440"}),400
    token = secrets.token_urlsafe(16)
    exp = (datetime.datetime.now() + datetime.timedelta(minutes=ttl)).isoformat()
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
    # students/parents may only mark own/child attendance. The old guard keyed
    # solely on users.linked_student_id, which is NULL for every
    # self-registered account - so it was skipped entirely and any student
    # holding the class QR could mark a classmate present. readable_student_ids()
    # also consults parent_students / parents, so multi-child parents keep
    # working. It returns None for admin/teacher, who stay unrestricted here.
    allowed = readable_student_ids(u)
    if allowed is not None:
        if not student_code:
            return jsonify({"error": "You can only mark your own attendance"}), 403
        probe = get_db().execute("SELECT id FROM students WHERE student_id=?", (student_code,)).fetchone()
        if not probe or probe['id'] not in allowed:
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

# =================================================================
#  Student & Parent Portal — read APIs (ownership enforced centrally)
# =================================================================
def _grade_for(pct):
    if pct is None: return ""
    if pct >= 90: return "A+"
    if pct >= 80: return "A"
    if pct >= 70: return "B+"
    if pct >= 60: return "B"
    if pct >= 50: return "C"
    if pct >= 40: return "D"
    return "E"

def _portal_scope(u, must_have_link=True):
    """Resolve the requested child (or the caller's own record)."""
    res = student_scope(u, request.args.get('student_pk') or request.args.get('student_id'),
                        must_have_link=must_have_link)
    if isinstance(res, tuple):
        return None, res
    if must_have_link and not res:
        return None, (jsonify({"error":"No student linked to this account"}), 403)
    return res, None

@app.route('/api/portal/profile')
def portal_profile():
    u = get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}), 401
    pk, err = _portal_scope(u)
    if err: return err
    db = get_db()
    s = _student_detail(pk)
    if not s:
        return jsonify({"error":"Not found"}), 404
    par = [dict(r) for r in db.execute(
        "SELECT name, phone, email, parent_id FROM parents WHERE student_id=? OR user_id=?",
        (pk, u['id'])).fetchall()]
    sch = db.execute("SELECT school_name, address, contact FROM settings WHERE id=1").fetchone()
    return jsonify({"student": s, "guardians": par,
                    "school": dict(sch) if sch else None})

@app.route('/api/portal/overview')
def portal_overview():
    """Everything the student/parent home screen needs in one round-trip."""
    u = get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}), 401
    pk, err = _portal_scope(u)
    if err: return err
    db = get_db()
    s = _student_detail(pk)
    if not s:
        return jsonify({"error":"Not found"}), 404

    mkey = request.args.get('month') or datetime.date.today().strftime("%Y-%m")
    try:
        y, m = [int(x) for x in mkey.split('-')]
    except Exception:
        y, m = datetime.date.today().year, datetime.date.today().month
        mkey = datetime.date.today().strftime("%Y-%m")
    import calendar as calmod
    dim = calmod.monthrange(y, m)[1]
    hset = set(x[0] for x in db.execute("SELECT date FROM holidays").fetchall())
    recs = {r['date']: dict(r) for r in db.execute(
        "SELECT date, status, leave_reason FROM attendance WHERE student_id=? AND substr(date,1,7)=?",
        (pk, mkey)).fetchall()}

    cal = []
    present = absent = leave = late = working = 0
    for d in range(1, dim + 1):
        ds = f"{y:04d}-{m:02d}-{d:02d}"
        dow = datetime.datetime.strptime(ds, "%Y-%m-%d").weekday()
        is_hol = (ds in hset) or dow == 6
        rec = recs.get(ds)
        st = rec['status'] if rec else ('H' if is_hol else None)
        cal.append({"date": ds, "dow": dow, "status": st, "holiday": is_hol,
                    "reason": (rec or {}).get('leave_reason') or ('Holiday' if is_hol else '')})
        if not is_hol:
            working += 1
            if st == 'P': present += 1
            elif st == 'A': absent += 1
            elif st == 'L': leave += 1
            elif st == 'T': late += 1
    attended = present + late
    pct = round(attended / working * 100, 1) if working else 0

    today = datetime.date.today().isoformat()
    trow = db.execute("SELECT status FROM attendance WHERE student_id=? AND date=? ORDER BY rowid DESC LIMIT 1",
                      (pk, today)).fetchone()
    hw_total = db.execute(
        "SELECT COUNT(*) FROM homework WHERE (class_id IS NULL OR class_id=?) AND (section_id IS NULL OR section_id=?)",
        (s['class_id'], s['section_id'])).fetchone()[0]
    hw_due = db.execute(
        "SELECT COUNT(*) FROM homework WHERE (class_id IS NULL OR class_id=?) AND (section_id IS NULL OR section_id=?) AND due_date<=?",
        (s['class_id'], s['section_id'], (datetime.date.today() + datetime.timedelta(days=3)).isoformat())).fetchone()[0]
    notices = [dict(r) for r in db.execute("SELECT * FROM notices ORDER BY id DESC LIMIT 5").fetchall()]
    upcoming = [dict(r) for r in db.execute("SELECT * FROM datesheets WHERE class_id=? ORDER BY date LIMIT 5",
                                            (s['class_id'],)).fetchall()]

    return jsonify({
        "student": s,
        "month": mkey,
        "calendar": cal,
        "stats": {"working": working, "present": present, "absent": absent,
                  "leave": leave, "late": late, "percentage": pct},
        "today": trow[0] if trow else None,
        "homework": {"total": hw_total, "due_soon": hw_due},
        "notices": notices,
        "upcoming_exams": upcoming,
    })

@app.route('/api/portal/attendance')
def portal_attendance():
    u = get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}), 401
    pk, err = _portal_scope(u)
    if err: return err
    db = get_db()
    mkey = request.args.get('month') or datetime.date.today().strftime("%Y-%m")
    try:
        y, m = [int(x) for x in mkey.split('-')]
    except Exception:
        y, m = datetime.date.today().year, datetime.date.today().month
        mkey = datetime.date.today().strftime("%Y-%m")
    import calendar as calmod
    dim = calmod.monthrange(y, m)[1]
    hset = set(x[0] for x in db.execute("SELECT date FROM holidays").fetchall())
    recs = {r['date']: dict(r) for r in db.execute(
        "SELECT date, status, leave_reason, time FROM attendance WHERE student_id=? AND substr(date,1,7)=?",
        (pk, mkey)).fetchall()}
    cal = []
    present = absent = leave = late = working = 0
    for d in range(1, dim + 1):
        ds = f"{y:04d}-{m:02d}-{d:02d}"
        dow = datetime.datetime.strptime(ds, "%Y-%m-%d").weekday()
        is_hol = (ds in hset) or dow == 6
        rec = recs.get(ds)
        st = rec['status'] if rec else ('H' if is_hol else None)
        cal.append({"date": ds, "dow": dow, "status": st, "holiday": is_hol,
                    "time": (rec or {}).get('time') or '',
                    "reason": (rec or {}).get('leave_reason') or ('Holiday' if is_hol else '')})
        if not is_hol:
            working += 1
            if st == 'P': present += 1
            elif st == 'A': absent += 1
            elif st == 'L': leave += 1
            elif st == 'T': late += 1
    attended = present + late
    pct = round(attended / working * 100, 1) if working else 0
    history = [dict(r) for r in db.execute(
        "SELECT date, status, leave_reason, time FROM attendance WHERE student_id=? ORDER BY date DESC LIMIT 60",
        (pk,)).fetchall()]
    return jsonify({"student_pk": pk, "month": mkey, "calendar": cal, "history": history,
                    "stats": {"working": working, "present": present, "absent": absent,
                              "leave": leave, "late": late, "percentage": pct}})

@app.route('/api/portal/marks')
def portal_marks():
    u = get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}), 401
    pk, err = _portal_scope(u)
    if err: return err
    db = get_db()
    exams = [r[0] for r in db.execute(
        "SELECT DISTINCT exam_type FROM marks m JOIN students s ON s.id=m.student_id "
        "WHERE m.student_id=? ORDER BY m.exam_type", (pk,)).fetchall()]
    out = []
    overall_obt = overall_max = 0
    for ex in exams:
        rows = [dict(r) for r in db.execute(
            "SELECT m.*, sub.name as subject_name FROM marks m JOIN subjects sub ON sub.id=m.subject_id "
            "WHERE m.student_id=? AND m.exam_type=? ORDER BY sub.name", (pk, ex)).fetchall()]
        obt = sum(r['obtained'] or 0 for r in rows)
        mx = sum(r['max_marks'] or 100 for r in rows)
        p = round(obt / mx * 100, 1) if mx else 0
        for r in rows:
            r['percentage'] = round((r['obtained'] or 0) / (r['max_marks'] or 100) * 100, 1)
            r['grade'] = _grade_for(r['percentage'])
        overall_obt += obt; overall_max += mx
        out.append({"exam_type": ex, "subjects": rows, "obtained": obt, "max_marks": mx,
                    "percentage": p, "grade": _grade_for(p)})
    overall_p = round(overall_obt / overall_max * 100, 1) if overall_max else None
    return jsonify({"student_pk": pk, "exams": out,
                    "overall": {"obtained": overall_obt, "max_marks": overall_max,
                                "percentage": overall_p, "grade": _grade_for(overall_p)}})

@app.route('/api/portal/homework')
def portal_homework():
    u = get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}), 401
    pk, err = _portal_scope(u)
    if err: return err
    db = get_db()
    s = _student_detail(pk)
    if not s:
        return jsonify({"error":"Not found"}), 404
    rows = [dict(r) for r in db.execute(
        "SELECT * FROM homework WHERE (class_id IS NULL OR class_id=?) AND (section_id IS NULL OR section_id=?) "
        "ORDER BY (due_date IS NULL), due_date DESC, id DESC", (s['class_id'], s['section_id'])).fetchall()]
    today = datetime.date.today()
    soon = (today + datetime.timedelta(days=3)).isoformat()
    for r in rows:
        due = r.get('due_date')
        if not due:
            r['status'] = 'Open'
        elif due < today.isoformat():
            r['status'] = 'Overdue'
        elif due <= soon:
            r['status'] = 'Due soon'
        else:
            r['status'] = 'Upcoming'
    return jsonify({"student_pk": pk, "class": s.get('class_name'),
                    "section": s.get('section_name'), "homework": rows})

@app.route('/api/portal/datesheet')
def portal_datesheet():
    u = get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}), 401
    pk, err = _portal_scope(u)
    if err: return err
    db = get_db()
    s = _student_detail(pk)
    if not s:
        return jsonify({"error":"Not found"}), 404
    rows = [dict(r) for r in db.execute(
        "SELECT * FROM datesheets WHERE class_id=? ORDER BY date, time", (s['class_id'],)).fetchall()]
    return jsonify({"student_pk": pk, "class": s.get('class_name'), "datesheet": rows})

@app.route('/api/portal/enotes')
def portal_enotes():
    u = get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}), 401
    db = get_db()
    rows = [dict(r) for r in db.execute("SELECT * FROM enotes ORDER BY id DESC LIMIT 50").fetchall()]
    return jsonify(rows)

@app.route('/api/portal/notices')
def portal_notices():
    u = get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}), 401
    db = get_db()
    rows = [dict(r) for r in db.execute("SELECT * FROM notices ORDER BY id DESC LIMIT 30").fetchall()]
    return jsonify(rows)

@app.route('/api/portal/school')
def portal_school():
    u = get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}), 401
    db = get_db()
    sch = db.execute("SELECT * FROM settings WHERE id=1").fetchone()
    events = [dict(r) for r in db.execute("SELECT * FROM school_events ORDER BY date DESC LIMIT 10").fetchall()]
    holidays = [dict(r) for r in db.execute("SELECT * FROM holidays ORDER BY date LIMIT 20").fetchall()]
    return jsonify({"school": dict(sch) if sch else {}, "events": events, "holidays": holidays})

# ---------- Homework (staff management) ----------
@app.route('/api/homework', methods=['GET','POST','PUT','DELETE'])
def homework_api():
    db = get_db()
    u = get_current_user()
    if not u:
        return jsonify({"error":"Not authenticated"}), 401
    if request.method == 'GET':
        if u['role'] in ('student', 'parent'):
            return portal_homework()
        rows = [dict(r) for r in db.execute(
            "SELECT h.*, c.name as class_name, sec.name as section_name FROM homework h "
            "LEFT JOIN classes c ON c.id=h.class_id LEFT JOIN sections sec ON sec.id=h.section_id "
            "ORDER BY (h.due_date IS NULL), h.due_date DESC, h.id DESC").fetchall()]
        return jsonify(rows)
    if u['role'] not in ('admin', 'teacher'):
        return jsonify({"error":"Access denied: staff only"}), 403
    if request.method == 'POST':
        d = request.get_json() or {}
        if not (d.get('title') or '').strip():
            return jsonify({"error":"Title is required"}), 400
        db.execute("INSERT INTO homework (class_id, section_id, subject, title, description, due_date, assigned_by, school_id, created_at) "
                   "VALUES (?,?,?,?,?,?,?,?,?)",
                   (d.get('class_id') or None, d.get('section_id') or None, d.get('subject', ''),
                    d.get('title'), d.get('description', ''), d.get('due_date') or None,
                    u['id'], 1, datetime.datetime.now().isoformat()))
        db.commit()
        return jsonify({"ok":True})
    hid = request.args.get('id')
    row = db.execute("SELECT assigned_by FROM homework WHERE id=?", (hid,)).fetchone()
    if not row:
        return jsonify({"error":"Not found"}), 404
    if u['role'] != 'admin' and row['assigned_by'] != u['id']:
        return jsonify({"error":"Access denied: you can only edit your own assignment"}), 403
    if request.method == 'PUT':
        d = request.get_json() or {}
        db.execute("UPDATE homework SET class_id=?, section_id=?, subject=?, title=?, description=?, due_date=? WHERE id=?",
                   (d.get('class_id') or None, d.get('section_id') or None, d.get('subject', ''),
                    d.get('title', ''), d.get('description', ''), d.get('due_date') or None, hid))
        db.commit()
        return jsonify({"ok":True})
    db.execute("DELETE FROM homework WHERE id=?", (hid,))
    db.commit()
    return jsonify({"ok":True})

# =====================================================================
# ---------- Timetable Management --------------------------------------
# =====================================================================
# Design notes
#   * A `timetable_version` is a whole week for ONE class+section that goes live
#     on an effective_from date. Editing never overwrites a published version:
#     admins fork a draft, then publish it. That makes change history truthful.
#   * Breaks/lunch are ordinary slots with kind<>'period', so the reader, the
#     editor and the conflict checker share one source of truth for the day shape.
#   * Every conflict is decided on the server (spec E). The browser may
#     pre-warn, but it is never the authority.

TT_DAYS = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
TT_KINDS = ("period","break","lunch","assembly")

def _tt_int(v):
    try:
        n = int(str(v).strip())
        return n
    except (TypeError, ValueError):
        return None

def _tt_minutes(v):
    """'09:30' -> 570. Returns None when the value is not a real clock time."""
    if v is None: return None
    m = re.fullmatch(r'(\d{1,2}):(\d{2})', str(v).strip())
    if not m: return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59: return None
    return h * 60 + mi

def _tt_hhmm(minutes):
    return '%02d:%02d' % (minutes // 60, minutes % 60)

def _tt_overlap(a1, a2, b1, b2):
    """Half-open interval overlap: touching edges (10:00 then 10:00) are fine."""
    return a1 < b2 and b1 < a2

def _tt_now(tz_name):
    """Wall-clock now in the school's timezone (spec C: current-period highlight)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo(tz_name or 'Asia/Kolkata'))
    except Exception:
        return datetime.datetime.now()

def _tt_active_session_id(db):
    row = db.execute("SELECT id FROM academic_sessions WHERE active=1 ORDER BY id LIMIT 1").fetchone()
    if row: return row[0]
    row = db.execute("SELECT id FROM academic_sessions ORDER BY id DESC LIMIT 1").fetchone()
    if row: return row[0]
    # last resort: keep the FK satisfiable even on a stripped database
    y = datetime.date.today().year
    cur = db.execute("""INSERT INTO academic_sessions (name,start_date,end_date,active)
                        VALUES (?,?,?,1)""", (f"{y}-{str(y+1)[2:]}", f"{y}-04-01", f"{y+1}-03-31"))
    db.commit()
    return cur.lastrowid

def _tt_settings(db, session_id, class_id=None, section_id=None):
    """Resolve school-day settings: class+section override > school-wide > defaults."""
    rows = db.execute("SELECT * FROM timetable_settings WHERE session_id=?", (session_id,)).fetchall()
    best, scope = None, 'default'
    if class_id is not None:
        for r in rows:
            if r['class_id'] == class_id and r['section_id'] == section_id:
                best, scope = r, 'class'; break
        if best is None:
            for r in rows:
                if r['class_id'] == class_id and r['section_id'] is None:
                    best, scope = r, 'class'; break
    if best is None:
        for r in rows:
            if r['class_id'] is None and r['section_id'] is None:
                best, scope = r, 'global'; break
    d = dict(best) if best else {}
    working = d.get('working_days') or 'Monday,Tuesday,Wednesday,Thursday,Friday,Saturday'
    return {
        "id": d.get('id'),
        "session_id": session_id,
        "class_id": class_id, "section_id": section_id,
        "open_time": d.get('open_time') or '08:00',
        "close_time": d.get('close_time') or '15:00',
        "timezone": d.get('timezone') or 'Asia/Kolkata',
        "working_days": [x.strip() for x in working.split(',') if x.strip()],
        "period_minutes": int(d.get('period_minutes') or 45),
        "scope": scope,
    }

def _teacher_ids_for_user(db, u):
    """teachers.id values for a logged-in teacher user.

    teachers.user_id is the intended link but is not populated on every install,
    so we fall back to an exact, unambiguous name match and otherwise return
    nothing rather than guessing (guessing would leak another teacher's schedule).
    """
    if not u or u['role'] != 'teacher':
        return []
    ids = [r[0] for r in db.execute("SELECT id FROM teachers WHERE user_id=?", (u['id'],)).fetchall()]
    if ids: return ids
    rows = db.execute("SELECT id FROM teachers WHERE lower(name)=lower(?)", (u['username'],)).fetchall()
    return [r[0] for r in rows] if len(rows) == 1 else []

def _tt_scope(db, u, class_id, section_id, student_id, view):
    """Work out which class+section this caller is allowed to read.

    Returns (class_id, section_id, student_id, error) — `error` is a (body, status)
    tuple to return straight from the route when the caller may not proceed.
    Students and parents can never choose their own class; it is derived from the
    database link, so a hand-crafted query string cannot widen access.
    """
    allowed = readable_student_ids(u)          # None = unrestricted (admin/teacher)
    if allowed is not None:                    # student or parent
        if not allowed:
            return None, None, None, ({"error":"No student record is linked to this account."}, 403)
        sid = student_id if (student_id in allowed) else sorted(allowed)[0]
        srow = db.execute("SELECT id, class_id, section_id FROM students WHERE id=?", (sid,)).fetchone()
        if not srow or srow['class_id'] is None:
            return None, None, None, ({"error":"No class is assigned to this student yet."}, 403)
        return srow['class_id'], srow['section_id'], sid, None
    if u['role'] == 'teacher':
        tids = _teacher_ids_for_user(db, u)
        if view == 'mine' or class_id is None:
            return None, None, None, None          # teacher: own-week view
        if section_id is None:
            sec = db.execute("SELECT id FROM sections WHERE class_id=? ORDER BY id LIMIT 1",
                             (class_id,)).fetchone()
            section_id = sec[0] if sec else None
        if section_id is None:
            return None, None, None, ({"error":"That class has no sections."}, 400)
        if not _teacher_teaches(db, tids, class_id, section_id):
            return None, None, None, ({"error":"You are not assigned to this class."}, 403)
        return class_id, section_id, None, None
    # admin
    if class_id is None or section_id is None:
        sec = db.execute("""SELECT s.class_id, s.id FROM sections s
                            ORDER BY s.class_id, s.id LIMIT 1""").fetchone()
        if not sec:
            return None, None, None, ({"error":"No classes configured yet."}, 400)
        class_id, section_id = sec['class_id'], sec['id']
    return class_id, section_id, None, None

def _teacher_teaches(db, tids, class_id, section_id):
    if not tids: return False
    q = ",".join("?" * len(tids))
    row = db.execute(f"""SELECT 1 FROM timetable_slots sl
                           JOIN timetable_versions v ON v.id = sl.version_id
                          WHERE sl.teacher_id IN ({q})
                            AND v.class_id=? AND v.section_id=? AND v.status<>'archived'
                          LIMIT 1""", list(tids) + [class_id, section_id]).fetchone()
    return row is not None

def _live_version(db, class_id, section_id, session_id, on_date=None):
    """The published version in force on `on_date` (latest effective_from <= date)."""
    on_date = on_date or datetime.date.today().isoformat()
    return db.execute("""SELECT * FROM timetable_versions
                          WHERE class_id=? AND section_id=? AND session_id=?
                            AND status='published' AND effective_from<=?
                          ORDER BY effective_from DESC, id DESC LIMIT 1""",
                      (class_id, section_id, session_id, on_date)).fetchone()

def _tt_log(db, version_id, class_id, section_id, action, summary, detail, changed_by):
    db.execute("""INSERT INTO timetable_changes
                  (version_id,class_id,section_id,action,summary,detail,changed_by,changed_at)
                  VALUES (?,?,?,?,?,?,?,?)""",
               (version_id, class_id, section_id, action, summary[:300],
                json.dumps(detail or {}, ensure_ascii=False),
                changed_by, datetime.datetime.now().isoformat()))

# ---------------- Conflict detection (server-side authority) ----------------
def _validate_tt_slots(db, ver, slots, settings):
    """Validate a proposed week. Returns a list of problems (empty = safe to save).

    codes: bad_day | non_working_day | invalid_time | outside_hours |
           unknown_subject | unknown_teacher | class_overlap |
           teacher_conflict | room_conflict
    """
    problems, seen = [], set()
    def add(code, message, idx, extra=None):
        key = (code, idx, message)
        if key in seen: return
        seen.add(key)
        p = {"code": code, "message": message, "slot_index": idx}
        if extra: p.update(extra)
        problems.append(p)

    open_m = _tt_minutes(settings.get('open_time'))
    close_m = _tt_minutes(settings.get('close_time'))
    if open_m is None: open_m = 0
    if close_m is None: close_m = 24 * 60
    working = settings.get('working_days') or []

    subj_ids = {r[0] for r in db.execute("SELECT id FROM subjects").fetchall()}
    teach_ids = {r[0] for r in db.execute("SELECT id FROM teachers").fetchall()}

    norm = []
    for i, s in enumerate(slots):
        day = str(s.get('day') or '').strip()
        label = str(s.get('name') or '').strip() or (s.get('kind') or 'period').title()
        st, en = _tt_minutes(s.get('start_time')), _tt_minutes(s.get('end_time'))
        e = {"index": i, "day": day, "name": label, "start": st, "end": en,
             "kind": s.get('kind') if s.get('kind') in TT_KINDS else 'period',
             "teacher_id": _tt_int(s.get('teacher_id')),
             "subject_id": _tt_int(s.get('subject_id')),
             "room": str(s.get('room') or '').strip(),
             "status": 'active' if (s.get('status') or 'active') == 'active' else 'cancelled'}
        if day not in TT_DAYS:
            add("bad_day", f"Cell {i+1}: '{day}' is not a valid day of the week.", i); continue
        if working and day not in working:
            add("non_working_day", f"Cell {i+1}: {day} is not a configured working day.", i)
        if st is None or en is None:
            add("invalid_time", f"Cell {i+1}: start and end must be clock times in HH:MM format.", i); continue
        if st >= en:
            add("invalid_time", f"Cell {i+1}: end time ({s.get('end_time')}) must be after start time ({s.get('start_time')}).", i); continue
        if st < open_m or en > close_m:
            add("outside_hours",
                f"Cell {i+1}: {s.get('start_time')}-{s.get('end_time')} falls outside school hours "
                f"({settings.get('open_time')}-{settings.get('close_time')}).", i)
        if e['subject_id'] and e['subject_id'] not in subj_ids:
            add("unknown_subject", f"Cell {i+1}: that subject no longer exists.", i)
        if e['teacher_id'] and e['teacher_id'] not in teach_ids:
            add("unknown_teacher", f"Cell {i+1}: that teacher no longer exists.", i)
        norm.append(e)

    # (1) this class cannot have two cells covering the same minutes — this is
    #     also what catches "two subjects in one period" and "period vs break".
    active = [e for e in norm if e['status'] == 'active' and e['start'] is not None and e['end'] is not None]
    for a in range(len(active)):
        for b in range(a + 1, len(active)):
            x, y = active[a], active[b]
            if x['day'] != y['day']: continue
            if _tt_overlap(x['start'], x['end'], y['start'], y['end']):
                add("class_overlap",
                    f"{x['day']}: '{x['name']}' ({_tt_hhmm(x['start'])}-{_tt_hhmm(x['end'])}) overlaps "
                    f"'{y['name']}' ({_tt_hhmm(y['start'])}-{_tt_hhmm(y['end'])}).",
                    x['index'], {"conflict_index": y['index']})

    # (2) cross-class: teacher and room clashes against every other live version
    #     of a DIFFERENT class+section in the same academic year. Other versions
    #     of this same class are alternatives (draft vs published), not clashes.
    others = db.execute("""SELECT sl.day, sl.start_time, sl.end_time, sl.name, sl.kind,
                                  sl.teacher_id, sl.room, sl.status,
                                  v.class_id, v.section_id,
                                  c.name AS class_name, s.name AS section_name
                             FROM timetable_slots sl
                             JOIN timetable_versions v ON v.id = sl.version_id
                             LEFT JOIN classes c ON c.id = v.class_id
                             LEFT JOIN sections s ON s.id = v.section_id
                            WHERE v.session_id=? AND v.status<>'archived'
                              AND sl.status='active' AND sl.version_id<>?
                              AND NOT (v.class_id=? AND v.section_id=?)""",
                         (ver['session_id'], ver['id'],
                          ver['class_id'], ver['section_id'])).fetchall()
    other_rows = []
    for o in others:
        os_, oe_ = _tt_minutes(o['start_time']), _tt_minutes(o['end_time'])
        if os_ is None or oe_ is None or os_ >= oe_: continue
        other_rows.append({"day": o['day'], "start": os_, "end": oe_,
                           "teacher_id": o['teacher_id'],
                           "room": (o['room'] or '').strip(),
                           "class_label": "%s-%s" % (o['class_name'] or '?', o['section_name'] or '?')})

    for e in active:
        for o in other_rows:
            if o['day'] != e['day']: continue
            if not _tt_overlap(e['start'], e['end'], o['start'], o['end']): continue
            span = "%s %s-%s" % (e['day'], _tt_hhmm(o['start']), _tt_hhmm(o['end']))
            if e['teacher_id'] and o['teacher_id'] == e['teacher_id']:
                tname = db.execute("SELECT name FROM teachers WHERE id=?", (e['teacher_id'],)).fetchone()
                who = tname[0] if tname else 'That teacher'
                add("teacher_conflict",
                    f"{who} is already assigned to {o['class_label']} on {span}.",
                    e['index'], {"class_label": o['class_label'], "when": span})
            if e['room'] and o['room'] and e['room'].lower() == o['room'].lower():
                add("room_conflict",
                    f"Room {e['room']} is already in use by {o['class_label']} on {span}.",
                    e['index'], {"class_label": o['class_label'], "when": span})
    return problems

def _tt_notify(db, ver, slots, summary):
    """Fan out in-app notifications and report delivery honestly.

    This application has no SMS/e-mail/WhatsApp gateway, so the return value
    states exactly which channel was used and that nothing external was sent.
    Never report success for a channel that was not actually contacted.
    """
    now = datetime.datetime.now().isoformat()
    targets = set()
    for r in db.execute("SELECT id FROM users WHERE role='admin'").fetchall():
        targets.add(r[0])
    tids = sorted({s['teacher_id'] for s in slots if s.get('teacher_id')} |
                  {s['substitute_teacher_id'] for s in slots if s.get('substitute_teacher_id')})
    if tids:
        q = ",".join("?" * len(tids))
        for r in db.execute(f"SELECT user_id FROM teachers WHERE user_id IS NOT NULL AND id IN ({q})", tids):
            targets.add(r[0])
    studs = [r[0] for r in db.execute("SELECT id FROM students WHERE class_id=? AND section_id=?",
                                      (ver['class_id'], ver['section_id'])).fetchall()]
    if studs:
        q = ",".join("?" * len(studs))
        for r in db.execute(f"SELECT id FROM users WHERE linked_student_id IN ({q})", studs):
            targets.add(r[0])
        for r in db.execute(f"""SELECT DISTINCT user_id FROM parent_students
                                WHERE student_id IN ({q}) AND user_id IS NOT NULL""", studs):
            targets.add(r[0])
    for uid in sorted(targets):
        db.execute("INSERT INTO notifications (user_id,type,title,content,date) VALUES (?,?,?,?,?)",
                   (uid, 'timetable', 'Timetable updated', summary, now))
    db.commit()
    return {"created": len(targets), "channel": "in_app",
            "external_channels": [], "external_sent": False,
            "note": "In-app notifications only. This app has no SMS, e-mail or WhatsApp gateway configured."}

def _tt_names(db):
    subjects = {r['id']: r['name'] for r in db.execute("SELECT id,name FROM subjects").fetchall()}
    teachers = {r['id']: r['name'] for r in db.execute("SELECT id,name FROM teachers").fetchall()}
    return subjects, teachers

def _tt_enrich(slot, subjects, teachers):
    d = dict(slot)
    d['subject_name'] = subjects.get(d.get('subject_id')) or d.get('subject_name') or ''
    d['teacher_name'] = teachers.get(d.get('teacher_id')) or ''
    d['substitute_name'] = teachers.get(d.get('substitute_teacher_id')) or ''
    return d

def _tt_days_list(settings):
    working = settings.get('working_days') or TT_DAYS[:6]
    return [d for d in TT_DAYS if d in working]

def _tt_live_payload(db, class_id, section_id, session_id, settings, date_obj, u, student_id=None):
    subjects, teachers = _tt_names(db)
    ver = _live_version(db, class_id, section_id, session_id, date_obj.isoformat())
    days = []
    slot_rows = []
    if ver:
        slot_rows = db.execute("SELECT * FROM timetable_slots WHERE version_id=? ORDER BY start_time",
                               (ver['id'],)).fetchall()
    by_day = {}
    for s in slot_rows:
        by_day.setdefault(s['day'], []).append(s)
    for d in _tt_days_list(settings):
        days.append({"day": d, "slots": [_tt_enrich(s, subjects, teachers) for s in by_day.get(d, [])]})

    cls = db.execute("SELECT name FROM classes WHERE id=?", (class_id,)).fetchone()
    sec = db.execute("SELECT name FROM sections WHERE id=?", (section_id,)).fetchone()

    now_dt = _tt_now(settings['timezone'])
    now_min = now_dt.hour * 60 + now_dt.minute
    today_iso = now_dt.date().isoformat()
    # `current`/`next` are only meaningful when the requested date IS today —
    # showing a "Now" badge against some other week would simply be a lie.
    is_today = (date_obj.isoformat() == today_iso)
    view_day = date_obj.strftime('%A')
    todays = [_tt_enrich(s, subjects, teachers) for s in by_day.get(view_day, [])
              if s['status'] == 'active']
    current = next((s for s in todays if _tt_minutes(s['start_time']) is not None
                    and _tt_minutes(s['end_time']) is not None
                    and _tt_minutes(s['start_time']) <= now_min < _tt_minutes(s['end_time'])), None) if is_today else None
    upcoming = [s for s in todays if _tt_minutes(s['start_time']) is not None
                and _tt_minutes(s['start_time']) > now_min] if is_today else []

    week_start = date_obj - datetime.timedelta(days=date_obj.weekday())
    week_end = week_start + datetime.timedelta(days=6)
    holidays = [dict(r) for r in db.execute(
        "SELECT date,name,type FROM holidays WHERE date>=? AND date<=? ORDER BY date",
        (week_start.isoformat(), week_end.isoformat())).fetchall()]

    subs = []
    if ver:
        subs = [dict(r) for r in db.execute("""SELECT sub.*, so.name AS original_name,
                                                      sn.name AS substitute_name,
                                                      sl.day, sl.start_time, sl.end_time,
                                                      sl.name AS slot_name, sl.subject_id
                                                 FROM timetable_substitutions sub
                                                 JOIN timetable_slots sl ON sl.id=sub.slot_id
                                                 LEFT JOIN teachers so ON so.id=sub.original_teacher_id
                                                 LEFT JOIN teachers sn ON sn.id=sub.substitute_teacher_id
                                                WHERE sl.version_id=? AND sub.date=? AND sub.status='approved'
                                                ORDER BY sl.start_time""",
                                            (ver['id'], date_obj.isoformat())).fetchall()]
        for s in subs:
            s['subject_name'] = subjects.get(s.get('subject_id')) or ''

    return {
        "scope": {"role": u['role'], "class_id": class_id, "section_id": section_id,
                  "class_name": cls['name'] if cls else '', "section_name": sec['name'] if sec else '',
                  "student_id": student_id},
        "session": {"id": session_id},
        "settings": settings,
        "version": ({"id": ver['id'], "name": ver['name'], "status": ver['status'],
                     "effective_from": ver['effective_from'], "published_at": ver['published_at']}
                    if ver else None),
        "published": ver is not None,
        "date": date_obj.isoformat(), "weekday": view_day, "today": today_iso,
        "now": now_dt.strftime('%H:%M'), "timezone": settings['timezone'],
        "days": days,
        "current_slot": current,
        "next_slot": upcoming[0] if upcoming else None,
        "holidays": holidays,
        "substitutions": subs,
    }

def _tt_teacher_week(db, u, session_id, settings, date_obj):
    """A teacher's own week across every class they teach (spec B)."""
    subjects, teachers = _tt_names(db)
    tids = _teacher_ids_for_user(db, u)
    if not tids:
        return {"scope": {"role": "teacher", "view": "mine", "teacher_ids": []},
                "session": {"id": session_id}, "settings": settings, "version": None,
                "published": False, "link_required": True,
                "message": "Your staff account is not linked to a teaching record yet. "
                           "Ask an administrator to link it so your periods can appear here.",
                "date": date_obj.isoformat(), "weekday": date_obj.strftime('%A'),
                "now": _tt_now(settings['timezone']).strftime('%H:%M'),
                "timezone": settings['timezone'], "days": [],
                "current_slot": None, "next_slot": None, "holidays": [], "substitutions": []}
    q = ",".join("?" * len(tids))
    rows = db.execute(f"""SELECT sl.*, v.class_id, v.section_id, v.effective_from, v.status AS v_status,
                                 c.name AS class_name, s.name AS section_name
                            FROM timetable_slots sl
                            JOIN timetable_versions v ON v.id=sl.version_id
                            LEFT JOIN classes c ON c.id=v.class_id
                            LEFT JOIN sections s ON s.id=v.section_id
                           WHERE v.session_id=? AND v.status='published'
                             AND v.effective_from<=?
                             AND (sl.teacher_id IN ({q}) OR sl.substitute_teacher_id IN ({q}))
                           ORDER BY sl.start_time""",
                      [session_id, date_obj.isoformat()] + tids + tids).fetchall()
    by_day = {}
    for r in rows:
        d = dict(r)
        d['subject_name'] = subjects.get(d.get('subject_id')) or ''
        d['teacher_name'] = teachers.get(d.get('teacher_id')) or ''
        d['substitute_name'] = teachers.get(d.get('substitute_teacher_id')) or ''
        d['is_substitution'] = bool(d.get('substitute_teacher_id'))
        by_day.setdefault(d['day'], []).append(d)

    now_dt = _tt_now(settings['timezone'])
    now_min = now_dt.hour * 60 + now_dt.minute
    today_iso = now_dt.date().isoformat()
    is_today = (date_obj.isoformat() == today_iso)
    view_day = date_obj.strftime('%A')
    todays = by_day.get(view_day, [])
    current = next((s for s in todays if s['status'] == 'active'
                    and _tt_minutes(s['start_time']) is not None
                    and _tt_minutes(s['end_time']) is not None
                    and _tt_minutes(s['start_time']) <= now_min < _tt_minutes(s['end_time'])), None) if is_today else None
    upcoming = [s for s in todays if s['status'] == 'active'
                and _tt_minutes(s['start_time']) is not None and _tt_minutes(s['start_time']) > now_min] if is_today else []

    week_start = date_obj - datetime.timedelta(days=date_obj.weekday())
    week_end = week_start + datetime.timedelta(days=6)
    holidays = [dict(r) for r in db.execute(
        "SELECT date,name,type FROM holidays WHERE date>=? AND date<=? ORDER BY date",
        (week_start.isoformat(), week_end.isoformat())).fetchall()]

    return {
        "scope": {"role": "teacher", "view": "mine", "teacher_ids": tids},
        "session": {"id": session_id}, "settings": settings, "version": None,
        "published": True, "link_required": False,
        "date": date_obj.isoformat(), "weekday": view_day, "today": today_iso,
        "now": now_dt.strftime('%H:%M'), "timezone": settings['timezone'],
        "days": [{"day": d, "slots": by_day.get(d, [])} for d in _tt_days_list(settings)],
        "current_slot": current, "next_slot": upcoming[0] if upcoming else None,
        "holidays": holidays, "substitutions": [],
    }

def _tt_write_slots(db, vid, rows):
    """Replace every cell of a version. Caller is responsible for validating
    first and for committing — that keeps validation and persistence separate."""
    db.execute("DELETE FROM timetable_slots WHERE version_id=?", (vid,))
    for s in rows:
        day = str(s.get('day') or '').strip()
        st, en = str(s.get('start_time') or '').strip(), str(s.get('end_time') or '').strip()
        kind = s.get('kind') if s.get('kind') in TT_KINDS else 'period'
        status = 'active' if (s.get('status') or 'active') == 'active' else 'cancelled'
        db.execute("""INSERT INTO timetable_slots
            (version_id,day,start_time,end_time,name,kind,subject_id,teacher_id,
             substitute_teacher_id,room,status,cancel_reason,notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (vid, day, st, en, str(s.get('name') or '')[:80], kind,
             _tt_int(s.get('subject_id')), _tt_int(s.get('teacher_id')),
             _tt_int(s.get('substitute_teacher_id')), str(s.get('room') or '')[:40],
             status, str(s.get('cancel_reason') or '')[:200], str(s.get('notes') or '')[:300]))

# ---------------- Timetable routes ----------------
@app.route('/api/timetable/settings', methods=['GET','PUT'])
def tt_settings_route():
    u = get_current_user()
    if not u: return jsonify({"error":"Not authenticated"}), 401
    if not can(u['role'], 'timetable', 'view'): return jsonify({"error":"Access denied"}), 403
    db = get_db()
    sid = _tt_int(request.args.get('session_id')) or _tt_active_session_id(db)
    class_id = _tt_int(request.args.get('class_id'))
    section_id = _tt_int(request.args.get('section_id'))
    if request.method == 'GET':
        return jsonify(_tt_settings(db, sid, class_id, section_id))
    if not can(u['role'], 'timetable', 'full'):
        return jsonify({"error":"Access denied: only administrators can change timetable settings."}), 403
    d = request.get_json(silent=True) or {}
    def _hhmm(v, default):
        if v is None: return default
        if _tt_minutes(v) is None:
            raise ValueError("Times must be in HH:MM format.")
        return str(v)
    try:
        open_t = _hhmm(d.get('open_time'), '08:00')
        close_t = _hhmm(d.get('close_time'), '15:00')
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if _tt_minutes(open_t) >= _tt_minutes(close_t):
        return jsonify({"error":"Opening time must be before closing time."}), 400
    days = d.get('working_days')
    if isinstance(days, (list, tuple)):
        days = ",".join(x for x in days if x in TT_DAYS)
    if not days:
        days = "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday"
    tz = str(d.get('timezone') or 'Asia/Kolkata').strip()
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
    except Exception:
        return jsonify({"error":f"'{tz}' is not a known timezone."}), 400
    try:
        pm = int(d.get('period_minutes') or 45)
        if pm < 5 or pm > 240: raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error":"period_minutes must be between 5 and 240."}), 400
    existing = db.execute("""SELECT id FROM timetable_settings
                             WHERE session_id=? AND COALESCE(class_id,-1)=COALESCE(?,-1)
                               AND COALESCE(section_id,-1)=COALESCE(?,-1)""",
                          (sid, class_id, section_id)).fetchone()
    now = datetime.datetime.now().isoformat()
    if existing:
        db.execute("""UPDATE timetable_settings SET open_time=?,close_time=?,timezone=?,
                             working_days=?,period_minutes=?,updated_by=?,updated_at=? WHERE id=?""",
                   (open_t, close_t, tz, days, pm, u['id'], now, existing['id']))
    else:
        db.execute("""INSERT INTO timetable_settings
                        (session_id,class_id,section_id,open_time,close_time,timezone,working_days,period_minutes,updated_by,updated_at)
                      VALUES (?,?,?,?,?,?,?,?,?,?)""",
                   (sid, class_id, section_id, open_t, close_t, tz, days, pm, u['id'], now))
    _tt_log(db, None, class_id, section_id, 'settings', 'Timetable settings updated',
            {"open_time": open_t, "close_time": close_t, "timezone": tz, "session_id": sid}, u['id'])
    db.commit()
    return jsonify({"ok":True, "settings":_tt_settings(db, sid, class_id, section_id)})

@app.route('/api/timetable/versions', methods=['GET','POST'])
def tt_versions():
    u = get_current_user()
    if not u: return jsonify({"error":"Not authenticated"}), 401
    if not can(u['role'], 'timetable', 'view'): return jsonify({"error":"Access denied"}), 403
    db = get_db()
    if request.method == 'GET':
        # The version list is the editor's view (drafts, publish dates, notes).
        # Everyone else reads the published schedule through /schedule instead.
        if not can(u['role'], 'timetable', 'full'):
            return jsonify({"error":"Access denied: only administrators can list timetable versions."}), 403
        class_id = _tt_int(request.args.get('class_id'))
        section_id = _tt_int(request.args.get('section_id'))
        status = request.args.get('status') or ''
        sql = """SELECT v.*, c.name AS class_name, s.name AS section_name,
                        a.name AS session_name,
                        (SELECT COUNT(*) FROM timetable_slots sl WHERE sl.version_id=v.id) AS slot_count
                   FROM timetable_versions v
                   LEFT JOIN classes c ON c.id=v.class_id
                   LEFT JOIN sections s ON s.id=v.section_id
                   LEFT JOIN academic_sessions a ON a.id=v.session_id
                  WHERE 1=1"""
        params = []
        if class_id is not None: sql += " AND v.class_id=?"; params.append(class_id)
        if section_id is not None: sql += " AND v.section_id=?"; params.append(section_id)
        if status: sql += " AND v.status=?"; params.append(status)
        sql += " ORDER BY v.effective_from DESC, v.id DESC LIMIT 200"
        return jsonify([dict(r) for r in db.execute(sql, params).fetchall()])
    if not can(u['role'], 'timetable', 'full'):
        return jsonify({"error":"Access denied: only administrators can create timetables."}), 403
    d = request.get_json(silent=True) or {}
    class_id, section_id = _tt_int(d.get('class_id')), _tt_int(d.get('section_id'))
    if not class_id or not section_id:
        return jsonify({"error":"class_id and section_id are required."}), 400
    if not db.execute("SELECT 1 FROM sections WHERE id=? AND class_id=?", (section_id, class_id)).fetchone():
        return jsonify({"error":"That section does not belong to that class."}), 400
    session_id = _tt_int(d.get('session_id')) or _tt_active_session_id(db)
    eff = str(d.get('effective_from') or datetime.date.today().isoformat())
    try: datetime.date.fromisoformat(eff)
    except ValueError: return jsonify({"error":"effective_from must be YYYY-MM-DD."}), 400
    name = str(d.get('name') or '').strip()[:120]
    try:
        cur = db.execute("""INSERT INTO timetable_versions
              (session_id,class_id,section_id,name,status,effective_from,created_by,created_at)
              VALUES (?,?,?,?,?,?,?,?)""",
              (session_id, class_id, section_id, name, 'draft', eff, u['id'],
               datetime.datetime.now().isoformat()))
    except sqlite3.IntegrityError:
        return jsonify({"error":"A version with that effective date already exists for this class."}), 409
    vid = cur.lastrowid
    _tt_log(db, vid, class_id, section_id, 'create', f"Created draft timetable for {eff}",
            {"session_id": session_id, "name": name}, u['id'])
    db.commit()
    return jsonify({"ok":True, "id":vid})

def _tt_get_version(db, u, vid, need_admin=True):
    v = db.execute("""SELECT v.*, c.name AS class_name, s.name AS section_name
                        FROM timetable_versions v
                        LEFT JOIN classes c ON c.id=v.class_id
                        LEFT JOIN sections s ON s.id=v.section_id WHERE v.id=?""", (vid,)).fetchone()
    if not v: return None, ({"error":"Timetable not found."}, 404)
    if need_admin and not can(u['role'], 'timetable', 'full'):
        # non-admins may only ever open a published version
        if v['status'] != 'published':
            return None, ({"error":"Access denied."}, 403)
    return v, None

@app.route('/api/timetable/versions/<int:vid>', methods=['GET','PUT','DELETE'])
def tt_version_detail(vid):
    u = get_current_user()
    if not u: return jsonify({"error":"Not authenticated"}), 401
    if not can(u['role'], 'timetable', 'view'): return jsonify({"error":"Access denied"}), 403
    db = get_db()
    admin = can(u['role'], 'timetable', 'full')
    v, err = _tt_get_version(db, u, vid, need_admin=False)
    if err: return jsonify(err[0]), err[1]
    if v['status'] != 'published' and not admin:
        return jsonify({"error":"Access denied."}), 403
    if request.method == 'GET':
        subjects, teachers = _tt_names(db)
        slots = [_tt_enrich(r, subjects, teachers)
                 for r in db.execute("SELECT * FROM timetable_slots WHERE version_id=? ORDER BY day, start_time",
                                     (vid,)).fetchall()]
        return jsonify({"version": dict(v), "slots": slots,
                        "settings": _tt_settings(db, v['session_id'], v['class_id'], v['section_id'])})
    if not admin:
        return jsonify({"error":"Access denied: only administrators can change timetables."}), 403
    if request.method == 'DELETE':
        if v['status'] == 'published':
            return jsonify({"error":"A published timetable cannot be deleted — archive it instead so history stays intact."}), 409
        db.execute("DELETE FROM timetable_versions WHERE id=?", (vid,))
        _tt_log(db, vid, v['class_id'], v['section_id'], 'delete', "Deleted draft timetable", {}, u['id'])
        db.commit()
        return jsonify({"ok":True})
    d = request.get_json(silent=True) or {}
    fields, params = [], []
    if 'name' in d:
        fields.append("name=?"); params.append(str(d.get('name') or '')[:120])
    if 'effective_from' in d:
        eff = str(d.get('effective_from') or '')
        try: datetime.date.fromisoformat(eff)
        except ValueError: return jsonify({"error":"effective_from must be YYYY-MM-DD."}), 400
        fields.append("effective_from=?"); params.append(eff)
    if not fields: return jsonify({"error":"Nothing to update."}), 400
    params.append(vid)
    try:
        db.execute(f"UPDATE timetable_versions SET {','.join(fields)} WHERE id=?", params)
    except sqlite3.IntegrityError:
        return jsonify({"error":"A published version with that effective date already exists."}), 409
    _tt_log(db, vid, v['class_id'], v['section_id'], 'edit', "Updated timetable details",
            {k: d.get(k) for k in d}, u['id'])
    db.commit()
    return jsonify({"ok":True})

@app.route('/api/timetable/validate', methods=['POST'])
def tt_validate():
    u = get_current_user()
    if not u: return jsonify({"error":"Not authenticated"}), 401
    if not can(u['role'], 'timetable', 'full'):
        return jsonify({"error":"Access denied: only administrators can validate timetables."}), 403
    db = get_db()
    d = request.get_json(silent=True) or {}
    vid = _tt_int(d.get('version_id'))
    v, err = _tt_get_version(db, u, vid) if vid else (None, None)
    if vid and err: return jsonify(err[0]), err[1]
    if v is None:
        class_id, section_id = _tt_int(d.get('class_id')), _tt_int(d.get('section_id'))
        session_id = _tt_int(d.get('session_id')) or _tt_active_session_id(db)
        if not class_id or not section_id:
            return jsonify({"error":"version_id or class_id+section_id is required."}), 400
        v = {"id": -1, "session_id": session_id, "class_id": class_id, "section_id": section_id}
    settings = _tt_settings(db, v['session_id'], v['class_id'], v['section_id'])
    problems = _validate_tt_slots(db, v, d.get('slots') or [], settings)
    errors = [p for p in problems if p['code'] != 'non_working_day']
    warnings = [p for p in problems if p['code'] == 'non_working_day']
    return jsonify({"ok": not errors, "errors": errors, "warnings": warnings, "settings": settings})

@app.route('/api/timetable/versions/<int:vid>/slots', methods=['PUT'])
def tt_save_slots(vid):
    u = get_current_user()
    if not u: return jsonify({"error":"Not authenticated"}), 401
    if not can(u['role'], 'timetable', 'full'):
        return jsonify({"error":"Access denied: only administrators can edit the timetable."}), 403
    db = get_db()
    v, err = _tt_get_version(db, u, vid)
    if err: return jsonify(err[0]), err[1]
    if v['status'] == 'published':
        return jsonify({"error":"This timetable is published. Duplicate it into a new draft to make changes."}), 409
    d = request.get_json(silent=True) or {}
    slots = d.get('slots')
    if not isinstance(slots, list):
        return jsonify({"error":"slots must be a list."}), 400
    if len(slots) > 500:
        return jsonify({"error":"Too many cells in one save (max 500)."}), 400
    settings = _tt_settings(db, v['session_id'], v['class_id'], v['section_id'])
    # Exact duplicate cells are checked first: they are a more precise diagnosis
    # than the generic "overlaps itself" the interval check would report.
    seen = set()
    dup_errors = []
    for i, s in enumerate(slots):
        key = (str(s.get('day') or '').strip(), str(s.get('start_time') or '').strip())
        if key in seen:
            dup_errors.append({"code": "duplicate_slot",
                               "message": f"Cell {i+1}: {key[0]} {key[1]} appears more than once.",
                               "slot_index": i})
        seen.add(key)
    if dup_errors:
        return jsonify({"error":"Duplicate cell.","saved":False, "errors":dup_errors,
                        "warnings":[]}), 409
    problems = _validate_tt_slots(db, v, slots, settings)
    errors = [p for p in problems if p['code'] != 'non_working_day']
    warnings = [p for p in problems if p['code'] == 'non_working_day']
    if errors:
        # Nothing is written: the server is the authority (spec E).
        return jsonify({"error":"Timetable has conflicts.","errors":errors,
                        "warnings":warnings, "saved":False}), 409
    subjects, teachers = _tt_names(db)
    now = datetime.datetime.now().isoformat()
    try:
        _tt_write_slots(db, vid, slots)
        _tt_log(db, vid, v['class_id'], v['section_id'], 'edit',
                f"Saved {len(slots)} timetable cells",
                {"slots": len(slots), "warnings": len(warnings)}, u['id'])
        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"error":"Could not save the timetable.","detail":str(e)[:200]}), 500
    return jsonify({"ok":True, "saved":True, "count":len(slots), "warnings":warnings})

def _tt_clear_cross_class(rows, keep_teachers):
    """Copying a week into ANOTHER class also copies its teacher and room, which
    can never validate — the source class still holds those teachers at those
    minutes, and that IS a real clash. So copy the day SHAPE (times, subject,
    breaks) and drop the staff/room assignments for the admin to fill in;
    conflicts are then checked against their real edits.
    Returns how many rows were changed."""
    if keep_teachers:
        return 0
    n = 0
    for r in rows:
        if r.get('teacher_id') or r.get('substitute_teacher_id') or (r.get('room') or '').strip():
            n += 1
        r['teacher_id'] = None
        r['substitute_teacher_id'] = None
        r['room'] = ''
    return n

@app.route('/api/timetable/versions/<int:vid>/duplicate', methods=['POST'])
def tt_duplicate(vid):
    """Copy a day, a whole week, or a week into another class (spec A)."""
    u = get_current_user()
    if not u: return jsonify({"error":"Not authenticated"}), 401
    if not can(u['role'], 'timetable', 'full'):
        return jsonify({"error":"Access denied: only administrators can duplicate timetables."}), 403
    db = get_db()
    v, err = _tt_get_version(db, u, vid)
    if err: return jsonify(err[0]), err[1]
    d = request.get_json(silent=True) or {}
    mode = str(d.get('mode') or 'day')
    # day-mode writes back into this very version, so it must be editable.
    # Copying FROM a published timetable into another class/week is a normal
    # admin action and is allowed (the destination must still be a draft).
    if mode == 'day' and v['status'] == 'published':
        return jsonify({"error":"A published timetable cannot be edited — duplicate it into a new draft first."}), 409
    settings = _tt_settings(db, v['session_id'], v['class_id'], v['section_id'])
    now_iso = datetime.datetime.now().isoformat()

    if mode == 'day':
        src = str(d.get('from_day') or '')
        targets = d.get('to_days') or []
        if src not in TT_DAYS:
            return jsonify({"error":"from_day is not a valid day."}), 400
        if not isinstance(targets, list) or not targets:
            return jsonify({"error":"to_days must be a non-empty list."}), 400
        bad = [t for t in targets if t not in TT_DAYS]
        if bad:
            return jsonify({"error":f"Invalid target day(s): {', '.join(map(str, bad))}"}), 400
        if src in targets:
            return jsonify({"error":"A day cannot be copied onto itself."}), 400
        src_rows = [dict(r) for r in db.execute(
            "SELECT * FROM timetable_slots WHERE version_id=? AND day=? ORDER BY start_time",
            (vid, src)).fetchall()]
        if not src_rows:
            return jsonify({"error":f"There is nothing scheduled on {src} to copy."}), 400
        # copy AFTER removing the target days, so the source survives
        db.execute("DELETE FROM timetable_slots WHERE version_id=? AND day IN (%s)"
                   % ",".join("?" * len(targets)), [vid] + list(targets))
        added = 0
        for t in targets:
            for r in src_rows:
                c = dict(r); c.pop('id', None); c['day'] = t
                db.execute("""INSERT INTO timetable_slots
                    (version_id,day,start_time,end_time,name,kind,subject_id,teacher_id,
                     substitute_teacher_id,room,status,cancel_reason,notes)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (vid, c['day'], c['start_time'], c['end_time'], c['name'], c['kind'],
                     c['subject_id'], c['teacher_id'], c['substitute_teacher_id'], c['room'],
                     c['status'], c['cancel_reason'], c['notes']))
                added += 1
        final = [dict(r) for r in db.execute(
            "SELECT * FROM timetable_slots WHERE version_id=?", (vid,)).fetchall()]
        problems = _validate_tt_slots(db, v, final, settings)
        errors = [p for p in problems if p['code'] != 'non_working_day']
        if errors:
            db.rollback()
            return jsonify({"error":"Copying would create conflicts — nothing was changed.",
                            "errors":errors, "saved":False}), 409
        _tt_log(db, vid, v['class_id'], v['section_id'], 'duplicate',
                f"Copied {src} to {', '.join(targets)}",
                {"from": src, "to": targets, "cells": added}, u['id'])
        db.commit()
        return jsonify({"ok":True, "copied":added, "mode":"day"})

    if mode == 'week':
        tid = _tt_int(d.get('to_version_id'))
        if not tid: return jsonify({"error":"to_version_id is required."}), 400
        tgt, terr = _tt_get_version(db, u, tid)
        if terr: return jsonify(terr[0]), terr[1]
        if tgt['status'] == 'published':
            return jsonify({"error":"The destination timetable is published; use a draft."}), 409
        if tid == vid: return jsonify({"error":"Cannot duplicate a timetable onto itself."}), 400
        rows = [dict(r) for r in db.execute("SELECT * FROM timetable_slots WHERE version_id=?", (vid,)).fetchall()]
        if not rows: return jsonify({"error":"There is nothing to copy."}), 400
        cross = (tgt['class_id'] != v['class_id'] or tgt['section_id'] != v['section_id'])
        cleared = _tt_clear_cross_class(rows, bool(d.get('keep_teachers'))) if cross else 0
        tset = _tt_settings(db, tgt['session_id'], tgt['class_id'], tgt['section_id'])
        problems = _validate_tt_slots(db, dict(tgt), rows, tset)
        errors = [p for p in problems if p['code'] != 'non_working_day']
        if errors:
            return jsonify({"error":"Copying would create conflicts — nothing was changed.",
                            "errors":errors, "saved":False}), 409
        _tt_write_slots(db, tid, rows)
        _tt_log(db, tid, tgt['class_id'], tgt['section_id'], 'duplicate',
                f"Copied timetable from #{vid}", {"from_version": vid, "cells": len(rows),
                                                  "cleared_teachers": cleared}, u['id'])
        db.commit()
        return jsonify({"ok":True, "copied":len(rows), "mode":"week", "to_version_id":tid,
                        "cleared_teachers":cleared})

    if mode == 'class':
        tc, ts = _tt_int(d.get('to_class_id')), _tt_int(d.get('to_section_id'))
        if not tc or not ts:
            return jsonify({"error":"to_class_id and to_section_id are required."}), 400
        if not db.execute("SELECT 1 FROM sections WHERE id=? AND class_id=?", (ts, tc)).fetchone():
            return jsonify({"error":"That section does not belong to that class."}), 400
        if tc == v['class_id'] and ts == v['section_id']:
            return jsonify({"error":"Choose a different class or section."}), 400
        rows = [dict(r) for r in db.execute("SELECT * FROM timetable_slots WHERE version_id=?", (vid,)).fetchall()]
        if not rows: return jsonify({"error":"There is nothing to copy."}), 400
        # Copy the day shape, not the staff — see _tt_clear_cross_class.
        cleared = _tt_clear_cross_class(rows, bool(d.get('keep_teachers')))
        eff = str(d.get('effective_from') or datetime.date.today().isoformat())
        try: datetime.date.fromisoformat(eff)
        except ValueError: return jsonify({"error":"effective_from must be YYYY-MM-DD."}), 400
        # validate BEFORE creating the destination so a failed copy leaves nothing behind
        pseudo = {"id": -1, "session_id": v['session_id'], "class_id": tc, "section_id": ts}
        tset = _tt_settings(db, v['session_id'], tc, ts)
        problems = [p for p in _validate_tt_slots(db, pseudo, rows, tset)
                    if p['code'] != 'non_working_day']
        if problems:
            return jsonify({"error":"Copying would create conflicts — nothing was created.",
                            "errors":problems, "saved":False}), 409
        try:
            cur = db.execute("""INSERT INTO timetable_versions
                  (session_id,class_id,section_id,name,status,effective_from,parent_id,created_by,created_at)
                  VALUES (?,?,?,?,?,?,?,?,?)""",
                  (v['session_id'], tc, ts, str(d.get('name') or '')[:120], 'draft', eff,
                   vid, u['id'], now_iso))
        except sqlite3.IntegrityError:
            return jsonify({"error":"A timetable with that effective date already exists for the target class."}), 409
        nid = cur.lastrowid
        _tt_write_slots(db, nid, rows)
        _tt_log(db, nid, tc, ts, 'duplicate',
                f"Copied timetable from {v['class_name']}-{v['section_name']} (#{vid})",
                {"from_version": vid, "cells": len(rows), "effective_from": eff,
                 "cleared_teachers": cleared}, u['id'])
        db.commit()
        return jsonify({"ok":True, "copied":len(rows), "mode":"class", "id":nid,
                        "cleared_teachers":cleared})
    return jsonify({"error":f"Unknown mode '{mode}'. Use day, week or class."}), 400

def _tt_validate_or_409(db, ver, slots, settings):
    """Return blocking errors (empty list when clean)."""
    return [p for p in _validate_tt_slots(db, ver, slots, settings)
            if p['code'] != 'non_working_day']

@app.route('/api/timetable/versions/<int:vid>/publish', methods=['POST'])
def tt_publish(vid):
    u = get_current_user()
    if not u: return jsonify({"error":"Not authenticated"}), 401
    if not can(u['role'], 'timetable', 'full'):
        return jsonify({"error":"Access denied: only administrators can publish timetables."}), 403
    db = get_db()
    v, err = _tt_get_version(db, u, vid)
    if err: return jsonify(err[0]), err[1]
    if v['status'] == 'published':
        return jsonify({"error":"This timetable is already published."}), 409
    d = request.get_json(silent=True) or {}
    eff = str(d.get('effective_from') or v['effective_from'])
    try: datetime.date.fromisoformat(eff)
    except ValueError: return jsonify({"error":"effective_from must be YYYY-MM-DD."}), 400
    slots = [dict(r) for r in db.execute("SELECT * FROM timetable_slots WHERE version_id=?", (vid,)).fetchall()]
    if not slots:
        return jsonify({"error":"Add at least one period before publishing."}), 400
    settings = _tt_settings(db, v['session_id'], v['class_id'], v['section_id'])
    errors = _tt_validate_or_409(db, v, slots, settings)
    if errors:
        return jsonify({"error":"Cannot publish: the timetable has conflicts.",
                        "errors":errors, "published":False}), 409
    dup = db.execute("""SELECT id, effective_from FROM timetable_versions
                         WHERE session_id=? AND class_id=? AND section_id=?
                           AND status='published' AND effective_from=? AND id<>?""",
                     (v['session_id'], v['class_id'], v['section_id'], eff, vid)).fetchone()
    if dup:
        return jsonify({"error":f"Another timetable is already published with effective date {eff}."}), 409
    warnings = []
    later = db.execute("""SELECT effective_from FROM timetable_versions
                           WHERE session_id=? AND class_id=? AND section_id=?
                             AND status='published' AND effective_from>? AND id<>?""",
                       (v['session_id'], v['class_id'], v['section_id'], eff, vid)).fetchall()
    for r in later:
        warnings.append({"code":"future_version_exists",
                         "message":f"A version effective from {r['effective_from']} is already published, "
                                   f"so this one will only be live on and after {eff} "
                                   f"up to {r['effective_from']}."})
    note = str(d.get('note') or '')[:300]
    now_iso = datetime.datetime.now().isoformat()
    db.execute("""UPDATE timetable_versions
                     SET status='published', effective_from=?, published_at=?, published_by=?, publish_note=?
                   WHERE id=?""", (eff, now_iso, u['id'], note, vid))
    _tt_log(db, vid, v['class_id'], v['section_id'], 'publish',
            f"Published timetable effective {eff}",
            {"effective_from": eff, "slots": len(slots), "note": note}, u['id'])
    cls = db.execute("SELECT name FROM classes WHERE id=?", (v['class_id'],)).fetchone()
    sec = db.execute("SELECT name FROM sections WHERE id=?", (v['section_id'],)).fetchone()
    label = "%s-%s" % (cls['name'] if cls else '?', sec['name'] if sec else '?')
    summary = f"The timetable for Class {label} is now effective from {eff}."
    if note: summary += f" Note: {note}"
    report = _tt_notify(db, v, slots, summary)
    db.commit()
    return jsonify({"ok":True, "published":True, "effective_from":eff,
                    "notifications":report, "warnings":warnings})

@app.route('/api/timetable/versions/<int:vid>/archive', methods=['POST'])
def tt_archive(vid):
    u = get_current_user()
    if not u: return jsonify({"error":"Not authenticated"}), 401
    if not can(u['role'], 'timetable', 'full'):
        return jsonify({"error":"Access denied: only administrators can archive timetables."}), 403
    db = get_db()
    v, err = _tt_get_version(db, u, vid)
    if err: return jsonify(err[0]), err[1]
    if v['status'] == 'archived': return jsonify({"ok":True, "status":"archived"})
    db.execute("UPDATE timetable_versions SET status='archived' WHERE id=?", (vid,))
    _tt_log(db, vid, v['class_id'], v['section_id'], 'archive', "Archived timetable",
            {"previous_status": v['status']}, u['id'])
    db.commit()
    return jsonify({"ok":True, "status":"archived"})

@app.route('/api/timetable/history')
def tt_history():
    u = get_current_user()
    if not u: return jsonify({"error":"Not authenticated"}), 401
    if not can(u['role'], 'timetable', 'full'):
        return jsonify({"error":"Access denied: only administrators can see change history."}), 403
    db = get_db()
    class_id = _tt_int(request.args.get('class_id'))
    section_id = _tt_int(request.args.get('section_id'))
    limit = _tt_int(request.args.get('limit')) or 50
    limit = max(1, min(limit, 200))
    sql = """SELECT h.*, us.username AS changed_by_name,
                    c.name AS class_name, s.name AS section_name
               FROM timetable_changes h
               LEFT JOIN users us ON us.id=h.changed_by
               LEFT JOIN classes c ON c.id=h.class_id
               LEFT JOIN sections s ON s.id=h.section_id
              WHERE 1=1"""
    params = []
    if class_id is not None: sql += " AND h.class_id=?"; params.append(class_id)
    if section_id is not None: sql += " AND h.section_id=?"; params.append(section_id)
    sql += " ORDER BY h.id DESC LIMIT ?"; params.append(limit)
    out = []
    for r in db.execute(sql, params).fetchall():
        row = dict(r)
        try: row['detail'] = json.loads(row.get('detail') or '{}')
        except Exception: row['detail'] = {}
        out.append(row)
    return jsonify(out)

# ---------------- Substitutions (per concrete date) ----------------
@app.route('/api/timetable/substitutions', methods=['GET','POST'])
def tt_substitutions():
    u = get_current_user()
    if not u: return jsonify({"error":"Not authenticated"}), 401
    if not can(u['role'], 'timetable', 'view'): return jsonify({"error":"Access denied"}), 403
    db = get_db()
    if request.method == 'GET':
        date = request.args.get('date') or datetime.date.today().isoformat()
        class_id = _tt_int(request.args.get('class_id'))
        section_id = _tt_int(request.args.get('section_id'))
        student_id = _tt_int(request.args.get('student_id'))
        view = (request.args.get('view') or '').strip()
        base = """SELECT sub.*, so.name AS original_name, sn.name AS substitute_name,
                         sl.day, sl.start_time, sl.end_time, sl.name AS slot_name, sl.subject_id,
                         v.class_id, v.section_id, c.name AS class_name, s.name AS section_name
                    FROM timetable_substitutions sub
                    JOIN timetable_slots sl ON sl.id=sub.slot_id
                    JOIN timetable_versions v ON v.id=sl.version_id
                    LEFT JOIN classes c ON c.id=v.class_id
                    LEFT JOIN sections s ON s.id=v.section_id
                    LEFT JOIN teachers so ON so.id=sub.original_teacher_id
                    LEFT JOIN teachers sn ON sn.id=sub.substitute_teacher_id
                   WHERE sub.date=? AND v.status='published'"""
        params = [date]
        allowed = readable_student_ids(u)
        if allowed is not None:                       # student / parent
            class_id, section_id, student_id, err = _tt_scope(db, u, class_id, section_id, student_id, view)
            if err: return jsonify(err[0]), err[1]
            base += " AND v.class_id=? AND v.section_id=?"; params += [class_id, section_id]
        elif u['role'] == 'teacher':
            tids = _teacher_ids_for_user(db, u)
            if not tids:
                return jsonify({"substitutions": [], "date": date, "link_required": True})
            q = ",".join("?" * len(tids))
            base += f" AND (sl.teacher_id IN ({q}) OR sl.substitute_teacher_id IN ({q}))"
            params += tids + tids
        else:                                          # admin
            if class_id is not None: base += " AND v.class_id=?"; params.append(class_id)
            if section_id is not None: base += " AND v.section_id=?"; params.append(section_id)
        # Admins may audit pending/rejected rows; everyone else only ever sees
        # substitutions that were actually authorised (spec B).
        st = (request.args.get('status') or '').strip()
        if st:
            if st not in ('pending', 'approved', 'rejected'):
                return jsonify({"error":"status must be pending, approved or rejected."}), 400
            base += " AND sub.status=?"; params.append(st)
        elif not can(u['role'], 'timetable', 'full'):
            base += " AND sub.status='approved'"
        base += " ORDER BY sl.start_time"
        rows = [dict(r) for r in db.execute(base, params).fetchall()]
        # one query for all subject names — the naive per-row lookup was O(n)
        sids = sorted({r['subject_id'] for r in rows if r.get('subject_id')})
        names = {}
        if sids:
            q = ",".join("?" * len(sids))
            names = {r['id']: r['name'] for r in
                     db.execute(f"SELECT id,name FROM subjects WHERE id IN ({q})", sids).fetchall()}
        for r in rows:
            r['subject_name'] = names.get(r.get('subject_id')) or ''
        return jsonify({"substitutions": rows, "date": date})

    # POST — administrators only
    if not can(u['role'], 'timetable', 'full'):
        return jsonify({"error":"Access denied: only administrators can assign substitutions."}), 403
    d = request.get_json(silent=True) or {}
    slot_id = _tt_int(d.get('slot_id'))
    sub_id = _tt_int(d.get('substitute_teacher_id'))
    date = str(d.get('date') or '')
    try: datetime.date.fromisoformat(date)
    except ValueError: return jsonify({"error":"date must be YYYY-MM-DD."}), 400
    if not slot_id: return jsonify({"error":"slot_id is required."}), 400
    # aliased: a bare v.status would collide with sl.status (see timetable_api)
    slot = db.execute("""SELECT sl.*, v.class_id, v.section_id, v.status AS version_status
                           FROM timetable_slots sl
                           JOIN timetable_versions v ON v.id=sl.version_id
                          WHERE sl.id=?""", (slot_id,)).fetchone()
    if not slot: return jsonify({"error":"Period not found."}), 404
    if slot['version_status'] != 'published':
        return jsonify({"error":"That timetable is not published."}), 409
    if not sub_id: return jsonify({"error":"substitute_teacher_id is required."}), 400
    if sub_id == slot['teacher_id']:
        return jsonify({"error":"The substitute must differ from the teacher already assigned."}), 400
    if not db.execute("SELECT 1 FROM teachers WHERE id=?", (sub_id,)).fetchone():
        return jsonify({"error":"That substitute teacher does not exist."}), 400
    # the substitute must actually be free for the whole period
    st, en = _tt_minutes(slot['start_time']), _tt_minutes(slot['end_time'])
    # The slot is a weekday pattern, so the chosen date must actually be that day.
    day_name = datetime.date.fromisoformat(date).strftime('%A')
    if day_name != slot['day']:
        return jsonify({"error": f"{date} is a {day_name}, but that period is scheduled on {slot['day']}."}), 400
    if st is None or en is None:
        return jsonify({"error":"That period has invalid times."}), 400
    busy = db.execute("""SELECT sl.day, sl.start_time, sl.end_time, v.class_id, v.section_id,
                                c.name AS class_name, s.name AS section_name
                           FROM timetable_slots sl
                           JOIN timetable_versions v ON v.id=sl.version_id
                           LEFT JOIN classes c ON c.id=v.class_id
                           LEFT JOIN sections s ON s.id=v.section_id
                          WHERE v.status='published' AND sl.status='active'
                            AND sl.day=? AND sl.version_id<>?
                            AND (sl.teacher_id=? OR sl.substitute_teacher_id=?)""",
                      (slot['day'], slot['version_id'], sub_id, sub_id)).fetchall()
    for b in busy:
        bs, be = _tt_minutes(b['start_time']), _tt_minutes(b['end_time'])
        if bs is not None and be is not None and _tt_overlap(st, en, bs, be):
            return jsonify({"error": f"That teacher is already assigned to "
                                     f"{b['class_name']}-{b['section_name']} on {b['day']} "
                                     f"{b['start_time']}-{b['end_time']}."}), 409
    # the substitute must not already be covering a different class that date
    for r in db.execute("""SELECT sl.start_time, sl.end_time FROM timetable_substitutions sub
                             JOIN timetable_slots sl ON sl.id=sub.slot_id
                            WHERE sub.date=? AND sub.status='approved'
                              AND sub.substitute_teacher_id=?""", (date, sub_id)).fetchall():
        os_, oe = _tt_minutes(r['start_time']), _tt_minutes(r['end_time'])
        if os_ is not None and oe is not None and _tt_overlap(st, en, os_, oe):
            return jsonify({"error":"That teacher already covers another class at that time."}), 409
    status = 'approved' if not can(u['role'], 'timetable', 'full') else (d.get('status') or 'approved')
    if status not in ('pending', 'approved', 'rejected'): status = 'approved'
    now_iso = datetime.datetime.now().isoformat()
    try:
        cur = db.execute("""INSERT INTO timetable_substitutions
            (slot_id,date,original_teacher_id,substitute_teacher_id,reason,status,requested_by,approved_by,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (slot_id, date, slot['teacher_id'], sub_id, str(d.get('reason') or '')[:200],
             status, u['id'], u['id'] if status == 'approved' else None, now_iso, now_iso))
    except sqlite3.IntegrityError:
        return jsonify({"error":"A substitution already exists for that period on that date."}), 409
    _tt_log(db, slot['version_id'], slot['class_id'], slot['section_id'], 'substitute',
            f"Substituted teacher on {date} {slot['start_time']}",
            {"slot_id": slot_id, "date": date, "status": status}, u['id'])
    db.commit()
    return jsonify({"ok":True, "id":cur.lastrowid, "status":status})

@app.route('/api/timetable/substitutions/<int:sid>', methods=['PUT','DELETE'])
def tt_substitution_detail(sid):
    u = get_current_user()
    if not u: return jsonify({"error":"Not authenticated"}), 401
    if not can(u['role'], 'timetable', 'full'):
        return jsonify({"error":"Access denied: only administrators can change substitutions."}), 403
    db = get_db()
    row = db.execute("""SELECT sub.*, v.class_id, v.section_id
                          FROM timetable_substitutions sub
                          JOIN timetable_slots sl ON sl.id=sub.slot_id
                          JOIN timetable_versions v ON v.id=sl.version_id
                         WHERE sub.id=?""", (sid,)).fetchone()
    if not row: return jsonify({"error":"Substitution not found."}), 404
    if request.method == 'DELETE':
        db.execute("DELETE FROM timetable_substitutions WHERE id=?", (sid,))
        _tt_log(db, None, row['class_id'], row['section_id'], 'substitute',
                f"Removed substitution #{sid}", {"date": row['date']}, u['id'])
        db.commit()
        return jsonify({"ok":True})
    d = request.get_json(silent=True) or {}
    status = d.get('status')
    if status not in ('pending', 'approved', 'rejected'):
        return jsonify({"error":"status must be pending, approved or rejected."}), 400
    db.execute("UPDATE timetable_substitutions SET status=?, approved_by=?, updated_at=? WHERE id=?",
               (status, u['id'] if status == 'approved' else None,
                datetime.datetime.now().isoformat(), sid))
    _tt_log(db, None, row['class_id'], row['section_id'], 'substitute',
            f"Substitution #{sid} marked {status}", {"date": row['date'], "status": status}, u['id'])
    db.commit()
    return jsonify({"ok":True, "status":status})

# ---------------- Role-scoped schedule (the screen everyone reads) ----------------
@app.route('/api/timetable/schedule')
def tt_schedule():
    u = get_current_user()
    if not u: return jsonify({"error":"Not authenticated"}), 401
    if not can(u['role'], 'timetable', 'view'): return jsonify({"error":"Access denied"}), 403
    db = get_db()
    session_id = _tt_int(request.args.get('session_id')) or _tt_active_session_id(db)
    class_id = _tt_int(request.args.get('class_id'))
    section_id = _tt_int(request.args.get('section_id'))
    student_id = _tt_int(request.args.get('student_id'))
    view = (request.args.get('view') or '').strip()
    date_str = request.args.get('date') or datetime.date.today().isoformat()
    try: date_obj = datetime.date.fromisoformat(date_str)
    except ValueError: date_obj = datetime.date.today()
    class_id, section_id, student_id, err = _tt_scope(db, u, class_id, section_id, student_id, view)
    if err: return jsonify(err[0]), err[1]
    settings = _tt_settings(db, session_id, class_id, section_id)
    if class_id is None:
        return jsonify(_tt_teacher_week(db, u, session_id, settings, date_obj))
    return jsonify(_tt_live_payload(db, class_id, section_id, session_id, settings, date_obj, u, student_id))

# ---------------- PDF export ----------------
def _tt_pdf_bytes(payload, title):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=12*mm, rightMargin=12*mm,
                            topMargin=12*mm, bottomMargin=12*mm)
    days = payload.get('days') or []
    # collect the union of start times so rows line up across columns
    order, seen = [], set()
    for d in days:
        for s in d['slots']:
            if s.get('kind') != 'period': continue
            if s['start_time'] not in seen:
                seen.add(s['start_time']); order.append(s['start_time'])
    order.sort()
    styles = getSampleStyleSheet()
    elems = [Paragraph(title, styles['Title']), Spacer(1, 6)]
    scope = payload.get('scope') or {}
    sub_line = payload.get('sub_line') or ''
    if sub_line:
        elems.append(Paragraph(sub_line, styles['Normal']))
    elems.append(Spacer(1, 8))
    if not order:
        elems.append(Paragraph("No published timetable has been set for this class yet.", styles['Normal']))
    else:
        head = ["Time"] + [d['day'] for d in days]
        data = [head]
        for t in order:
            row = [t]
            for d in days:
                hit = next((s for s in d['slots'] if s['start_time'] == t and s['kind'] == 'period'), None)
                if not hit:
                    row.append("")
                    continue
                if hit['status'] == 'cancelled':
                    row.append("CANCELLED\n" + (hit.get('subject_name') or hit.get('name') or ''))
                    continue
                parts = [hit.get('subject_name') or hit.get('name') or '']
                if hit.get('teacher_name'): parts.append(hit['teacher_name'])
                if hit.get('room'): parts.append("Room " + hit['room'])
                if hit.get('substitute_name'): parts.append("Sub: " + hit['substitute_name'])
                if scope.get('view') == 'mine' and hit.get('class_name'):
                    parts.insert(1, "Class %s-%s" % (hit['class_name'], hit.get('section_name') or ''))
                row.append("\n".join(p for p in parts if p))
            data.append(row)
        # breaks / lunch rows
        for d in days:
            for s in d['slots']:
                if s.get('kind') in ('break', 'lunch', 'assembly'):
                    pass
        breaks = {}
        for d in days:
            for s in d['slots']:
                if s.get('kind') == 'period': continue
                key = (s['start_time'], s['end_time'], s.get('name') or s['kind'])
                breaks.setdefault(key, set()).add(d['day'])
        for (st, en, nm), dset in sorted(breaks.items()):
            data.append(["%s-%s" % (st, en), "%s (%s)" % (nm, ", ".join(sorted(dset)))]
                        + [""] * (len(days) - 1))
        t = Table(data, repeatRows=1, colWidths=[26*mm] + [None] * len(days))
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTSIZE', (0, 0), (-1, -1), 7.5),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        elems.append(t)
    doc.build(elems)
    return buf.getvalue()

@app.route('/api/timetable/pdf')
def tt_pdf():
    u = get_current_user()
    if not u: return jsonify({"error":"Not authenticated"}), 401
    if not can(u['role'], 'timetable', 'view'): return jsonify({"error":"Access denied"}), 403
    db = get_db()
    session_id = _tt_int(request.args.get('session_id')) or _tt_active_session_id(db)
    class_id = _tt_int(request.args.get('class_id'))
    section_id = _tt_int(request.args.get('section_id'))
    student_id = _tt_int(request.args.get('student_id'))
    view = (request.args.get('view') or '').strip()
    date = datetime.date.today()
    class_id, section_id, student_id, err = _tt_scope(db, u, class_id, section_id, student_id, view)
    if err: return jsonify(err[0]), err[1]
    settings = _tt_settings(db, session_id, class_id, section_id)
    school = db.execute("SELECT school_name FROM settings WHERE id=1").fetchone()
    school_name = (school[0] if school and school[0] else 'Dynamic CuroBase')
    if class_id is None:
        payload = _tt_teacher_week(db, u, session_id, settings, date)
        title = "%s — Weekly Timetable (%s)" % (school_name, u['username'])
        payload['sub_line'] = "Week beginning %s" % (date - datetime.timedelta(days=date.weekday()))
    else:
        payload = _tt_live_payload(db, class_id, section_id, session_id, settings, date, u, student_id)
        cls = payload['scope'].get('class_name') or '?'
        sec = payload['scope'].get('section_name') or '?'
        title = "%s — Class %s-%s Timetable" % (school_name, cls, sec)
        payload['sub_line'] = "Academic session %s • Week beginning %s" % (
            payload.get('session', {}).get('id', ''),
            (date - datetime.timedelta(days=date.weekday())).isoformat())
    try:
        data = _tt_pdf_bytes(payload, title)
    except Exception as e:
        return jsonify({"error":"Could not build the PDF.","detail":str(e)[:200]}), 500
    fn = "timetable_%s_%s.pdf" % (
        ("%s-%s" % (payload['scope'].get('class_name'), payload['scope'].get('section_name')))
        if class_id is not None else u['username'],
        date.isoformat())
    return send_file(io.BytesIO(data), as_attachment=True, download_name=fn,
                     mimetype="application/pdf")

# ---------- Static fallback ----------
@app.route('/manifest.json')
def manifest():
    return send_from_directory(APP_DIR, 'manifest.json')

if __name__=='__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
