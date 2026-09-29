import threading, time, os, sys
try:
    import webview
except ImportError:
    webview=None
APP_DIR=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)
import app as flask_app
def start():
    flask_app.app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False, threaded=True)
def main():
    t=threading.Thread(target=start, daemon=True); t.start(); time.sleep(1.5)
    if webview:
        webview.create_window("Dynamic Attendance App","http://127.0.0.1:5000", width=1200, height=800, min_size=(900,600), resizable=True)
        webview.start()
    else:
        import webbrowser
        webbrowser.open("http://127.0.0.1:5000")
        print("Running at http://127.0.0.1:5000")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt: sys.exit(0)
if __name__=='__main__': main()
