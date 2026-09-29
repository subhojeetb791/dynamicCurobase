# Smart School Attendance — Multi-Platform (Desktop + Mobile + Public Website, Shared Backend)

Modern **Smart School Operating System**: attendance (P/A/L/T + time/subject/session), QR (permanent + expiring class QR), calendar, heatmap, insights, goals, badges, alerts, timetable, parent snapshot, digital ID, timeline, review requests, reports (Excel/PDF), offline queue + audit trail — one Flask + SQLite backend serving **Desktop (pywebview/Electron), Smartphone (PWA/Expo), Public Website**.

```
              🌐 PUBLIC (/public)
                     │
                     ▼
            🔐 AUTH (session, RBAC)
                     │
                     ▼
           ☁️ SHARED FLASK BACKEND
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
   🗄️ SQLite DB              📁 photos/qrcodes
        │
   ┌────┼────┐
   ▼    ▼    ▼
 🖥️   📱   🌐
Desktop Mobile Web
```

## Technology Used
- **Backend:** Python 3.13, Flask 3.1.3, SQLite, Werkzeug, qrcode, Pillow, openpyxl, reportlab, pywebview (desktop)
- **Frontend:** HTML5, CSS3 (SaaS navy/blue theme), Vanilla JS, PWA manifest, responsive (desktop-first)
- **Auth:** Flask session (server-side, `secret_key`), SHA256 hashing, RBAC decorators, `session` cookie `same-origin`
- **Storage:** SQLite `data/attendance.db`, `data/photos/`, `data/qrcodes/`
- **Alternative stack note:** If starting from scratch, spec suggests Next.js+TS+Tailwind+Firebase; existing Flask stack was preserved as required — Firebase setup documented below for migration.

## Project Structure
```
attendance_app/
├── app.py               # Flask app, RBAC, all APIs (869→~1200 lines)
├── desktop.py           # pywebview wrapper (Flask thread + native window)
├── index.html           # 10 screens + login + Access Denied
├── static/
│   ├── style.css        # SaaS theme, responsive, cards, tables
│   └── app.js           # RBAC nav, dashboards, all features
├── data/
│   ├── attendance.db    # SQLite
│   ├── photos/          # student photos
│   └── qrcodes/         # QR pngs
├── manifest.json        # PWA
├── requirements.txt
├── start_website.bat    # double-click launch
├── start_public_https.bat # cloudflared/ngrok helper
├── .env.example
└── README.md
```

## Prerequisites
- Python 3.10+ (tested 3.13, 3.14)
- `pip install -r requirements.txt` (Flask, pywebview, qrcode, Pillow, openpyxl, reportlab)

## Installation
```bash
git clone <repo>
cd attendance_app
pip install -r requirements.txt
python app.py
# open http://127.0.0.1:5000
```

## Environment Variables (.env.example)
```
ATTENDANCE_SECRET=dynamic-attendance-rbac-2026-secret-key
FLASK_ENV=development
PORT=5000
# For Firebase migration (if switching from SQLite):
NEXT_PUBLIC_FIREBASE_API_KEY=
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=
NEXT_PUBLIC_FIREBASE_PROJECT_ID=
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=
NEXT_PUBLIC_FIREBASE_APP_ID=
FIREBASE_SERVICE_ACCOUNT_JSON=
```

## Database Setup
- SQLite auto-creates on first run (`init_db()`). No manual setup.
- To reseed demo data: `python -c "import app; app.init_db()"` or run `python` with `seed_demo.py` (already included in `data`).
- Tables: `users, students, teachers, parents, staff, attendance, holidays, subjects, marks, notices, enotes, messages, whatsapp_groups, complaints, datesheets, midday_meals, scholarships, login_history, settings`

## Local Development Commands
```bash
python app.py              # website http://127.0.0.1:5000
python desktop.py          # native window 1200x800
python -m py_compile app.py # lint check
```

## Build Commands
```bash
# No build step for Flask; for production use gunicorn/waitress:
pip install waitress
waitress-serve --host=0.0.0.0 --port=5000 app:app
```

## Test Commands
```bash
# RBAC audit (covers all 25 features)
python -m py_compile app.py
python tests/test_rbac.py  # or run full_audit.py via python
```

## Demo Login Accounts (local dev only)
| Role | Username | Password | Linked |
|------|----------|----------|--------|
| Admin | admin | admin123 | — |
| Teacher | teacher | teacher123 | — |
| Teacher2 | teacher2 | teacher123 | — |
| Student | student | student123 | STU001 Aarav Sharma (1-A) |
| Parent | parent | parent123 | STU001 (child) |

Role selection on login is **NOT trusted** — backend uses DB `users.role`.

## Firebase Setup (if migrating from SQLite)
1. Create Firebase project → Enable Auth (Email/Password)
2. Create Firestore + Storage → Add web app → copy config to `.env`
3. Deploy rules: `firebase deploy --only firestore:rules,storage`
4. Create collections as per Database Structure

## Deployment (Desktop + Mobile + Public Web, one backend)
- **Shared backend:** `python app.py` → `http://127.0.0.1:5000` (SQLite `data/attendance.db`, session auth, RBAC). Phone same WiFi: `http://<PC-IP>:5000`.
- **Desktop:** `python desktop.py` (pywebview, Admin/Teacher) or Electron: `cd electron && npm i && npm start` (`BACKEND_URL=http://127.0.0.1:5000`), package with `npm run dist` → Windows installer.
- **Mobile:** PWA — open site on phone → Add to Home Screen (bottom nav, offline queue, `frontend/static/sw.js`); Expo — see `mobile/README.md` (`expo-camera` QR → `POST /api/qr/scan-temp`, `expo-notifications` ← `/api/notifications`).
- **Public website:** `/public` (SEO meta, sitemap `/sitemap.xml`, robots) — only `/api/public/*` (info/notices/events/contact), never private data.
- **Public HTTPS:** `%TEMP%\cloudflared.exe tunnel --url http://127.0.0.1:5000` (or `ngrok http 5000` after authtoken).
- **Render/Railway:** `pip install -r requirements.txt` + start `python app.py` + env `ATTENDANCE_SECRET`.

## Demo Seed Data (after `seed_demo.py`)
- 1 admin, 2 teachers, 8 students (STU001-008), 4 parents, 48 attendance rows, 3 enotes, 4 notices, 1 whatsapp, 2 complaints, 3 datesheets, 2 marks

## Troubleshooting
- `Port 5000 in use` → `taskkill /F /IM python.exe` or change `app.run(port=5001)`
- `ngrok ERR_NGROK_4018` → need `ngrok config add-authtoken` (Cloudflare `trycloudflare.com` works without)
- `no file` on logo → ensure `data/` writable, max 2MB PNG/JPG/WebP

## Security Notes
- Passwords hashed SHA256 (upgrade to bcrypt in production)
- Session `httpOnly` cookie, `same-origin` fetch, server-side `can(role,feature,action)` on every mutating API
- Hiding buttons is **not** enough — backend returns `403 Access denied` for `Teacher→Delete Student`, `Student→Add E-Note`, etc.
- Validate `linked_student_id` ownership for student/parent isolation
- No secrets in repo — use `.env`, `.env.example` is template
