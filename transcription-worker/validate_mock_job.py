#!/usr/bin/env python3
"""
validate_mock_job.py — validate a local dev transcription job for consistency.

Connects to the local dev database, lists available jobs, lets you pick one,
then runs a suite of structural checks: segment counts, timestamps, speaker
matching correctness, job-event audit trail, local audio/fixture file presence,
and MSW traffic.json coverage.

Usage:
    python validate_mock_job.py
    python validate_mock_job.py --env /path/to/.env
    python validate_mock_job.py --job-id <uuid>       # skip interactive selection
    python validate_mock_job.py --all                  # validate every job
"""

import argparse
import json
import os
import pathlib
import re
import sys
import uuid
from datetime import timezone
from typing import Any

# ---------------------------------------------------------------------------
# .env loader (no python-dotenv dependency)
# ---------------------------------------------------------------------------

def _load_env_file(path: str) -> None:
    try:
        with open(path) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                os.environ.setdefault(key, val)
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

_USE_COLOR = sys.stdout.isatty()

def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text

def green(t: str) -> str:   return _c(t, "32")
def red(t: str) -> str:     return _c(t, "31")
def yellow(t: str) -> str:  return _c(t, "33")
def cyan(t: str) -> str:    return _c(t, "36")
def bold(t: str) -> str:    return _c(t, "1")
def dim(t: str) -> str:     return _c(t, "2")

PASS  = green("✓")
FAIL  = red("✗")
WARN  = yellow("⚠")
SKIP  = dim("–")

# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def _connect(database_url: str):
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        sys.exit(red("psycopg2 not installed. Run: pip install psycopg2-binary"))

    # normalise SQLAlchemy-style URLs to plain psycopg2 DSN
    dsn = re.sub(r"^postgresql\+\w+://", "postgresql://", database_url)
    try:
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        return conn
    except Exception as exc:
        sys.exit(red(f"DB connection failed: {exc}\nURL: {dsn}"))


def _cursor(conn):
    import psycopg2.extras
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


# ---------------------------------------------------------------------------
# Job listing
# ---------------------------------------------------------------------------

def fetch_jobs(conn) -> list[dict]:
    with _cursor(conn) as cur:
        cur.execute("""
            SELECT
                j.id,
                j.user_id,
                j.status,
                j.language,
                j.audio_s3_key,
                j.speaker_count_hint,
                j.speaker_ids,
                j.matched_speaker_count,
                j.total_segment_count,
                j.error_message,
                j.created_at,
                j.updated_at,
                j.completed_at,
                COUNT(s.id) AS actual_segment_count
            FROM transcription_jobs j
            LEFT JOIN transcript_segments s ON s.job_id = j.id
            GROUP BY j.id
            ORDER BY j.created_at DESC
            LIMIT 50
        """)
        return [dict(r) for r in cur.fetchall()]


def fetch_job(conn, job_id: uuid.UUID) -> dict | None:
    jobs = fetch_jobs(conn)
    for j in jobs:
        if str(j["id"]) == str(job_id):
            return j
    # fall back to direct query (older jobs outside LIMIT 50)
    with _cursor(conn) as cur:
        cur.execute("""
            SELECT j.*, COUNT(s.id) AS actual_segment_count
            FROM transcription_jobs j
            LEFT JOIN transcript_segments s ON s.job_id = j.id
            WHERE j.id = %s
            GROUP BY j.id
        """, (str(job_id),))
        row = cur.fetchone()
        return dict(row) if row else None


STATUS_COLOURS = {
    "pending":     yellow,
    "transcribing": cyan,
    "matching":    cyan,
    "complete":    green,
    "failed":      red,
}

def _fmt_status(status: str) -> str:
    fn = STATUS_COLOURS.get(status, str)
    return fn(status)


def print_job_table(jobs: list[dict]) -> None:
    print()
    print(bold(f"  {'#':>3}  {'Status':<13} {'Created (UTC)':<20} {'Lang':<7} {'Segs':>5}  Job ID"))
    print(dim("  " + "─" * 80))
    for i, j in enumerate(jobs, 1):
        created = j["created_at"].strftime("%Y-%m-%d %H:%M:%S") if j["created_at"] else "?"
        segs = j["actual_segment_count"] or 0
        print(
            f"  {i:>3}  {_fmt_status(j['status']):<13}  "   # status has ANSI escapes, pad after
            f" {created:<20} {j['language'] or '?':<7} {segs:>5}  "
            f"{dim(str(j['id']))}"
        )
    print()


def prompt_selection(jobs: list[dict]) -> dict:
    while True:
        try:
            raw = input(bold("Select job number (or q to quit): ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        if raw.lower() in ("q", "quit", "exit"):
            sys.exit(0)
        try:
            idx = int(raw)
            if 1 <= idx <= len(jobs):
                return jobs[idx - 1]
        except ValueError:
            pass
        print(red(f"  Enter a number between 1 and {len(jobs)}"))


# ---------------------------------------------------------------------------
# Validation framework
# ---------------------------------------------------------------------------

class Result:
    def __init__(self, label: str, icon: str, detail: str = ""):
        self.label = label
        self.icon = icon
        self.detail = detail

    def is_fail(self) -> bool:
        return self.icon == FAIL

    def is_warn(self) -> bool:
        return self.icon == WARN


def _ok(label: str, detail: str = "") -> Result:
    return Result(label, PASS, detail)

def _fail(label: str, detail: str = "") -> Result:
    return Result(label, FAIL, detail)

def _warn(label: str, detail: str = "") -> Result:
    return Result(label, WARN, detail)

def _skip(label: str, detail: str = "") -> Result:
    return Result(label, SKIP, detail)


def print_results(section: str, results: list[Result]) -> int:
    """Print a validation section. Returns count of failures."""
    failures = sum(1 for r in results if r.is_fail())
    warnings = sum(1 for r in results if r.is_warn())
    header_icon = FAIL if failures else (WARN if warnings else PASS)
    print(f"\n  {header_icon}  {bold(section)}")
    for r in results:
        detail = f"  {dim(r.detail)}" if r.detail else ""
        print(f"      {r.icon}  {r.label}{detail}")
    return failures


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_job_record(job: dict) -> list[Result]:
    results = []

    valid_statuses = {"pending", "transcribing", "matching", "complete", "failed"}
    if job["status"] in valid_statuses:
        results.append(_ok("status is valid", job["status"]))
    else:
        results.append(_fail("status is valid", f"got {job['status']!r}"))

    if job["audio_s3_key"]:
        results.append(_ok("audio_s3_key set", job["audio_s3_key"]))
    else:
        results.append(_fail("audio_s3_key set"))

    if job["language"]:
        results.append(_ok("language set", job["language"]))
    else:
        results.append(_warn("language not set"))

    # timestamp ordering
    created = job["created_at"]
    updated = job["updated_at"]
    completed = job["completed_at"]

    if created and updated:
        # make both offset-aware or both naive before comparing
        if created.tzinfo != updated.tzinfo:
            pass  # skip comparison if mixed tz-awareness
        elif updated >= created:
            results.append(_ok("updated_at ≥ created_at"))
        else:
            results.append(_fail("updated_at ≥ created_at", f"created={created}, updated={updated}"))

    if job["status"] == "complete":
        if completed:
            results.append(_ok("completed_at is set"))
        else:
            results.append(_fail("completed_at is set", "status=complete but completed_at is NULL"))
    elif job["status"] == "failed":
        if job["error_message"]:
            results.append(_ok("error_message set on failure", job["error_message"][:80]))
        else:
            results.append(_warn("error_message not set", "status=failed but error_message is NULL"))

    return results


def check_segments(conn, job: dict) -> list[Result]:
    results = []
    job_id = str(job["id"])
    status = job["status"]

    if status not in ("complete", "failed"):
        return [_skip("segment checks skipped", f"job status is {status!r}")]

    with _cursor(conn) as cur:
        cur.execute("""
            SELECT id, anonymous_label, speaker_profile_id,
                   start_time, end_time, text
            FROM transcript_segments
            WHERE job_id = %s
            ORDER BY start_time
        """, (job_id,))
        segs = [dict(r) for r in cur.fetchall()]

    actual = len(segs)
    claimed = job["total_segment_count"]

    if claimed is not None:
        if actual == claimed:
            results.append(_ok("segment count matches total_segment_count", str(actual)))
        else:
            results.append(_fail(
                "segment count matches total_segment_count",
                f"DB has {actual}, total_segment_count={claimed}"
            ))
    else:
        if actual > 0:
            results.append(_warn("total_segment_count is NULL", f"{actual} segments found"))
        else:
            results.append(_skip("total_segment_count", "NULL and no segments"))

    if not segs:
        if status == "complete":
            results.append(_fail("at least one segment exists"))
        return results

    results.append(_ok("at least one segment exists", f"{actual} total"))

    # timing sanity
    bad_timing = [s for s in segs if s["start_time"] >= s["end_time"]]
    if bad_timing:
        results.append(_fail(
            "all segments have start_time < end_time",
            f"{len(bad_timing)} violation(s): e.g. [{bad_timing[0]['start_time']:.3f}, {bad_timing[0]['end_time']:.3f}]"
        ))
    else:
        results.append(_ok("all segments have start_time < end_time"))

    neg_times = [s for s in segs if s["start_time"] < 0 or s["end_time"] < 0]
    if neg_times:
        results.append(_fail("no negative timestamps", f"{len(neg_times)} segment(s) with t < 0"))
    else:
        results.append(_ok("no negative timestamps"))

    # non-empty text
    empty_text = [s for s in segs if not (s["text"] or "").strip()]
    if empty_text:
        results.append(_warn("all segments have non-empty text", f"{len(empty_text)} empty"))
    else:
        results.append(_ok("all segments have non-empty text"))

    # label format
    valid_label = re.compile(r"^(SPEAKER_\d+|TURN_\d+|OVERLAP)$")
    bad_labels = [s for s in segs if not valid_label.match(s.get("anonymous_label") or "")]
    if bad_labels:
        results.append(_warn(
            "all anonymous_labels match expected pattern",
            f"{len(bad_labels)} unexpected: {bad_labels[0]['anonymous_label']!r}"
        ))
    else:
        results.append(_ok("all anonymous_labels match expected pattern"))

    # gap analysis — warn on gaps > 10 s between consecutive segments
    large_gaps = []
    for a, b in zip(segs, segs[1:]):
        gap = b["start_time"] - a["end_time"]
        if gap > 10.0:
            large_gaps.append((a["end_time"], b["start_time"], gap))
    if large_gaps:
        g = large_gaps[0]
        results.append(_warn(
            "no large gaps between segments (>10 s)",
            f"{len(large_gaps)} gap(s), largest at {g[0]:.1f}–{g[1]:.1f} s ({g[2]:.1f} s)"
        ))
    else:
        results.append(_ok("no large gaps between segments (>10 s)"))

    return results


def check_speaker_matching(conn, job: dict) -> list[Result]:
    results = []
    job_id = str(job["id"])
    speaker_ids = job.get("speaker_ids") or []

    if not speaker_ids:
        return [_skip("speaker matching checks skipped", "no speaker_ids on job")]

    with _cursor(conn) as cur:
        cur.execute("""
            SELECT COUNT(DISTINCT speaker_profile_id) AS matched_count
            FROM transcript_segments
            WHERE job_id = %s AND speaker_profile_id IS NOT NULL
        """, (job_id,))
        row = cur.fetchone()
        actual_matched = row["matched_count"] if row else 0

    claimed = job["matched_speaker_count"]
    if claimed is not None:
        if actual_matched == claimed:
            results.append(_ok("matched_speaker_count is accurate", str(actual_matched)))
        else:
            results.append(_fail(
                "matched_speaker_count is accurate",
                f"segments reference {actual_matched} distinct profiles, matched_speaker_count={claimed}"
            ))
    else:
        results.append(_warn("matched_speaker_count is NULL"))

    # referenced profiles actually exist
    with _cursor(conn) as cur:
        cur.execute("""
            SELECT DISTINCT s.speaker_profile_id
            FROM transcript_segments s
            WHERE s.job_id = %s AND s.speaker_profile_id IS NOT NULL
        """, (job_id,))
        ref_ids = [str(r["speaker_profile_id"]) for r in cur.fetchall()]

    if ref_ids:
        placeholders = ",".join(["%s"] * len(ref_ids))
        with _cursor(conn) as cur:
            cur.execute(
                f"SELECT id FROM speaker_profiles WHERE id IN ({placeholders})",
                ref_ids
            )
            found_ids = {str(r["id"]) for r in cur.fetchall()}
        missing = set(ref_ids) - found_ids
        if missing:
            results.append(_fail(
                "all referenced speaker profiles exist",
                f"missing: {', '.join(list(missing)[:3])}"
            ))
        else:
            results.append(_ok("all referenced speaker profiles exist", f"{len(ref_ids)} profile(s)"))

    # turn distances
    with _cursor(conn) as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM transcript_turn_distances WHERE job_id = %s",
            (job_id,)
        )
        td_count = cur.fetchone()["n"]

    if td_count > 0:
        results.append(_ok("turn distance records exist", f"{td_count} rows"))
        with _cursor(conn) as cur:
            cur.execute("""
                SELECT cosine_dist FROM transcript_turn_distances
                WHERE job_id = %s AND (cosine_dist < 0 OR cosine_dist > 2)
            """, (job_id,))
            bad = cur.fetchall()
        if bad:
            results.append(_fail(
                "all cosine_dist values in [0, 2]",
                f"{len(bad)} out-of-range value(s)"
            ))
        else:
            results.append(_ok("all cosine_dist values in [0, 2]"))
    else:
        results.append(_warn("no turn distance records found", "expected if speaker_ids were provided"))

    return results


def check_job_events(conn, job: dict) -> list[Result]:
    results = []
    job_id = str(job["id"])

    with _cursor(conn) as cur:
        cur.execute("""
            SELECT source, event, occurred_at
            FROM job_events
            WHERE job_id = %s
            ORDER BY occurred_at
        """, (job_id,))
        events = [dict(r) for r in cur.fetchall()]

    event_names = [e["event"] for e in events]

    if not events:
        if job["status"] in ("complete", "failed", "matching", "transcribing"):
            return [_warn("no job events recorded", "expected audit trail for this status")]
        return [_skip("no job events (job may not have been processed yet)")]

    results.append(_ok("job events present", f"{len(events)} event(s)"))

    # expected events by terminal status
    EXPECTED = {
        "complete": ["worker.received", "job.complete"],
        "failed":   ["worker.received", "job.failed"],
    }
    for expected in EXPECTED.get(job["status"], []):
        if expected in event_names:
            results.append(_ok(f"event '{expected}' recorded"))
        else:
            results.append(_fail(f"event '{expected}' recorded", f"found: {event_names}"))

    # chronological ordering
    timestamps = [e["occurred_at"] for e in events if e["occurred_at"]]
    for a, b in zip(timestamps, timestamps[1:]):
        # normalise tz-awareness before comparing
        if a.tzinfo and not b.tzinfo:
            break
        if not a.tzinfo and b.tzinfo:
            break
        if b < a:
            results.append(_fail("events are in chronological order", f"{a} → {b}"))
            break
    else:
        results.append(_ok("events are in chronological order"))

    # duplicate events
    from collections import Counter
    dupes = [ev for ev, n in Counter(event_names).items() if n > 1]
    if dupes:
        results.append(_warn("no duplicate events", f"duplicated: {dupes}"))
    else:
        results.append(_ok("no duplicate events"))

    return results


def check_local_files(job: dict) -> list[Result]:
    results = []

    local_storage = os.environ.get("LOCAL_STORAGE_PATH", "").strip()
    fixtures_dir = os.environ.get("DEV_FIXTURES_DIR", "").strip()
    job_id = str(job["id"])

    # audio file
    if local_storage:
        s3_key = job.get("audio_s3_key", "")
        audio_path = pathlib.Path(local_storage) / s3_key.lstrip("/")
        if audio_path.exists():
            size_kb = audio_path.stat().st_size // 1024
            if size_kb == 0:
                results.append(_fail("audio file exists and is non-empty", str(audio_path)))
            else:
                results.append(_ok("audio file exists and is non-empty", f"{audio_path} ({size_kb} KB)"))
        else:
            results.append(_warn("audio file not found", str(audio_path)))
    else:
        results.append(_skip("LOCAL_STORAGE_PATH not set — skipping audio file check"))

    # fixture files
    if fixtures_dir:
        job_fixtures = pathlib.Path(fixtures_dir) / job_id
        if job_fixtures.exists():
            results.append(_ok("fixture directory exists", str(job_fixtures)))
            for stage in ("transcribe", "diarize", "matcher"):
                fp = job_fixtures / f"{stage}.json"
                if fp.exists():
                    try:
                        data = json.loads(fp.read_text())
                        if isinstance(data, (list, dict)) and data:
                            results.append(_ok(f"  {stage}.json is valid non-empty JSON"))
                        else:
                            results.append(_warn(f"  {stage}.json", "valid JSON but empty"))
                    except json.JSONDecodeError as exc:
                        results.append(_fail(f"  {stage}.json is valid JSON", str(exc)))
                else:
                    results.append(_skip(f"  {stage}.json not present", "fallback to synthetic data"))
        else:
            results.append(_skip("no fixture directory for this job", str(job_fixtures)))
    else:
        results.append(_skip("DEV_FIXTURES_DIR not set — skipping fixture checks"))

    return results


def check_traffic_json(job: dict) -> list[Result]:
    results = []
    job_id = str(job["id"])

    # look for traffic.json relative to this script (chat-vue/src/mocks/)
    script_dir = pathlib.Path(__file__).parent
    candidates = [
        script_dir.parent / "chat-vue" / "src" / "mocks" / "traffic.json",
    ]
    traffic_path = next((p for p in candidates if p.exists()), None)

    if traffic_path is None:
        return [_skip("traffic.json not found", "run window.__traffic.export() and place in chat-vue/src/mocks/")]

    try:
        entries = json.loads(traffic_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return [_fail("traffic.json is valid JSON", str(exc))]

    results.append(_ok("traffic.json is valid JSON", f"{len(entries)} entries"))

    # check for entries that reference this job_id
    job_entries = [
        e for e in entries
        if isinstance(e, dict) and job_id in json.dumps(e.get("response", ""))
    ]
    if job_entries:
        paths = sorted({e.get("path", "?") for e in job_entries})
        results.append(_ok(
            "job_id referenced in traffic.json responses",
            f"{len(job_entries)} entry/entries: {', '.join(paths[:5])}"
        ))
    else:
        results.append(_warn(
            "job_id not found in traffic.json responses",
            "this job may not have been recorded in the current snapshot"
        ))

    # check coverage: which transcription endpoints are in traffic.json
    transcribe_paths = {
        e.get("path", "").split("?")[0]
        for e in entries
        if isinstance(e, dict) and "/transcribe/" in (e.get("path") or "")
    }
    expected_paths = {
        "/api/v1/transcribe/jobs",
        f"/api/v1/transcribe/jobs/{job_id}",
        f"/api/v1/transcribe/jobs/{job_id}/confirm",
        f"/api/v1/transcribe/jobs/{job_id}/transcript",
    }
    missing_paths = expected_paths - transcribe_paths
    if missing_paths:
        results.append(_warn(
            "full transcription flow covered in traffic.json",
            f"missing endpoints: {', '.join(sorted(missing_paths))}"
        ))
    else:
        results.append(_ok("full transcription flow covered in traffic.json"))

    return results


# ---------------------------------------------------------------------------
# Run all checks for one job
# ---------------------------------------------------------------------------

def validate_job(conn, job: dict) -> int:
    """Run all validations. Returns total failure count."""
    job_id = str(job["id"])
    status = job["status"]

    print()
    print(bold("  " + "═" * 72))
    print(bold(f"  Validating job {job_id}"))
    print(f"  Status: {_fmt_status(status)}   Language: {job['language'] or '?'}   "
          f"Created: {job['created_at']}")
    if job.get("error_message"):
        print(f"  Error: {red(job['error_message'][:100])}")
    print(bold("  " + "═" * 72))

    total_failures = 0
    total_failures += print_results("Job record",            check_job_record(job))
    total_failures += print_results("Transcript segments",   check_segments(conn, job))
    total_failures += print_results("Speaker matching",      check_speaker_matching(conn, job))
    total_failures += print_results("Job event audit trail", check_job_events(conn, job))
    total_failures += print_results("Local files",           check_local_files(job))
    total_failures += print_results("MSW traffic.json",      check_traffic_json(job))

    print()
    if total_failures == 0:
        print(f"  {green('All checks passed.')}  (job {job_id})")
    else:
        print(f"  {red(f'{total_failures} check(s) failed.')}  (job {job_id})")
    print()

    return total_failures


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a local dev transcription job for structural consistency."
    )
    parser.add_argument("--env", default=None, help="Path to .env file (default: transcription-worker/.env)")
    parser.add_argument("--job-id", default=None, help="UUID of a specific job to validate")
    parser.add_argument("--all", action="store_true", help="Validate all jobs in the DB")
    args = parser.parse_args()

    # load env
    env_path = args.env or str(pathlib.Path(__file__).parent / ".env")
    _load_env_file(env_path)

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        sys.exit(red(
            "DATABASE_URL not set.\n"
            "  Set it in transcription-worker/.env or export it before running:\n"
            "    DATABASE_URL=postgresql+psycopg2://user:pass@localhost/chat-api python validate_mock_job.py"
        ))

    conn = _connect(database_url)

    jobs = fetch_jobs(conn)
    if not jobs:
        print(yellow("No transcription jobs found in the database."))
        sys.exit(0)

    if args.job_id:
        try:
            target_id = uuid.UUID(args.job_id)
        except ValueError:
            sys.exit(red(f"Invalid UUID: {args.job_id!r}"))
        job = fetch_job(conn, target_id)
        if not job:
            sys.exit(red(f"Job {args.job_id} not found."))
        selected = [job]
    elif args.all:
        selected = jobs
    else:
        print_job_table(jobs)
        selected = [prompt_selection(jobs)]

    total_failures = 0
    for job in selected:
        total_failures += validate_job(conn, job)

    conn.close()

    if len(selected) > 1:
        print(bold(f"  Summary: {len(selected)} job(s) validated, "
                   f"{total_failures} total failure(s)."))
        print()

    sys.exit(1 if total_failures else 0)


if __name__ == "__main__":
    main()
