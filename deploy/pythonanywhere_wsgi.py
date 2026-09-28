"""WSGI entry point for PythonAnywhere.

pythonanywhere_setup.sh copies this over the web app's WSGI file
(/var/www/<username>_pythonanywhere_com_wsgi.py). Debug mode stays off:
app.run(debug=True) only happens when app.py is run directly.
"""
import os
import sys

PROJECT = os.path.expanduser("~/nuzlocke_db")
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

# The site is served over HTTPS only (Force HTTPS), so the login cookie is
# marked Secure and never travels over plain HTTP.
os.environ.setdefault("NUZLOCKE_SECURE_COOKIES", "1")

from app import app as application  # noqa: E402,F401
