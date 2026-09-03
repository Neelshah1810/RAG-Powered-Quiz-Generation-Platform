"""
Academix AI — Database migration runner.

Applies every `supabase/migrations/*.sql` file, in filename order, that has not
already been recorded in the `schema_migrations` table. Each file runs inside a
single transaction: either the whole file applies, or nothing from it does.

Usage
-----
    python -m scripts.migrate              # apply pending migrations
    python -m scripts.migrate --status     # list applied / pending, change nothing
    python -m scripts.migrate --force NAME # re-apply one file even if recorded

Requires `DATABASE_URL` in backend/.env — the Supabase Postgres URI from
Dashboard → Settings → Database → Connection string. Use the **Session pooler**
(port 5432) URI: transaction-mode pooling (6543) rejects the prepared
statements this driver issues.

Uses pg8000, a pure-Python driver, because this project must run on machines
without the MSVC runtime that psycopg/asyncpg binary wheels need.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import ssl
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"

sys.path.insert(0, str(BACKEND_DIR))

from scripts.sql_split import (  # noqa: E402
    is_noise,
    split_sql_statements,
    summarise,
)

TRACKING_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    filename    TEXT PRIMARY KEY,
    checksum    TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    duration_ms INTEGER
)
"""


def load_database_url() -> str:
    """Read DATABASE_URL from the environment, falling back to backend/.env."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url

    env_path = BACKEND_DIR / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "DATABASE_URL":
                return value.strip().strip('"').strip("'")

    sys.exit(
        "DATABASE_URL is not set.\n\n"
        "Add it to backend/.env, e.g.\n"
        "  DATABASE_URL=postgresql://postgres.<ref>:<password>"
        "@aws-0-<region>.pooler.supabase.com:5432/postgres\n\n"
        "Copy it from Supabase Dashboard -> Settings -> Database ->\n"
        "Connection string -> URI (Session pooler)."
    )


def connect(url: str):
    """Open a pg8000 connection from a postgres:// URI."""
    import pg8000.dbapi

    parsed = urlparse(url)
    if parsed.scheme not in ("postgres", "postgresql"):
        sys.exit(f"DATABASE_URL must be a postgres:// URI, got {parsed.scheme!r}")
    if not parsed.hostname:
        sys.exit("DATABASE_URL is missing a host.")
    if not parsed.password:
        sys.exit(
            "DATABASE_URL is missing the password.\n"
            "Replace the [YOUR-PASSWORD] placeholder with your real DB password."
        )

    port = parsed.port or 5432
    if port == 6543:
        print(
            "  ! Port 6543 is the transaction-mode pooler, which rejects prepared\n"
            "    statements. Switch to the Session pooler URI (port 5432).",
            file=sys.stderr,
        )

    # Supabase requires TLS. Verification is left off because the pooler serves
    # a cert for a wildcard host that does not always match the URI, and the
    # alternative would be shipping a CA bundle with the repo.
    tls = ssl.create_default_context()
    tls.check_hostname = False
    tls.verify_mode = ssl.CERT_NONE

    return pg8000.dbapi.connect(
        user=unquote(parsed.username or "postgres"),
        password=unquote(parsed.password),
        host=parsed.hostname,
        port=port,
        database=(parsed.path or "/postgres").lstrip("/") or "postgres",
        ssl_context=tls,
        timeout=60,
    )


def migration_files() -> list[Path]:
    if not MIGRATIONS_DIR.is_dir():
        sys.exit(f"No migrations directory at {MIGRATIONS_DIR}")
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def applied_migrations(conn) -> dict[str, str]:
    cur = conn.cursor()
    cur.execute(TRACKING_TABLE_DDL)
    conn.commit()
    cur.execute("SELECT filename, checksum FROM public.schema_migrations")
    rows = cur.fetchall()
    cur.close()
    return {r[0]: r[1] for r in rows}


def apply_file(conn, path: Path, verbose: bool) -> None:
    """Run every statement in one file inside a single transaction."""
    sql = path.read_text(encoding="utf-8")
    statements = [s for s in split_sql_statements(sql) if not is_noise(s)]

    print(f"\n-> {path.name}  ({len(statements)} statements)")
    started = time.time()
    cur = conn.cursor()

    try:
        for idx, statement in enumerate(statements, 1):
            if verbose:
                print(f"   [{idx:>3}/{len(statements)}] {summarise(statement)}")
            try:
                cur.execute(statement)
            except Exception as exc:
                conn.rollback()
                print(
                    f"\n   FAILED at statement {idx}/{len(statements)}:\n"
                    f"   {summarise(statement, 400)}\n\n"
                    f"   {type(exc).__name__}: {exc}\n\n"
                    f"   Nothing from {path.name} was applied (rolled back).",
                    file=sys.stderr,
                )
                raise SystemExit(1) from exc

        duration_ms = int((time.time() - started) * 1000)
        cur.execute(
            """
            INSERT INTO public.schema_migrations (filename, checksum, duration_ms)
            VALUES (%s, %s, %s)
            ON CONFLICT (filename) DO UPDATE
                SET checksum = EXCLUDED.checksum,
                    applied_at = timezone('utc', now()),
                    duration_ms = EXCLUDED.duration_ms
            """,
            (path.name, checksum(path), duration_ms),
        )
        conn.commit()
        print(f"   OK  ({duration_ms} ms)")
    finally:
        cur.close()


def print_notices(conn) -> None:
    notices = getattr(conn, "notices", None) or getattr(
        getattr(conn, "_c", None), "notices", None
    )
    if not notices:
        return
    messages = []
    for note in notices:
        text = note.get(b"M") if isinstance(note, dict) else None
        if text:
            messages.append(text.decode("utf-8", "replace"))
    if messages:
        print("\nServer notices:")
        for m in messages:
            print(f"   . {m}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Academix AI DB migrations.")
    parser.add_argument("--status", action="store_true", help="Report state only.")
    parser.add_argument("--force", metavar="FILENAME", help="Re-apply one migration.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Echo each statement.")
    args = parser.parse_args()

    url = load_database_url()
    files = migration_files()

    host = urlparse(url).hostname
    print(f"Academix AI migrations -> {host}")

    conn = connect(url)
    try:
        already = applied_migrations(conn)

        if args.status:
            print(f"\n{'STATE':<10} {'CHECKSUM':<18} FILE")
            for path in files:
                recorded = already.get(path.name)
                current = checksum(path)
                if recorded is None:
                    state = "pending"
                elif recorded != current:
                    state = "CHANGED"
                else:
                    state = "applied"
                print(f"{state:<10} {current:<18} {path.name}")
            return

        if args.force:
            target = next((p for p in files if p.name == args.force), None)
            if target is None:
                sys.exit(f"No migration named {args.force!r} in {MIGRATIONS_DIR}")
            apply_file(conn, target, args.verbose)
            print_notices(conn)
            print("\nDone (forced).")
            return

        pending = [
            p for p in files
            if already.get(p.name) != checksum(p)
        ]
        if not pending:
            print("\nEverything already applied. Nothing to do.")
            return

        for path in pending:
            apply_file(conn, path, args.verbose)

        print_notices(conn)
        print(f"\nDone. Applied {len(pending)} migration(s).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
