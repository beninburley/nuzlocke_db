#!/usr/bin/env bash
# Set up (or update) this app on PythonAnywhere. Run it from a PythonAnywhere
# Bash console after creating a "Manual configuration" web app:
#
#   git clone https://github.com/beninburley/nuzlocke_db.git ~/nuzlocke_db   # first time only
#   bash ~/nuzlocke_db/deploy/pythonanywhere_setup.sh
#
# It clones or updates the code in ~/nuzlocke_db, installs dependencies in
# ~/.virtualenvs/nuzlocke, points the web app's WSGI file at the app and reloads
# it. It is safe to re-run; that is also how you deploy updates. The database
# (~/nuzlocke_db/instance/nuzlocke.db) is never touched, apart from the app's
# own startup migrations.
set -euo pipefail

REPO="https://github.com/beninburley/nuzlocke_db.git"
PROJECT="$HOME/nuzlocke_db"
VENV="$HOME/.virtualenvs/nuzlocke"
WSGI="/var/www/${USER,,}_pythonanywhere_com_wsgi.py"

if [ -d "$PROJECT/.git" ]; then
    echo "Updating code in $PROJECT"
    git -C "$PROJECT" pull --ff-only
else
    echo "Cloning code into $PROJECT"
    git clone "$REPO" "$PROJECT"
fi

if [ ! -x "$VENV/bin/python" ]; then
    PYTHON="$(command -v python3.11 || command -v python3)"
    echo "Creating virtualenv $VENV with $PYTHON"
    "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$PROJECT/requirements.txt"

# Create the database (or run pending migrations) now, so a problem shows up
# here rather than as a 500 error on the site.
(cd "$PROJECT" && "$VENV/bin/python" -c "import app")

if [ -f "$WSGI" ]; then
    cp "$PROJECT/deploy/pythonanywhere_wsgi.py" "$WSGI"   # writing the WSGI file also reloads the site
    echo "Updated $WSGI and reloaded the web app"
else
    echo "No web app found yet ($WSGI is missing)."
    echo "Create one on the Web tab (Manual configuration, Python 3.11), then re-run this script."
fi

echo
echo "Done. On the Web tab make sure:"
echo "  Source code:  $PROJECT"
echo "  Virtualenv:   $VENV"
echo "  Password protection and Force HTTPS are both on."
