# Dynamic Attendance App — Website

Modern SaaS School Management Website running at **http://localhost:5000**

## How to Run (Local Website)
1. Double-click `start_website.bat`  OR run:
   ```
   python app.py
   # or
   python3.13 app.py
   ```
2. Open browser: http://127.0.0.1:5000
3. Login: `admin / admin123`  or `teacher / teacher123`

## On Phone (Same WiFi)
- Find PC IP: `ipconfig` -> WiFi IP e.g. `10.175.1.88`
- On phone browser: `http://10.175.1.88:5000`
- Add to Home Screen -> works like app (PWA manifest)

## Desktop App
```
python desktop.py
```
Opens native window (pywebview) 1200x800.

## Deploy to Internet
- **Render / Railway / PythonAnywhere**: upload folder, set start command `python app.py`, port 5000
- **GitHub Pages (frontend only)**: frontend is in `index.html` + `static/` — needs Flask backend for data
- Requirements in `requirements.txt`

## Tech
Flask + SQLite + pywebview + qrcode + openpyxl + reportlab
All data in `data/attendance.db`

## Features
Dashboard, Students (photo + QR), Attendance P/A/L, Holidays, Monthly Excel/PDF, Classes 1-12, Staff, WhatsApp Groups, Notices, E-Notes, Mid-Day Meal, Scholarship, Complaints, DateSheet, Settings & Security
