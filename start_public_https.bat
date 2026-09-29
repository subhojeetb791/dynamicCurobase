@echo off
echo Public HTTPS via Cloudflare (no account needed) or ngrok (needs token)
echo.
echo Option 1: Cloudflare Quick Tunnel (free, no auth)
echo   %TEMP%\cloudflared.exe tunnel --url http://127.0.0.1:5000
echo.
echo Option 2: ngrok (needs authtoken from https://dashboard.ngrok.com/get-started/your-authtoken)
echo   ngrok config add-authtoken YOUR_TOKEN
echo   ngrok http 5000
echo.
pause
%TEMP%\cloudflared.exe tunnel --url http://127.0.0.1:5000
