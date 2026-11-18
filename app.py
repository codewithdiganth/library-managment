import os
import json
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from contextlib import closing
from difflib import SequenceMatcher
from functools import wraps
from io import BytesIO

import requests

from dotenv import load_dotenv
from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db, init_db

load_dotenv()


def create_app():
    app = Flask(__name__)
    secret_key = os.environ.get("FLASK_SECRET_KEY", "")
    if len(secret_key) < 32:
        raise RuntimeError("Set FLASK_SECRET_KEY to a secret of at least 32 characters.")
    app.config["SECRET_KEY"] = secret_key
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    init_db()

    @app.before_request
    def load_user_and_check_csrf():
        g.user = None
        user_id = session.get("user_id")
        if user_id:
            db = get_db()
            g.user = db.execute(
                "SELECT id, name, email, role, member_code, department FROM users WHERE id = ? AND active = 1",
                (user_id,),
            ).fetchone()
            db.close()
            if g.user is None:
                session.clear()
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
            expected = session.get("csrf_token", "")
            if not expected or not secrets.compare_digest(supplied, expected):
                abort(400, description="Invalid or expired request token.")

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("index"))
            return view(*args, **kwargs)
        return wrapped

    def roles_required(*roles):
        def decorator(view):
            @wraps(view)
            @login_required
            def wrapped(*args, **kwargs):
                if g.user["role"] not in roles:
                    abort(403)
                return view(*args, **kwargs)
            return wrapped
        return decorator

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="Northstar Library")

    @app.route("/", methods=["GET", "POST"])
    def index():
        if g.user:
            return redirect(url_for("dashboard"))
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            db = get_db()
            user = db.execute(
                "SELECT id, password_hash, role FROM users WHERE email = ? AND active = 1",
                (email,),
            ).fetchone()
            db.close()
            if user and check_password_hash(user["password_hash"], password):
                session.clear()
                session.permanent = True
                session["user_id"] = user["id"]
                session["csrf_token"] = secrets.token_urlsafe(32)
                return redirect(url_for("dashboard"))
            flash("That email and password combination was not recognized.", "error")
        return render_template("login.html", csrf_token=session["csrf_token"])

    @app.post("/logout")
    @login_required
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.get("/dashboard")
    @login_required
    def dashboard():
        db = get_db()
        if g.user["role"] == "student":
            metrics = {
                "active_loans": db.execute(
                    "SELECT COUNT(*) FROM loans WHERE user_id = ? AND returned_at IS NULL", (g.user["id"],)
                ).fetchone()[0],
                "overdue": db.execute(
                    "SELECT COUNT(*) FROM loans WHERE user_id = ? AND returned_at IS NULL AND due_at < date('now')",
                    (g.user["id"],),
                ).fetchone()[0],
                "fine_balance": db.execute(
                    "SELECT COALESCE(SUM(fine), 0) FROM loans WHERE user_id = ? AND fine_paid = 0", (g.user["id"],)
                ).fetchone()[0],
            }
        else:
            metrics = {
                "active_loans": db.execute("SELECT COUNT(*) FROM loans WHERE returned_at IS NULL").fetchone()[0],
                "overdue": db.execute(
                    "SELECT COUNT(*) FROM loans WHERE returned_at IS NULL AND due_at < date('now')"
                ).fetchone()[0],
                "fine_balance": db.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'student' AND active = 1"
                ).fetchone()[0],
            }
        db.close()
        return render_template("dashboard.html", user=g.user, metrics=metrics, csrf_token=session["csrf_token"])

    @app.get("/api/books")
    @login_required
    def list_books():
        query = request.args.get("q", "").strip()[:100].casefold()
        category = request.args.get("category", "").strip()[:60]
        available_only = request.args.get("available", "") == "1"
        with closing(get_db()) as db:
            rows = db.execute(
                """SELECT b.*, MAX(b.total_copies - COUNT(l.id), 0) AS available_copies
                   FROM books b LEFT JOIN loans l ON l.book_id = b.id AND l.returned_at IS NULL
                   GROUP BY b.id ORDER BY b.title COLLATE NOCASE"""
            ).fetchall()
        books = [dict(row) for row in rows]
        if category:
            books = [book for book in books if book["category"].casefold() == category.casefold()]
        if available_only:
            books = [book for book in books if book["available_copies"] > 0]
        if query:
            tokens = [t for t in query.split() if t]
            token_matches = [
                book for book in books
                if all(t in f"{book['title']} {book['author']} {book['category']} {book['isbn']}".casefold() for t in tokens)
            ]
            exact = [book for book in books if any(
                query in str(book[field]).casefold() for field in ("title", "author", "category", "isbn")
            )]
            if exact:
                books = exact
            elif token_matches:
                books = token_matches
            else:
                ranked = []
                for book in books:
                    searchable = (book["title"], book["author"], book["category"], book["isbn"])
                    score = max(SequenceMatcher(None, query, value.casefold()).ratio() for value in searchable)
                    if score >= 0.48:
                        ranked.append((score, book))
                books = [book for _, book in sorted(ranked, key=lambda match: match[0], reverse=True)]
        return jsonify(books=books, categories=sorted({book["category"] for book in rows}))

    @app.post("/api/books")
    @roles_required("staff", "admin")
    def add_book():
        data = request.get_json(silent=True) or {}
        fields = {key: str(data.get(key, "")).strip() for key in ("isbn", "title", "author", "category")}
        if any(not value or len(value) > 160 for value in fields.values()):
            return jsonify(error="ISBN, title, author and category are required."), 400
        if len(fields["isbn"]) not in (10, 13) or not fields["isbn"].replace("-", "").isalnum():
            return jsonify(error="Enter a valid 10- or 13-character ISBN."), 400
        try:
            copies = int(data.get("total_copies", 1))
            if not 0 <= copies <= 500:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify(error="Copies must be a number from 0 to 500."), 400
        optional = {key: str(data.get(key, "")).strip()[:500] for key in ("description", "cover_url")}
        location = {key: str(data.get(key, default)).strip()[:40] for key, default in (("shelf", "A"), ("rack", "01"), ("floor", "1"))}
        try:
            with closing(get_db()) as db, db:
                cursor = db.execute(
                    """INSERT INTO books (isbn, title, author, category, description, cover_url, total_copies, shelf, rack, floor)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (fields["isbn"].replace("-", ""), fields["title"], fields["author"], fields["category"],
                     optional["description"], optional["cover_url"], copies, location["shelf"], location["rack"], location["floor"]),
                )
                book_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            return jsonify(error="That ISBN is already in the catalog."), 409
        return jsonify(id=book_id, message="Book added to the catalog."), 201

    @app.patch("/api/books/<int:book_id>")
    @roles_required("staff", "admin")
    def update_book(book_id):
        data = request.get_json(silent=True) or {}
        allowed = {"isbn", "title", "author", "category", "description", "cover_url", "total_copies", "shelf", "rack", "floor"}
        updates = {key: data[key] for key in allowed if key in data}
        if not updates:
            return jsonify(error="No book fields were provided."), 400
        if any(not str(value).strip() for key, value in updates.items() if key in {"isbn", "title", "author", "category"}):
            return jsonify(error="ISBN, title, author and category cannot be blank."), 400
        if "total_copies" in updates:
            try:
                updates["total_copies"] = int(updates["total_copies"])
                if not 0 <= updates["total_copies"] <= 500:
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify(error="Copies must be a number from 0 to 500."), 400
        if "isbn" in updates:
            updates["isbn"] = str(updates["isbn"]).replace("-", "").strip()
            if len(updates["isbn"]) not in (10, 13) or not updates["isbn"].isalnum():
                return jsonify(error="Enter a valid 10- or 13-character ISBN."), 400
        columns = ", ".join(f"{column} = ?" for column in updates)
        try:
            with closing(get_db()) as db, db:
                cursor = db.execute(f"UPDATE books SET {columns} WHERE id = ?", (*updates.values(), book_id))
                if not cursor.rowcount:
                    return jsonify(error="Book not found."), 404
        except sqlite3.IntegrityError:
            return jsonify(error="That ISBN is already in the catalog."), 409
        return jsonify(message="Book updated.")

    @app.delete("/api/books/<int:book_id>")
    @roles_required("staff", "admin")
    def delete_book(book_id):
        with closing(get_db()) as db, db:
            active = db.execute(
                "SELECT COUNT(*) FROM loans WHERE book_id = ? AND returned_at IS NULL", (book_id,)
            ).fetchone()[0]
            if active:
                return jsonify(error="Return all copies before removing this title."), 409
            cursor = db.execute("DELETE FROM books WHERE id = ?", (book_id,))
            if not cursor.rowcount:
                return jsonify(error="Book not found."), 404
        return jsonify(message="Book removed from the catalog.")

    @app.get("/api/members")
    @roles_required("staff", "admin")
    def list_members():
        with closing(get_db()) as db:
            members = db.execute(
                """SELECT u.id, u.name, u.email, u.role, u.member_code, u.department, u.active,
                          COUNT(l.id) AS loans_count,
                          SUM(CASE WHEN l.returned_at IS NULL THEN 1 ELSE 0 END) AS active_loans
                   FROM users u LEFT JOIN loans l ON l.user_id = u.id
                   WHERE u.role = 'student' GROUP BY u.id ORDER BY u.name COLLATE NOCASE"""
            ).fetchall()
        return jsonify(members=[dict(member) for member in members])

    @app.get("/api/members/<int:member_id>/history")
    @roles_required("staff", "admin")
    def member_history(member_id):
        with closing(get_db()) as db:
            member = db.execute(
                "SELECT id, name, email, member_code FROM users WHERE id = ? AND role = 'student'", (member_id,)
            ).fetchone()
            if member is None:
                return jsonify(error="Member not found."), 404
            loans = db.execute(
                """SELECT b.title, b.author, l.issued_at, l.due_at, l.returned_at, l.fine, l.fine_paid
                   FROM loans l JOIN books b ON b.id = l.book_id WHERE l.user_id = ?
                   ORDER BY l.issued_at DESC""", (member_id,)
            ).fetchall()
        return jsonify(member=dict(member), history=[dict(loan) for loan in loans])

    @app.post("/api/members")
    @roles_required("admin")
    def add_member():
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        department = str(data.get("department", "")).strip()[:100]
        if not name or len(name) > 120 or "@" not in email or len(email) > 200 or len(password) < 8:
            return jsonify(error="Enter a name, valid email and password of at least 8 characters."), 400
        code = f"STU-{secrets.token_hex(3).upper()}"
        try:
            with closing(get_db()) as db, db:
                cursor = db.execute(
                    "INSERT INTO users (name, email, password_hash, role, member_code, department) VALUES (?, ?, ?, 'student', ?, ?)",
                    (name, email, generate_password_hash(password), code, department),
                )
                member_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            return jsonify(error="An account with that email already exists."), 409
        return jsonify(id=member_id, member_code=code, message="Student account created."), 201

    @app.patch("/api/members/<int:member_id>")
    @roles_required("admin")
    def update_member(member_id):
        data = request.get_json(silent=True) or {}
        updates = {}
        for key in ("name", "email", "department"):
            if key in data:
                updates[key] = str(data[key]).strip()
        if "active" in data:
            updates["active"] = 1 if data["active"] in (1, "1", True, "true") else 0
        if "password" in data and str(data["password"]).strip():
            pwd = str(data["password"]).strip()
            if len(pwd) < 8:
                return jsonify(error="Password must be at least 8 characters."), 400
            updates["password_hash"] = generate_password_hash(pwd)
        if not updates:
            return jsonify(error="Provide details to update."), 400
        if "email" in updates:
            updates["email"] = updates["email"].lower()
            if "@" not in updates["email"] or len(updates["email"]) > 200:
                return jsonify(error="Enter a valid email address."), 400
        if "name" in updates and (not updates["name"] or len(updates["name"]) > 120):
            return jsonify(error="Name must be between 1 and 120 characters."), 400
        if "department" in updates:
            updates["department"] = updates["department"][:100]
        columns = ", ".join(f"{column} = ?" for column in updates)
        try:
            with closing(get_db()) as db, db:
                cursor = db.execute(
                    f"UPDATE users SET {columns} WHERE id = ? AND role = 'student'", (*updates.values(), member_id)
                )
                if not cursor.rowcount:
                    return jsonify(error="Member not found."), 404
        except sqlite3.IntegrityError:
            return jsonify(error="An account with that email already exists."), 409
        return jsonify(message="Member details updated.")

    @app.delete("/api/members/<int:member_id>")
    @roles_required("admin")
    def remove_member(member_id):
        with closing(get_db()) as db, db:
            active = db.execute(
                "SELECT COUNT(*) FROM loans WHERE user_id = ? AND returned_at IS NULL", (member_id,)
            ).fetchone()[0]
            if active:
                return jsonify(error="Close active loans before deactivating this member."), 409
            cursor = db.execute("UPDATE users SET active = 0 WHERE id = ? AND role = 'student'", (member_id,))
            if not cursor.rowcount:
                return jsonify(error="Member not found."), 404
        return jsonify(message="Member deactivated. Their borrowing history is preserved.")

    @app.get("/api/loans")
    @login_required
    def list_loans():
        member_id = g.user["id"] if g.user["role"] == "student" else request.args.get("member_id")
        query = """SELECT l.id, l.user_id, u.name AS member_name, u.member_code, l.book_id, b.title, b.author,
                          l.issued_at, l.due_at, l.returned_at, l.fine, l.fine_paid,
                          CASE WHEN l.returned_at IS NULL AND l.due_at < date('now')
                               THEN ROUND((julianday(date('now')) - julianday(l.due_at)) * 5.0, 2)
                               ELSE l.fine END AS current_fine
                   FROM loans l JOIN users u ON u.id = l.user_id JOIN books b ON b.id = l.book_id"""
        params = []
        if member_id:
            query += " WHERE l.user_id = ?"
            params.append(member_id)
        query += " ORDER BY l.returned_at IS NULL DESC, l.due_at ASC"
        with closing(get_db()) as db:
            loans = db.execute(query, params).fetchall()
        return jsonify(loans=[dict(loan) for loan in loans])

    @app.post("/api/circulation/issue")
    @roles_required("staff", "admin")
    def issue_book():
        data = request.get_json(silent=True) or {}
        member_code = str(data.get("member_code", "")).strip().upper()
        raw_isbn = str(data.get("isbn", "")).replace("-", "").strip()
        # Support scanning format prefix e.g. "BOOK:9780143127796"
        if raw_isbn.startswith("BOOK:"):
            raw_isbn = raw_isbn[5:].strip()
        # Support scanning member QR e.g. "MEMBER:STU-2401"
        if member_code.startswith("MEMBER:"):
            member_code = member_code[7:].strip()
        isbn = raw_isbn
        try:
            days = int(data.get("days", 14))
            if not 1 <= days <= 60:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify(error="Loan period must be between 1 and 60 days."), 400
        if not member_code or not isbn:
            return jsonify(error="Scan or enter both a member code and an ISBN."), 400
        today = date.today()
        with closing(get_db()) as db, db:
            member = db.execute(
                "SELECT id FROM users WHERE member_code = ? AND role = 'student' AND active = 1", (member_code,)
            ).fetchone()
            book = db.execute("SELECT id, total_copies, title FROM books WHERE isbn = ?", (isbn,)).fetchone()
            if member is None:
                return jsonify(error="Active student member was not found."), 404
            if book is None:
                return jsonify(error="Book was not found in the catalog."), 404
            active_count = db.execute(
                "SELECT COUNT(*) FROM loans WHERE book_id = ? AND returned_at IS NULL", (book["id"],)
            ).fetchone()[0]
            if active_count >= book["total_copies"]:
                return jsonify(error="No copies of this title are currently available."), 409
            duplicate = db.execute(
                "SELECT 1 FROM loans WHERE user_id = ? AND book_id = ? AND returned_at IS NULL",
                (member["id"], book["id"]),
            ).fetchone()
            if duplicate:
                return jsonify(error="This member already has an active loan for this title."), 409
            outstanding = db.execute(
                "SELECT COUNT(*) FROM loans WHERE user_id = ? AND returned_at IS NULL", (member["id"],)
            ).fetchone()[0]
            if outstanding >= 5:
                return jsonify(error="This member has reached the five-book limit."), 409
            cursor = db.execute(
                "INSERT INTO loans (user_id, book_id, issued_at, due_at) VALUES (?, ?, ?, ?)",
                (member["id"], book["id"], today.isoformat(), (today + timedelta(days=days)).isoformat()),
            )
            db.execute(
                "INSERT INTO activity_log (user_id, book_id, action) VALUES (?, ?, 'borrow')",
                (member["id"], book["id"]),
            )
        return jsonify(loan_id=cursor.lastrowid, title=book["title"], due_at=(today + timedelta(days=days)).isoformat()), 201

    @app.post("/api/circulation/return")
    @roles_required("staff", "admin")
    def return_book():
        data = request.get_json(silent=True) or {}
        member_code = str(data.get("member_code", "")).strip().upper()
        isbn = str(data.get("isbn", "")).replace("-", "").strip()
        if isbn.startswith("BOOK:"):
            isbn = isbn[5:].strip()
        if member_code.startswith("MEMBER:"):
            member_code = member_code[7:].strip()
        loan_id = data.get("loan_id")
        with closing(get_db()) as db, db:
            if loan_id:
                loan = db.execute(
                    "SELECT id, user_id, book_id, due_at FROM loans WHERE id = ? AND returned_at IS NULL", (loan_id,)
                ).fetchone()
            else:
                loan = db.execute(
                    """SELECT l.id, l.user_id, l.book_id, l.due_at FROM loans l
                       JOIN users u ON u.id = l.user_id JOIN books b ON b.id = l.book_id
                       WHERE u.member_code = ? AND b.isbn = ? AND l.returned_at IS NULL ORDER BY l.issued_at LIMIT 1""",
                    (member_code, isbn),
                ).fetchone()
            if loan is None:
                return jsonify(error="No active loan matches those details."), 404
            days_late = max((date.today() - date.fromisoformat(loan["due_at"])).days, 0)
            fine = round(days_late * 5.0, 2)
            db.execute("UPDATE loans SET returned_at = ?, fine = ? WHERE id = ?", (date.today().isoformat(), fine, loan["id"]))
            db.execute(
                "INSERT INTO activity_log (user_id, book_id, action) VALUES (?, ?, 'return')",
                (loan["user_id"], loan["book_id"]),
            )
            available = db.execute(
                """SELECT b.total_copies - COUNT(l.id) FROM books b LEFT JOIN loans l
                   ON l.book_id = b.id AND l.returned_at IS NULL WHERE b.id = ? GROUP BY b.id""",
                (loan["book_id"],),
            ).fetchone()[0]
            waiting = db.execute(
                "SELECT id, user_id FROM waiting_queue WHERE book_id = ? AND status = 'waiting' ORDER BY created_at, id LIMIT ?",
                (loan["book_id"], max(available, 0)),
            ).fetchall()
            for entry in waiting:
                db.execute(
                    "UPDATE waiting_queue SET status = 'notified', notified_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (entry["id"],),
                )
                db.execute(
                    "INSERT INTO notifications (user_id, message, kind) VALUES (?, ?, 'queue')",
                    (entry["user_id"], "A book you queued for is available. Visit the library desk to check it out."),
                )
        return jsonify(message="Book returned successfully.", fine=fine, days_overdue=days_late)

    @app.post("/api/fines/<int:loan_id>/pay")
    @login_required
    def pay_fine(loan_id):
        with closing(get_db()) as db, db:
            loan = db.execute("SELECT user_id, fine FROM loans WHERE id = ?", (loan_id,)).fetchone()
            if loan is None:
                return jsonify(error="Loan record was not found."), 404
            if g.user["role"] == "student" and loan["user_id"] != g.user["id"]:
                abort(403)
            db.execute("UPDATE loans SET fine_paid = 1 WHERE id = ?", (loan_id,))
        return jsonify(message="Fine marked as paid.", amount=loan["fine"])

    @app.get("/qr/book/<int:book_id>.png")
    @login_required
    def book_qr(book_id):
        with closing(get_db()) as db:
            book = db.execute("SELECT isbn FROM books WHERE id = ?", (book_id,)).fetchone()
        if book is None:
            abort(404)
        return qr_image(f"BOOK:{book['isbn']}")

    @app.get("/qr/member/<int:member_id>.png")
    @login_required
    def member_qr(member_id):
        if g.user["role"] == "student" and g.user["id"] != member_id:
            abort(403)
        with closing(get_db()) as db:
            member = db.execute(
                "SELECT member_code FROM users WHERE id = ? AND role = 'student' AND active = 1", (member_id,)
            ).fetchone()
        if member is None:
            abort(404)
        return qr_image(f"MEMBER:{member['member_code']}")

    def qr_image(value):
        import qrcode
        image = qrcode.make(value)
        output = BytesIO()
        image.save(output, format="PNG")
        output.seek(0)
        return send_file(output, mimetype="image/png", max_age=300)

    @app.get("/api/seats")
    @login_required
    def list_seats():
        day = request.args.get("day", date.today().isoformat())
        slot = request.args.get("slot", "10:00")
        try:
            start = datetime.strptime(f"{day} {slot}", "%Y-%m-%d %H:%M")
        except ValueError:
            return jsonify(error="Choose a valid date and time."), 400
        end = start + timedelta(hours=2)
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        with closing(get_db()) as db, db:
            # Auto release unconfirmed reservations after 15 minutes of start time
            db.execute(
                "UPDATE reservations SET status = 'released' WHERE status = 'booked' AND datetime(starts_at, '+15 minutes') < datetime(?)",
                (now_str,)
            )
            db.execute(
                "UPDATE reservations SET status = 'completed' WHERE status IN ('booked', 'checked_in') AND datetime(ends_at) <= datetime(?)",
                (now_str,)
            )
            reservations = db.execute(
                """SELECT seat_id, user_id, starts_at, ends_at, status FROM reservations
                   WHERE status IN ('booked', 'checked_in') AND datetime(starts_at) < datetime(?) AND datetime(ends_at) > datetime(?)""",
                (end.strftime("%Y-%m-%d %H:%M:%S"), start.strftime("%Y-%m-%d %H:%M:%S")),
            ).fetchall()
            seats = db.execute("SELECT id, label, zone FROM seats WHERE active = 1 ORDER BY zone, label").fetchall()
        current = {row["seat_id"]: row for row in reservations}
        return jsonify(
            seats=[{"id": seat["id"], "label": seat["label"], "zone": seat["zone"],
                    "status": "occupied" if seat["id"] in current else "available",
                    "mine": bool(seat["id"] in current and current[seat["id"]]["user_id"] == (g.user["id"] if g.user else -1))}
                   for seat in seats],
            starts_at=start.strftime("%Y-%m-%d %H:%M:%S"), ends_at=end.strftime("%Y-%m-%d %H:%M:%S"),
            bookable=bool(g.user["role"] == "student" and start >= now - timedelta(minutes=5) and start <= now + timedelta(days=7)),
        )

    @app.get("/api/reservations")
    @login_required
    def list_reservations():
        query = """SELECT r.id, r.user_id, u.name AS member_name, s.label AS seat, s.zone,
                          r.starts_at, r.ends_at, r.status, r.checked_in_at
                   FROM reservations r JOIN users u ON u.id = r.user_id JOIN seats s ON s.id = r.seat_id"""
        params = []
        if g.user["role"] == "student":
            query += " WHERE r.user_id = ?"
            params.append(g.user["id"])
        query += " ORDER BY r.starts_at DESC LIMIT 50"
        with closing(get_db()) as db:
            reservations = db.execute(query, params).fetchall()
        return jsonify(reservations=[dict(row) for row in reservations])

    @app.post("/api/reservations")
    @roles_required("student")
    def create_reservation():
        data = request.get_json(silent=True) or {}
        try:
            seat_id = int(data.get("seat_id"))
            start = datetime.strptime(str(data.get("starts_at", "")), "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return jsonify(error="Choose a valid seat and start time."), 400
        end = start + timedelta(hours=2)
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        if start < now - timedelta(minutes=5) or start > now + timedelta(days=7) or start.minute not in (0, 30):
            return jsonify(error="Choose a time within the next seven days, on the hour or half-hour."), 400
        with closing(get_db()) as db, db:
            # Auto release expired reservations first
            db.execute(
                "UPDATE reservations SET status = 'released' WHERE status = 'booked' AND datetime(starts_at, '+15 minutes') < datetime(?)",
                (now_str,)
            )
            overlap = db.execute(
                "SELECT 1 FROM reservations WHERE user_id = ? AND status IN ('booked', 'checked_in') AND datetime(starts_at) < datetime(?) AND datetime(ends_at) > datetime(?)",
                (g.user["id"], end.strftime("%Y-%m-%d %H:%M:%S"), start.strftime("%Y-%m-%d %H:%M:%S")),
            ).fetchone()
            seat = db.execute("SELECT id FROM seats WHERE id = ? AND active = 1", (seat_id,)).fetchone()
            reserved = db.execute(
                "SELECT 1 FROM reservations WHERE seat_id = ? AND status IN ('booked', 'checked_in') AND datetime(starts_at) < datetime(?) AND datetime(ends_at) > datetime(?)",
                (seat_id, end.strftime("%Y-%m-%d %H:%M:%S"), start.strftime("%Y-%m-%d %H:%M:%S")),
            ).fetchone()
            if seat is None:
                return jsonify(error="That seat is no longer available."), 404
            if overlap:
                return jsonify(error="You already have a reservation during this time."), 409
            if reserved:
                return jsonify(error="That seat has already been booked for this time."), 409
            cursor = db.execute(
                "INSERT INTO reservations (user_id, seat_id, starts_at, ends_at) VALUES (?, ?, ?, ?)",
                (g.user["id"], seat_id, start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")),
            )
        return jsonify(id=cursor.lastrowid, starts_at=start.strftime("%Y-%m-%d %H:%M:%S"), ends_at=end.strftime("%Y-%m-%d %H:%M:%S")), 201

    @app.post("/api/reservations/<int:reservation_id>/check-in")
    @login_required
    def check_in_reservation(reservation_id):
        with closing(get_db()) as db, db:
            reservation = db.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
            if reservation is None:
                return jsonify(error="Reservation not found."), 404
            if g.user["role"] == "student" and reservation["user_id"] != g.user["id"]:
                abort(403)
            now = datetime.now()
            starts = datetime.fromisoformat(reservation["starts_at"])
            if reservation["status"] != "booked" or now < starts - timedelta(minutes=15) or now > starts + timedelta(minutes=15):
                return jsonify(error="Check-in is available from 15 minutes before to 15 minutes after your start time."), 409
            db.execute("UPDATE reservations SET status = 'checked_in', checked_in_at = ? WHERE id = ?", (now.strftime("%Y-%m-%d %H:%M:%S"), reservation_id))
        return jsonify(message="You are checked in.")

    @app.delete("/api/reservations/<int:reservation_id>")
    @login_required
    def cancel_reservation(reservation_id):
        with closing(get_db()) as db, db:
            reservation = db.execute("SELECT user_id, status FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
            if reservation is None:
                return jsonify(error="Reservation not found."), 404
            if g.user["role"] == "student" and reservation["user_id"] != g.user["id"]:
                abort(403)
            if reservation["status"] not in ("booked", "checked_in"):
                return jsonify(error="This reservation can no longer be cancelled."), 409
            db.execute("UPDATE reservations SET status = 'cancelled' WHERE id = ?", (reservation_id,))
        return jsonify(message="Reservation cancelled.")

    @app.get("/api/queue")
    @login_required
    def list_queue():
        query = """SELECT q.id, q.user_id, u.name AS member_name, b.id AS book_id, b.title, b.author,
                          q.created_at, q.notified_at, q.status FROM waiting_queue q
                    JOIN users u ON u.id = q.user_id JOIN books b ON b.id = q.book_id"""
        params = []
        if g.user["role"] == "student":
            query += " WHERE q.user_id = ?"
            params.append(g.user["id"])
        query += " ORDER BY q.created_at"
        with closing(get_db()) as db:
            rows = db.execute(query, params).fetchall()
            queue = []
            for row in rows:
                item = dict(row)
                item["position"] = db.execute(
                    "SELECT COUNT(*) FROM waiting_queue WHERE book_id = ? AND status = 'waiting' AND created_at <= ?",
                    (item["book_id"], item["created_at"]),
                ).fetchone()[0] if item["status"] == "waiting" else None
                queue.append(item)
        return jsonify(queue=queue)

    @app.post("/api/queue")
    @roles_required("student")
    def join_queue():
        data = request.get_json(silent=True) or {}
        try:
            book_id = int(data.get("book_id"))
        except (TypeError, ValueError):
            return jsonify(error="Choose a valid book."), 400
        with closing(get_db()) as db, db:
            book = db.execute("SELECT id, title, total_copies FROM books WHERE id = ?", (book_id,)).fetchone()
            if book is None:
                return jsonify(error="Book not found."), 404
            active = db.execute(
                "SELECT COUNT(*) FROM loans WHERE book_id = ? AND returned_at IS NULL", (book_id,)
            ).fetchone()[0]
            if active < book["total_copies"]:
                return jsonify(error="This title is available now. Place a loan instead."), 409
            duplicate = db.execute(
                "SELECT 1 FROM waiting_queue WHERE book_id = ? AND user_id = ? AND status IN ('waiting', 'notified')",
                (book_id, g.user["id"]),
            ).fetchone()
            if duplicate:
                return jsonify(error="You are already in the queue for this title."), 409
            cursor = db.execute("INSERT INTO waiting_queue (user_id, book_id) VALUES (?, ?)", (g.user["id"], book_id))
        return jsonify(id=cursor.lastrowid, message="You joined the waiting queue."), 201

    @app.delete("/api/queue/<int:queue_id>")
    @login_required
    def leave_queue(queue_id):
        with closing(get_db()) as db, db:
            entry = db.execute("SELECT user_id FROM waiting_queue WHERE id = ?", (queue_id,)).fetchone()
            if entry is None:
                return jsonify(error="Queue entry not found."), 404
            if g.user["role"] == "student" and entry["user_id"] != g.user["id"]:
                abort(403)
            db.execute("UPDATE waiting_queue SET status = 'cancelled' WHERE id = ?", (queue_id,))
        return jsonify(message="You left the waiting queue.")

    def provider_reply(system_prompt, user_prompt):
        provider = os.environ.get("AI_PROVIDER", "openai").strip().lower()
        if provider == "anthropic":
            token = os.environ.get("ANTHROPIC_API_KEY", "").strip()
            if not token:
                return None
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": token, "anthropic-version": "2023-06-01"},
                json={"model": os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"), "max_tokens": 500,
                      "system": system_prompt, "messages": [{"role": "user", "content": user_prompt}]},
                timeout=12,
            )
            response.raise_for_status()
            return response.json()["content"][0]["text"]
        if provider == "openai":
            token = os.environ.get("OPENAI_API_KEY", "").strip()
            if not token:
                return None
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                json={"model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), "temperature": 0.3,
                      "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]},
                timeout=12,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if isinstance(content, list):
                return "".join(part.get("text", "") for part in content if isinstance(part, dict))
            return content
        return None

    @app.get("/api/recommendations")
    @login_required
    def recommendations():
        with closing(get_db()) as db:
            history = db.execute(
                """SELECT b.category, b.title FROM loans l JOIN books b ON b.id = l.book_id
                   WHERE l.user_id = ? ORDER BY l.issued_at DESC LIMIT 10""", (g.user["id"],)
            ).fetchall()
            preferences = [row[0] for row in db.execute(
                "SELECT category FROM preferences WHERE user_id = ?", (g.user["id"],)
            ).fetchall()]
            if not preferences:
                preferences = list(dict.fromkeys(row["category"] for row in history))
            rows = db.execute(
                """SELECT b.*,
                          b.total_copies - (SELECT COUNT(*) FROM loans active WHERE active.book_id = b.id AND active.returned_at IS NULL) AS available_copies,
                          (SELECT COUNT(*) FROM loans past WHERE past.book_id = b.id) AS popularity
                   FROM books b ORDER BY popularity DESC, b.title"""
            ).fetchall()
        excluded_titles = {row["title"].casefold() for row in history}
        candidates = [dict(row) for row in rows if row["available_copies"] > 0 and row["title"].casefold() not in excluded_titles]
        results = []
        source = "rule-based"
        if candidates:
            try:
                content = provider_reply(
                    "Recommend only catalog books in the input. Return JSON with a recommendations array of objects containing isbn and a short reason.",
                    f"Reader categories: {preferences}. Previously read: {[row['title'] for row in history]}. Catalog: "
                    + json.dumps([{"isbn": book["isbn"], "title": book["title"], "category": book["category"], "description": book["description"]} for book in candidates[:18]]),
                )
                if content:
                    start, end = content.find("{"), content.rfind("}") + 1
                    payload = json.loads(content[start:end])
                    by_isbn = {book["isbn"]: book for book in candidates}
                    for suggestion in payload.get("recommendations", []):
                        book = by_isbn.get(str(suggestion.get("isbn", "")))
                        if book:
                            results.append({**book, "reason": str(suggestion.get("reason", "A thoughtful next read."))[:220]})
                    source = "ai" if results else "rule-based"
            except (requests.RequestException, KeyError, ValueError, TypeError, AttributeError):
                results = []
        if not results:
            candidates.sort(key=lambda book: (book["category"] not in preferences, -book["popularity"], book["title"]))
            results = [{**book, "reason": f"Based on your interest in {book['category']}." if book["category"] in preferences
                        else f"A highly regarded title in {book['category']}."} for book in candidates[:5]]
        return jsonify(recommendations=results[:5], source=source, preferences=preferences)

    @app.post("/api/preferences")
    @roles_required("student")
    def save_preferences():
        data = request.get_json(silent=True) or {}
        categories = data.get("categories", [])
        if not isinstance(categories, list) or len(categories) > 10 or any(not isinstance(item, str) or len(item) > 60 for item in categories):
            return jsonify(error="Choose up to 10 valid categories."), 400
        with closing(get_db()) as db, db:
            db.execute("DELETE FROM preferences WHERE user_id = ?", (g.user["id"],))
            db.executemany("INSERT INTO preferences (user_id, category) VALUES (?, ?)",
                           [(g.user["id"], category.strip()) for category in dict.fromkeys(categories) if category.strip()])
        return jsonify(message="Your reading preferences were saved.")

    @app.post("/api/chat")
    @login_required
    def chat():
        data = request.get_json(silent=True) or {}
        question = str(data.get("message", "")).strip()[:1000]
        if len(question) < 2:
            return jsonify(error="Ask a question to get started."), 400
        try:
            answer = provider_reply(
                "You are Northstar University's library assistant. Use only these facts: weekdays 8:00 AM–10:00 PM; weekends 10:00 AM–6:00 PM; loans are 14 days; overdue fines are Rs. 5 per day; renewals are handled by staff.",
                question,
            )
        except (requests.RequestException, KeyError, ValueError):
            answer = None
        source = "ai" if answer else "library assistant"
        if not answer:
            normalized = question.casefold()
            if any(word in normalized for word in ("hour", "open", "close", "time", "weekend")):
                answer = "The library is open weekdays from 8:00 AM to 10:00 PM, and weekends from 10:00 AM to 6:00 PM."
            elif any(word in normalized for word in ("fine", "late", "overdue", "fee", "cost", "charge")):
                answer = "Overdue books accrue a fine of Rs. 5 per day. Your due dates and account balance are available in My books."
            elif any(word in normalized for word in ("rule", "borrow", "loan", "renew", "checkout", "limit")):
                answer = "Students may borrow up to five books for 14 days. Renewals and exceptions are handled by the library desk."
            elif any(word in normalized for word in ("seat", "desk", "room", "study", "space", "reserve")):
                answer = "Study seats can be reserved for 2-hour blocks up to 7 days in advance. Remember to check in within 15 minutes of your start time."
            else:
                with closing(get_db()) as db:
                    books = db.execute(
                        """SELECT b.title, b.author, MAX(b.total_copies - COUNT(l.id), 0) AS available
                           FROM books b LEFT JOIN loans l ON l.book_id = b.id AND l.returned_at IS NULL GROUP BY b.id"""
                    ).fetchall()
                terms = [term for term in re.findall(r"[a-zA-Z0-9]{3,}", normalized) if term not in {"the", "and", "for", "book", "books", "find", "with", "have"}]
                matches = [book for book in books if any(term in f"{book['title']} {book['author']}".casefold() for term in terms)]
                answer = " ".join(f"'{book['title']}' by {book['author']} has {book['available']} copies available." for book in matches[:3]) if matches else "I can help with book availability, library hours, study spaces, borrowing rules and overdue fines (Rs. 5/day). Tell me a title or ask about any of these topics."
        return jsonify(answer=answer, source=source)

    @app.get("/api/notifications")
    @login_required
    def list_notifications():
        with closing(get_db()) as db, db:
            due_loans = db.execute(
                """SELECT b.title, l.due_at FROM loans l JOIN books b ON b.id = l.book_id
                   WHERE l.user_id = ? AND l.returned_at IS NULL AND l.due_at <= date('now', '+3 days')""",
                (g.user["id"],),
            ).fetchall()
            for loan in due_loans:
                message = f"{loan['title']} is due on {loan['due_at']}. Return or renew it at the library desk to avoid Rs. 5/day fine."
                exists = db.execute(
                    "SELECT 1 FROM notifications WHERE user_id = ? AND message = ? AND date(created_at) = date('now')",
                    (g.user["id"], message),
                ).fetchone()
                if not exists:
                    db.execute("INSERT INTO notifications (user_id, message, kind) VALUES (?, ?, 'due')", (g.user["id"], message))
            notifications = db.execute(
                "SELECT id, message, kind, created_at, read_at FROM notifications WHERE user_id = ? ORDER BY read_at IS NULL DESC, created_at DESC LIMIT 30",
                (g.user["id"],),
            ).fetchall()
            unread = db.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL", (g.user["id"],)).fetchone()[0]
        return jsonify(notifications=[dict(row) for row in notifications], unread=unread)

    @app.post("/api/notifications/<int:notification_id>/read")
    @login_required
    def mark_notification_read(notification_id):
        with closing(get_db()) as db, db:
            cursor = db.execute(
                "UPDATE notifications SET read_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                (notification_id, g.user["id"]),
            )
            if not cursor.rowcount:
                return jsonify(error="Notification not found."), 404
        return jsonify(message="Notification marked as read.")

    @app.post("/api/notifications/read-all")
    @login_required
    def mark_all_notifications_read():
        with closing(get_db()) as db, db:
            db.execute("UPDATE notifications SET read_at = CURRENT_TIMESTAMP WHERE user_id = ? AND read_at IS NULL", (g.user["id"],))
        return jsonify(message="All notifications marked as read.")

    @app.get("/api/analytics")
    @roles_required("admin")
    def analytics():
        today = date.today()
        first_day = today - timedelta(days=13)
        labels = [(first_day + timedelta(days=index)).isoformat() for index in range(14)]
        with closing(get_db()) as db:
            totals = {
                "total_books": db.execute("SELECT COUNT(*) FROM books").fetchone()[0],
                "active_loans": db.execute("SELECT COUNT(*) FROM loans WHERE returned_at IS NULL").fetchone()[0],
                "active_members": db.execute("SELECT COUNT(*) FROM users WHERE role = 'student' AND active = 1").fetchone()[0],
                "overdue": db.execute(
                    "SELECT COUNT(*) FROM loans WHERE returned_at IS NULL AND due_at < date('now')"
                ).fetchone()[0],
            }
            seats = db.execute("SELECT COUNT(*) FROM seats WHERE active = 1").fetchone()[0]
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            occupied = db.execute(
                "SELECT COUNT(DISTINCT seat_id) FROM reservations WHERE status IN ('booked', 'checked_in') AND starts_at <= datetime(?) AND ends_at > datetime(?)",
                (now_str, now_str)
            ).fetchone()[0]
            issued_rows = db.execute(
                "SELECT date(issued_at) AS day, COUNT(*) AS count FROM loans WHERE date(issued_at) >= ? GROUP BY date(issued_at)",
                (first_day.isoformat(),),
            ).fetchall()
            returned_rows = db.execute(
                "SELECT date(returned_at) AS day, COUNT(*) AS count FROM loans WHERE returned_at IS NOT NULL AND date(returned_at) >= ? GROUP BY date(returned_at)",
                (first_day.isoformat(),),
            ).fetchall()
            member_rows = db.execute(
                "SELECT date(created_at) AS day, COUNT(DISTINCT user_id) AS count FROM activity_log WHERE action = 'borrow' AND date(created_at) >= ? GROUP BY date(created_at)",
                (first_day.isoformat(),),
            ).fetchall()
            popular = db.execute(
                """SELECT b.title, COUNT(l.id) AS loans FROM books b LEFT JOIN loans l ON l.book_id = b.id
                   GROUP BY b.id ORDER BY loans DESC, b.title LIMIT 6"""
            ).fetchall()
            overdue = db.execute(
                """SELECT CASE WHEN julianday('now') - julianday(due_at) <= 7 THEN '1–7 days'
                               WHEN julianday('now') - julianday(due_at) <= 14 THEN '8–14 days'
                               ELSE '15+ days' END AS band, COUNT(*) AS count
                   FROM loans WHERE returned_at IS NULL AND due_at < date('now') GROUP BY band"""
            ).fetchall()
        issued = {row["day"]: row["count"] for row in issued_rows}
        returned = {row["day"]: row["count"] for row in returned_rows}
        members = {row["day"]: row["count"] for row in member_rows}
        return jsonify(
            updated_at=datetime.now().astimezone().isoformat(timespec="minutes"),
            totals={**totals, "seat_count": seats, "seats_in_use": occupied,
                    "seat_usage": round(occupied / seats * 100) if seats else 0},
            circulation={"labels": labels, "issued": [issued.get(day, 0) for day in labels],
                         "returned": [returned.get(day, 0) for day in labels]},
            active_members={"labels": labels, "values": [members.get(day, 0) for day in labels]},
            popular={"labels": [row["title"] for row in popular], "values": [row["loans"] for row in popular]},
            overdue={"labels": [row["band"] for row in overdue] or ["No overdue loans"],
                     "values": [row["count"] for row in overdue] or [0]},
        )

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    def api_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error=getattr(error, "description", "Request could not be completed.")), error.code
        return error

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
