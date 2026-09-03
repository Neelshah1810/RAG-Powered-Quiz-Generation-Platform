"""
Academix AI — end-to-end API test.

Exercises every PRD Phase-1 flow against a running backend and a real Supabase
project, then cleans up after itself.

    python -m tests.e2e_test                 # full run
    python -m tests.e2e_test --skip-llm      # skip generation (no Groq calls)
    python -m tests.e2e_test --keep          # leave fixtures behind to inspect

It creates its own throwaway course and users (prefixed `e2e-`), so it never
touches the pilot data already in the project.
"""

from __future__ import annotations

import argparse
import io
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import requests

BASE = "http://127.0.0.1:8000/api"
TIMEOUT = 180

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


# ── Reporting ────────────────────────────────────────────────────────────────

class Report:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self.skipped: list[tuple[str, str]] = []

    def ok(self, name: str, detail: str = "") -> None:
        self.passed.append(name)
        print(f"  [PASS] {name}" + (f" — {detail}" if detail else ""))

    def fail(self, name: str, detail: str) -> None:
        self.failed.append((name, detail))
        print(f"  [FAIL] {name}\n         {detail}")

    def skip(self, name: str, why: str) -> None:
        self.skipped.append((name, why))
        print(f"  [SKIP] {name} — {why}")

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            self.ok(name, detail)
        else:
            self.fail(name, detail or "condition was false")
        return condition

    def summary(self) -> int:
        print("\n" + "=" * 74)
        print(f"PASSED {len(self.passed)}   FAILED {len(self.failed)}   SKIPPED {len(self.skipped)}")
        if self.failed:
            print("\nFailures:")
            for name, detail in self.failed:
                print(f"  - {name}: {detail}")
        print("=" * 74)
        return 1 if self.failed else 0


R = Report()


# ── HTTP helpers ─────────────────────────────────────────────────────────────

class Client:
    def __init__(self, label: str) -> None:
        self.label = label
        self.token: Optional[str] = None
        self.user: dict = {}

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", TIMEOUT)
        headers = dict(self.headers)
        headers.update(kwargs.pop("headers", {}))
        return requests.request(method, f"{BASE}{path}", headers=headers, **kwargs)

    def get(self, path: str, **kw) -> requests.Response:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw) -> requests.Response:
        return self.request("POST", path, **kw)

    def patch(self, path: str, **kw) -> requests.Response:
        return self.request("PATCH", path, **kw)

    def delete(self, path: str, **kw) -> requests.Response:
        return self.request("DELETE", path, **kw)

    def login(self, email: str, password: str) -> bool:
        response = requests.post(
            f"{BASE}/auth/login",
            json={"email": email, "password": password},
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            return False
        payload = response.json()
        self.token = payload["access_token"]
        self.user = payload["user"]
        return True


def detail_of(response: requests.Response) -> str:
    try:
        body = response.json()
    except Exception:
        return f"HTTP {response.status_code} {response.text[:200]}"
    if isinstance(body, dict) and "detail" in body:
        return f"HTTP {response.status_code}: {body['detail']}"
    return f"HTTP {response.status_code}: {str(body)[:200]}"


# ── Fixtures ─────────────────────────────────────────────────────────────────

# Fixture accounts use the real institute domain: `email-validator` refuses
# reserved TLDs like .test/.invalid/.localhost, so a throwaway domain would
# fail schema validation before the API is ever reached.
SUFFIX = uuid.uuid4().hex[:6]
TEACHER_EMAIL = f"e2e-teacher-{SUFFIX}@academix.ai"
STUDENT_EMAIL = f"e2e-student-{SUFFIX}@academix.ai"
OUTSIDER_EMAIL = f"e2e-outsider-{SUFFIX}@academix.ai"
PASSWORD = "E2eTest!2026"

# Deliberately factual, self-contained content so grounded generation and the
# faithfulness check have something unambiguous to work with.
NOTES = """[Page 1]
Unit 3: Process Scheduling in Operating Systems

A process scheduler decides which process in the ready queue runs next on the
CPU. Academix OS defines three distinct scheduler levels: the long-term
scheduler admits jobs into the system, the short-term scheduler selects which
ready process runs next, and the medium-term scheduler swaps processes out of
main memory.

The short-term scheduler is invoked most frequently, roughly every 100
milliseconds in the Academix reference implementation.

[Page 2]
First-Come First-Served (FCFS) scheduling runs processes strictly in arrival
order. FCFS is non-preemptive. Its principal weakness is the convoy effect, in
which a single long-running process forces many short processes to wait,
inflating the average waiting time.

Shortest Job First (SJF) scheduling selects the process with the smallest next
CPU burst. SJF is provably optimal for minimising average waiting time, but it
requires knowing the length of the next CPU burst in advance, which is not
available in practice and must be estimated.

[Page 3]
Round Robin (RR) scheduling assigns each process a fixed time quantum. The
Academix reference implementation uses a default quantum of 20 milliseconds.
If the quantum is set too large, Round Robin degenerates into FCFS. If it is
set too small, the overhead of context switching dominates useful work.

Priority scheduling can cause starvation, in which a low-priority process
never runs. The standard remedy is aging, which gradually raises the priority
of a process the longer it waits in the ready queue.
"""

PYQ = """[Page 1]
ACADEMIX INSTITUTE OF TECHNOLOGY
Internal Examination - Operating Systems
Time: 90 Minutes                                        Maximum Marks: 40

SECTION A - Answer ALL questions.                                (5 x 2 = 10)

Q1. Define the term "time quantum" in Round Robin scheduling.        [2]
Q2. State the convoy effect.                                          [2]
Q3. List the three levels of process scheduler.                       [2]
Q4. Define starvation in the context of priority scheduling.          [2]
Q5. State the default time quantum used by the reference kernel.      [2]

SECTION B - Answer ANY THREE questions.                          (3 x 5 = 15)

Q6. Explain the working of First-Come First-Served scheduling and
    describe its principal weakness.                                  [5]
Q7. Compare Shortest Job First scheduling with Round Robin
    scheduling in terms of average waiting time.                      [5]
Q8. Describe how aging prevents starvation in priority scheduling.    [5]
Q9. Explain what happens to Round Robin when the time quantum is
    set too large, and when it is set too small.                      [5]

SECTION C - Answer ANY ONE question.                             (1 x 15 = 15)

Q10. Analyse why Shortest Job First is provably optimal for average
     waiting time, and justify why it cannot be implemented directly
     in a real operating system.                                     [15]
Q11. Design a scheduling policy for an interactive system, evaluate
     the trade-offs of your chosen quantum, and justify your design
     against the alternatives discussed in the course.                [15]
"""


def wait_for_ingestion(
    client: Client, course_id: str, document_id: str, timeout: int = 150
) -> dict:
    """Poll a document until ingestion settles."""
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        response = client.get(f"/rag/documents/{course_id}")
        if response.status_code == 200:
            for document in response.json():
                if document["id"] == document_id:
                    last = document
                    if document["status"] in ("indexed", "failed"):
                        return document
        time.sleep(3)
    return last


# ── Test phases ──────────────────────────────────────────────────────────────

def phase_health() -> bool:
    print("\n=== 1. Health & availability ===")
    try:
        response = requests.get(f"{BASE}/health", timeout=10)
    except Exception as exc:
        R.fail("backend reachable", str(exc))
        return False
    return R.check(
        "backend reachable", response.status_code == 200, detail_of(response)
    )


def phase_auth(admin_email: str, admin_password: str) -> Optional[Client]:
    print("\n=== 2. Authentication & RBAC ===")

    admin = Client("admin")
    if not admin.login(admin_email, admin_password):
        R.fail(
            "admin login",
            f"could not sign in as {admin_email}. Pass --admin-email/"
            f"--admin-password if the seeded credentials differ.",
        )
        return None
    R.ok("admin login", f"{admin.user['full_name']} ({admin.user['role']})")

    R.check("admin role is admin", admin.user["role"] == "admin", admin.user["role"])

    # Unauthenticated access must be refused.
    anon = requests.get(f"{BASE}/courses/", timeout=TIMEOUT)
    R.check(
        "unauthenticated request rejected",
        anon.status_code in (401, 403),
        detail_of(anon),
    )

    # A garbage token must not be accepted.
    bad = requests.get(
        f"{BASE}/courses/", headers={"Authorization": "Bearer not-a-jwt"}, timeout=TIMEOUT
    )
    R.check("forged token rejected", bad.status_code == 401, detail_of(bad))

    me = admin.get("/auth/me")
    R.check("GET /auth/me", me.status_code == 200, detail_of(me))

    return admin


def phase_provision(admin: Client) -> dict:
    print("\n=== 3. Provisioning (admin) ===")
    created: dict[str, Any] = {"users": [], "course_id": None}

    for label, email, role in (
        ("teacher", TEACHER_EMAIL, "teacher"),
        ("student", STUDENT_EMAIL, "student"),
        ("outsider", OUTSIDER_EMAIL, "student"),
    ):
        response = admin.post(
            "/auth/signup",
            json={
                "email": email,
                "password": PASSWORD,
                "full_name": f"E2E {label.title()} {SUFFIX}",
                "role": role,
                "department": "Computer Science",
            },
        )
        if response.status_code in (200, 201):
            created["users"].append(response.json())
            R.ok(f"create {label} account", email)
        else:
            R.fail(f"create {label} account", detail_of(response))

    # Duplicate email must be refused.
    duplicate = admin.post(
        "/auth/signup",
        json={
            "email": TEACHER_EMAIL,
            "password": PASSWORD,
            "full_name": "Duplicate",
            "role": "teacher",
        },
    )
    R.check("duplicate email rejected", duplicate.status_code == 409, detail_of(duplicate))

    # Short password must be refused.
    weak = admin.post(
        "/auth/signup",
        json={
            "email": f"e2e-weak-{SUFFIX}@academix.ai",
            "password": "123",
            "full_name": "Weak",
            "role": "student",
        },
    )
    R.check("weak password rejected", weak.status_code in (400, 422), detail_of(weak))

    course = admin.post(
        "/courses/",
        json={
            "name": f"E2E Operating Systems {SUFFIX}",
            "code": f"E2E{SUFFIX.upper()}",
            "semester": 5,
            "department_name": "Computer Science",
            "description": "Throwaway course created by the end-to-end test.",
        },
    )
    if course.status_code in (200, 201):
        created["course_id"] = course.json()["id"]
        R.ok("create course", course.json()["code"])
    else:
        R.fail("create course", detail_of(course))
        return created

    duplicate_course = admin.post(
        "/courses/",
        json={"name": "Clash", "code": f"E2E{SUFFIX.upper()}", "semester": 5},
    )
    R.check(
        "duplicate course code rejected",
        duplicate_course.status_code == 409,
        detail_of(duplicate_course),
    )

    by_email = {u["email"]: u["id"] for u in created["users"]}
    course_id = created["course_id"]

    for email, role in ((TEACHER_EMAIL, "teacher"), (STUDENT_EMAIL, "student")):
        if email not in by_email:
            continue
        response = admin.post(
            f"/courses/{course_id}/enroll",
            json={"user_id": by_email[email], "role": role},
        )
        R.check(f"enroll {role}", response.status_code in (200, 201), detail_of(response))

    # A student account must not be enrollable as a course teacher (PRD §14).
    if STUDENT_EMAIL in by_email:
        bad_role = admin.post(
            f"/courses/{course_id}/enroll",
            json={"user_id": by_email[STUDENT_EMAIL], "role": "teacher"},
        )
        R.check(
            "student cannot be enrolled as teacher",
            bad_role.status_code in (400, 409),
            detail_of(bad_role),
        )

    # Double enrollment must be refused.
    if TEACHER_EMAIL in by_email:
        again = admin.post(
            f"/courses/{course_id}/enroll",
            json={"user_id": by_email[TEACHER_EMAIL], "role": "teacher"},
        )
        R.check("duplicate enrollment rejected", again.status_code == 409, detail_of(again))

    roster = admin.get(f"/courses/{course_id}/enrollments")
    if roster.status_code == 200:
        R.ok("People roster", f"{len(roster.json())} member(s)")
    else:
        R.fail("People roster", detail_of(roster))

    created["user_ids"] = by_email
    return created


def phase_isolation(course_id: str, teacher: Client, student: Client, outsider: Client) -> None:
    print("\n=== 4. Data isolation (PRD §14) ===")

    visible = student.get("/courses/")
    if visible.status_code == 200:
        ids = {c["id"] for c in visible.json()}
        R.check("enrolled student sees the course", course_id in ids)
    else:
        R.fail("student course list", detail_of(visible))

    unenrolled = outsider.get("/courses/")
    if unenrolled.status_code == 200:
        ids = {c["id"] for c in unenrolled.json()}
        R.check("non-member does NOT see the course", course_id not in ids)
    else:
        R.fail("outsider course list", detail_of(unenrolled))

    direct = outsider.get(f"/courses/{course_id}")
    R.check(
        "non-member blocked from course detail",
        direct.status_code == 404,
        detail_of(direct),
    )

    for label, path in (
        ("stream", f"/classroom/{course_id}/stream"),
        ("materials", f"/classroom/{course_id}/materials"),
        ("assignments", f"/classroom/{course_id}/assignments"),
        ("roster", f"/courses/{course_id}/enrollments"),
    ):
        response = outsider.get(path)
        R.check(
            f"non-member blocked from {label}",
            response.status_code in (403, 404),
            detail_of(response),
        )

    # Students must never reach Paper Style or the PYQ corpus.
    paper = student.post(
        "/rag/generate",
        json={
            "course_id": course_id,
            "mode": "paper_style",
            "exam_type": "internal",
            "question_count": 5,
        },
    )
    R.check(
        "student blocked from Paper Style",
        paper.status_code == 403,
        detail_of(paper),
    )

    profile = student.get(f"/rag/style-profile/{course_id}/internal")
    R.check(
        "student blocked from style profile",
        profile.status_code == 403,
        detail_of(profile),
    )

    corpus = student.get(f"/rag/documents/{course_id}")
    R.check(
        "student blocked from raw document list",
        corpus.status_code == 403,
        detail_of(corpus),
    )

    # A student must not be able to post an institute-wide notice.
    notice = student.post(
        "/notices/", json={"title": "Nope", "body": "Should be refused."}
    )
    R.check(
        "student cannot post a notice", notice.status_code == 403, detail_of(notice)
    )

    # A teacher must not be able to post institute-wide.
    wide = teacher.post(
        "/notices/", json={"title": "Institute-wide", "body": "Teachers may not."}
    )
    R.check(
        "teacher cannot post institute-wide notice",
        wide.status_code == 403,
        detail_of(wide),
    )

    # A student must not be able to schedule a lecture or exam.
    lecture = student.post(
        "/scheduler/events",
        json={
            "title": "Fake lecture",
            "event_type": "lecture",
            "start_at": "2026-12-01T10:00:00Z",
            "end_at": "2026-12-01T11:00:00Z",
        },
    )
    R.check(
        "student cannot create a lecture",
        lecture.status_code in (403, 422),
        detail_of(lecture),
    )

    # Admin-only endpoints must reject a teacher.
    users = teacher.get("/users/")
    R.check("teacher blocked from user list", users.status_code == 403, detail_of(users))


def phase_ingestion(course_id: str, teacher: Client, student: Client) -> dict:
    print("\n=== 5. Material upload & RAG ingestion (PRD §8.2 Stage 1) ===")
    result: dict[str, Any] = {"notes_doc": None, "pyq_doc": None, "material_id": None}

    notes = teacher.post(
        f"/classroom/{course_id}/materials",
        files={"file": ("unit3-scheduling.txt", io.BytesIO(NOTES.encode()), "text/plain")},
        data={"title": "Unit 3 — Process Scheduling", "source_type": "notes", "topic_tag": "Scheduling"},
    )
    if notes.status_code in (200, 201):
        material = notes.json()
        result["material_id"] = material["id"]
        result["notes_doc"] = material.get("document_id")
        R.ok("upload notes", material["title"])
    else:
        R.fail("upload notes", detail_of(notes))
        return result

    # An unsupported type must be refused up front.
    bad = teacher.post(
        f"/classroom/{course_id}/materials",
        files={"file": ("payload.exe", io.BytesIO(b"MZ\x00\x00binary"), "application/octet-stream")},
        data={"title": "Bad file", "source_type": "notes"},
    )
    R.check("unsupported file type rejected", bad.status_code == 415, detail_of(bad))

    # A PYQ upload without an exam type must be refused (it could not feed a profile).
    no_exam = teacher.post(
        f"/classroom/{course_id}/materials",
        files={"file": ("paper.txt", io.BytesIO(PYQ.encode()), "text/plain")},
        data={"title": "PYQ no exam type", "source_type": "pyq"},
    )
    R.check(
        "PYQ without exam_type rejected", no_exam.status_code == 400, detail_of(no_exam)
    )

    pyq = teacher.post(
        f"/classroom/{course_id}/materials",
        files={"file": ("internal-2025.txt", io.BytesIO(PYQ.encode()), "text/plain")},
        data={
            "title": "Internal Exam 2025",
            "source_type": "pyq",
            "exam_type": "internal",
            "year": 2025,
        },
    )
    if pyq.status_code in (200, 201):
        result["pyq_doc"] = pyq.json().get("document_id")
        R.ok("upload PYQ paper", "internal 2025")
    else:
        R.fail("upload PYQ paper", detail_of(pyq))

    if result["notes_doc"]:
        document = wait_for_ingestion(teacher, course_id, result["notes_doc"])
        R.check(
            "notes indexed",
            document.get("status") == "indexed",
            f"status={document.get('status')} chunks={document.get('chunk_count')} "
            f"err={document.get('error_message')}",
        )
        R.check(
            "notes produced chunks",
            (document.get("chunk_count") or 0) > 0,
            f"chunk_count={document.get('chunk_count')}",
        )

    corpus = teacher.get(f"/rag/corpus/{course_id}")
    if corpus.status_code == 200:
        payload = corpus.json()
        R.check(
            "corpus reports ready",
            payload["ready"],
            f"chunks={payload['total_chunks']} msg={payload.get('message')}",
        )
    else:
        R.fail("corpus status", detail_of(corpus))

    # Students must not see PYQ material in the Classwork list (PRD §14).
    student_materials = student.get(f"/classroom/{course_id}/materials")
    if student_materials.status_code == 200:
        types = {m.get("source_type") for m in student_materials.json()}
        R.check(
            "student's material list excludes PYQ",
            "pyq" not in types,
            f"source_types seen: {types}",
        )
    else:
        R.fail("student material list", detail_of(student_materials))

    if result["material_id"]:
        download = student.get(
            f"/classroom/{course_id}/materials/{result['material_id']}/download"
        )
        if download.status_code == 200:
            url = download.json().get("download_url", "")
            R.check("signed download URL issued", url.startswith("http"), url[:60])
            if url.startswith("http"):
                fetched = requests.get(url, timeout=60)
                R.check(
                    "signed URL actually serves the file",
                    fetched.status_code == 200 and b"Round Robin" in fetched.content,
                    f"HTTP {fetched.status_code}, {len(fetched.content)} bytes",
                )
        else:
            R.fail("signed download URL", detail_of(download))

    return result


def phase_pyq_and_profile(course_id: str, teacher: Client, pyq_doc: Optional[str]) -> None:
    print("\n=== 6. PYQ extraction & Style Profile (PRD §8.2 Stage 2) ===")
    if not pyq_doc:
        R.skip("style profile", "PYQ upload did not succeed")
        return

    document = wait_for_ingestion(teacher, course_id, pyq_doc)
    R.check(
        "PYQ indexed",
        document.get("status") == "indexed",
        f"status={document.get('status')} note={document.get('error_message')}",
    )

    profile = teacher.get(f"/rag/style-profile/{course_id}/internal")
    if profile.status_code == 200:
        payload = profile.json()
        R.ok(
            "style profile built",
            f"{payload['question_count']} questions, {len(payload['section_structure'])} "
            f"section(s), total_marks={payload.get('total_marks')}, "
            f"confidence={payload['confidence_score']:.2f}",
        )
        R.check(
            "profile learned section structure",
            len(payload["section_structure"]) >= 2,
            f"sections={[s.get('section') for s in payload['section_structure']]}",
        )
        R.check(
            "profile learned Bloom distribution",
            bool(payload["bloom_distribution"]),
            str(payload["bloom_distribution"]),
        )
    else:
        R.fail("style profile built", detail_of(profile))

    recompute = teacher.post(f"/rag/style-profile/{course_id}/internal/recompute")
    R.check(
        "style profile recompute", recompute.status_code == 200, detail_of(recompute)
    )


def phase_quiz(course_id: str, student: Client) -> None:
    print("\n=== 7. Quiz Generation + auto-marking (student) ===")

    response = student.post(
        "/rag/generate",
        json={
            "course_id": course_id,
            "mode": "quiz_generation",
            "topic_tags": ["Round Robin scheduling", "FCFS", "starvation"],
            "difficulty": "medium",
            "question_count": 5,
            "question_types": ["mcq", "true_false"],
        },
    )
    if response.status_code != 200:
        R.fail("generate quiz", detail_of(response))
        return

    generated = response.json()
    questions = generated["questions"]
    R.ok(
        "generate quiz",
        f"{len(questions)} question(s), {generated['total_marks']} marks",
    )
    if generated.get("warnings"):
        for warning in generated["warnings"]:
            print(f"         note: {warning}")

    R.check("quiz produced questions", len(questions) > 0)
    if not questions:
        return

    R.check(
        "every question cites a source",
        all(q.get("source_texts") for q in questions),
        f"{sum(1 for q in questions if not q.get('source_texts'))} without sources",
    )
    R.check(
        "MCQ answers are option letters",
        all(
            q["correct_answer"] in ("A", "B", "C", "D")
            for q in questions
            if q["question_type"] == "mcq"
        ),
        str([q["correct_answer"] for q in questions if q["question_type"] == "mcq"]),
    )
    R.check(
        "MCQs have four options",
        all(
            len(q.get("options") or []) == 4
            for q in questions
            if q["question_type"] == "mcq"
        ),
    )

    attempt = student.post("/rag/attempts", json={"set_id": generated["id"]})
    if attempt.status_code not in (200, 201):
        R.fail("start attempt", detail_of(attempt))
        return
    attempt_data = attempt.json()
    R.ok("start attempt", attempt_data["id"])

    # While in progress the answer key must not be in the payload.
    leaked = [q for q in attempt_data["questions"] if q.get("correct_answer")]
    R.check(
        "answer key withheld during attempt",
        not leaked,
        f"{len(leaked)} question(s) leaked their answer",
    )

    # A second start must reuse the same attempt, not fork one.
    again = student.post("/rag/attempts", json={"set_id": generated["id"]})
    R.check(
        "re-opening reuses the in-progress attempt",
        again.status_code in (200, 201)
        and again.json()["id"] == attempt_data["id"],
        f"{again.json().get('id')} vs {attempt_data['id']}",
    )

    # Answer everything correctly using the key from the generate response.
    answers = {q["id"]: q["correct_answer"] for q in questions}
    submitted = student.post(
        f"/rag/attempts/{attempt_data['id']}/submit",
        json={"answers": answers, "time_spent_seconds": 90},
    )
    if submitted.status_code != 200:
        R.fail("submit attempt", detail_of(submitted))
        return

    marked = submitted.json()
    auto_available = marked.get("auto_graded_marks") or 0
    R.ok(
        "submit attempt",
        f"score {marked['score']}/{auto_available} auto-markable "
        f"(set total {marked['total_marks']})",
    )
    R.check(
        "all-correct submission scores full auto marks",
        auto_available > 0 and marked["score"] == auto_available,
        f"score={marked['score']} auto_available={auto_available}",
    )
    R.check(
        "per-question results returned",
        len(marked.get("results") or []) == len(questions),
        f"{len(marked.get('results') or [])} results for {len(questions)} questions",
    )

    # Re-submitting must be refused.
    twice = student.post(
        f"/rag/attempts/{attempt_data['id']}/submit", json={"answers": answers}
    )
    R.check("double submission rejected", twice.status_code == 409, detail_of(twice))

    # Now verify a deliberately wrong answer scores zero.
    fresh = student.post("/rag/attempts", json={"set_id": generated["id"]})
    if fresh.status_code in (200, 201):
        wrong = {}
        for q in questions:
            if q["question_type"] == "mcq":
                wrong[q["id"]] = "A" if q["correct_answer"] != "A" else "B"
            elif q["question_type"] == "true_false":
                wrong[q["id"]] = "False" if q["correct_answer"] == "True" else "True"
        graded = student.post(
            f"/rag/attempts/{fresh.json()['id']}/submit", json={"answers": wrong}
        )
        if graded.status_code == 200:
            R.check(
                "all-wrong submission scores zero",
                graded.json()["score"] == 0,
                f"score={graded.json()['score']}",
            )
        else:
            R.fail("all-wrong submission", detail_of(graded))

    history = student.get("/rag/attempts")
    R.check(
        "attempt history lists attempts",
        history.status_code == 200 and len(history.json()) >= 2,
        detail_of(history),
    )


def phase_paper_style(course_id: str, teacher: Client, student: Client) -> None:
    print("\n=== 8. Paper Style + review gate (teacher, PRD §8.2 Stage 6) ===")

    response = teacher.post(
        "/rag/generate",
        json={
            "course_id": course_id,
            "mode": "paper_style",
            "exam_type": "internal",
            "difficulty": "medium",
            "question_count": 6,
            "question_types": ["short_answer", "long_answer"],
        },
    )
    if response.status_code != 200:
        R.fail("generate paper draft", detail_of(response))
        return

    generated = response.json()
    questions = generated["questions"]
    R.ok(
        "generate paper draft",
        f"{len(questions)} question(s), {generated['total_marks']} marks, "
        f"status={generated['status']}",
    )
    for warning in generated.get("warnings") or []:
        print(f"         note: {warning}")

    R.check(
        "paper lands as draft, not approved",
        generated["status"] == "draft",
        generated["status"],
    )

    set_id = generated["id"]

    # A student must not be able to read it, even with the id.
    peek = student.get(f"/rag/sets/{set_id}")
    R.check("student cannot read paper set", peek.status_code == 404, detail_of(peek))

    export_blocked = student.get(f"/rag/sets/{set_id}/export")
    R.check(
        "student cannot export paper set",
        export_blocked.status_code == 404,
        detail_of(export_blocked),
    )

    if not questions:
        R.skip("paper review flow", "no questions generated")
        return

    first = questions[0]

    edited = teacher.patch(
        f"/rag/sets/{set_id}/questions/{first['id']}",
        json={"question_text": "Explain, in your own words, why aging prevents starvation.", "marks": 5},
    )
    if edited.status_code == 200:
        payload = edited.json()
        R.ok("teacher edits a question", "teacher_edited flag set")
        R.check("edit marks question as teacher-edited", payload["teacher_edited"])
        R.check(
            "edit clears the stale faithfulness score",
            payload.get("faithfulness_score") is None,
            str(payload.get("faithfulness_score")),
        )
    else:
        R.fail("teacher edits a question", detail_of(edited))

    if len(questions) > 1:
        removed = teacher.delete(f"/rag/sets/{set_id}/questions/{questions[-1]['id']}")
        R.check("teacher deletes a question", removed.status_code == 204, detail_of(removed))

        after = teacher.get(f"/rag/sets/{set_id}")
        if after.status_code == 200:
            remaining = after.json()["questions"]
            R.check(
                "totals recalculated after delete",
                after.json()["total_questions"] == len(remaining),
                f"total_questions={after.json()['total_questions']} actual={len(remaining)}",
            )
            R.check(
                "question order stays contiguous",
                [q["question_order"] for q in remaining] == list(range(1, len(remaining) + 1)),
                str([q["question_order"] for q in remaining]),
            )

    pdf = teacher.get(f"/rag/sets/{set_id}/export", params={"include_sources": "true"})
    if pdf.status_code == 200:
        R.check(
            "draft exports as PDF",
            pdf.content[:4] == b"%PDF",
            f"{len(pdf.content)} bytes, content-type={pdf.headers.get('content-type')}",
        )
    else:
        R.fail("draft exports as PDF", detail_of(pdf))

    approved = teacher.post(f"/rag/sets/{set_id}/approve", json={"status": "approved"})
    if approved.status_code == 200:
        payload = approved.json()
        R.check("teacher approves the set", payload["status"] == "approved", payload["status"])
        R.check("approval is timestamped", bool(payload.get("approved_at")))
    else:
        R.fail("teacher approves the set", detail_of(approved))

    # Approved sets are locked (PRD §13 auditability).
    relock = teacher.patch(
        f"/rag/sets/{set_id}/questions/{first['id']}", json={"marks": 9}
    )
    R.check(
        "approved set is immutable", relock.status_code == 409, detail_of(relock)
    )

    reapprove = teacher.post(f"/rag/sets/{set_id}/approve", json={"status": "approved"})
    R.check("cannot re-approve", reapprove.status_code == 409, detail_of(reapprove))

    undelete = teacher.delete(f"/rag/sets/{set_id}")
    R.check(
        "approved set cannot be deleted", undelete.status_code == 409, detail_of(undelete)
    )


def phase_classroom(course_id: str, teacher: Client, student: Client) -> None:
    print("\n=== 9. Classroom: assignments, submission, grading (PRD §9) ===")

    announcement = teacher.post(
        f"/classroom/{course_id}/announcements",
        json={"text": "Reminder: Unit 3 quiz on Friday."},
    )
    R.check(
        "post announcement",
        announcement.status_code in (200, 201),
        detail_of(announcement),
    )

    assignment = teacher.post(
        f"/classroom/{course_id}/assignments",
        json={
            "title": "Scheduling worksheet",
            "instructions": "Compare FCFS and SJF using the Unit 3 notes.",
            "due_at": "2026-12-20T23:59:00Z",
            "max_points": 20,
            "topic_tag": "Scheduling",
        },
    )
    if assignment.status_code not in (200, 201):
        R.fail("create assignment", detail_of(assignment))
        return
    assignment_data = assignment.json()
    assignment_id = assignment_data["id"]
    R.ok("create assignment", f"{assignment_data['title']} ({assignment_data['max_points']} pts)")

    # The due date must appear on the calendar (PRD §10).
    events = teacher.get(
        "/scheduler/events",
        params={"start_date": "2026-12-01T00:00:00Z", "end_date": "2026-12-31T23:59:00Z"},
    )
    if events.status_code == 200:
        due_events = [
            e for e in events.json()
            if e.get("assignment_id") == assignment_id and e["event_type"] == "assignment_due"
        ]
        R.check("due date auto-added to calendar", len(due_events) == 1, f"{len(due_events)} found")
    else:
        R.fail("calendar due-date sync", detail_of(events))

    # Editing the due date must move the event, not duplicate it.
    teacher.patch(
        f"/classroom/{course_id}/assignments/{assignment_id}",
        json={"due_at": "2026-12-22T23:59:00Z"},
    )
    events = teacher.get(
        "/scheduler/events",
        params={"start_date": "2026-12-01T00:00:00Z", "end_date": "2026-12-31T23:59:00Z"},
    )
    if events.status_code == 200:
        due_events = [e for e in events.json() if e.get("assignment_id") == assignment_id]
        R.check(
            "editing due date does not duplicate the event",
            len(due_events) == 1,
            f"{len(due_events)} due events after edit",
        )

    # Student view carries their own status.
    listing = student.get(f"/classroom/{course_id}/assignments")
    if listing.status_code == 200:
        mine = next((a for a in listing.json() if a["id"] == assignment_id), None)
        R.check(
            "student sees not_submitted status",
            mine is not None and mine.get("my_status") == "not_submitted",
            str(mine.get("my_status") if mine else "assignment missing"),
        )
    else:
        R.fail("student assignment list", detail_of(listing))

    empty = student.post(f"/classroom/{course_id}/assignments/{assignment_id}/submit", data={})
    R.check("empty submission rejected", empty.status_code == 400, detail_of(empty))

    submitted = student.post(
        f"/classroom/{course_id}/assignments/{assignment_id}/submit",
        files={"file": ("answer.txt", io.BytesIO(b"FCFS is non-preemptive; SJF minimises average waiting time."), "text/plain")},
        data={"text_response": "See attached comparison."},
    )
    if submitted.status_code not in (200, 201):
        R.fail("student submits", detail_of(submitted))
        return
    submission = submitted.json()
    R.ok("student submits", f"status={submission['status']}")

    # A teacher must not be able to submit.
    teacher_submit = teacher.post(
        f"/classroom/{course_id}/assignments/{assignment_id}/submit",
        data={"text_response": "Teachers cannot submit."},
    )
    R.check(
        "teacher cannot submit work",
        teacher_submit.status_code == 403,
        detail_of(teacher_submit),
    )

    submissions = teacher.get(
        f"/classroom/{course_id}/assignments/{assignment_id}/submissions"
    )
    if submissions.status_code == 200:
        rows = submissions.json()
        R.ok("teacher sees the grading list", f"{len(rows)} row(s)")
        R.check(
            "grading list includes every enrolled student",
            len(rows) >= 1,
            f"{len(rows)} rows",
        )
        target = next((r for r in rows if r["student_id"] == student.user["id"]), None)
        R.check("submitted work appears in the list", target is not None)
    else:
        R.fail("teacher grading list", detail_of(submissions))
        return

    # A student must not be able to read the whole grading list.
    peek = student.get(f"/classroom/{course_id}/assignments/{assignment_id}/submissions")
    R.check(
        "student cannot read other submissions",
        peek.status_code == 403,
        detail_of(peek),
    )

    # Downloading the submitted file.
    if submission.get("id"):
        download = teacher.get(f"/classroom/submissions/{submission['id']}/download")
        if download.status_code == 200:
            url = download.json()["download_url"]
            fetched = requests.get(url, timeout=60)
            R.check(
                "teacher downloads the submission",
                fetched.status_code == 200 and b"non-preemptive" in fetched.content,
                f"HTTP {fetched.status_code}",
            )
        else:
            R.fail("teacher downloads the submission", detail_of(download))

    # Grading beyond max_points must be refused.
    over = teacher.post(
        f"/classroom/{course_id}/grades",
        json={"submission_id": submission["id"], "points_awarded": 999},
    )
    R.check("grade above max_points rejected", over.status_code == 400, detail_of(over))

    graded = teacher.post(
        f"/classroom/{course_id}/grades",
        json={
            "submission_id": submission["id"],
            "points_awarded": 17.5,
            "feedback_text": "Good comparison; mention the convoy effect explicitly.",
        },
    )
    if graded.status_code in (200, 201):
        R.ok("teacher grades the submission", f"{graded.json()['points_awarded']}/20")
    else:
        R.fail("teacher grades the submission", detail_of(graded))

    mine = student.get(f"/classroom/{course_id}/assignments/{assignment_id}/my-submission")
    if mine.status_code == 200 and mine.json():
        payload = mine.json()
        grade = payload.get("grade") or {}
        R.check(
            "student sees their grade and feedback",
            grade.get("points_awarded") == 17.5 and bool(grade.get("feedback_text")),
            str(grade),
        )
        R.check("submission marked graded", payload["status"] == "graded", payload["status"])
    else:
        R.fail("student sees their grade", detail_of(mine))

    # Once graded, resubmission must be refused.
    resubmit = student.post(
        f"/classroom/{course_id}/assignments/{assignment_id}/submit",
        data={"text_response": "Trying again after grading."},
    )
    R.check(
        "resubmission after grading rejected",
        resubmit.status_code == 409,
        detail_of(resubmit),
    )

    unsubmit = student.post(f"/classroom/{course_id}/assignments/{assignment_id}/unsubmit")
    R.check(
        "un-submitting graded work rejected",
        unsubmit.status_code == 409,
        detail_of(unsubmit),
    )

    stream = student.get(f"/classroom/{course_id}/stream")
    if stream.status_code == 200:
        kinds = {item["type"] for item in stream.json()}
        R.check(
            "stream merges announcements, material and assignments",
            {"announcement", "material", "assignment"}.issubset(kinds),
            f"types seen: {kinds}",
        )
    else:
        R.fail("course stream", detail_of(stream))


def phase_scheduler(course_id: str, teacher: Client, student: Client, outsider: Client) -> None:
    print("\n=== 10. Scheduler (PRD §10) ===")

    lecture = teacher.post(
        "/scheduler/events",
        json={
            "title": "Unit 3 lecture",
            "event_type": "lecture",
            "course_id": course_id,
            "start_at": "2026-11-10T09:00:00Z",
            "end_at": "2026-11-10T10:00:00Z",
            "location": "Room 204",
        },
    )
    if lecture.status_code not in (200, 201):
        R.fail("create lecture", detail_of(lecture))
        return
    lecture_id = lecture.json()["id"]
    R.ok("create lecture", lecture.json()["title"])

    R.check(
        "event colour auto-assigned by type",
        lecture.json()["color"] == "#FBC02D",
        lecture.json()["color"],
    )

    conflict = teacher.post(
        "/scheduler/events/check-conflicts",
        json={
            "start_at": "2026-11-10T09:30:00Z",
            "end_at": "2026-11-10T10:30:00Z",
            "course_id": course_id,
        },
    )
    if conflict.status_code == 200:
        payload = conflict.json()
        R.check(
            "overlapping event detected",
            payload["has_conflict"] and len(payload["conflicting_events"]) >= 1,
            payload.get("message") or "no message",
        )
    else:
        R.fail("conflict detection", detail_of(conflict))

    no_conflict = teacher.post(
        "/scheduler/events/check-conflicts",
        json={
            "start_at": "2026-11-10T14:00:00Z",
            "end_at": "2026-11-10T15:00:00Z",
            "course_id": course_id,
        },
    )
    R.check(
        "non-overlapping event reports no conflict",
        no_conflict.status_code == 200 and not no_conflict.json()["has_conflict"],
        detail_of(no_conflict),
    )

    # Enrolled student sees the course lecture; outsider does not.
    seen = student.get(
        "/scheduler/events",
        params={"start_date": "2026-11-01T00:00:00Z", "end_date": "2026-11-30T00:00:00Z"},
    )
    if seen.status_code == 200:
        R.check(
            "enrolled student sees the course lecture",
            any(e["id"] == lecture_id for e in seen.json()),
        )
    else:
        R.fail("student event list", detail_of(seen))

    hidden = outsider.get(
        "/scheduler/events",
        params={"start_date": "2026-11-01T00:00:00Z", "end_date": "2026-11-30T00:00:00Z"},
    )
    if hidden.status_code == 200:
        R.check(
            "non-member does NOT see the course lecture",
            not any(e["id"] == lecture_id for e in hidden.json()),
        )
    else:
        R.fail("outsider event list", detail_of(hidden))

    # A student must not be able to delete a teacher's lecture.
    forbidden = student.delete(f"/scheduler/events/{lecture_id}")
    R.check(
        "student cannot delete a lecture",
        forbidden.status_code == 403,
        detail_of(forbidden),
    )

    invalid = teacher.post(
        "/scheduler/events",
        json={
            "title": "Backwards",
            "event_type": "meeting",
            "start_at": "2026-11-10T11:00:00Z",
            "end_at": "2026-11-10T10:00:00Z",
        },
    )
    R.check(
        "end-before-start rejected", invalid.status_code == 422, detail_of(invalid)
    )

    forged = teacher.post(
        "/scheduler/events",
        json={
            "title": "Fake deadline",
            "event_type": "assignment_due",
            "start_at": "2026-11-11T10:00:00Z",
            "end_at": "2026-11-11T11:00:00Z",
        },
    )
    R.check(
        "assignment_due cannot be created by hand",
        forged.status_code == 422,
        detail_of(forged),
    )

    # An event spanning a month boundary must show in both months.
    spanning = teacher.post(
        "/scheduler/events",
        json={
            "title": "Revision week",
            "event_type": "other",
            "course_id": course_id,
            "start_at": "2026-11-29T09:00:00Z",
            "end_at": "2026-12-02T17:00:00Z",
        },
    )
    if spanning.status_code in (200, 201):
        spanning_id = spanning.json()["id"]
        november = teacher.get(
            "/scheduler/events",
            params={"start_date": "2026-11-01T00:00:00Z", "end_date": "2026-11-30T23:59:00Z"},
        )
        december = teacher.get(
            "/scheduler/events",
            params={"start_date": "2026-12-01T00:00:00Z", "end_date": "2026-12-31T23:59:00Z"},
        )
        in_nov = any(e["id"] == spanning_id for e in november.json())
        in_dec = any(e["id"] == spanning_id for e in december.json())
        R.check(
            "month-spanning event appears in both months",
            in_nov and in_dec,
            f"november={in_nov} december={in_dec}",
        )
        teacher.delete(f"/scheduler/events/{spanning_id}")

    deleted = teacher.delete(f"/scheduler/events/{lecture_id}")
    R.check("delete event", deleted.status_code == 204, detail_of(deleted))


def phase_notices(course_id: str, admin: Client, teacher: Client, student: Client, outsider: Client) -> None:
    print("\n=== 11. Notice Board (PRD §11 / §14) ===")

    wide = admin.post(
        "/notices/",
        json={
            "title": f"E2E institute notice {SUFFIX}",
            "body": "Visible to everyone.",
            "notice_type": "admin",
        },
    )
    R.check("admin posts institute-wide notice", wide.status_code in (200, 201), detail_of(wide))

    course_notice = teacher.post(
        "/notices/",
        json={
            "title": f"E2E course notice {SUFFIX}",
            "body": "Only for this course.",
            "notice_type": "announcement",
            "course_id": course_id,
        },
    )
    if course_notice.status_code not in (200, 201):
        R.fail("teacher posts course notice", detail_of(course_notice))
        return
    course_notice_id = course_notice.json()["id"]
    R.ok("teacher posts course notice", course_notice.json()["title"])

    student_feed = student.get("/notices/", params={"limit": 100})
    if student_feed.status_code == 200:
        ids = {n["id"] for n in student_feed.json()["notices"]}
        R.check("enrolled student sees the course notice", course_notice_id in ids)
    else:
        R.fail("student notice feed", detail_of(student_feed))

    outsider_feed = outsider.get("/notices/", params={"limit": 100})
    if outsider_feed.status_code == 200:
        ids = {n["id"] for n in outsider_feed.json()["notices"]}
        R.check("non-member does NOT see the course notice", course_notice_id not in ids)
    else:
        R.fail("outsider notice feed", detail_of(outsider_feed))

    # A grade notice must reach only the graded student.
    if student_feed.status_code == 200:
        grade_notices = [
            n for n in student_feed.json()["notices"] if n["notice_type"] == "grade"
        ]
        R.check(
            "student receives their own grade notice",
            len(grade_notices) >= 1,
            f"{len(grade_notices)} grade notice(s)",
        )
    other = teacher.get("/notices/", params={"notice_type": "grade", "limit": 100})
    if other.status_code == 200:
        leaked = [
            n for n in other.json()["notices"]
            if n.get("target_user_id") and n["target_user_id"] != teacher.user["id"]
        ]
        R.check(
            "another user's grade notice is not leaked",
            not leaked,
            f"{len(leaked)} leaked",
        )

    unread = student.get("/notices/unread-count")
    if unread.status_code == 200:
        before = unread.json()["unread_count"]
        R.ok("unread count", str(before))
        marked = student.post("/notices/mark-all-read")
        R.check("mark all read", marked.status_code == 200, detail_of(marked))
        after = student.get("/notices/unread-count")
        R.check(
            "unread count drops to zero",
            after.status_code == 200 and after.json()["unread_count"] == 0,
            detail_of(after),
        )
    else:
        R.fail("unread count", detail_of(unread))

    # A teacher must not delete an admin's notice.
    if wide.status_code in (200, 201):
        forbidden = teacher.delete(f"/notices/{wide.json()['id']}")
        R.check(
            "teacher cannot delete another author's notice",
            forbidden.status_code == 403,
            detail_of(forbidden),
        )


def phase_admin(admin: Client, created: dict) -> None:
    print("\n=== 12. Admin surfaces ===")

    stats = admin.get("/users/stats/summary")
    if stats.status_code == 200:
        payload = stats.json()
        R.ok(
            "user stats",
            f"total={payload['total']} teachers={payload['teachers']} students={payload['students']}",
        )
        R.check(
            "stats add up",
            payload["total"] == payload["admins"] + payload["teachers"] + payload["students"],
            str(payload),
        )
    else:
        R.fail("user stats", detail_of(stats))

    filtered = admin.get("/users/", params={"role": "teacher"})
    if filtered.status_code == 200:
        R.check(
            "user list filters by role",
            all(u["role"] == "teacher" for u in filtered.json()),
        )
    else:
        R.fail("user list by role", detail_of(filtered))

    searched = admin.get("/users/", params={"search": SUFFIX})
    R.check(
        "user search works",
        searched.status_code == 200 and len(searched.json()) >= 2,
        detail_of(searched),
    )

    self_demote = admin.patch(f"/users/{admin.user['id']}/role", json={"role": "student"})
    R.check(
        "admin cannot demote themselves",
        self_demote.status_code == 400,
        detail_of(self_demote),
    )

    self_delete = admin.delete(f"/users/{admin.user['id']}")
    R.check(
        "admin cannot delete themselves",
        self_delete.status_code == 400,
        detail_of(self_delete),
    )

    course_id = created.get("course_id")
    if course_id:
        csv_body = f"email,role\n{OUTSIDER_EMAIL},student\nnobody-{SUFFIX}@academix.ai,student\n"
        imported = admin.post(
            f"/courses/{course_id}/enroll/csv",
            files={"file": ("roster.csv", io.BytesIO(csv_body.encode()), "text/csv")},
        )
        if imported.status_code == 200:
            payload = imported.json()
            R.ok(
                "CSV roster import",
                f"enrolled={payload['enrolled']} skipped={payload['skipped']} "
                f"errors={len(payload['errors'])}",
            )
            R.check(
                "CSV import reports unknown emails",
                any("nobody-" in e for e in payload["errors"]),
                str(payload["errors"]),
            )
        else:
            R.fail("CSV roster import", detail_of(imported))

        # Undo that import so isolation assertions elsewhere stay valid.
        if OUTSIDER_EMAIL in created.get("user_ids", {}):
            admin.delete(
                f"/courses/{course_id}/enroll/{created['user_ids'][OUTSIDER_EMAIL]}"
            )


def cleanup(admin: Client, created: dict) -> None:
    print("\n=== Cleanup ===")
    course_id = created.get("course_id")
    if course_id:
        response = admin.delete(f"/courses/{course_id}")
        print(f"  delete course: HTTP {response.status_code}")
    for user in created.get("users", []):
        response = admin.delete(f"/users/{user['id']}")
        print(f"  delete {user['email']}: HTTP {response.status_code}")


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Academix AI end-to-end test")
    parser.add_argument("--admin-email", default="admin@academix.ai")
    parser.add_argument("--admin-password", default="password123")
    parser.add_argument("--skip-llm", action="store_true", help="Skip generation phases")
    parser.add_argument("--keep", action="store_true", help="Do not delete fixtures")
    args = parser.parse_args()

    print("=" * 74)
    print("Academix AI — end-to-end test")
    print(f"Target: {BASE}")
    print("=" * 74)

    if not phase_health():
        print("\nBackend is not reachable. Start it with:")
        print("  cd backend && venv\\Scripts\\python -m uvicorn app.main:app --reload --port 8000")
        return 1

    admin = phase_auth(args.admin_email, args.admin_password)
    if admin is None:
        return R.summary()

    created = phase_provision(admin)
    course_id = created.get("course_id")
    if not course_id:
        return R.summary()

    teacher = Client("teacher")
    student = Client("student")
    outsider = Client("outsider")

    for client, email in ((teacher, TEACHER_EMAIL), (student, STUDENT_EMAIL), (outsider, OUTSIDER_EMAIL)):
        if not client.login(email, PASSWORD):
            R.fail(f"{client.label} login", email)
        else:
            R.ok(f"{client.label} login", email)

    try:
        if teacher.token and student.token and outsider.token:
            phase_isolation(course_id, teacher, student, outsider)
            ingested = phase_ingestion(course_id, teacher, student)

            if args.skip_llm:
                R.skip("PYQ extraction & style profile", "--skip-llm")
                R.skip("quiz generation", "--skip-llm")
                R.skip("paper style", "--skip-llm")
            else:
                phase_pyq_and_profile(course_id, teacher, ingested.get("pyq_doc"))
                phase_quiz(course_id, student)
                phase_paper_style(course_id, teacher, student)

            phase_classroom(course_id, teacher, student)
            phase_scheduler(course_id, teacher, student, outsider)
            phase_notices(course_id, admin, teacher, student, outsider)
        phase_admin(admin, created)
    finally:
        if not args.keep:
            cleanup(admin, created)
        else:
            print(f"\n=== Fixtures kept: course {course_id}, suffix {SUFFIX} ===")

    return R.summary()


if __name__ == "__main__":
    sys.exit(main())
