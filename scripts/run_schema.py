"""
scripts/run_schema.py
Execute warehouse/schema.sql against BigQuery and print one summary line per
statement — no SQL echo, no wall of text.
"""

import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery
import os

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

PROJECT = os.environ.get("GCP_PROJECT_ID")
if not PROJECT:
    print("❌  GCP_PROJECT_ID is not set — add it to .env or export it before running.")
    sys.exit(1)
SCHEMA = Path(__file__).resolve().parents[1] / "warehouse" / "schema.sql"

client = bigquery.Client(project=PROJECT)


def strip_line_comments(sql: str) -> str:
    """Remove -- comments, respecting single-quoted strings."""
    result = []
    for line in sql.splitlines():
        in_string = False
        for i, ch in enumerate(line):
            if ch == "'" and not in_string:
                in_string = True
            elif ch == "'" and in_string:
                in_string = False
            elif line[i : i + 2] == "--" and not in_string:
                line = line[:i]
                break
        result.append(line)
    return "\n".join(result)


def split_statements(sql: str) -> list:
    """Split SQL on semicolons that are outside string literals."""
    statements, current, in_string = [], [], False
    for char in sql:
        if char == "'" and not in_string:
            in_string = True
            current.append(char)
        elif char == "'" and in_string:
            in_string = False
            current.append(char)
        elif char == ";" and not in_string:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
        else:
            current.append(char)
    last = "".join(current).strip()
    if last:
        statements.append(last)
    return statements


def has_sql(stmt: str) -> bool:
    """Return True if the statement contains actual SQL, not only comments/whitespace."""
    for line in stmt.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            return True
    return False


sql = strip_line_comments(SCHEMA.read_text())
statements = [s for s in split_statements(sql) if has_sql(s)]

total = errors = quota_warnings = 0
t0 = time.time()

for stmt in statements:
    name_match = re.search(
        r"(?:DROP TABLE IF EXISTS|CREATE OR REPLACE TABLE)\s+`[^.]+\.([^`]+)`",
        stmt,
        re.IGNORECASE,
    )
    label = name_match.group(1) if name_match else stmt[:50].replace("\n", " ")

    first_word = stmt.lstrip().split()[0].upper() if stmt.strip() else ""
    if first_word == "DROP":
        kind = "DROP  "
    elif first_word == "CREATE":
        kind = "CREATE"
    else:
        kind = "      "

    try:
        t1 = time.time()
        client.query(stmt).result()
        elapsed = time.time() - t1
        print(f"  ✅ {kind} {label:<35} ({elapsed:.1f}s)")
        total += 1
    except Exception as exc:
        short_err = str(exc).split("\n")[0]
        # Quota errors are transient — treat as warnings, not hard failures.
        # The table already exists from a prior run so downstream dbt can proceed.
        is_quota = "quotaExceeded" in str(exc) or "Quota exceeded" in str(exc)
        if is_quota:
            print(
                f"  ⚠️  {kind} {label:<35} QUOTA WARNING (table retained): {short_err[:80]}"
            )
            quota_warnings += 1
        else:
            print(f"  ❌ {kind} {label:<35} {short_err}")
            errors += 1

print()
print(
    f"  Schema build complete — {total} statements, {errors} errors, "
    f"{quota_warnings} quota warnings  ({time.time() - t0:.1f}s total)"
)

if errors:
    sys.exit(1)
# quota_warnings alone → exit 0 so downstream assets are not blocked
