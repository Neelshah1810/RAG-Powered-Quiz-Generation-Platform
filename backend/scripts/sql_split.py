"""
Academix AI — PostgreSQL statement splitter.

The migration scripts contain `DO $$ ... $$` blocks and function bodies wrapped
in dollar quotes, so they cannot be split on a naive `;`. This walks the text
once, tracking which quoting context it is inside, and only treats a semicolon
as a boundary when it appears at the top level.

Handles: line comments (`--`), block comments (`/* */`, nestable per the
PostgreSQL grammar), single-quoted literals (with `''` escapes), double-quoted
identifiers, and dollar-quoted strings with or without a tag (`$$`, `$body$`).
"""

from __future__ import annotations

import re

_DOLLAR_TAG = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")


def split_sql_statements(sql: str) -> list[str]:
    """Split a SQL script into individually executable statements."""
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(sql)

    while i < n:
        ch = sql[i]

        # -- line comment
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            end = n if end == -1 else end + 1
            buf.append(sql[i:end])
            i = end
            continue

        # /* block comment */ — PostgreSQL allows these to nest.
        if sql.startswith("/*", i):
            depth = 1
            j = i + 2
            while j < n and depth:
                if sql.startswith("/*", j):
                    depth += 1
                    j += 2
                elif sql.startswith("*/", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            buf.append(sql[i:j])
            i = j
            continue

        # 'single-quoted literal'
        if ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":  # '' escape
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            buf.append(sql[i:j])
            i = j
            continue

        # "double-quoted identifier"
        if ch == '"':
            j = i + 1
            while j < n:
                if sql[j] == '"':
                    if j + 1 < n and sql[j + 1] == '"':
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            buf.append(sql[i:j])
            i = j
            continue

        # $tag$ dollar-quoted string $tag$
        if ch == "$":
            m = _DOLLAR_TAG.match(sql, i)
            if m:
                tag = m.group(0)
                close = sql.find(tag, m.end())
                j = n if close == -1 else close + len(tag)
                buf.append(sql[i:j])
                i = j
                continue

        # Top-level statement boundary.
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)

    return statements


def is_noise(statement: str) -> bool:
    """
    True for statements that carry no DDL/DML — comment-only fragments, and the
    file-level BEGIN/COMMIT that the runner manages itself.
    """
    stripped = re.sub(r"--[^\n]*", "", statement)
    stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.DOTALL).strip()
    if not stripped:
        return True
    return stripped.rstrip(";").strip().upper() in {
        "BEGIN",
        "COMMIT",
        "END",
        "START TRANSACTION",
    }


def summarise(statement: str, width: int = 88) -> str:
    """A one-line label for progress output."""
    body = re.sub(r"--[^\n]*", "", statement)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    body = " ".join(body.split())
    return body[:width] + ("…" if len(body) > width else "")
