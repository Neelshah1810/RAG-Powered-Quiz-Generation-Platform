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

## Deploying to Railway

Run the backend and frontend as two services.

- **Backend**: root `backend`, start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Set the same variables as `backend/.env`, plus `FRONTEND_URL=https://<frontend>.up.railway.app` (any `*.up.railway.app` origin is already allowed by CORS; add custom domains to `EXTRA_CORS_ORIGINS`).
- **Frontend**: root `frontend`, build `npm run build`, start `npm run preview` (binds `0.0.0.0:$PORT`). Set `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` and `VITE_API_URL=https://<backend>.up.railway.app` (`/api` is appended automatically). These are baked in at build time, so **redeploy the frontend after changing them**.

If `VITE_API_URL` is missing or wrong, API calls hit the frontend itself and get `index.html` back; the app now rejects that and logs `Expected JSON ... but got HTML` in the browser console.

## Chat (Teams/WhatsApp-style)

Sidebar → **Chat**, for every role.

| | Admin | Teacher | Student |
|---|---|---|---|
| Create groups | ✅ | ✅ | ❌ |
| Find/add people | everyone | only people enrolled in courses of the semester(s) they teach | ❌ (sees only groups they were added to) |
| Send text/files/polls | ✅ | ✅ | only in groups set to **Everyone can send** |
| React with emoji, vote in polls | ✅ | ✅ | ✅ |
| Mark message important, change settings, add/remove members | group admins (teachers/admins in the group) | | |
| Delete message | own + any (group admin) | own + any (group admin) | own |

Each group has a **"Who can send messages"** setting: *Teachers/admins only* (announcement channel) or *Everyone can send* (discussion group). It can be changed any time from Group info.

Features: text with links, images/videos/files (up to `MAX_UPLOAD_MB`, stored in the private `chat-media` bucket and served by signed URLs), polls (single/multiple choice, close poll), WhatsApp-style reactions, *Important* messages, unread badges, typing indicator, toasts for new messages.

**Real-time:** the backend exposes a WebSocket at `/api/chat/ws` (the token is sent in the first frame, not the URL). Writes go through REST and are then pushed to every member's open sockets. Railway supports WebSockets with no extra configuration. The frontend derives `wss://…` from `VITE_API_URL` and pings every 25 s, reconnects with backoff, and refetches after reconnecting, so nothing is lost if a connection drops.

> Run the backend as **one replica / one uvicorn worker** (the Railway default). Connections are tracked in memory; with several replicas, messages still arrive but only after a refresh/reconnect.

**Database:** `supabase/migrations/006_chat.sql` (tables `chat_groups`, `chat_members`, `chat_messages`, `chat_reactions`, `chat_poll_votes`, function `chat_group_summaries`, bucket `chat-media`). Apply with `python -m scripts.migrate --force 006_chat.sql`.

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

## Student Quiz Generation API

### `POST /api/rag/quiz/generate`

A simplified endpoint for student quiz generation. It accepts a minimal payload and internally routes through the full RAG pipeline with `mode=quiz_generation` and `style_aware=False`, ensuring PYQ content is never exposed to students (PRD §14).

**Request body:**

```json
{
  "course_id": "uuid",
  "topic_tags": ["sorting", "trees"],
  "question_count": 5,
  "difficulty": "medium",
  "question_types": ["mcq", "short_answer"],
  "prompt": "optional free-text steer"
}
```

| Field | Type | Default | Notes |
|---|---|---|---|
| `course_id` | `string` | *required* | UUID of the course |
| `topic_tags` | `string[]` | `[]` | Optional topic filters |
| `question_count` | `int` | `5` | 1–50 |
| `difficulty` | `string` | `"medium"` | `easy`, `medium`, or `hard` |
| `question_types` | `string[]` | `["mcq","short_answer"]` | `mcq`, `short_answer`, `long_answer`, `true_false`, `fill_blank` |
| `prompt` | `string?` | `null` | Free-text guidance for the LLM |

**Response:** Same `GeneratedSetResponse` as `/api/rag/generate`.

> For **style-aware exam prep** (student wants questions styled like past papers), use the original `/api/rag/generate` with `style_aware=true` and `exam_type` set.

### `POST /api/rag/mindmap/generate`

Generates an interactive, drill-down mind map from a single indexed document. Uses Groq's strict JSON schema mode to guarantee a recursive tree structure matching `MindmapNode`.

**Request body:**

```json
{
  "material_id": "uuid",
  "topic": "optional specific concept",
  "max_depth": 4,
  "max_children_per_node": 6
}
```

| Field | Type | Default | Notes |
|---|---|---|---|
| `material_id` | `string` | *required* | UUID of a `content_documents` row with `status='indexed'` |
| `topic` | `string?` | `null` | Optional focus area |
| `max_depth` | `int` | `4` | 1–5. Deepest recursion allowed |
| `max_children_per_node` | `int` | `6` | 1–10. Breadth limit |

**Response:** A JSON object representing the saved `mindmaps` row (optional persistence), including the generated `tree` of `MindmapNode`s.

#### How to test

1. Log in and navigate to the RAG Chat / Quiz Generation page.
2. Ensure you have a course selected and at least one document uploaded in Classwork and marked as indexed.
3. Type "generate a mind map" or click the suggestion chip. (Smart intent routing intercepts this and opens the document picker).
4. Select a document from the dropdown and optionally provide a topic.
5. Click **Generate Mind Map**.
6. **Interactive Navigation:** Click on any child node with a chevron to drill down. Use the breadcrumb bar or the back button to navigate back up.
7. **Fullscreen Mode:** Click the Expand icon (↗) in the mind map header to view deeply nested, expanded trees in a responsive grid overlay.

### `GET /api/rag/mindmap/{id}`

Fetches a previously saved mind map by its UUID. The user must be the original creator of the mind map.

**Response:** The `MindmapResponse` object containing the `tree`.
