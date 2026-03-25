# LMS SQLite Schema (lms_database)

This container stores the LMS data in `myapp.db`. The database is initialized (idempotently) by `init_db.py`.

## Core tables

### Metadata
- `app_info(key UNIQUE, value, created_at)`

### Users & Roles
- `users(email UNIQUE, username UNIQUE, full_name, password_hash, is_active, created_at, updated_at)`
- `roles(name UNIQUE, description)`
- `user_roles(user_id, role_id)` (PK: `user_id, role_id`)

### Courses & Lessons/Modules
- `courses(slug UNIQUE, title, description, level, is_published, created_by_user_id, created_at, updated_at)`
- `course_lessons(course_id, slug, title, content_type, content_text, video_url, resource_url, sort_order, estimated_minutes, is_published, created_at, updated_at)`
  - Unique: `(course_id, slug)`

### Enrollment
- `enrollments(user_id, course_id, status, enrolled_at, completed_at)`
  - Unique: `(user_id, course_id)`

### Progress
- `lesson_progress(user_id, course_id, lesson_id, status, progress_percent, started_at, completed_at, updated_at)`
  - Unique: `(user_id, lesson_id)`

## Optional quizzes
- `quizzes(course_id, lesson_id NULL, title, description, passing_score, is_published, created_at, updated_at)`
- `quiz_questions(quiz_id, prompt, question_type, sort_order, created_at)`
- `quiz_options(question_id, option_text, is_correct, sort_order)`
- `quiz_submissions(quiz_id, user_id, attempt, score_percent, passed, submitted_at)`
  - Unique: `(quiz_id, user_id, attempt)`
- `quiz_answers(submission_id, question_id, selected_option_id NULL, free_text_answer, is_correct)`

## Seed data (local dev)
`init_db.py` seeds the following (using `INSERT OR IGNORE`):
- Roles: `admin`, `instructor`, `student`
- Users:
  - `admin@example.com` / `admin`
  - `instructor@example.com` / `instructor`
  - `student@example.com` / `student`
- Courses:
  - `intro-to-lms`
  - `react-basics`
- Lessons across those courses
- Sample enrollment: `student@example.com` enrolled in `intro-to-lms`
- Sample progress: student completed `intro-to-lms/welcome`
- Sample quiz: `LMS Basics Quiz` attached to `intro-to-lms/quizzes` lesson

## How to inspect quickly
- Interactive python shell: `python db_shell.py`
- SQLite CLI (if installed): `sqlite3 myapp.db`
- Node viewer: `cd db_visualizer && npm install && npm start` (make sure `SQLITE_DB` is set via `source sqlite.env`)
