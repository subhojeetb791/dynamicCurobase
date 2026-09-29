# Smart Attendance Mobile (Expo + PWA, shared Flask backend)

## Option A — PWA (no build, works today)
1. Run backend: `python app.py` (same centralized DB + auth).
2. On phone (same WiFi): open `http://<PC-IP>:5000` → Chrome → Add to Home Screen.
3. Bottom nav (Home/Attendance/Timetable/Notices/Profile) + offline queue in `frontend/app.js` (`attQueue`, service worker).

## Option B — Expo (Android/iOS, same backend)
```bash
npx create-expo-app smart-attendance-mobile
cd smart-attendance-mobile
npx expo install expo-camera expo-notifications expo-secure-store
# Screens: Login, StudentHome, ParentHome, TeacherMark, Timetable, Notices, DigitalID, QRScan
# API base: https://<your-backend> (Flask, session cookie or token)
# QR scan: expo-camera BarCodeScanner → POST /api/qr/scan-temp {token, code}
# Push: expo-notifications → map to /api/notifications polling
npx expo start
eas build -p android   # APK/AAB
eas build -p ios
```

All platforms share `POST /api/auth/login` (role redirect), RBAC `403` on server, and the same Postgres/SQLite schema.
