# Compiled Transcripts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store one compiled transcript per transcription job (turn list + the matching settings that produced it), compiled lazily with server defaults on first read and re-compiled on demand, so the logged-in page, the download and the public demo all show the same thing.

**Architecture:** A pure `compile_turns` function in the API ports the browser's `computeTurns` rules; a `compiled_transcripts` table holds the result keyed by job. `TranscriptionService.get_transcript` and `PublicService.transcription_detail` both go through one `load_or_compile` helper. The Vue side keeps `computeTurns` for live slider preview, seeds the sliders from the embedded settings, and shows Re-compile only when they differ.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic + pytest (chat-api); Vue 3 + Pinia + vitest + @vue/test-utils (chat-vue).

**Spec:** `docs/superpowers/specs/2026-09-03-compiled-transcripts-design.md`

## Global Constraints

- Default settings: `cosine_dist_threshold=0.25`, `separation_min=0.0`, `quality_min=0.0`, `confidence_min=0.0`.
- Validation: `0 < cosine_dist_threshold <= 2`; the three minimums in `[0, 1]`; violations are 422.
- `match_type` ∈ `high | medium | low | none`; `label` is `"Unknown"` when `match_type` is `none`.
- Wire field name is `match_type` (snake_case). The Vue `ComputedTurn` keeps `matchType`; the store maps once on load.
- One compiled row per job; re-compile replaces it. No history.
- Worker is untouched. `failed` jobs are never compiled. Jobs without turn-distance rows return `turns: null`.
- Run API tests from `chat-api/` with `uv run pytest tests/unit -q`. Run Vue tests from `chat-vue/` with `npm run test`. (Two auth specs may fail on a checkout with `VITE_DEV_AUTH_BYPASS=true` in `.env.local`; that is environment noise, not a regression.)
- Commit after every task. Commit messages end with:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01QFjyRToBef9ffJ73oBrMKn
  ```

## File map

**chat-api**
- Create `app/services/transcript_compiler.py` — `compile_turns`, `group_turn_distances`, `load_or_compile`, `compile_defaults`.
- Create `app/db/migrations/versions/v2w3x4y5z6a7_add_compiled_transcripts.py`.
- Create `tests/fixtures/compile_turns_cases.json` — shared fixture, also read by the Vue test.
- Create `tests/unit/services/test_transcript_compiler.py`.
- Modify `app/schemas/transcription.py` — `CompileSettings`, `CompiledTurn`, extended `TranscriptResponse`.
- Modify `app/schemas/public.py` — extended `PublicTranscriptionDetail`.
- Modify `app/models/transcription.py` — `CompiledTranscript`.
- Modify `app/repositories/transcription.py` — `get_compiled_transcript`, `upsert_compiled_transcript`.
- Modify `app/config.py` — four `compile_*` settings.
- Modify `app/services/transcription_service.py` — `get_transcript`, `compile_transcript`, `get_turn_distances` (reuse grouping).
- Modify `app/services/public_service.py`, `app/api/v1/public/deps.py`.
- Modify `app/api/v1/transcribe/jobs.py` — `POST /jobs/{id}/compile`.
- Modify tests: `tests/unit/services/test_transcription_service.py`, `tests/unit/api/test_transcribe_jobs.py`, `tests/unit/services/test_public_service.py`, `tests/unit/test_is_public_columns.py` (sibling model test).

**chat-vue**
- Modify `src/types/index.ts`, `src/lib/transcribeApi.ts`, `src/stores/transcribe.ts`.
- Modify `src/composables/useMatchingThresholds.ts` — `seedThresholds`, `currentSettings`, `settingsDiffer`, `compiledToComputed`.
- Create `src/composables/__tests__/useMatchingThresholds.spec.ts`.
- Modify `src/components/transcribe/RunDetailView.vue`, `MatchingAnalysis.vue`, `TranscriptDisplay.vue`, `src/views/DemoView.vue`.
- Modify tests: `src/stores/__tests__/transcribe.spec.ts`, `src/components/transcribe/__tests__/RunDetailView.spec.ts`, `src/views/__tests__/DemoView.spec.ts`; create `src/components/transcribe/__tests__/TranscriptDisplay.spec.ts`, `MatchingAnalysis.spec.ts`.

---

### Task 1: Schemas, the pure compile function, and the shared fixture

**Files:**
- Create: `chat-api/tests/fixtures/compile_turns_cases.json`
- Create: `chat-api/app/services/transcript_compiler.py`
- Create: `chat-api/tests/unit/services/test_transcript_compiler.py`
- Modify: `chat-api/app/schemas/transcription.py:116-118`

**Interfaces:**
- Produces `CompileSettings(BaseModel)` with fields `cosine_dist_threshold: float`, `separation_min: float`, `quality_min: float`, `confidence_min: float`, all defaulted to the global defaults.
- Produces `CompiledTurn(BaseModel)`: `start_time: float`, `end_time: float`, `text: str`, `label: str`, `match_type: Literal["high","medium","low","none"]`.
- Produces `TranscriptResponse` with `segments`, `turns: Optional[List[CompiledTurn]] = None`, `settings: CompileSettings = CompileSettings()`, `compiled_at: Optional[datetime] = None`.
- Produces `compile_turns(turns: list[dict], settings: CompileSettings) -> list[CompiledTurn]` where each input dict is `{"start_time", "end_time", "text", "candidates": [{"candidate_id", "speaker_name", "cosine_dist"}]}` (the same shape `TurnDistanceResponse` serialises to).

- [ ] **Step 1: Write the shared fixture**

Create `chat-api/tests/fixtures/compile_turns_cases.json`. Every case is `(turns, settings) → expected`. The numbers are chosen so each branch of the rules fires exactly once.

```json
{
  "cases": [
    {
      "name": "no candidates is unknown/none",
      "settings": {"cosine_dist_threshold": 0.25, "separation_min": 0.0, "quality_min": 0.0, "confidence_min": 0.0},
      "turns": [{"start_time": 0.0, "end_time": 1.0, "text": "a", "candidates": []}],
      "expected": [{"start_time": 0.0, "end_time": 1.0, "text": "a", "label": "Unknown", "match_type": "none"}]
    },
    {
      "name": "best within threshold is high",
      "settings": {"cosine_dist_threshold": 0.25, "separation_min": 0.0, "quality_min": 0.0, "confidence_min": 0.0},
      "turns": [{"start_time": 0.0, "end_time": 1.0, "text": "a", "candidates": [
        {"candidate_id": "c1", "speaker_name": "Jane", "cosine_dist": 0.20},
        {"candidate_id": "c2", "speaker_name": "Barry", "cosine_dist": 0.40}
      ]}],
      "expected": [{"start_time": 0.0, "end_time": 1.0, "text": "a", "label": "Jane", "match_type": "high"}]
    },
    {
      "name": "equal to threshold is still high",
      "settings": {"cosine_dist_threshold": 0.25, "separation_min": 0.0, "quality_min": 0.0, "confidence_min": 0.0},
      "turns": [{"start_time": 0.0, "end_time": 1.0, "text": "a", "candidates": [
        {"candidate_id": "c1", "speaker_name": "Jane", "cosine_dist": 0.25}
      ]}],
      "expected": [{"start_time": 0.0, "end_time": 1.0, "text": "a", "label": "Jane", "match_type": "high"}]
    },
    {
      "name": "above threshold with zero minimums is medium",
      "settings": {"cosine_dist_threshold": 0.25, "separation_min": 0.0, "quality_min": 0.0, "confidence_min": 0.0},
      "turns": [{"start_time": 1.0, "end_time": 2.0, "text": "b", "candidates": [
        {"candidate_id": "c1", "speaker_name": "Jane", "cosine_dist": 0.50},
        {"candidate_id": "c2", "speaker_name": "Barry", "cosine_dist": 0.30}
      ]}],
      "expected": [{"start_time": 1.0, "end_time": 2.0, "text": "b", "label": "Barry", "match_type": "medium"}]
    },
    {
      "name": "fails quality but passes separation is low",
      "settings": {"cosine_dist_threshold": 0.25, "separation_min": 0.1, "quality_min": 0.9, "confidence_min": 0.0},
      "turns": [{"start_time": 1.0, "end_time": 2.0, "text": "b", "candidates": [
        {"candidate_id": "c1", "speaker_name": "Jane", "cosine_dist": 0.50},
        {"candidate_id": "c2", "speaker_name": "Barry", "cosine_dist": 0.30}
      ]}],
      "expected": [{"start_time": 1.0, "end_time": 2.0, "text": "b", "label": "Barry", "match_type": "low"}]
    },
    {
      "name": "fails separation minimum is unknown/none",
      "settings": {"cosine_dist_threshold": 0.25, "separation_min": 0.5, "quality_min": 0.0, "confidence_min": 0.0},
      "turns": [{"start_time": 1.0, "end_time": 2.0, "text": "b", "candidates": [
        {"candidate_id": "c1", "speaker_name": "Jane", "cosine_dist": 0.50},
        {"candidate_id": "c2", "speaker_name": "Barry", "cosine_dist": 0.30}
      ]}],
      "expected": [{"start_time": 1.0, "end_time": 2.0, "text": "b", "label": "Unknown", "match_type": "none"}]
    },
    {
      "name": "tied candidates above threshold is unknown/none",
      "settings": {"cosine_dist_threshold": 0.25, "separation_min": 0.0, "quality_min": 0.0, "confidence_min": 0.0},
      "turns": [{"start_time": 1.0, "end_time": 2.0, "text": "b", "candidates": [
        {"candidate_id": "c1", "speaker_name": "Jane", "cosine_dist": 0.40},
        {"candidate_id": "c2", "speaker_name": "Barry", "cosine_dist": 0.40}
      ]}],
      "expected": [{"start_time": 1.0, "end_time": 2.0, "text": "b", "label": "Unknown", "match_type": "none"}]
    },
    {
      "name": "single candidate above threshold is unknown/none",
      "settings": {"cosine_dist_threshold": 0.25, "separation_min": 0.0, "quality_min": 0.0, "confidence_min": 0.0},
      "turns": [{"start_time": 1.0, "end_time": 2.0, "text": "b", "candidates": [
        {"candidate_id": "c1", "speaker_name": "Jane", "cosine_dist": 0.40}
      ]}],
      "expected": [{"start_time": 1.0, "end_time": 2.0, "text": "b", "label": "Unknown", "match_type": "none"}]
    },
    {
      "name": "null speaker name becomes Unknown label even on a match",
      "settings": {"cosine_dist_threshold": 0.25, "separation_min": 0.0, "quality_min": 0.0, "confidence_min": 0.0},
      "turns": [{"start_time": 0.0, "end_time": 1.0, "text": "a", "candidates": [
        {"candidate_id": "c1", "speaker_name": null, "cosine_dist": 0.10}
      ]}],
      "expected": [{"start_time": 0.0, "end_time": 1.0, "text": "a", "label": "Unknown", "match_type": "high"}]
    }
  ]
}
```

Check the "low" case by hand: best 0.30, runner-up 0.50 → separation = 1 − 0.30/0.50 = 0.4 ≥ 0.1; quality = 0.25/0.30 = 0.833 < 0.9 → not medium; separation passes → low.

- [ ] **Step 2: Write the failing test**

Create `chat-api/tests/unit/services/test_transcript_compiler.py`:

```python
"""compile_turns must agree with chat-vue's computeTurns; both read the same fixture file."""
import json
from pathlib import Path

import pytest

from app.schemas.transcription import CompileSettings, CompiledTurn
from app.services.transcript_compiler import compile_turns

CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "compile_turns_cases.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_compile_turns_matches_fixture(case):
    out = compile_turns(case["turns"], CompileSettings(**case["settings"]))
    assert [t.model_dump() for t in out] == case["expected"]


def test_compiled_turn_rejects_unknown_match_type():
    with pytest.raises(ValueError):
        CompiledTurn(start_time=0, end_time=1, text="a", label="x", match_type="great")


def test_compile_settings_defaults_and_bounds():
    s = CompileSettings()
    assert (s.cosine_dist_threshold, s.separation_min, s.quality_min, s.confidence_min) == (0.25, 0.0, 0.0, 0.0)
    for bad in (
        {"cosine_dist_threshold": 0},
        {"cosine_dist_threshold": 2.01},
        {"separation_min": -0.1},
        {"quality_min": 1.1},
        {"confidence_min": 2},
    ):
        with pytest.raises(ValueError):
            CompileSettings(**bad)
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd chat-api && uv run pytest tests/unit/services/test_transcript_compiler.py -q`
Expected: ImportError on `CompileSettings` / `transcript_compiler`.

- [ ] **Step 4: Add the schemas**

In `chat-api/app/schemas/transcription.py`, add `Literal` to the `typing` import and `Field` to the pydantic import if missing, then replace the `TranscriptResponse` block with:

```python
# ── Compiled transcript ───────────────────────────────────────────────────────

MatchType = Literal["high", "medium", "low", "none"]


class CompileSettings(BaseModel):
    """The matching thresholds a compiled transcript was produced with."""
    cosine_dist_threshold: float = Field(0.25, gt=0, le=2)
    separation_min: float = Field(0.0, ge=0, le=1)
    quality_min: float = Field(0.0, ge=0, le=1)
    confidence_min: float = Field(0.0, ge=0, le=1)


class CompiledTurn(BaseModel):
    start_time: float
    end_time: float
    text: str
    label: str            # speaker name, or "Unknown"
    match_type: MatchType


class TranscriptResponse(BaseModel):
    segments: List[SegmentResponse]
    turns: Optional[List[CompiledTurn]] = None   # None: job has no turn-distance data
    settings: CompileSettings = Field(default_factory=CompileSettings)
    compiled_at: Optional[datetime] = None
```

Make sure `datetime` is imported at the top of the schema module (`from datetime import datetime`); it already is if `JobStatusResponse` uses it.

- [ ] **Step 5: Write the compile function**

Create `chat-api/app/services/transcript_compiler.py`:

```python
"""Turn a job's per-turn candidate distances into a labelled transcript.

`compile_turns` is a line-for-line port of `computeTurns` in
chat-vue/src/composables/useMatchingThresholds.ts. Both are tested against
chat-api/tests/fixtures/compile_turns_cases.json — change one, change both.
"""
from app.schemas.transcription import CompiledTurn, CompileSettings


def compile_turns(turns: list[dict], settings: CompileSettings) -> list[CompiledTurn]:
    out: list[CompiledTurn] = []
    for turn in turns:
        base = {"start_time": turn["start_time"], "end_time": turn["end_time"], "text": turn["text"]}
        ranked = sorted(turn["candidates"], key=lambda c: c["cosine_dist"])
        if not ranked:
            out.append(CompiledTurn(**base, label="Unknown", match_type="none"))
            continue
        best = ranked[0]
        name = best["speaker_name"] or "Unknown"
        if best["cosine_dist"] <= settings.cosine_dist_threshold:
            out.append(CompiledTurn(**base, label=name, match_type="high"))
            continue
        if len(ranked) >= 2 and ranked[1]["cosine_dist"] > best["cosine_dist"]:
            separation = 1 - best["cosine_dist"] / ranked[1]["cosine_dist"]
            quality = settings.cosine_dist_threshold / best["cosine_dist"]
            confidence = separation * quality
            if (
                separation >= settings.separation_min
                and quality >= settings.quality_min
                and confidence >= settings.confidence_min
            ):
                out.append(CompiledTurn(**base, label=name, match_type="medium"))
                continue
            if separation >= settings.separation_min:
                out.append(CompiledTurn(**base, label=name, match_type="low"))
                continue
        out.append(CompiledTurn(**base, label="Unknown", match_type="none"))
    return out
```

- [ ] **Step 6: Run the tests**

Run: `cd chat-api && uv run pytest tests/unit/services/test_transcript_compiler.py tests/unit -q`
Expected: all pass (the new file plus the existing 333).

- [ ] **Step 7: Commit**

```bash
git add chat-api/app/schemas/transcription.py chat-api/app/services/transcript_compiler.py chat-api/tests/fixtures/compile_turns_cases.json chat-api/tests/unit/services/test_transcript_compiler.py
git commit -m "feat(chat-api): compile_turns and compiled-transcript schemas"
```

---

### Task 2: Model, migration, repository

**Files:**
- Modify: `chat-api/app/models/transcription.py` (after `TranscriptTurnDistance`, before `TranscriptionJobEvent`)
- Create: `chat-api/app/db/migrations/versions/v2w3x4y5z6a7_add_compiled_transcripts.py`
- Modify: `chat-api/app/repositories/transcription.py` (after `get_turn_distances`)
- Create: `chat-api/tests/unit/test_compiled_transcript_model.py`

**Interfaces:**
- Produces model `CompiledTranscript` with `job_id`, `settings: dict`, `turns: list`, `compiled_at: datetime`.
- Produces `TranscriptionRepository.get_compiled_transcript(job_id: UUID) -> Optional[CompiledTranscript]`.
- Produces `TranscriptionRepository.upsert_compiled_transcript(job_id: UUID, settings: dict, turns: list[dict], compiled_at: datetime) -> CompiledTranscript` (adds/updates on the session; caller commits).

- [ ] **Step 1: Write the failing model test**

Create `chat-api/tests/unit/test_compiled_transcript_model.py`:

```python
from app.models.transcription import CompiledTranscript


def test_compiled_transcript_table_shape():
    t = CompiledTranscript.__table__
    assert t.name == "compiled_transcripts"
    assert t.c.job_id.unique is True
    fk = next(iter(t.c.job_id.foreign_keys))
    assert fk.column.table.name == "transcription_jobs" and fk.ondelete == "CASCADE"
    assert t.c.settings.nullable is False
    assert t.c.turns.nullable is False
    assert t.c.compiled_at.nullable is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd chat-api && uv run pytest tests/unit/test_compiled_transcript_model.py -q`
Expected: ImportError `CompiledTranscript`.

- [ ] **Step 3: Add the model**

In `chat-api/app/models/transcription.py`, after the `TranscriptTurnDistance` class:

```python
class CompiledTranscript(UUIDMixin, Base):
    """One per job: the turn list produced by `compile_turns` plus the settings it used."""
    __tablename__ = "compiled_transcripts"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transcription_jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    settings: Mapped[dict] = mapped_column(JSON, nullable=False)
    turns: Mapped[list] = mapped_column(JSON, nullable=False)
    compiled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

- [ ] **Step 4: Write the migration**

Create `chat-api/app/db/migrations/versions/v2w3x4y5z6a7_add_compiled_transcripts.py`:

```python
"""add compiled_transcripts (one compiled turn list + settings per transcription job)

Revision ID: v2w3x4y5z6a7
Revises: u1v2w3x4y5z6
Create Date: 2026-09-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "v2w3x4y5z6a7"
down_revision: Union[str, None] = "u1v2w3x4y5z6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compiled_transcripts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transcription_jobs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("turns", sa.JSON(), nullable=False),
        sa.Column("compiled_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("compiled_transcripts")
```

`UUIDMixin` gives `id` a client-side `uuid.uuid4` default and no server default, so the `id` column above needs none.

- [ ] **Step 5: Add the repository methods**

In `chat-api/app/repositories/transcription.py`, import `CompiledTranscript` from `app.models.transcription` and add after `get_turn_distances`:

```python
    async def get_compiled_transcript(self, job_id: UUID) -> Optional[CompiledTranscript]:
        result = await self.db.execute(
            select(CompiledTranscript).where(CompiledTranscript.job_id == job_id)
        )
        return result.scalar_one_or_none()

    async def upsert_compiled_transcript(
        self, job_id: UUID, settings: dict, turns: list[dict], compiled_at: datetime
    ) -> CompiledTranscript:
        """Replace the job's compiled transcript (one row per job). Caller commits."""
        row = await self.get_compiled_transcript(job_id)
        if row is None:
            row = CompiledTranscript(job_id=job_id, settings=settings, turns=turns, compiled_at=compiled_at)
            self.db.add(row)
        else:
            row.settings = settings
            row.turns = turns
            row.compiled_at = compiled_at
        await self.db.flush()
        return row
```

Make sure `datetime` is imported in the repository module (`from datetime import datetime`).

- [ ] **Step 6: Run the tests**

Run: `cd chat-api && uv run pytest tests/unit -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add chat-api/app/models/transcription.py chat-api/app/db/migrations/versions/v2w3x4y5z6a7_add_compiled_transcripts.py chat-api/app/repositories/transcription.py chat-api/tests/unit/test_compiled_transcript_model.py
git commit -m "feat(chat-api): compiled_transcripts table, model and repository"
```

---

### Task 3: Lazy compile on read, explicit re-compile in the service

**Files:**
- Modify: `chat-api/app/config.py` (after `gpu_scale_in_seconds`)
- Modify: `chat-api/app/services/transcript_compiler.py`
- Modify: `chat-api/app/services/transcription_service.py` (`get_transcript`, `get_turn_distances`, new `compile_transcript`)
- Modify: `chat-api/tests/unit/services/test_transcription_service.py` (`make_service`, `TestGetTranscript`, new `TestCompileTranscript`)

**Interfaces:**
- Consumes `compile_turns`, `CompileSettings`, `CompiledTurn`, repo methods from Tasks 1–2.
- Produces `compile_defaults(settings) -> CompileSettings` (reads the four `compile_*` config values).
- Produces `group_turn_distances(rows) -> list[dict]` (rows are `(TranscriptTurnDistance, speaker_name)` tuples as returned by `repo.get_turn_distances`).
- Produces `async load_or_compile(repo, job_id, defaults, *, force=None) -> Optional[CompiledTranscript]` — returns the stored row, or compiles (with `force` if given, else `defaults`) and upserts; returns `None` when the job has no turn-distance rows. Does **not** commit.
- Produces `TranscriptionService.compile_transcript(user_id, job_id, settings: CompileSettings) -> TranscriptResponse`.
- Produces a module-level helper `transcript_response(segments, compiled, defaults) -> TranscriptResponse` used by both services.

- [ ] **Step 1: Write the failing service tests**

In `chat-api/tests/unit/services/test_transcription_service.py`:

Extend `make_service` (inside the function, next to the other repo mocks):

```python
    repo.get_turn_distances = AsyncMock(return_value=[])
    repo.get_compiled_transcript = AsyncMock(return_value=None)
    # Behaves like the real upsert: hands back a row carrying what was written.
    repo.upsert_compiled_transcript = AsyncMock(side_effect=lambda **kw: MagicMock(**kw))
```

and to the `settings` block:

```python
    settings.compile_cosine_dist_threshold = 0.25
    settings.compile_separation_min = 0.0
    settings.compile_quality_min = 0.0
    settings.compile_confidence_min = 0.0
```

Add a module-level helper after `make_service`:

```python
def turn_row(start, end, text, cand_id, name, dist):
    td = MagicMock(start_time=start, end_time=end, text=text, candidate_id=cand_id, cosine_dist=dist)
    return (td, name)


def complete_job(job_id=None):
    j = MagicMock()
    j.id = job_id or uuid4()
    j.status = "complete"
    j.transcribe_output_s3_key = "k"
    return j
```

Add to `TestGetTranscript`:

```python
    async def test_no_turn_data_returns_null_turns_with_defaults(self):
        service, repo, *_ = make_service()
        repo.get_job.return_value = complete_job()
        repo.get_segments.return_value = []

        res = await service.get_transcript("user1", uuid4())

        assert res.turns is None and res.compiled_at is None
        assert res.settings.cosine_dist_threshold == 0.25
        repo.upsert_compiled_transcript.assert_not_awaited()

    async def test_first_read_compiles_with_defaults_and_stores(self):
        service, repo, *_ = make_service()
        job = complete_job()
        repo.get_job.return_value = job
        repo.get_segments.return_value = []
        c1, c2 = uuid4(), uuid4()
        repo.get_turn_distances.return_value = [
            turn_row(0.0, 1.0, "hi", c1, "Jane", 0.1),
            turn_row(0.0, 1.0, "hi", c2, "Barry", 0.6),
        ]

        res = await service.get_transcript("user1", job.id)

        args = repo.upsert_compiled_transcript.await_args.kwargs
        assert args["job_id"] == job.id
        assert args["settings"] == {"cosine_dist_threshold": 0.25, "separation_min": 0.0, "quality_min": 0.0, "confidence_min": 0.0}
        assert args["turns"] == [{"start_time": 0.0, "end_time": 1.0, "text": "hi", "label": "Jane", "match_type": "high"}]
        assert res.turns[0].label == "Jane" and res.turns[0].match_type == "high"
        assert res.compiled_at == args["compiled_at"]
        repo.db.commit.assert_awaited()

    async def test_stored_compiled_row_is_returned_without_recompiling(self):
        service, repo, *_ = make_service()
        repo.get_job.return_value = complete_job()
        repo.get_segments.return_value = []
        when = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
        repo.get_compiled_transcript.return_value = MagicMock(
            settings={"cosine_dist_threshold": 0.3, "separation_min": 0.1, "quality_min": 0.0, "confidence_min": 0.0},
            turns=[{"start_time": 0.0, "end_time": 1.0, "text": "hi", "label": "Barry", "match_type": "medium"}],
            compiled_at=when,
        )

        res = await service.get_transcript("user1", uuid4())

        assert res.settings.cosine_dist_threshold == 0.3
        assert res.turns[0].label == "Barry" and res.compiled_at == when
        repo.get_turn_distances.assert_not_awaited()
        repo.upsert_compiled_transcript.assert_not_awaited()

    async def test_failed_job_with_partial_segments_is_never_compiled(self):
        service, repo, *_ = make_service()
        job = complete_job()
        job.status = "failed"
        repo.get_job.return_value = job
        repo.get_segments.return_value = []
        repo.get_turn_distances.return_value = [turn_row(0.0, 1.0, "hi", uuid4(), "Jane", 0.1)]

        res = await service.get_transcript("user1", uuid4())

        assert res.turns is None
        repo.upsert_compiled_transcript.assert_not_awaited()
```

Add a new class after `TestGetTranscript`:

```python
class TestCompileTranscript:
    async def test_recompile_replaces_row_and_records_event(self):
        from app.schemas.transcription import CompileSettings

        service, repo, *_ = make_service()
        job = complete_job()
        repo.get_job.return_value = job
        repo.get_segments.return_value = []
        repo.get_turn_distances.return_value = [
            turn_row(0.0, 1.0, "hi", uuid4(), "Jane", 0.5),
            turn_row(0.0, 1.0, "hi", uuid4(), "Barry", 0.3),
        ]
        repo.get_compiled_transcript.return_value = MagicMock(settings={}, turns=[], compiled_at=None)
        settings = CompileSettings(cosine_dist_threshold=0.2, separation_min=0.5)

        res = await service.compile_transcript("user1", job.id, settings)

        args = repo.upsert_compiled_transcript.await_args.kwargs
        assert args["settings"]["separation_min"] == 0.5
        assert args["turns"][0]["match_type"] == "none"   # separation 0.4 < 0.5
        assert res.settings.separation_min == 0.5
        repo.append_event.assert_any_await(job.id, "api", "transcript.compiled", settings.model_dump())
        repo.db.commit.assert_awaited()

    async def test_409_when_job_not_complete(self):
        from app.schemas.transcription import CompileSettings

        service, repo, *_ = make_service()
        job = complete_job()
        job.status = "transcribing"
        repo.get_job.return_value = job
        with pytest.raises(ConflictError):
            await service.compile_transcript("user1", job.id, CompileSettings())

    async def test_409_when_no_turn_data(self):
        from app.schemas.transcription import CompileSettings

        service, repo, *_ = make_service()
        repo.get_job.return_value = complete_job()
        repo.get_turn_distances.return_value = []
        with pytest.raises(ConflictError):
            await service.compile_transcript("user1", uuid4(), CompileSettings())

    async def test_404_for_unknown_job(self):
        from app.schemas.transcription import CompileSettings

        service, repo, *_ = make_service()
        repo.get_job.return_value = None
        with pytest.raises(NotFoundError):
            await service.compile_transcript("user1", uuid4(), CompileSettings())
```

Make sure `datetime, timezone` and `NotFoundError` are imported at the top of the test file (check the existing imports; add what is missing).

- [ ] **Step 2: Run to verify they fail**

Run: `cd chat-api && uv run pytest tests/unit/services/test_transcription_service.py -q -k "TestGetTranscript or TestCompileTranscript"`
Expected: the four new `TestGetTranscript` tests fail on missing `turns`/`upsert` behaviour; `TestCompileTranscript` fails with AttributeError `compile_transcript`.

- [ ] **Step 3: Add the config values**

In `chat-api/app/config.py`, after `gpu_scale_in_seconds`:

```python
    # Defaults for compiling a transcript from turn distances (see transcript_compiler.py).
    # Must stay equal to the CompileSettings field defaults and the chat-vue slider defaults.
    compile_cosine_dist_threshold: float = 0.25
    compile_separation_min: float = 0.0
    compile_quality_min: float = 0.0
    compile_confidence_min: float = 0.0
```

- [ ] **Step 4: Add the shared helpers to the compiler module**

Append to `chat-api/app/services/transcript_compiler.py`:

```python
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from app.schemas.transcription import SegmentResponse, TranscriptResponse


def compile_defaults(settings) -> CompileSettings:
    return CompileSettings(
        cosine_dist_threshold=settings.compile_cosine_dist_threshold,
        separation_min=settings.compile_separation_min,
        quality_min=settings.compile_quality_min,
        confidence_min=settings.compile_confidence_min,
    )


def group_turn_distances(rows) -> list[dict]:
    """(TranscriptTurnDistance, speaker_name) rows → one dict per turn with its candidates,
    in start-time order. The same shape TurnDistanceResponse serialises to."""
    turns: dict[tuple, dict] = {}
    for td, speaker_name in rows:
        key = (td.start_time, td.end_time)
        if key not in turns:
            turns[key] = {"start_time": td.start_time, "end_time": td.end_time, "text": td.text, "candidates": []}
        turns[key]["candidates"].append(
            {"candidate_id": td.candidate_id, "speaker_name": speaker_name, "cosine_dist": td.cosine_dist}
        )
    return list(turns.values())


async def load_or_compile(repo, job_id: UUID, defaults: CompileSettings, *, force: Optional[CompileSettings] = None):
    """The job's compiled transcript row. With `force`, always recompile with those settings;
    otherwise return the stored row, compiling with `defaults` on first read.
    None when the job has no turn-distance rows. Caller commits."""
    if force is None:
        row = await repo.get_compiled_transcript(job_id)
        if row is not None:
            return row
    grouped = group_turn_distances(await repo.get_turn_distances(job_id))
    if not grouped:
        return None
    settings = force or defaults
    turns = [t.model_dump() for t in compile_turns(grouped, settings)]
    return await repo.upsert_compiled_transcript(
        job_id=job_id, settings=settings.model_dump(), turns=turns, compiled_at=datetime.now(timezone.utc)
    )


def transcript_response(segments: list[SegmentResponse], compiled, defaults: CompileSettings) -> TranscriptResponse:
    if compiled is None:
        return TranscriptResponse(segments=segments, turns=None, settings=defaults, compiled_at=None)
    return TranscriptResponse(
        segments=segments,
        turns=[CompiledTurn(**t) for t in compiled.turns],
        settings=CompileSettings(**compiled.settings),
        compiled_at=compiled.compiled_at,
    )
```

Move the imports to the top of the module and keep them tidy (one import block).

- [ ] **Step 5: Wire the service**

In `chat-api/app/services/transcription_service.py`:

Import at top:

```python
from app.schemas.transcription import CompileSettings  # add to the existing schema import list
from app.services.transcript_compiler import compile_defaults, group_turn_distances, load_or_compile, transcript_response
```

Replace the body of `get_transcript` from `segments = await self._repo.get_segments(job_id)` to the end with:

```python
        segments = await self._repo.get_segments(job_id)
        segment_responses = [self._segment_response(seg) for seg in segments]
        if job.status == "complete":
            compiled = await load_or_compile(self._repo, job_id, self._compile_defaults())
            await self._repo.db.commit()
            return transcript_response(segment_responses, compiled, self._compile_defaults())
        # failed with partial data: never compiled
        if job.transcribe_output_s3_key:
            return transcript_response(segment_responses, None, self._compile_defaults())
        raise ConflictError("No transcript available")
```

Add these methods next to `get_transcript`:

```python
    def _compile_defaults(self) -> CompileSettings:
        return compile_defaults(self._settings)

    @staticmethod
    def _segment_response(seg) -> SegmentResponse:
        return SegmentResponse(
            segment_id=seg.id,
            anonymous_label=seg.anonymous_label,
            speaker_name=seg.speaker_profile.speaker_name if seg.speaker_profile is not None else None,
            start_time=seg.start_time,
            end_time=seg.end_time,
            text=seg.text,
        )

    async def compile_transcript(self, user_id: str, job_id: UUID, settings: CompileSettings) -> TranscriptResponse:
        """Re-compile with `settings`, replacing the stored transcript."""
        job = await self._repo.get_job(job_id, user_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        if job.status != "complete":
            raise ConflictError("Transcript can only be compiled for a complete job")
        compiled = await load_or_compile(self._repo, job_id, self._compile_defaults(), force=settings)
        if compiled is None:
            raise ConflictError("This job has no matching data to compile")
        await self._repo.append_event(job_id, "api", "transcript.compiled", settings.model_dump())
        await self._repo.db.commit()
        segments = [self._segment_response(seg) for seg in await self._repo.get_segments(job_id)]
        return transcript_response(segments, compiled, self._compile_defaults())
```

Replace the grouping loop in `get_turn_distances` with the shared helper:

```python
    async def get_turn_distances(self, user_id: str, job_id: UUID) -> TurnDistancesResponse:
        job = await self._repo.get_job(job_id, user_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        grouped = group_turn_distances(await self._repo.get_turn_distances(job_id))
        return TurnDistancesResponse(turns=[TurnDistanceResponse(**t) for t in grouped])
```

`TurnCandidateResponse` is no longer referenced from the service after this; remove it from the import list if it is now unused (pydantic builds it from the dicts).

- [ ] **Step 6: Run the tests**

Run: `cd chat-api && uv run pytest tests/unit -q`
Expected: all pass, including the existing `TestGetTranscript` and turn-distance tests.

- [ ] **Step 7: Commit**

```bash
git add chat-api/app/config.py chat-api/app/services/transcript_compiler.py chat-api/app/services/transcription_service.py chat-api/tests/unit/services/test_transcription_service.py
git commit -m "feat(chat-api): compile transcripts lazily on read, re-compile on demand"
```

---

### Task 4: `POST /jobs/{id}/compile` endpoint

**Files:**
- Modify: `chat-api/app/api/v1/transcribe/jobs.py` (after `get_transcript`)
- Modify: `chat-api/tests/unit/api/test_transcribe_jobs.py`

**Interfaces:**
- Consumes `TranscriptionService.compile_transcript` and `CompileSettings` from Task 3.
- Produces `POST /api/v1/transcribe/jobs/{job_id}/compile`, body `CompileSettings`, response `TranscriptResponse`.

- [ ] **Step 1: Write the failing endpoint tests**

In `chat-api/tests/unit/api/test_transcribe_jobs.py`, add `CompileSettings` to the schema imports, add to `make_mock_service`:

```python
    svc.compile_transcript = AsyncMock(return_value=TranscriptResponse(segments=[]))
```

and a new test class (follow the existing `client` fixture and class layout in the file):

```python
class TestCompileTranscript:
    HEADERS = {"Authorization": "Bearer fake-token"}

    async def test_posts_settings_and_returns_transcript(self, client):
        ac, svc = client
        job_id = uuid4()
        body = {"cosine_dist_threshold": 0.3, "separation_min": 0.1, "quality_min": 0.0, "confidence_min": 0.0}
        res = await ac.post(f"/api/v1/transcribe/jobs/{job_id}/compile", json=body, headers=self.HEADERS)
        assert res.status_code == 200
        assert "turns" in res.json() and "settings" in res.json()
        _user, jid, settings = svc.compile_transcript.await_args.args
        assert jid == job_id and settings == CompileSettings(**body)

    async def test_422_on_out_of_range_settings(self, client):
        ac, _ = client
        res = await ac.post(
            f"/api/v1/transcribe/jobs/{uuid4()}/compile",
            json={"cosine_dist_threshold": 0, "separation_min": 0, "quality_min": 0, "confidence_min": 0},
            headers=self.HEADERS,
        )
        assert res.status_code == 422

    async def test_409_when_service_conflicts(self, client):
        ac, svc = client
        svc.compile_transcript.side_effect = ConflictError("no matching data")
        res = await ac.post(f"/api/v1/transcribe/jobs/{uuid4()}/compile", json={}, headers=self.HEADERS)
        assert res.status_code == 409
```

The `client` fixture in this file yields a `(client, mock_service)` tuple; the existing tests unpack it the same way.

- [ ] **Step 2: Run to verify they fail**

Run: `cd chat-api && uv run pytest tests/unit/api/test_transcribe_jobs.py -q -k TestCompileTranscript`
Expected: 404/405 on the route.

- [ ] **Step 3: Add the route**

In `chat-api/app/api/v1/transcribe/jobs.py`, add `CompileSettings` to the schema import list and after `get_transcript`:

```python
@router.post("/jobs/{job_id}/compile", response_model=TranscriptResponse)
async def compile_transcript(
    job_id: UUID,
    settings: CompileSettings,
    current_user: dict = Depends(get_current_user),
    service: TranscriptionService = Depends(get_transcription_service),
) -> TranscriptResponse:
    """Re-compile the transcript with these matching settings, replacing the stored one."""
    return await service.compile_transcript(current_user["sub"], job_id, settings)
```

- [ ] **Step 4: Run the tests**

Run: `cd chat-api && uv run pytest tests/unit -q`
Expected: all pass.

- [ ] **Step 5: Document the endpoint**

In `chat-api/CLAUDE.md`, find the line that documents `GET /jobs/{id}/turn-distances` (grep `turn-distances`) and add directly under it:

```
- `POST /api/v1/transcribe/jobs/{id}/compile` — body `CompileSettings`; re-compiles the stored transcript (see `services/transcript_compiler.py`). `GET …/transcript` compiles lazily with the `compile_*` defaults on first read.
```

- [ ] **Step 6: Commit**

```bash
git add chat-api/app/api/v1/transcribe/jobs.py chat-api/tests/unit/api/test_transcribe_jobs.py chat-api/CLAUDE.md
git commit -m "feat(chat-api): POST /transcribe/jobs/{id}/compile"
```

---

### Task 5: Public transcription detail carries the compiled transcript

**Files:**
- Modify: `chat-api/app/schemas/public.py:45-46`
- Modify: `chat-api/app/services/public_service.py` (`__init__`, `transcription_detail`)
- Modify: `chat-api/app/api/v1/public/deps.py`
- Modify: `chat-api/tests/unit/services/test_public_service.py`

**Interfaces:**
- Consumes `load_or_compile`, `transcript_response`, `compile_defaults` from Task 3.
- Produces `PublicService(scans, transcriptions, conversations, storage, compile_defaults: CompileSettings | None = None)`.
- Produces `PublicTranscriptionDetail` with `turns`, `settings`, `compiled_at` (same semantics as `TranscriptResponse`).

- [ ] **Step 1: Write the failing tests**

Append to `chat-api/tests/unit/services/test_public_service.py`:

```python
from app.schemas.transcription import CompileSettings


def turn_row(start, end, text, cand_id, name, dist):
    td = MagicMock(start_time=start, end_time=end, text=text, candidate_id=cand_id, cosine_dist=dist)
    return (td, name)


async def test_transcription_detail_compiles_lazily_and_returns_turns():
    svc, _, transcriptions, _, _ = make_service()
    job = MagicMock(id=uuid4(), created_at=datetime.now(timezone.utc), matched_speaker_count=1)
    transcriptions.get_public_job.return_value = job
    transcriptions.get_segment_stats.return_value = (1.0, 1)
    transcriptions.get_segments.return_value = []
    transcriptions.get_compiled_transcript.return_value = None
    transcriptions.get_turn_distances.return_value = [turn_row(0.0, 1.0, "hi", uuid4(), "Jane", 0.1)]
    transcriptions.upsert_compiled_transcript.return_value = MagicMock(
        settings=CompileSettings().model_dump(),
        turns=[{"start_time": 0.0, "end_time": 1.0, "text": "hi", "label": "Jane", "match_type": "high"}],
        compiled_at=datetime.now(timezone.utc),
    )

    out = await svc.transcription_detail(job.id)

    assert out.turns[0].label == "Jane" and out.settings.cosine_dist_threshold == 0.25
    transcriptions.upsert_compiled_transcript.assert_awaited_once()
    transcriptions.db.commit.assert_awaited()


async def test_transcription_detail_without_turn_data_has_null_turns():
    svc, _, transcriptions, _, _ = make_service()
    job = MagicMock(id=uuid4(), created_at=datetime.now(timezone.utc), matched_speaker_count=None)
    transcriptions.get_public_job.return_value = job
    transcriptions.get_segment_stats.return_value = (None, 0)
    transcriptions.get_segments.return_value = []
    transcriptions.get_compiled_transcript.return_value = None
    transcriptions.get_turn_distances.return_value = []

    out = await svc.transcription_detail(job.id)

    assert out.turns is None and out.compiled_at is None
    transcriptions.upsert_compiled_transcript.assert_not_awaited()
```

Add `from datetime import datetime, timezone`, `from unittest.mock import MagicMock` and `from uuid import uuid4` at the top if they are not already imported.

- [ ] **Step 2: Run to verify they fail**

Run: `cd chat-api && uv run pytest tests/unit/services/test_public_service.py -q`
Expected: the two new tests fail (`turns` missing / AttributeError).

- [ ] **Step 3: Extend the schema**

In `chat-api/app/schemas/public.py`, import `CompiledTurn, CompileSettings` from `app.schemas.transcription` alongside `SegmentResponse`, and add `datetime` to the imports if missing:

```python
class PublicTranscriptionDetail(PublicTranscriptionSummary):
    segments: List[SegmentResponse] = Field(default_factory=list)
    turns: Optional[List[CompiledTurn]] = None
    settings: CompileSettings = Field(default_factory=CompileSettings)
    compiled_at: Optional[datetime] = None
```

- [ ] **Step 4: Update the service and its wiring**

In `chat-api/app/services/public_service.py`:

```python
from app.schemas.transcription import CompileSettings, SegmentResponse
from app.services.transcript_compiler import load_or_compile, transcript_response
```

Constructor:

```python
    def __init__(self, scans, transcriptions, conversations, storage, compile_defaults: CompileSettings | None = None):
        self._scans = scans
        self._transcriptions = transcriptions
        self._conversations = conversations
        self._storage = storage
        self._compile_defaults = compile_defaults or CompileSettings()
```

`transcription_detail` — replace the `return PublicTranscriptionDetail(...)` with:

```python
        compiled = await load_or_compile(self._transcriptions, job_id, self._compile_defaults)
        await self._transcriptions.db.commit()
        tr = transcript_response(segments, compiled, self._compile_defaults)
        return PublicTranscriptionDetail(
            **summary.model_dump(),
            segments=tr.segments,
            turns=tr.turns,
            settings=tr.settings,
            compiled_at=tr.compiled_at,
        )
```

In `chat-api/app/api/v1/public/deps.py`, import `compile_defaults` from `app.services.transcript_compiler` and pass `compile_defaults(s)` as the fifth argument to `PublicService(...)`.

- [ ] **Step 5: Run the tests**

Run: `cd chat-api && uv run pytest tests/unit -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add chat-api/app/schemas/public.py chat-api/app/services/public_service.py chat-api/app/api/v1/public/deps.py chat-api/tests/unit/services/test_public_service.py
git commit -m "feat(chat-api): public transcription detail returns the compiled transcript"
```

---

### Task 6: Vue types, API call, and the threshold composable

**Files:**
- Modify: `chat-vue/src/types/index.ts:251-253` and `:380-382`
- Modify: `chat-vue/src/lib/transcribeApi.ts` (after `getTranscript`)
- Modify: `chat-vue/src/composables/useMatchingThresholds.ts`
- Create: `chat-vue/src/composables/__tests__/useMatchingThresholds.spec.ts`

**Interfaces:**
- Produces types `CompileSettings`, `CompiledTurn`, `MatchType`; `TranscriptResponse` gains `turns: CompiledTurn[] | null`, `settings: CompileSettings`, `compiled_at: string | null`; `PublicTranscriptionDetail` gains the same three.
- Produces `compileTranscript(jobId: string, settings: CompileSettings): Promise<TranscriptResponse>`.
- Produces from the composable: `seedThresholds(s: CompileSettings): void`, `currentSettings(): CompileSettings`, `settingsDiffer(s: CompileSettings): boolean`, `compiledToComputed(turns: CompiledTurn[]): ComputedTurn[]`.

- [ ] **Step 1: Write the failing composable test**

Create `chat-vue/src/composables/__tests__/useMatchingThresholds.spec.ts`:

```ts
import { describe, expect, it } from "vitest"
import cases from "../../../../chat-api/tests/fixtures/compile_turns_cases.json"
import {
  computeTurns,
  compiledToComputed,
  currentSettings,
  seedThresholds,
  settingsDiffer,
  useMatchingThresholds,
} from "../useMatchingThresholds"
import type { CompiledTurn, TurnDistanceData } from "@/types"

describe("computeTurns agrees with the API's compile_turns", () => {
  for (const c of cases.cases) {
    it(c.name, () => {
      const s = c.settings
      const out = computeTurns(c.turns as TurnDistanceData[], s.cosine_dist_threshold, s.separation_min, s.quality_min, s.confidence_min)
      expect(out.map(({ matchType, ...rest }) => ({ ...rest, match_type: matchType }))).toEqual(c.expected)
    })
  }
})

describe("threshold seeding", () => {
  it("seeds the sliders and reports no difference afterwards", () => {
    const s = { cosine_dist_threshold: 0.3, separation_min: 0.1, quality_min: 0.2, confidence_min: 0.05 }
    seedThresholds(s)
    const { cosineDistThreshold, separationMin } = useMatchingThresholds()
    expect(cosineDistThreshold.value).toBe(0.3)
    expect(separationMin.value).toBe(0.1)
    expect(currentSettings()).toEqual(s)
    expect(settingsDiffer(s)).toBe(false)
    cosineDistThreshold.value = 0.31
    expect(settingsDiffer(s)).toBe(true)
  })
})

describe("compiledToComputed", () => {
  it("maps match_type to matchType", () => {
    const turns: CompiledTurn[] = [{ start_time: 0, end_time: 1, text: "a", label: "Jane", match_type: "high" }]
    expect(compiledToComputed(turns)).toEqual([{ start_time: 0, end_time: 1, text: "a", label: "Jane", matchType: "high" }])
  })
})
```

The relative import reaches the shared fixture in `chat-api/tests/fixtures/`; vitest loads JSON outside the project root without configuration (verified on this checkout). Do not copy the fixture.

- [ ] **Step 2: Run to verify it fails**

Run: `cd chat-vue && npx vitest run src/composables/__tests__/useMatchingThresholds.spec.ts`
Expected: fails on missing exports (`seedThresholds` etc.). The `computeTurns` cases may already pass; that is fine, they guard the port.

- [ ] **Step 3: Add the types**

In `chat-vue/src/types/index.ts`, replace `TranscriptResponse`:

```ts
export type MatchType = "high" | "medium" | "low" | "none"

export interface CompileSettings {
  cosine_dist_threshold: number
  separation_min: number
  quality_min: number
  confidence_min: number
}

export interface CompiledTurn {
  start_time: number
  end_time: number
  text: string
  label: string
  match_type: MatchType
}

export interface TranscriptResponse {
  segments: TranscriptSegment[]
  turns: CompiledTurn[] | null      // null: job has no turn-distance data
  settings: CompileSettings
  compiled_at: string | null
}
```

and `PublicTranscriptionDetail`:

```ts
export interface PublicTranscriptionDetail extends PublicTranscriptionSummary {
  segments: TranscriptSegment[]
  turns: CompiledTurn[] | null
  settings: CompileSettings
  compiled_at: string | null
}
```

Run `npx vue-tsc --noEmit -p tsconfig.app.json` and fix every place that builds a `TranscriptResponse` literal (tests and `DemoView.vue`'s `{ segments: transcript.segments }`) — for now give them `turns: null, settings: DEFAULT_COMPILE_SETTINGS, compiled_at: null`, where `DEFAULT_COMPILE_SETTINGS` is exported from the composable in Step 5. `DemoView.vue` is rewritten properly in Task 9.

- [ ] **Step 4: Add the API call**

In `chat-vue/src/lib/transcribeApi.ts`, import `CompileSettings` from `@/types` and add after `getTranscript`:

```ts
export async function compileTranscript(jobId: string, settings: CompileSettings): Promise<TranscriptResponse> {
  const res = await apiClient.post(`/api/v1/transcribe/jobs/${jobId}/compile`, settings)
  return res.data
}
```

- [ ] **Step 5: Extend the composable**

In `chat-vue/src/composables/useMatchingThresholds.ts`, import `CompiledTurn, CompileSettings` from `@/types`, keep the four module-level refs, and add:

```ts
export const DEFAULT_COMPILE_SETTINGS: CompileSettings = {
  cosine_dist_threshold: 0.25, separation_min: 0, quality_min: 0, confidence_min: 0,
}

/** Set the sliders to a transcript's embedded settings (called whenever a transcript loads). */
export function seedThresholds(s: CompileSettings): void {
  cosineDistThreshold.value = s.cosine_dist_threshold
  separationMin.value = s.separation_min
  qualityMin.value = s.quality_min
  confidenceMin.value = s.confidence_min
}

export function currentSettings(): CompileSettings {
  return {
    cosine_dist_threshold: cosineDistThreshold.value,
    separation_min: separationMin.value,
    quality_min: qualityMin.value,
    confidence_min: confidenceMin.value,
  }
}

const EPS = 1e-9
export function settingsDiffer(s: CompileSettings): boolean {
  const c = currentSettings()
  return (Object.keys(s) as (keyof CompileSettings)[]).some(k => Math.abs(c[k] - s[k]) > EPS)
}

export function compiledToComputed(turns: CompiledTurn[]): ComputedTurn[] {
  return turns.map(({ match_type, ...rest }) => ({ ...rest, matchType: match_type }))
}
```

Add a comment above `computeTurns`: `// Mirrors compile_turns in chat-api/app/services/transcript_compiler.py; both run chat-api/tests/fixtures/compile_turns_cases.json.`

- [ ] **Step 6: Run the tests**

Run: `cd chat-vue && npm run test`
Expected: the new spec passes; everything else still passes (apart from the known `.env.local` auth noise).

- [ ] **Step 7: Commit**

```bash
git add chat-vue/src/types/index.ts chat-vue/src/lib/transcribeApi.ts chat-vue/src/composables/useMatchingThresholds.ts chat-vue/src/composables/__tests__/useMatchingThresholds.spec.ts
git commit -m "feat(chat-vue): compiled transcript types, compile API call, threshold seeding"
```

---

### Task 7: Store `recompile` and seeding on load

**Files:**
- Modify: `chat-vue/src/stores/transcribe.ts` (`loadTranscript`, new `recompile`, return list)
- Modify: `chat-vue/src/stores/__tests__/transcribe.spec.ts`

**Interfaces:**
- Consumes `compileTranscript`, `seedThresholds` from Task 6.
- Produces `store.recompile(jobId: string, settings: CompileSettings): Promise<void>` — posts, replaces `activeTranscript` if that job is active, re-seeds the sliders.
- `loadTranscript` now calls `seedThresholds(result.settings)` after storing the result.

- [ ] **Step 1: Write the failing store tests**

In `chat-vue/src/stores/__tests__/transcribe.spec.ts`, add `getTranscript: vi.fn()` and `compileTranscript: vi.fn()` to the `vi.mock("@/lib/transcribeApi", …)` factory, import `useMatchingThresholds` from `@/composables/useMatchingThresholds`, and add:

```ts
describe("compiled transcripts", () => {
  const transcript = (over: Record<string, unknown> = {}) => ({
    segments: [],
    turns: [{ start_time: 0, end_time: 1, text: "a", label: "Jane", match_type: "high" }],
    settings: { cosine_dist_threshold: 0.3, separation_min: 0.1, quality_min: 0, confidence_min: 0 },
    compiled_at: "2026-09-03T12:00:00Z",
    ...over,
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.getTranscript).mockReset()
    vi.mocked(api.compileTranscript).mockReset()
  })

  it("loadTranscript seeds the sliders from the embedded settings", async () => {
    vi.mocked(api.getTranscript).mockResolvedValue(transcript() as never)
    const store = useTranscribeStore()
    await store.loadTranscript("t1")
    const { cosineDistThreshold, separationMin } = useMatchingThresholds()
    expect(cosineDistThreshold.value).toBe(0.3)
    expect(separationMin.value).toBe(0.1)
  })

  it("recompile posts the settings and replaces the active transcript", async () => {
    const store = useTranscribeStore()
    store.jobs.push(job())
    store.activeJobId = "t1"
    const next = transcript({ settings: { cosine_dist_threshold: 0.2, separation_min: 0.5, quality_min: 0, confidence_min: 0 } })
    vi.mocked(api.compileTranscript).mockResolvedValue(next as never)

    await store.recompile("t1", next.settings)

    expect(api.compileTranscript).toHaveBeenCalledWith("t1", next.settings)
    expect(store.activeTranscript).toEqual(next)
    expect(useMatchingThresholds().separationMin.value).toBe(0.5)
  })
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd chat-vue && npx vitest run src/stores/__tests__/transcribe.spec.ts`
Expected: first fails on slider value, second on `store.recompile is not a function`.

- [ ] **Step 3: Implement**

In `chat-vue/src/stores/transcribe.ts`, import `seedThresholds` from `@/composables/useMatchingThresholds` and `CompileSettings` from `@/types`. In `loadTranscript`, after `activeTranscript.value = result`, add `seedThresholds(result.settings)`. Add after `loadTranscript`:

```ts
  /** Re-compile the stored transcript with new matching settings; the response replaces it. */
  async function recompile(jobId: string, settings: CompileSettings): Promise<void> {
    logJob(jobId, { ts: ts(), direction: 'request', label: `POST /jobs/${jobId.slice(0, 8)}…/compile` })
    try {
      const result = await api.compileTranscript(jobId, settings)
      logJob(jobId, { ts: ts(), direction: 'response', label: '200 compiled', detail: `${result.turns?.length ?? 0} turns` })
      if (activeJobId.value === jobId) activeTranscript.value = result
      seedThresholds(result.settings)
    } catch (err) {
      logJob(jobId, { ts: ts(), direction: 'response', label: 'compile failed', error: true })
      throw err
    }
  }
```

Add `recompile` to the returned object next to `loadTranscript`.

- [ ] **Step 4: Run the tests**

Run: `cd chat-vue && npm run test`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add chat-vue/src/stores/transcribe.ts chat-vue/src/stores/__tests__/transcribe.spec.ts
git commit -m "feat(chat-vue): store recompile; seed thresholds from the loaded transcript"
```

---

### Task 8: Run detail page shows stored turns, Re-compile and Reset

**Files:**
- Modify: `chat-vue/src/components/transcribe/RunDetailView.vue:94-100` (`computedTurnsForDisplay`)
- Modify: `chat-vue/src/components/transcribe/MatchingAnalysis.vue`
- Create: `chat-vue/src/components/transcribe/__tests__/MatchingAnalysis.spec.ts`
- Modify: `chat-vue/src/components/transcribe/__tests__/RunDetailView.spec.ts`

**Interfaces:**
- Consumes `compiledToComputed`, `settingsDiffer`, `currentSettings`, `seedThresholds`, `store.recompile`.
- `RunDetailView` renders `compiledToComputed(store.activeTranscript.turns)` while the sliders equal the embedded settings, else the local preview.
- `MatchingAnalysis` shows `[data-testid="recompile"]` and `[data-testid="reset-thresholds"]` only when `settingsDiffer(store.activeTranscript.settings)`.

- [ ] **Step 1: Write the failing tests**

Create `chat-vue/src/components/transcribe/__tests__/MatchingAnalysis.spec.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@/lib/transcribeApi", () => ({
  fetchTurnDistances: vi.fn(),
  compileTranscript: vi.fn(),
}))

import * as api from "@/lib/transcribeApi"
import MatchingAnalysis from "../MatchingAnalysis.vue"
import { useTranscribeStore } from "@/stores/transcribe"
import { seedThresholds, useMatchingThresholds } from "@/composables/useMatchingThresholds"

const settings = { cosine_dist_threshold: 0.25, separation_min: 0, quality_min: 0, confidence_min: 0 }
const turns = [{ start_time: 0, end_time: 1, text: "a", candidates: [{ candidate_id: "c1", speaker_name: "Jane", cosine_dist: 0.1 }] }]

async function mountOpen() {
  setActivePinia(createPinia())
  const store = useTranscribeStore()
  store.activeJobId = "t1"
  store.activeTranscript = { segments: [], turns: [], settings, compiled_at: "2026-09-03T12:00:00Z" }
  store.turnDistanceData["t1"] = turns
  seedThresholds(settings)
  const w = mount(MatchingAnalysis, { props: { jobId: "t1" } })
  await w.find("button").trigger("click")   // open the panel
  await flushPromises()
  return { store, w }
}

describe("MatchingAnalysis — re-compile", () => {
  beforeEach(() => {
    vi.mocked(api.fetchTurnDistances).mockReset().mockResolvedValue({ turns })
    vi.mocked(api.compileTranscript).mockReset()
  })

  it("hides Re-compile while the sliders equal the embedded settings", async () => {
    const { w } = await mountOpen()
    expect(w.find('[data-testid="recompile"]').exists()).toBe(false)
  })

  it("shows Re-compile and Reset once a slider moves, and Reset restores", async () => {
    const { w } = await mountOpen()
    useMatchingThresholds().cosineDistThreshold.value = 0.4
    await flushPromises()
    expect(w.find('[data-testid="recompile"]').exists()).toBe(true)
    await w.find('[data-testid="reset-thresholds"]').trigger("click")
    expect(useMatchingThresholds().cosineDistThreshold.value).toBe(0.25)
    expect(w.find('[data-testid="recompile"]').exists()).toBe(false)
  })

  it("Re-compile posts the current sliders and hides itself on success", async () => {
    const { w } = await mountOpen()
    useMatchingThresholds().cosineDistThreshold.value = 0.4
    await flushPromises()
    const next = { segments: [], turns: [], settings: { ...settings, cosine_dist_threshold: 0.4 }, compiled_at: "2026-09-03T12:01:00Z" }
    vi.mocked(api.compileTranscript).mockResolvedValue(next as never)
    await w.find('[data-testid="recompile"]').trigger("click")
    await flushPromises()
    expect(api.compileTranscript).toHaveBeenCalledWith("t1", { ...settings, cosine_dist_threshold: 0.4 })
    expect(w.find('[data-testid="recompile"]').exists()).toBe(false)
  })
})
```

In `chat-vue/src/components/transcribe/__tests__/RunDetailView.spec.ts`, add a describe block (reuse the file's `job` and `mountWithJob` helpers; add `getTranscript: vi.fn()` and `compileTranscript: vi.fn()` to the mock factory):

```ts
describe("RunDetailView — compiled transcript display", () => {
  const settings = { cosine_dist_threshold: 0.25, separation_min: 0, quality_min: 0, confidence_min: 0 }

  beforeEach(() => {
    vi.mocked(api.fetchTurnDistances).mockReset().mockResolvedValue({
      turns: [{ start_time: 0, end_time: 1, text: "a", candidates: [{ candidate_id: "c1", speaker_name: "Jane", cosine_dist: 0.9 }] }],
    })
  })

  it("renders the stored turns, not the local preview, when sliders equal the embedded settings", async () => {
    const { store, w } = mountWithJob(job())
    store.activeTranscript = {
      segments: [],
      turns: [{ start_time: 0, end_time: 1, text: "a", label: "Stored", match_type: "high" }],
      settings, compiled_at: "2026-09-03T12:00:00Z",
    }
    seedThresholds(settings)
    await flushPromises()
    expect(w.text()).toContain("Stored")
    expect(w.text()).not.toContain("Unknown")
  })

  it("switches to the local preview once a slider differs", async () => {
    const { store, w } = mountWithJob(job())
    store.activeTranscript = {
      segments: [],
      turns: [{ start_time: 0, end_time: 1, text: "a", label: "Stored", match_type: "high" }],
      settings, compiled_at: "2026-09-03T12:00:00Z",
    }
    seedThresholds(settings)
    await flushPromises()
    useMatchingThresholds().cosineDistThreshold.value = 0.95   // 0.9 now within threshold → "Jane"
    await flushPromises()
    expect(w.text()).toContain("Jane")
    expect(w.text()).not.toContain("Stored")
  })
})
```

Import `seedThresholds, useMatchingThresholds` from `@/composables/useMatchingThresholds` at the top of that spec.

- [ ] **Step 2: Run to verify they fail**

Run: `cd chat-vue && npx vitest run src/components/transcribe/__tests__/MatchingAnalysis.spec.ts src/components/transcribe/__tests__/RunDetailView.spec.ts`
Expected: the new tests fail (no `recompile` button; preview rendered instead of "Stored").

- [ ] **Step 3: RunDetailView displays stored turns when clean**

In `chat-vue/src/components/transcribe/RunDetailView.vue`, extend the composable import to include `compiledToComputed, settingsDiffer` and replace `computedTurnsForDisplay`:

```ts
const computedTurnsForDisplay = computed((): ComputedTurn[] => {
  const jobId = store.activeJobId
  if (!jobId) return []
  const transcript = store.activeTranscript
  // Stored compile wins while the sliders match the settings it was compiled with.
  if (transcript?.turns && !settingsDiffer(transcript.settings)) {
    return compiledToComputed(transcript.turns)
  }
  const turns = store.turnDistanceData[jobId]
  if (!turns?.length) return []
  return computeTurns(turns, cosineDistThreshold.value, separationMin.value, qualityMin.value, confidenceMin.value)
})
```

Also pass the settings and compile time into the transcript display for the download header (Task 9 consumes them): on the `<TranscriptDisplay v-else-if="store.activeTranscript" …>` element add `:settings="currentSettings()"` and `:compiled-at="settingsDiffer(store.activeTranscript.settings) ? null : store.activeTranscript.compiled_at"`, importing `currentSettings` too. (`TranscriptDisplay` gains those optional props in Task 9; adding them now is harmless.)

- [ ] **Step 4: MatchingAnalysis gets Re-compile and Reset**

In `chat-vue/src/components/transcribe/MatchingAnalysis.vue` script, extend the composable import with `currentSettings, seedThresholds, settingsDiffer` and add:

```ts
const isCompiling = ref(false)
const compileError = ref<string | null>(null)

const embeddedSettings = computed(() => store.activeTranscript?.settings ?? null)
const dirty = computed(() => embeddedSettings.value !== null && settingsDiffer(embeddedSettings.value))

function resetThresholds() {
  if (embeddedSettings.value) seedThresholds(embeddedSettings.value)
}

async function recompile() {
  isCompiling.value = true
  compileError.value = null
  try {
    await store.recompile(props.jobId, currentSettings())
  } catch {
    compileError.value = "Re-compile failed — try again."
  } finally {
    isCompiling.value = false
  }
}
```

The `computedTurns` computed in this component stays a live preview (it drives the stats and the turn list under the sliders).

In the template, directly after the sliders grid (before the stats bar), add:

```html
        <div v-if="dirty" class="flex items-center gap-2 mb-2 text-xs">
          <button
            type="button"
            data-testid="recompile"
            class="rounded bg-indigo-600 px-2.5 py-1 font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
            :disabled="isCompiling"
            @click="recompile"
          >{{ isCompiling ? "Compiling…" : "Re-compile transcript" }}</button>
          <button
            type="button"
            data-testid="reset-thresholds"
            class="text-gray-500 hover:text-gray-700"
            :disabled="isCompiling"
            @click="resetThresholds"
          >Reset</button>
          <span class="text-gray-400">Sliders differ from the compiled transcript</span>
          <span v-if="compileError" class="text-red-600">{{ compileError }}</span>
        </div>
```

- [ ] **Step 5: Run the tests**

Run: `cd chat-vue && npm run test`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add chat-vue/src/components/transcribe/RunDetailView.vue chat-vue/src/components/transcribe/MatchingAnalysis.vue chat-vue/src/components/transcribe/__tests__/MatchingAnalysis.spec.ts chat-vue/src/components/transcribe/__tests__/RunDetailView.spec.ts
git commit -m "feat(chat-vue): show the compiled transcript; Re-compile and Reset in matching analysis"
```

---

### Task 9: Download header and the demo page

**Files:**
- Modify: `chat-vue/src/components/transcribe/TranscriptDisplay.vue`
- Modify: `chat-vue/src/views/DemoView.vue:168-170`
- Create: `chat-vue/src/components/transcribe/__tests__/TranscriptDisplay.spec.ts`
- Modify: `chat-vue/src/views/__tests__/DemoView.spec.ts`

**Interfaces:**
- `TranscriptDisplay` gains optional props `settings?: CompileSettings` and `compiledAt?: string | null`.
- Produces exported `transcriptText(turns, segments, settings?, compiledAt?)` from `TranscriptDisplay.vue`'s script (a `<script>` block, not `<script setup>`, so it can be imported by the test) — the exact file body the download writes.

- [ ] **Step 1: Write the failing tests**

Create `chat-vue/src/components/transcribe/__tests__/TranscriptDisplay.spec.ts`:

```ts
import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import TranscriptDisplay, { transcriptText } from "../TranscriptDisplay.vue"

const settings = { cosine_dist_threshold: 0.25, separation_min: 0, quality_min: 0.1, confidence_min: 0 }
const turns = [{ start_time: 0.03, end_time: 7.62, text: "Hi", label: "Jane", matchType: "high" as const }]

describe("transcriptText", () => {
  it("writes a settings header then the turn lines with the tier", () => {
    const text = transcriptText(turns, [], settings, "2026-09-03T12:00:00Z")
    expect(text.split("\n")).toEqual([
      "# compiled 2026-09-03T12:00:00Z  cosine<=0.25  separation>=0.00  quality>=0.10  confidence>=0.00",
      "[0.03 - 7.62] Jane [high]: Hi",
    ])
  })

  it("marks an uncompiled preview in the header", () => {
    const text = transcriptText(turns, [], settings, null)
    expect(text.startsWith("# preview (not compiled)  cosine<=0.25")).toBe(true)
  })

  it("falls back to segment lines with no header when there are no turns", () => {
    const seg = { segment_id: "s", anonymous_label: "PROBABLY_Jane", speaker_name: null, start_time: 0.21, end_time: 7.68, text: "Hi" }
    expect(transcriptText([], [seg])).toBe("[0.21 - 7.68] PROBABLY_Jane: Hi")
  })
})

describe("TranscriptDisplay", () => {
  it("renders dynamic mode when computed turns are given", () => {
    const w = mount(TranscriptDisplay, {
      props: { transcript: { segments: [], turns: null, settings, compiled_at: null }, computedTurns: turns },
    })
    expect(w.text()).toContain("Jane")
  })
})
```

In `chat-vue/src/views/__tests__/DemoView.spec.ts`, add a test (import `getPublicTranscription` from the mocked module):

```ts
  it("renders a public transcript's compiled turns with speaker labels", async () => {
    vi.mocked(getShowcase).mockResolvedValue({
      ...showcase,
      scans: [],
      transcriptions: [{ job_id: "t1", created_at: "2026-09-01T00:00:00Z", duration_seconds: 16, segment_count: 5, speaker_count: 2 }],
    } as never)
    vi.mocked(getPublicTranscription).mockResolvedValue({
      job_id: "t1", created_at: "2026-09-01T00:00:00Z", duration_seconds: 16, segment_count: 5, speaker_count: 2,
      segments: [{ segment_id: "s", anonymous_label: "PROBABLY_Barry", speaker_name: null, start_time: 8.7, end_time: 11.4, text: "Sounds good" }],
      turns: [{ start_time: 8.55, end_time: 11.27, text: "Sounds good", label: "Barry", match_type: "medium" }],
      settings: { cosine_dist_threshold: 0.25, separation_min: 0, quality_min: 0, confidence_min: 0 },
      compiled_at: "2026-09-03T12:00:00Z",
    } as never)
    const w = mountDemo()
    await flushPromises()
    await w.find('[data-testid="transcription-chip"]').trigger("click")
    await flushPromises()
    expect(w.text()).toContain("Barry")
    expect(w.text()).not.toContain("PROBABLY_Barry")
  })
```

Transcriptions on the demo page open only when their chip is clicked (`openTranscription`), so the click is required.

- [ ] **Step 2: Run to verify they fail**

Run: `cd chat-vue && npx vitest run src/components/transcribe/__tests__/TranscriptDisplay.spec.ts src/views/__tests__/DemoView.spec.ts`
Expected: `transcriptText` is not exported; the demo test finds `PROBABLY_Barry`.

- [ ] **Step 3: Extract the download text and add the header**

In `chat-vue/src/components/transcribe/TranscriptDisplay.vue`, add a plain `<script lang="ts">` block above the existing `<script setup>`:

```ts
<script lang="ts">
import type { CompileSettings, TranscriptSegment } from "@/types"
import type { ComputedTurn } from "@/composables/useMatchingThresholds"

/** The exact transcript.txt body. Turns (with a settings header) when present, else segments. */
export function transcriptText(
  turns: ComputedTurn[],
  segments: TranscriptSegment[],
  settings?: CompileSettings,
  compiledAt?: string | null,
): string {
  if (turns.length === 0) {
    return segments
      .map(s => `[${s.start_time.toFixed(2)} - ${s.end_time.toFixed(2)}] ${s.speaker_name ?? s.anonymous_label}: ${s.text}`)
      .join("\n")
  }
  const lines = turns.map(t =>
    `[${t.start_time.toFixed(2)} - ${t.end_time.toFixed(2)}] ${t.label} [${t.matchType}]: ${t.text}`)
  if (settings) {
    const state = compiledAt ? `compiled ${compiledAt}` : "preview (not compiled)"
    lines.unshift(
      `# ${state}  cosine<=${settings.cosine_dist_threshold.toFixed(2)}  separation>=${settings.separation_min.toFixed(2)}` +
      `  quality>=${settings.quality_min.toFixed(2)}  confidence>=${settings.confidence_min.toFixed(2)}`,
    )
  }
  return lines.join("\n")
}
</script>
```

In the `<script setup>`: extend the props to

```ts
const props = defineProps<{
  transcript: TranscriptResponse
  computedTurns?: ComputedTurn[]
  settings?: CompileSettings
  compiledAt?: string | null
}>()
```

and replace the body of `downloadTranscript` up to `const blob` with:

```ts
  const lines = transcriptText(props.computedTurns ?? [], props.transcript.segments, props.settings, props.compiledAt)
```

Remove the now-duplicated inline mapping. Keep the rest of the function as it is.

- [ ] **Step 4: Demo renders compiled turns**

In `chat-vue/src/views/DemoView.vue`, import `compiledToComputed` from `@/composables/useMatchingThresholds` and replace the `TranscriptDisplay` line:

```html
          <TranscriptDisplay
            :transcript="transcript"
            :computed-turns="transcript.turns ? compiledToComputed(transcript.turns) : undefined"
            :settings="transcript.settings"
            :compiled-at="transcript.compiled_at"
          />
```

`transcript` is a `PublicTranscriptionDetail`, which structurally satisfies `TranscriptResponse` (it has `segments`, `turns`, `settings`, `compiled_at`).

- [ ] **Step 5: Run the full Vue suite and type-check**

Run: `cd chat-vue && npm run test && npx vue-tsc --noEmit -p tsconfig.app.json`
Expected: tests pass; no type errors.

- [ ] **Step 6: Commit**

```bash
git add chat-vue/src/components/transcribe/TranscriptDisplay.vue chat-vue/src/views/DemoView.vue chat-vue/src/components/transcribe/__tests__/TranscriptDisplay.spec.ts chat-vue/src/views/__tests__/DemoView.spec.ts
git commit -m "feat(chat-vue): settings header in transcript download; demo renders compiled turns"
```

---

### Task 10: Docs and final verification

**Files:**
- Modify: `chat-vue/CLAUDE.md` (transcribe section), `CLAUDE.md` (root, "Chat data model" or a new transcription bullet), `docs/superpowers/specs/2026-09-03-compiled-transcripts-design.md` (status line)

- [ ] **Step 1: Document the concept where the next reader looks**

In the root `CLAUDE.md`, under the runtime flow's transcription lines, add one bullet:

```
- **Compiled transcripts:** the API turns a job's stored turn distances into a labelled turn list with `compile_turns` (`chat-api/app/services/transcript_compiler.py`), compiled with the `compile_*` defaults on first read and re-compiled via `POST …/jobs/{id}/compile`. One row per job in `compiled_transcripts`, settings embedded. The Vue `computeTurns` mirrors it for slider preview; both run `chat-api/tests/fixtures/compile_turns_cases.json`.
```

In `chat-vue/CLAUDE.md`, where the matching analysis / thresholds are described (grep `useMatchingThresholds`), add: "Sliders are seeded from the loaded transcript's `settings`; `RunDetailView` shows the stored `turns` until a slider differs, then the local preview; `MatchingAnalysis` offers Re-compile / Reset while they differ."

Change the spec's status line to `**Status:** implemented 2026-09-03`.

- [ ] **Step 2: Run everything**

```bash
cd chat-api && uv run pytest -q
cd ../chat-vue && npm run test && npm run build
```

Expected: API suite green; Vue tests green except the known `.env.local` auth noise; build succeeds.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md chat-vue/CLAUDE.md docs/superpowers/specs/2026-09-03-compiled-transcripts-design.md
git commit -m "docs: compiled transcripts"
```

- [ ] **Step 4: Deploy note for the operator**

Pushing to `main` runs the Deploy workflow; the API job applies migration `v2w3x4y5z6a7` before the Vue deploy. Existing jobs compile on their first open. Nothing to bake.
