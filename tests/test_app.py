import os
import re
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch
from pathlib import Path

TEST_DIRECTORY = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = str(Path(TEST_DIRECTORY.name) / "library.db")
os.environ["FLASK_SECRET_KEY"] = "test-only-secret-key-that-is-at-least-32-characters"
os.environ["SEED_DEMO_DATA"] = "true"

from app import app, create_app
from database import get_db, init_db


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True

    def setUp(self):
        self.client = app.test_client()

    def csrf_token(self):
        response = self.client.get("/")
        match = re.search(r'name="csrf_token" value="([^"]+)', response.get_data(as_text=True))
        self.assertIsNotNone(match)
        return match.group(1)

    def login(self, email, password):
        token = self.csrf_token()
        return self.client.post(
            "/", data={"csrf_token": token, "email": email, "password": password}
        )

    def current_csrf_token(self):
        with self.client.session_transaction() as state:
            return state["csrf_token"]

    def test_app_requires_a_strong_configured_secret(self):
        with patch.dict("os.environ", {"FLASK_SECRET_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "FLASK_SECRET_KEY"):
                create_app()

    def test_bad_password_is_rejected(self):
        token = self.csrf_token()
        response = self.client.post(
            "/",
            data={"csrf_token": token, "email": "maya@northstar.edu", "password": "incorrect"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("was not recognized", response.get_data(as_text=True))

    def test_csrf_is_required(self):
        response = self.client.post(
            "/", data={"email": "maya@northstar.edu", "password": "student123"}
        )
        self.assertEqual(response.status_code, 400)

    def test_login_opens_student_workspace(self):
        token = self.csrf_token()
        response = self.client.post(
            "/",
            data={"csrf_token": token, "email": "maya@northstar.edu", "password": "student123"},
        )
        self.assertEqual(response.status_code, 302)
        dashboard = self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("STUDENT WORKSPACE", dashboard.get_data(as_text=True))

    def test_demo_passwords_are_hashed(self):
        db = get_db()
        password_hash = db.execute(
            "SELECT password_hash FROM users WHERE email = ?", ("maya@northstar.edu",)
        ).fetchone()[0]
        db.close()
        self.assertNotEqual(password_hash, "student123")

    def test_demo_accounts_are_not_seeded_without_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("database.DATABASE_PATH", Path(directory) / "library.db"):
                with patch.dict("os.environ", {"SEED_DEMO_DATA": "false"}):
                    init_db()
                db = get_db()
                try:
                    user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                    book_count = db.execute("SELECT COUNT(*) FROM books").fetchone()[0]
                finally:
                    db.close()
        self.assertEqual(user_count, 0)
        self.assertGreater(book_count, 0)

    def test_existing_demo_accounts_are_deactivated_without_losing_history(self):
        demo_emails = (
            "admin@northstar.edu", "staff@northstar.edu", "maya@northstar.edu",
            "ethan@northstar.edu", "sofia@northstar.edu",
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch("database.DATABASE_PATH", Path(directory) / "library.db"):
                with patch.dict("os.environ", {"SEED_DEMO_DATA": "true"}):
                    init_db()
                db = get_db()
                loans_before = db.execute("SELECT COUNT(*) FROM loans").fetchone()[0]
                db.close()
                with patch.dict("os.environ", {"SEED_DEMO_DATA": "false"}):
                    init_db()
                db = get_db()
                try:
                    inactive_count = db.execute(
                        "SELECT COUNT(*) FROM users WHERE email IN (?, ?, ?, ?, ?) AND active = 0",
                        demo_emails,
                    ).fetchone()[0]
                    loans_after = db.execute("SELECT COUNT(*) FROM loans").fetchone()[0]
                finally:
                    db.close()
        self.assertEqual(inactive_count, len(demo_emails))
        self.assertEqual(loans_after, loans_before)

    def test_catalog_search_finds_typo(self):
        self.login("maya@northstar.edu", "student123")
        response = self.client.get("/api/books?q=Atmoic%20Habits")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["books"][0]["title"], "Atomic Habits")

    def test_student_cannot_add_catalog_book(self):
        self.login("maya@northstar.edu", "student123")
        response = self.client.post(
            "/api/books", json={"isbn": "1234567890", "title": "Test", "author": "Test", "category": "Test"},
            headers={"X-CSRF-Token": self.current_csrf_token()},
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_member(self):
        self.login("admin@northstar.edu", "admin123")
        response = self.client.post(
            "/api/members",
            json={"name": "New Member", "email": "new.member@northstar.edu", "password": "longpass123", "department": "Physics"},
            headers={"X-CSRF-Token": self.current_csrf_token()},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.get_json()["member_code"].startswith("STU-"))

    def test_staff_issue_return_and_qr(self):
        self.login("staff@northstar.edu", "staff123")
        token = self.current_csrf_token()
        issue = self.client.post(
            "/api/circulation/issue",
            json={"member_code": "STU-2401", "isbn": "9780143127796"},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(issue.status_code, 201)
        db = get_db()
        loan_id = db.execute(
            "SELECT id FROM loans WHERE user_id = (SELECT id FROM users WHERE member_code = ?) AND book_id = (SELECT id FROM books WHERE isbn = ?) AND returned_at IS NULL",
            ("STU-2401", "9780143127796"),
        ).fetchone()[0]
        db.execute("UPDATE loans SET due_at = ? WHERE id = ?", ((date.today() - timedelta(days=2)).isoformat(), loan_id))
        db.commit()
        db.close()
        returned = self.client.post(
            "/api/circulation/return", json={"loan_id": loan_id}, headers={"X-CSRF-Token": token}
        )
        self.assertEqual(returned.status_code, 200)
        self.assertEqual(returned.get_json()["fine"], 10.0)
        db = get_db()
        book_id = db.execute("SELECT id FROM books WHERE isbn = ?", ("9780143127796",)).fetchone()[0]
        db.close()
        qr = self.client.get(f"/qr/book/{book_id}.png")
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr.mimetype, "image/png")

    def test_analytics_is_admin_only_and_populated(self):
        self.login("maya@northstar.edu", "student123")
        self.assertEqual(self.client.get("/api/analytics").status_code, 403)
        self.client.post("/logout", data={"csrf_token": self.current_csrf_token()})
        self.login("admin@northstar.edu", "admin123")
        response = self.client.get("/api/analytics")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["totals"]["total_books"], 20)
        self.assertEqual(len(payload["circulation"]["labels"]), 14)
        self.assertTrue(payload["popular"]["labels"])

    def test_student_seat_reservation_blocks_overlap(self):
        self.login("maya@northstar.edu", "student123")
        db = get_db()
        seat_id = db.execute("SELECT id FROM seats WHERE label = 'Q03'").fetchone()[0]
        db.close()
        start = (date.today() + timedelta(days=1)).isoformat() + " 10:00:00"
        headers = {"X-CSRF-Token": self.current_csrf_token()}
        payload = {"seat_id": seat_id, "starts_at": start}
        response = self.client.post("/api/reservations", json=payload, headers=headers)
        self.assertEqual(response.status_code, 201)
        conflict = self.client.post("/api/reservations", json=payload, headers=headers)
        self.assertEqual(conflict.status_code, 409)

    def test_waiting_member_is_notified_when_book_returns(self):
        self.login("staff@northstar.edu", "staff123")
        token = self.current_csrf_token()
        loan_ids = []
        for member_code in ("STU-2402", "STU-2403"):
            issued = self.client.post(
                "/api/circulation/issue",
                json={"member_code": member_code, "isbn": "9780596007126"},
                headers={"X-CSRF-Token": token},
            )
            self.assertEqual(issued.status_code, 201)
            db = get_db()
            loan_ids.append(db.execute(
                "SELECT id FROM loans WHERE book_id = (SELECT id FROM books WHERE isbn = ?) AND returned_at IS NULL ORDER BY id DESC LIMIT 1",
                ("9780596007126",),
            ).fetchone()[0])
            db.close()
        self.client.post("/logout", data={"csrf_token": token})
        self.login("maya@northstar.edu", "student123")
        queue = self.client.post(
            "/api/queue", json={"book_id": 4}, headers={"X-CSRF-Token": self.current_csrf_token()}
        )
        self.assertEqual(queue.status_code, 201)
        self.client.post("/logout", data={"csrf_token": self.current_csrf_token()})
        self.login("staff@northstar.edu", "staff123")
        returned = self.client.post(
            "/api/circulation/return", json={"loan_id": loan_ids[0]},
            headers={"X-CSRF-Token": self.current_csrf_token()},
        )
        self.assertEqual(returned.status_code, 200)
        db = get_db()
        state = db.execute("SELECT status FROM waiting_queue WHERE id = ?", (queue.get_json()["id"],)).fetchone()[0]
        notification_count = db.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = (SELECT id FROM users WHERE email = ?) AND kind = 'queue'",
            ("maya@northstar.edu",),
        ).fetchone()[0]
        db.close()
        self.assertEqual(state, "notified")
        self.assertEqual(notification_count, 1)

    def test_ai_features_use_rule_based_fallback(self):
        self.login("maya@northstar.edu", "student123")
        with patch.dict("os.environ", {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "", "AI_PROVIDER": "openai"}):
            recommendations = self.client.get("/api/recommendations")
            chat = self.client.post(
                "/api/chat", json={"message": "What time does the library open?"},
                headers={"X-CSRF-Token": self.current_csrf_token()},
            )
        self.assertEqual(recommendations.status_code, 200)
        self.assertEqual(recommendations.get_json()["source"], "rule-based")
        self.assertTrue(recommendations.get_json()["recommendations"])
        self.assertIn("weekdays", chat.get_json()["answer"])

    def test_due_notifications_are_deduplicated_and_read(self):
        self.login("maya@northstar.edu", "student123")
        notifications = self.client.get("/api/notifications").get_json()
        reminder = next(item for item in notifications["notifications"] if "Clean Code" in item["message"])
        again = self.client.get("/api/notifications").get_json()
        matching = [item for item in again["notifications"] if "Clean Code" in item["message"]]
        self.assertEqual(len(matching), 1)
        read = self.client.post(
            f"/api/notifications/{reminder['id']}/read", json={},
            headers={"X-CSRF-Token": self.current_csrf_token()},
        )
        self.assertEqual(read.status_code, 200)

    def test_student_can_renew_active_loan_twice_but_not_a_third_time(self):
        self.login("maya@northstar.edu", "student123")
        token = self.current_csrf_token()
        db = get_db()
        loan = db.execute(
            """SELECT l.id, l.due_at FROM loans l JOIN users u ON u.id = l.user_id
               WHERE u.email = 'maya@northstar.edu' AND l.returned_at IS NULL
               ORDER BY l.id LIMIT 1"""
        ).fetchone()
        db.close()
        headers = {"X-CSRF-Token": token}
        first = self.client.post(f"/api/loans/{loan['id']}/renew", json={}, headers=headers)
        second = self.client.post(f"/api/loans/{loan['id']}/renew", json={}, headers=headers)
        third = self.client.post(f"/api/loans/{loan['id']}/renew", json={}, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(third.status_code, 409)
        db = get_db()
        renewed = db.execute(
            "SELECT due_at, renewals FROM loans WHERE id = ?", (loan["id"],)
        ).fetchone()
        db.close()
        self.assertEqual(renewed["renewals"], 2)
        self.assertGreater(renewed["due_at"], loan["due_at"])

    def test_staff_can_export_loans_csv(self):
        self.login("staff@northstar.edu", "staff123")
        response = self.client.get("/api/export/loans.csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        self.assertIn(b"Loan ID", response.data)


if __name__ == "__main__":
    unittest.main()
