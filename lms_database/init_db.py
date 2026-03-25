#!/usr/bin/env python3
"""Initialize SQLite database for lms_database (LMS schema + seeds).

This script is designed to be **repeatable / idempotent**:
- Tables are created with `IF NOT EXISTS`
- Seed rows use `INSERT OR IGNORE` (or stable UNIQUE keys) to avoid duplication
- It maintains a lightweight `app_info` metadata table

The DB file is stored locally in this container directory (default: myapp.db).
"""

from __future__ import annotations

import os
import sqlite3
from typing import Iterable, Tuple

DB_NAME = "myapp.db"
DB_USER = "kaviasqlite"  # Not used for SQLite, but kept for consistency
DB_PASSWORD = "kaviadefaultpassword"  # Not used for SQLite, but kept for consistency
DB_PORT = "5000"  # Not used for SQLite, but kept for consistency


def _connect(db_path: str) -> sqlite3.Connection:
    """Create a SQLite connection with foreign keys enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Improve concurrency for local dev; safe defaults.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _exec_many(conn: sqlite3.Connection, statements: Iterable[str]) -> None:
    """Execute multiple SQL statements (each expected to be complete)."""
    cur = conn.cursor()
    for stmt in statements:
        cur.execute(stmt)
    conn.commit()


def _seed_many(
    conn: sqlite3.Connection,
    stmt: str,
    rows: Iterable[Tuple],
) -> None:
    """Execute an executemany seed statement and commit."""
    cur = conn.cursor()
    cur.executemany(stmt, list(rows))
    conn.commit()


def _upsert_app_info(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Upsert into app_info using a unique key."""
    conn.execute(
        "INSERT INTO app_info (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def _create_schema(conn: sqlite3.Connection) -> None:
    """Create LMS schema (tables, indexes).

    Notes:
    - We model roles as a separate table + mapping table for future flexibility.
    - We store password hashes for local dev/demo; production auth should be handled by backend auth flow.
    - Progress is tracked at lesson granularity via `lesson_progress`.
    - Quizzes are optional; schema supports quiz -> questions -> options + submissions/answers.
    """
    ddl = [
        # ---------------------------------------------------------------------
        # Metadata
        # ---------------------------------------------------------------------
        """
        CREATE TABLE IF NOT EXISTS app_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        # ---------------------------------------------------------------------
        # Users / Roles
        # ---------------------------------------------------------------------
        """
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,              -- admin | instructor | student
            description TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            username TEXT NOT NULL UNIQUE,
            full_name TEXT,
            password_hash TEXT,                     -- for local dev seed only
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS user_roles (
            user_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, role_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
        )
        """,
        # ---------------------------------------------------------------------
        # Courses / Lessons (Modules)
        # ---------------------------------------------------------------------
        """
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,              -- stable key for seed + URLs
            title TEXT NOT NULL,
            description TEXT,
            level TEXT,                             -- beginner|intermediate|advanced (optional)
            is_published INTEGER NOT NULL DEFAULT 1,
            created_by_user_id INTEGER,             -- instructor owner
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS course_lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            slug TEXT NOT NULL,                     -- unique per course
            title TEXT NOT NULL,
            content_type TEXT NOT NULL DEFAULT 'text', -- text|video|link
            content_text TEXT,
            video_url TEXT,
            resource_url TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            estimated_minutes INTEGER,
            is_published INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(course_id, slug),
            FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
        )
        """,
        # ---------------------------------------------------------------------
        # Enrollments
        # ---------------------------------------------------------------------
        """
        CREATE TABLE IF NOT EXISTS enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'enrolled', -- enrolled|completed|dropped
            enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            UNIQUE(user_id, course_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
        )
        """,
        # ---------------------------------------------------------------------
        # Progress / Completions
        # ---------------------------------------------------------------------
        """
        CREATE TABLE IF NOT EXISTS lesson_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            lesson_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'not_started', -- not_started|in_progress|completed
            progress_percent INTEGER NOT NULL DEFAULT 0, -- 0..100
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, lesson_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE,
            FOREIGN KEY (lesson_id) REFERENCES course_lessons(id) ON DELETE CASCADE
        )
        """,
        # ---------------------------------------------------------------------
        # Optional quizzes
        # ---------------------------------------------------------------------
        """
        CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            lesson_id INTEGER,                        -- quiz can be attached to lesson (optional)
            title TEXT NOT NULL,
            description TEXT,
            passing_score INTEGER NOT NULL DEFAULT 70, -- percent
            is_published INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE,
            FOREIGN KEY (lesson_id) REFERENCES course_lessons(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS quiz_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER NOT NULL,
            prompt TEXT NOT NULL,
            question_type TEXT NOT NULL DEFAULT 'single_choice', -- single_choice|multiple_choice|free_text
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS quiz_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            option_text TEXT NOT NULL,
            is_correct INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (question_id) REFERENCES quiz_questions(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS quiz_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 1,
            score_percent INTEGER,
            passed INTEGER,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(quiz_id, user_id, attempt),
            FOREIGN KEY (quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS quiz_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            selected_option_id INTEGER,  -- for choice questions
            free_text_answer TEXT,       -- for free-text
            is_correct INTEGER,
            FOREIGN KEY (submission_id) REFERENCES quiz_submissions(id) ON DELETE CASCADE,
            FOREIGN KEY (question_id) REFERENCES quiz_questions(id) ON DELETE CASCADE,
            FOREIGN KEY (selected_option_id) REFERENCES quiz_options(id) ON DELETE SET NULL
        )
        """,
        # ---------------------------------------------------------------------
        # Helpful indexes
        # ---------------------------------------------------------------------
        "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
        "CREATE INDEX IF NOT EXISTS idx_courses_created_by ON courses(created_by_user_id)",
        "CREATE INDEX IF NOT EXISTS idx_lessons_course ON course_lessons(course_id, sort_order)",
        "CREATE INDEX IF NOT EXISTS idx_enrollments_user ON enrollments(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_enrollments_course ON enrollments(course_id)",
        "CREATE INDEX IF NOT EXISTS idx_progress_user_course ON lesson_progress(user_id, course_id)",
        "CREATE INDEX IF NOT EXISTS idx_quizzes_course ON quizzes(course_id)",
    ]
    _exec_many(conn, ddl)


def _seed_data(conn: sqlite3.Connection) -> None:
    """Seed local-development data (roles, users, demo courses/lessons, sample enrollments)."""
    # Roles (stable by UNIQUE(name))
    _seed_many(
        conn,
        "INSERT OR IGNORE INTO roles (name, description) VALUES (?, ?)",
        [
            ("admin", "Platform administrator"),
            ("instructor", "Course instructor/author"),
            ("student", "Learner/student"),
        ],
    )

    # Users (stable by UNIQUE(email) + UNIQUE(username))
    # NOTE: password_hash values are placeholders for local dev only.
    _seed_many(
        conn,
        "INSERT OR IGNORE INTO users (email, username, full_name, password_hash, is_active) VALUES (?, ?, ?, ?, ?)",
        [
            ("admin@example.com", "admin", "Admin User", "dev_hash_admin", 1),
            ("instructor@example.com", "instructor", "Instructor User", "dev_hash_instructor", 1),
            ("student@example.com", "student", "Student User", "dev_hash_student", 1),
        ],
    )

    # Assign roles using INSERT OR IGNORE and lookups by unique keys.
    conn.execute(
        """
        INSERT OR IGNORE INTO user_roles (user_id, role_id)
        SELECT u.id, r.id
        FROM users u, roles r
        WHERE u.email = ? AND r.name = ?
        """,
        ("admin@example.com", "admin"),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO user_roles (user_id, role_id)
        SELECT u.id, r.id
        FROM users u, roles r
        WHERE u.email = ? AND r.name = ?
        """,
        ("instructor@example.com", "instructor"),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO user_roles (user_id, role_id)
        SELECT u.id, r.id
        FROM users u, roles r
        WHERE u.email = ? AND r.name = ?
        """,
        ("student@example.com", "student"),
    )
    conn.commit()

    # Demo courses (stable by UNIQUE(slug))
    # created_by_user_id resolved via instructor user
    conn.execute(
        """
        INSERT OR IGNORE INTO courses (slug, title, description, level, is_published, created_by_user_id)
        SELECT
            ?, ?, ?, ?, ?,
            (SELECT id FROM users WHERE email = ?)
        """,
        (
            "intro-to-lms",
            "Intro to the LMS",
            "Learn how to navigate courses, lessons, and track your progress.",
            "beginner",
            1,
            "instructor@example.com",
        ),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO courses (slug, title, description, level, is_published, created_by_user_id)
        SELECT
            ?, ?, ?, ?, ?,
            (SELECT id FROM users WHERE email = ?)
        """,
        (
            "react-basics",
            "React Basics",
            "A quick start guide to components, state, and effects.",
            "beginner",
            1,
            "instructor@example.com",
        ),
    )
    conn.commit()

    # Demo lessons (stable by UNIQUE(course_id, slug))
    # Course IDs resolved via slug
    lesson_rows = [
        # intro-to-lms
        (
            "intro-to-lms",
            "welcome",
            "Welcome",
            "text",
            "Welcome to the LMS demo. Use the catalog to explore courses and start learning.",
            None,
            None,
            1,
            3,
            1,
        ),
        (
            "intro-to-lms",
            "enrollment",
            "Enrollment & Progress",
            "text",
            "Enroll in a course to start tracking lesson completion. Mark lessons complete as you go.",
            None,
            None,
            2,
            5,
            1,
        ),
        (
            "intro-to-lms",
            "quizzes",
            "Quizzes (Optional)",
            "text",
            "Some lessons may include quizzes. Submit answers and view your score.",
            None,
            None,
            3,
            4,
            1,
        ),
        # react-basics
        (
            "react-basics",
            "components",
            "Components",
            "text",
            "Components are reusable UI building blocks. Learn function components and props.",
            None,
            None,
            1,
            8,
            1,
        ),
        (
            "react-basics",
            "state-and-effects",
            "State & Effects",
            "text",
            "State lets your UI change over time. Effects run side-effects like data fetching.",
            None,
            None,
            2,
            10,
            1,
        ),
        (
            "react-basics",
            "resources",
            "Resources",
            "link",
            None,
            None,
            "https://react.dev/learn",
            3,
            2,
            1,
        ),
    ]

    for (
        course_slug,
        lesson_slug,
        title,
        content_type,
        content_text,
        video_url,
        resource_url,
        sort_order,
        estimated_minutes,
        is_published,
    ) in lesson_rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO course_lessons (
                course_id, slug, title, content_type, content_text, video_url, resource_url,
                sort_order, estimated_minutes, is_published
            )
            VALUES (
                (SELECT id FROM courses WHERE slug = ?),
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                course_slug,
                lesson_slug,
                title,
                content_type,
                content_text,
                video_url,
                resource_url,
                sort_order,
                estimated_minutes,
                is_published,
            ),
        )
    conn.commit()

    # Seed a sample enrollment for the student into intro-to-lms
    conn.execute(
        """
        INSERT OR IGNORE INTO enrollments (user_id, course_id, status)
        VALUES (
            (SELECT id FROM users WHERE email = ?),
            (SELECT id FROM courses WHERE slug = ?),
            ?
        )
        """,
        ("student@example.com", "intro-to-lms", "enrolled"),
    )
    conn.commit()

    # Seed sample progress: student completed "welcome" lesson
    conn.execute(
        """
        INSERT OR IGNORE INTO lesson_progress (
            user_id, course_id, lesson_id, status, progress_percent, started_at, completed_at
        )
        VALUES (
            (SELECT id FROM users WHERE email = ?),
            (SELECT id FROM courses WHERE slug = ?),
            (
                SELECT l.id
                FROM course_lessons l
                JOIN courses c ON c.id = l.course_id
                WHERE c.slug = ? AND l.slug = ?
            ),
            ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        """,
        ("student@example.com", "intro-to-lms", "intro-to-lms", "welcome", "completed", 100),
    )
    conn.commit()

    # Optional: seed a simple quiz on intro-to-lms "quizzes" lesson
    conn.execute(
        """
        INSERT OR IGNORE INTO quizzes (course_id, lesson_id, title, description, passing_score, is_published)
        VALUES (
            (SELECT id FROM courses WHERE slug = ?),
            (
                SELECT l.id
                FROM course_lessons l
                JOIN courses c ON c.id = l.course_id
                WHERE c.slug = ? AND l.slug = ?
            ),
            ?, ?, ?, ?
        )
        """,
        (
            "intro-to-lms",
            "intro-to-lms",
            "quizzes",
            "LMS Basics Quiz",
            "A quick check to ensure you understand enrollments and progress.",
            70,
            1,
        ),
    )
    conn.commit()

    # Add one question + options if quiz exists (guarded via INSERT OR IGNORE with SELECT)
    conn.execute(
        """
        INSERT OR IGNORE INTO quiz_questions (quiz_id, prompt, question_type, sort_order)
        SELECT q.id, ?, 'single_choice', 1
        FROM quizzes q
        JOIN courses c ON c.id = q.course_id
        WHERE c.slug = ? AND q.title = ?
        """,
        ("What action starts progress tracking for a course?", "intro-to-lms", "LMS Basics Quiz"),
    )
    conn.commit()

    # Options (attach to the question we just inserted)
    conn.execute(
        """
        INSERT OR IGNORE INTO quiz_options (question_id, option_text, is_correct, sort_order)
        SELECT qq.id, ?, ?, ?
        FROM quiz_questions qq
        JOIN quizzes q ON q.id = qq.quiz_id
        JOIN courses c ON c.id = q.course_id
        WHERE c.slug = ? AND q.title = ? AND qq.sort_order = 1
        """,
        ("Enrolling in the course", 1, 1, "intro-to-lms", "LMS Basics Quiz"),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO quiz_options (question_id, option_text, is_correct, sort_order)
        SELECT qq.id, ?, ?, ?
        FROM quiz_questions qq
        JOIN quizzes q ON q.id = qq.quiz_id
        JOIN courses c ON c.id = q.course_id
        WHERE c.slug = ? AND q.title = ? AND qq.sort_order = 1
        """,
        ("Viewing the course catalog", 0, 2, "intro-to-lms", "LMS Basics Quiz"),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO quiz_options (question_id, option_text, is_correct, sort_order)
        SELECT qq.id, ?, ?, ?
        FROM quiz_questions qq
        JOIN quizzes q ON q.id = qq.quiz_id
        JOIN courses c ON c.id = q.course_id
        WHERE c.slug = ? AND q.title = ? AND qq.sort_order = 1
        """,
        ("Logging out and back in", 0, 3, "intro-to-lms", "LMS Basics Quiz"),
    )
    conn.commit()


def _write_connection_files(db_path: str) -> None:
    """Write db_connection.txt and db_visualizer/sqlite.env (repeatable)."""
    current_dir = os.getcwd()
    connection_string = f"sqlite:///{current_dir}/{DB_NAME}"

    try:
        with open("db_connection.txt", "w", encoding="utf-8") as f:
            f.write("# SQLite connection methods:\n")
            f.write(f"# Python: sqlite3.connect('{DB_NAME}')\n")
            f.write(f"# Connection string: {connection_string}\n")
            f.write(f"# File path: {current_dir}/{DB_NAME}\n")
        print("Connection information saved to db_connection.txt")
    except Exception as e:
        print(f"Warning: Could not save connection info: {e}")

    # Ensure db_visualizer directory exists
    if not os.path.exists("db_visualizer"):
        os.makedirs("db_visualizer", exist_ok=True)
        print("Created db_visualizer directory")

    try:
        with open("db_visualizer/sqlite.env", "w", encoding="utf-8") as f:
            f.write(f'export SQLITE_DB="{db_path}"\n')
        print("Environment variables saved to db_visualizer/sqlite.env")
    except Exception as e:
        print(f"Warning: Could not save environment variables: {e}")


def main() -> None:
    """Main entrypoint: create schema + seed data.

    Returns: None. Exits with success unless an exception is raised.
    """
    print("Starting SQLite setup...")

    db_exists = os.path.exists(DB_NAME)
    if db_exists:
        print(f"SQLite database already exists at {DB_NAME}")
        try:
            conn_test = sqlite3.connect(DB_NAME)
            conn_test.execute("SELECT 1")
            conn_test.close()
            print("Database is accessible and working.")
        except Exception as e:
            print(f"Warning: Database exists but may be corrupted: {e}")
    else:
        print("Creating new SQLite database...")

    db_path = os.path.abspath(DB_NAME)
    conn = _connect(DB_NAME)
    try:
        _create_schema(conn)

        # App metadata
        _upsert_app_info(conn, "project_name", "lms_database")
        _upsert_app_info(conn, "version", "1.0.0")
        _upsert_app_info(conn, "description", "Simple LMS schema (users/roles/courses/lessons/enrollments/progress/quizzes)")

        _seed_data(conn)

        # Stats
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        table_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM users")
        user_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM courses")
        course_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM course_lessons")
        lesson_count = cur.fetchone()[0]
    finally:
        conn.close()

    _write_connection_files(db_path)

    print("\nSQLite setup complete!")
    print(f"Database: {DB_NAME}")
    print(f"Location: {os.getcwd()}/{DB_NAME}")
    print("")
    print("To use with Node.js viewer, run: source db_visualizer/sqlite.env")
    print("")
    print("Database statistics:")
    print(f"  Tables: {table_count}")
    print(f"  Users: {user_count}")
    print(f"  Courses: {course_count}")
    print(f"  Lessons: {lesson_count}")

    # If sqlite3 CLI is available, show how to use it
    try:
        import subprocess

        result = subprocess.run(["which", "sqlite3"], capture_output=True, text=True)
        if result.returncode == 0:
            print("")
            print("SQLite CLI is available. You can also use:")
            print(f"  sqlite3 {DB_NAME}")
    except Exception:
        pass

    print("\nScript completed successfully.")


if __name__ == "__main__":
    main()
