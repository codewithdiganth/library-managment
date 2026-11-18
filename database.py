import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()


DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", Path(__file__).with_name("library.db")))


def get_db():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(get_db()) as db, db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'staff', 'student')),
                member_code TEXT UNIQUE,
                department TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                isbn TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                cover_url TEXT NOT NULL DEFAULT '',
                total_copies INTEGER NOT NULL DEFAULT 1 CHECK(total_copies >= 0),
                shelf TEXT NOT NULL DEFAULT 'A',
                rack TEXT NOT NULL DEFAULT '01',
                floor TEXT NOT NULL DEFAULT '1',
                published_year INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS loans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                book_id INTEGER NOT NULL REFERENCES books(id),
                issued_at TEXT NOT NULL,
                due_at TEXT NOT NULL,
                returned_at TEXT,
                fine REAL NOT NULL DEFAULT 0,
                fine_paid INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS seats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL UNIQUE,
                zone TEXT NOT NULL DEFAULT 'Quiet study',
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                seat_id INTEGER NOT NULL REFERENCES seats(id),
                starts_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'booked',
                checked_in_at TEXT,
                UNIQUE(seat_id, starts_at)
            );
            CREATE TABLE IF NOT EXISTS waiting_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                book_id INTEGER NOT NULL REFERENCES books(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                notified_at TEXT,
                status TEXT NOT NULL DEFAULT 'waiting',
                UNIQUE(user_id, book_id, status)
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                message TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'info',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                read_at TEXT
            );
            CREATE TABLE IF NOT EXISTS preferences (
                user_id INTEGER NOT NULL REFERENCES users(id),
                category TEXT NOT NULL,
                PRIMARY KEY(user_id, category)
            );
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id),
                book_id INTEGER REFERENCES books(id),
                action TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        seed_env = os.environ.get("SEED_DEMO_DATA")
        seed_demo_accounts = (seed_env is None) or (seed_env.casefold() in {"1", "true", "yes", "on"})
        if seed_demo_accounts and db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            demo_users = [
                ("Avery Morgan", "admin@northstar.edu", "admin123", "admin", "ADM-001", "Library Services"),
                ("Jordan Lee", "staff@northstar.edu", "staff123", "staff", "STF-001", "Library Services"),
                ("Maya Patel", "maya@northstar.edu", "student123", "student", "STU-2401", "Computer Science"),
                ("Ethan Brooks", "ethan@northstar.edu", "student123", "student", "STU-2402", "Economics"),
                ("Sofia Chen", "sofia@northstar.edu", "student123", "student", "STU-2403", "Design"),
            ]
            db.executemany(
                "INSERT INTO users (name, email, password_hash, role, member_code, department) VALUES (?, ?, ?, ?, ?, ?)",
                [(name, email, generate_password_hash(password), role, code, department)
                 for name, email, password, role, code, department in demo_users],
            )
        if not seed_demo_accounts:
            db.execute(
                """UPDATE users SET active = 0
                   WHERE email IN (
                       'admin@northstar.edu', 'staff@northstar.edu', 'maya@northstar.edu',
                       'ethan@northstar.edu', 'sofia@northstar.edu'
                   )"""
            )

        if db.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0:
            books = [
                ("9780062316097", "Sapiens", "Yuval Noah Harari", "History", "A brief history of humankind, from early humans to the modern age.", 4),
                ("9780735211292", "Atomic Habits", "James Clear", "Personal Growth", "Practical strategies for building good habits and breaking bad ones.", 3),
                ("9780132350884", "Clean Code", "Robert C. Martin", "Computer Science", "A handbook of agile software craftsmanship.", 3),
                ("9780596007126", "Head First Design Patterns", "Eric Freeman", "Computer Science", "A visually engaging guide to reusable object-oriented design.", 2),
                ("9780143127741", "The Midnight Library", "Matt Haig", "Fiction", "A novel about the choices that shape a life.", 4),
                ("9780062457714", "Educated", "Tara Westover", "Memoir", "A memoir about education, family and finding a voice.", 2),
                ("9780307465351", "The Lean Startup", "Eric Ries", "Business", "A method for building products through rapid experimentation.", 3),
                ("9780140449136", "Meditations", "Marcus Aurelius", "Philosophy", "The Roman emperor's reflections on Stoic philosophy.", 2),
                ("9780262033848", "Introduction to Algorithms", "Thomas H. Cormen", "Computer Science", "A comprehensive introduction to modern algorithms.", 2),
                ("9780735219106", "The Psychology of Money", "Morgan Housel", "Business", "Timeless lessons on wealth, greed and happiness.", 3),
                ("9780143126560", "Thinking, Fast and Slow", "Daniel Kahneman", "Psychology", "A tour of the two systems that drive human thought.", 2),
                ("9781501124020", "Quiet", "Susan Cain", "Psychology", "The power of introverts in a world that cannot stop talking.", 2),
                ("9780374533557", "The Design of Everyday Things", "Don Norman", "Design", "A foundational exploration of human-centered design.", 3),
                ("9780385490818", "Into the Wild", "Jon Krakauer", "Travel", "The story of a young man's journey into the Alaskan wilderness.", 2),
                ("9780143127550", "Algorithms to Live By", "Brian Christian", "Computer Science", "How computer science can help solve everyday decisions.", 2),
                ("9780062315007", "The Alchemist", "Paulo Coelho", "Fiction", "A shepherd travels in search of a worldly treasure.", 3),
                ("9780393356182", "The Body", "Bill Bryson", "Science", "A tour of the human body and its remarkable systems.", 2),
                ("9780897335599", "Design for the Real World", "Victor Papanek", "Design", "A classic argument for socially responsible design.", 2),
                ("9780593321201", "The Creative Act", "Rick Rubin", "Arts", "A meditation on the creative process and making art.", 2),
                ("9780143127796", "Factfulness", "Hans Rosling", "Science", "A framework for seeing the world with clearer perspective.", 3),
            ]
            db.executemany(
                "INSERT INTO books (isbn, title, author, category, description, total_copies, cover_url, shelf, rack, floor, published_year) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(isbn, title, author, category, description, copies,
                  f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false",
                  chr(65 + index % 5), f"{index // 5 + 1:02d}", "1" if index < 10 else "2", 2020)
                 for index, (isbn, title, author, category, description, copies) in enumerate(books)],
            )

        if db.execute("SELECT COUNT(*) FROM seats").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO seats (label, zone) VALUES (?, ?)",
                [(f"{zone}{number:02d}", "Quiet study" if zone == "Q" else "Collaborative")
                 for zone in ("Q", "C") for number in range(1, 9)],
            )

        if db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0:
            student_ids = [row[0] for row in db.execute("SELECT id FROM users WHERE role='student' ORDER BY id")]
            seat_ids = [row[0] for row in db.execute("SELECT id FROM seats ORDER BY id LIMIT 2")]
            now = datetime.now().replace(second=0, microsecond=0)
            if len(student_ids) >= 2 and len(seat_ids) >= 2:
                db.executemany(
                    "INSERT INTO reservations (user_id, seat_id, starts_at, ends_at, status, checked_in_at) VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (student_ids[0], seat_ids[0], (now - timedelta(minutes=10)).isoformat(timespec="minutes"),
                         (now + timedelta(minutes=80)).isoformat(timespec="minutes"), "checked_in", now.isoformat(timespec="minutes")),
                        (student_ids[1], seat_ids[1], (now + timedelta(hours=2)).isoformat(timespec="minutes"),
                         (now + timedelta(hours=4)).isoformat(timespec="minutes"), "booked", None),
                    ],
                )

        if db.execute("SELECT COUNT(*) FROM loans").fetchone()[0] == 0:
            student_ids = [row[0] for row in db.execute("SELECT id FROM users WHERE role='student' ORDER BY id")]
            book_ids = [row[0] for row in db.execute("SELECT id FROM books ORDER BY id")]
            today = date.today()
            if len(student_ids) >= 3 and len(book_ids) > 12:
                sample_loans = [
                    (student_ids[0], book_ids[0], (today - timedelta(days=9)).isoformat(), (today + timedelta(days=5)).isoformat(), None),
                    (student_ids[0], book_ids[2], (today - timedelta(days=17)).isoformat(), (today - timedelta(days=3)).isoformat(), None),
                    (student_ids[1], book_ids[4], (today - timedelta(days=2)).isoformat(), (today + timedelta(days=12)).isoformat(), None),
                    (student_ids[2], book_ids[12], (today - timedelta(days=6)).isoformat(), (today + timedelta(days=8)).isoformat(), None),
                    (student_ids[1], book_ids[6], (today - timedelta(days=30)).isoformat(), (today - timedelta(days=16)).isoformat(), (today - timedelta(days=15)).isoformat()),
                ]
                db.executemany(
                    "INSERT INTO loans (user_id, book_id, issued_at, due_at, returned_at) VALUES (?, ?, ?, ?, ?)",
                    sample_loans,
                )
                db.executemany(
                    "INSERT INTO activity_log (user_id, book_id, action) VALUES (?, ?, ?)",
                    [(student_ids[0], book_ids[0], "borrow"), (student_ids[0], book_ids[2], "borrow"),
                     (student_ids[1], book_ids[4], "borrow"), (student_ids[2], book_ids[12], "borrow")],
                )
