"""Look at an account, set its password or change its role, from a console.

Usage:
    python scripts/manage_account.py USERNAME                      # show the account
    python scripts/manage_account.py USERNAME --password           # set a new password
    python scripts/manage_account.py USERNAME --role admin         # change the role
    python scripts/manage_account.py USERNAME --create [--password] [--role ROLE]

The password is asked for (twice) and never echoed, so it doesn't end up in
the shell history. Setting it logs the account out everywhere. Roles:
trainer, mod, content_creator, admin.
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import accounts  # noqa: E402
import db  # noqa: E402


def ask_password():
    while True:
        password = getpass.getpass("New password: ")
        problem = accounts.password_problem(password)
        if problem:
            print(problem)
        elif getpass.getpass("Same password again: ") != password:
            print("Those didn't match.")
        else:
            return password


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("username")
    parser.add_argument("--create", action="store_true", help="create the account if it doesn't exist")
    parser.add_argument("--password", action="store_true", help="set a new password (asked for)")
    parser.add_argument("--role", choices=accounts.ROLES)
    args = parser.parse_args()

    conn = db.connect()
    db.init_db(conn)
    user = conn.execute("SELECT * FROM users WHERE username = ?", (args.username,)).fetchone()
    if user is None:
        if not args.create:
            sys.exit(f"No account named {args.username!r}. Add --create to make one.")
        problem = accounts.username_problem(args.username)
        if problem:
            sys.exit(problem)
        with conn:
            conn.execute("INSERT INTO users (username, role) VALUES (?, ?)",
                         (args.username, args.role or accounts.DEFAULT_ROLE))
        user = conn.execute("SELECT * FROM users WHERE username = ?", (args.username,)).fetchone()
        print(f"Created {user['username']}.")

    if args.role and args.role != user["role"]:
        with conn:
            conn.execute("UPDATE users SET role = ? WHERE id = ?", (args.role, user["id"]))
        print(f"Role set to {args.role}.")
    if args.password:
        password = ask_password()
        with conn:
            conn.execute("UPDATE users SET password_hash = ?, session_epoch = session_epoch + 1 WHERE id = ?",
                         (accounts.hash_password(password), user["id"]))
        print("Password set.")

    user = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    attempts = conn.execute("SELECT COUNT(*) FROM attempts WHERE user_id = ?", (user["id"],)).fetchone()[0]
    print(f"{user['username']}: role {user['role']}, {attempts} attempts, joined {user['created_at']}, "
          f"{'has a password' if user['password_hash'] else 'NO PASSWORD (cannot log in)'}")
    conn.close()


if __name__ == "__main__":
    main()
