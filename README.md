# Smart Library Management System (Northstar Library)

A modern, full-featured web-based Smart Library Management System designed for universities and academic institutions.

---

## 🔑 Login Credentials

The system seeds demo accounts automatically on first run:

| Role | Name | Email | Password | Member Code | Access Level |
|---|---|---|---|---|---|
| **Administrator** | Avery Morgan | `admin@northstar.edu` | `admin123` | `ADM-001` | Full administrative control, Analytics, Member Management, Catalog, Circulation |
| **Library Staff** | Jordan Lee | `staff@northstar.edu` | `staff123` | `STF-001` | Loans desk, Book check-out & returns, Catalog management, Member overview |
| **Student** | Maya Patel | `maya@northstar.edu` | `student123` | `STU-2401` | Student workspace, My books, Seat reservation, Waitlist, AI Assistant, Audio Library |
| **Student** | Ethan Brooks | `ethan@northstar.edu` | `student123` | `STU-2402` | Student workspace, My books, Seat reservation, Waitlist, AI Assistant, Audio Library |
| **Student** | Sofia Chen | `sofia@northstar.edu` | `student123` | `STU-2403` | Student workspace, My books, Seat reservation, Waitlist, AI Assistant, Audio Library |

---

## 🚀 Quick Start

### 1. Requirements
- Python 3.10+ (tested on Python 3.13 and 3.15)
- pip

### 2. Setup Virtual Environment & Install Dependencies
```bash
python -m venv .venv
.\.venv\Scripts\activate      # Windows
# or: source .venv/bin/activate  # macOS / Linux

pip install -r requirements.txt pytest
```

### 3. Environment Variables (.env)
A `.env` file is included in the project root:
```ini
FLASK_SECRET_KEY=northstar-library-production-secure-key-32chars
DATABASE_PATH=library.db
SEED_DEMO_DATA=true
AI_PROVIDER=openai
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

### 4. Run the Application
```bash
python app.py
```
Open your browser and navigate to:
```
http://127.0.0.1:8080
```

### 5. Run the Test Suite
```bash
pytest -v
```

---

## 📚 Feature Overview

1. **Role-Based Authentication & Workspaces**:
   - Secure login for Admin, Staff, and Students with role-tailored dashboards and metric summaries.
2. **Catalog & Smart Search**:
   - Real-time catalog browsing with 20 curated titles across 12 categories.
   - Typographic and image-backed book covers with availability badges.
   - Smart search engine supporting typo tolerance (e.g. "Atmoic Habits" -> "Atomic Habits") and multi-token queries.
3. **Member Management**:
   - Add, edit, and deactivate/reactivate student member accounts.
   - Store and view student mobile numbers in member profiles.
   - View complete student borrowing and fine payment histories.
4. **Circulation & QR Codes**:
   - Issue books (7, 14, or 21 day loans) and check in returns.
   - Instant QR code generation for members (`/qr/member/<id>.png`) and books (`/qr/book/<id>.png`).
   - Integrated camera/ISBN scanner for quick code entry.
5. **Overdue Fine System**:
   - Overdue fine calculation at **Rs. 5 per day** overdue.
   - Transparent fine accrual display and fine payment settlement.
6. **Real-Time Analytics Dashboard**:
   - Live administrative charts powered by local Chart.js:
     - 14-day book issues and returns line chart.
     - Most popular catalog titles.
     - Daily active borrowers.
     - Overdue distribution breakdown.
     - Current study seat occupancy doughnut chart.
7. **Seat Reservation System**:
   - Interactive visual seat map for Quiet Study and Collaborative zones.
   - 2-hour session bookings up to 7 days in advance.
   - Automatic release of unconfirmed bookings after 15 minutes of session start.
8. **Digital Waiting Queue**:
   - Queue up for titles when all copies are checked out.
   - Automatic user notification when queued books are returned.
9. **Digital Book Locator**:
   - Floor, shelf (A–E), and rack (01–04) visual locator map.
10. **AI Assistant & Chatbot**:
    - Interactive library chatbot answering questions about borrowing rules, hours, seat bookings, and overdue fines (Rs. 5/day).
    - Rule-based fallback ensures 100% functionality even when no external AI API key is configured.
11. **Personalized Book Recommendations**:
    - Recommendations based on past borrowing history and student category preferences.
12. **Smart Book Scanner**:
    - HTML5 camera video stream for scanning ISBN barcodes and QR codes.
    - Quick actions to check out, return, or locate books.
13. **Audio Library with Text-to-Speech**:
    - Native browser speech synthesis (`window.speechSynthesis`) to listen to book summaries and excerpts.
    - Play, Pause, Resume, Stop, and playback speed controls (0.85x – 1.4x).
14. **Notification Bell**:
    - Topbar notification center with unread count badge.
    - Due date reminders and waitlist availability notices.
    - Click to mark as read or mark all read.
