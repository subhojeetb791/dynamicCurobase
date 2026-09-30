import type { CapacitorConfig } from '@capacitor/cli';

// Production backend: set CAPACITOR_SERVER_URL at sync time, e.g.
//   CAPACITOR_SERVER_URL=https://dynamiccuro.onrender.com npx cap sync android
// When `server.url` is set, the app loads the LIVE backend (works with PC off).
// When unset, the app uses the bundled `frontend/` copy (offline-capable shell).
const serverUrl = process.env.CAPACITOR_SERVER_URL?.replace(/\/$/, '');

const config: CapacitorConfig = {
  appId: 'com.smartattendance.school',
  appName: 'Smart Attendance',
  webDir: 'frontend',
  backgroundColor: '#0f1f3c',
  ...(serverUrl ? { server: { url: serverUrl, cleartext: false } } : {}),
  android: {
    allowMixedContent: false,
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 1500,
      backgroundColor: '#0f1f3c',
      showSpinner: false,
    },
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert'],
    },
  },
};

export default config;
