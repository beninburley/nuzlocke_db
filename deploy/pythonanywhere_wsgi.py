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

from app import app as application  # noqa: E402,F401
