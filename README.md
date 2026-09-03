# Academix AI — RAG-Powered Quiz Generation Platform

A single-institute academic platform with three roles (Admin, Teacher, Student) centered on a **Retrieval-Augmented Generation (RAG) Quiz Generation Engine**.

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React + Vite + TypeScript + TailwindCSS |
| Backend | FastAPI (Python) |
| Database | Supabase PostgreSQL + pgvector |
| Auth | Supabase Auth (JWT) |
| Storage | Supabase Storage |
| LLM | Groq API (`openai/gpt-oss-120b`) |
| Embeddings | sentence-transformers (local) or hash fallback |

## Prerequisites

- **Python 3.11+** — [Download](https://python.org)
- **Node.js 20+** — [Download](https://nodejs.org)
- **Supabase project** with credentials in `backend/.env` and `frontend/.env`
- **Groq API Key** — [console.groq.com](https://console.groq.com)
- **Windows only:** for high-quality local embeddings, install [MSVC VC++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe). Until then the app uses `EMBEDDING_PROVIDER=hash` (works, lower retrieval quality).

Redis and Celery are **not** required for this setup — ingestion and generation run in-process.

## One-time setup

### 1. Database

```bash
cd backend
python -m venv venv
# Windows:
venv\Scripts\activate
pip install -r requirements.txt

# Apply schema (needs DATABASE_URL in .env — Session pooler, port 5432)
python -m scripts.migrate
python seed_data.py
```

Or paste `supabase/migrations/001_schema.sql` into the Supabase SQL Editor.

Storage buckets (already created on the pilot project): `course-materials`, `pyq-papers`, `submissions`, `avatars`.

### 2. Environment

Copy and fill:

- `backend/.env` — from `backend/.env.example` (Supabase + Groq + `DATABASE_URL`)
- `frontend/.env` — from `frontend/.env.example`

Generation model on this Groq key: `openai/gpt-oss-120b` (verify with `openai/gpt-oss-20b`).

### 3. Frontend

```bash
cd frontend
npm install
```

## Run (two terminals)

**Terminal 1 — Backend**

```bash
cd backend
venv\Scripts\activate
# Prefer python -m on Windows if uvicorn.exe is blocked by antivirus:
python -m uvicorn app.main:app --reload --port 8000
```

API: http://localhost:8000  
Docs: http://localhost:8000/docs

**Terminal 2 — Frontend**

```bash
cd frontend
npm run dev
```

App: http://localhost:5173

## Demo accounts

Password for all: `password123`

| Role | Email |
|---|---|
| Admin | `admin@academix.ai` |
| Teacher | `teacher@academix.ai` |
| Student | `student@academix.ai` |

## How to test

1. **Login** as each role — sidebar nav should match PRD §5.
2. **Admin** → Manage Users / Manage Courses → enroll teacher + student on a course.
3. **Teacher** → Classroom → open course → Classwork → Upload Material (notes PDF/TXT). Wait until status shows `indexed`.
4. **Teacher** → Paper Style → generate an Internal/External draft → edit → Approve.
5. **Student** → Quiz Generation → same course → generate quiz → answer → Submit (sources panel should show citations).
6. **Teacher** → create Assignment → **Student** opens it → Turn in → **Teacher** grades.
7. **Scheduler** / **Notice Board** — create events and course notices (teachers must pick a course).

## Project structure

```
├── backend/                    # FastAPI
│   ├── app/
│   │   ├── main.py
│   │   ├── routers/            # auth, users, courses, classroom, scheduler, notices, rag
│   │   ├── services/           # business logic + rag/
│   │   └── models/
│   ├── scripts/migrate.py      # applies supabase/migrations
│   └── seed_data.py
├── frontend/                   # React + Vite
├── supabase/migrations/        # 001_schema.sql
└── PRD_RAG_Quiz_Engine.md
```

## Features

- Auth/RBAC for Admin, Teacher, Student
- Classroom (Stream, Materials + RAG ingest, Assignments, Submissions, Grading)
- Quiz Generation (Student) and Paper Style (Teacher) on one RAG engine
- Scheduler and Notice Board with role-based isolation
- Admin user/course management
