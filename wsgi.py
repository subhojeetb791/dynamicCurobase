"""WSGI production entry point for Smart Attendance.

Render/Gunicorn loads the ``application`` object from this file::

    gunicorn --bind 0.0.0.0:$PORT --workers 3 --timeout 60 wsgi:application

Local dev still uses ``python app.py`` (Flask dev server).
"""
import os

os.environ.setdefault("FLASK_ENV", os.environ.get("FLASK_ENV", "production"))

from app import app as application  # noqa: E402  (Flask WSGI callable)

# ``app`` alias kept for backwards-compat with ``gunicorn app:app``.
app = application

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    application.run(host="0.0.0.0", port=port, debug=False)
