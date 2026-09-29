// Electron shell for Smart Attendance Desktop (shares Flask backend).
// Usage: npm i electron && BACKEND_URL=http://127.0.0.1:5000 npx electron ./electron
const { app, BrowserWindow } = require('electron');
const BACKEND = process.env.BACKEND_URL || 'http://127.0.0.1:5000';
function create() {
  const win = new BrowserWindow({
    width: 1280, height: 800, autoHideMenuBar: true,
    webPreferences: { contextIsolation: true },
  });
  win.loadURL(BACKEND);
}
app.whenReady().then(create);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
