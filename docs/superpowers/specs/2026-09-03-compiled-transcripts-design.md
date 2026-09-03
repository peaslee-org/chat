# Compiled transcripts — design

**Date:** 2026-09-03
**Status:** approved in discussion; awaiting implementation plan

## Goal

Make "the transcript" of a transcription job a single stored artifact that
every surface reads: the logged-in run detail page, the download, and the
public demo. Today the run detail page re-scores the worker's per-turn
candidate distances in the browser with slider defaults, while the demo shows
the worker's original `PROBABLY_` labels from the segment rows — the same job
reads differently depending on where it is viewed.

A **compiled transcript** is the turn list produced by applying a set of
matching settings to the stored turn distances, with those settings embedded.
A new job is compiled automatically with the defaults on first read. A user
can change the settings and re-compile; the new result replaces the old one.

## Decisions taken in discussion

- **One compiled transcript per job.** Re-compiling replaces it. No history.
  The raw turn distances are never modified, so any earlier result can be
  reproduced by re-compiling with its settings.
- **The API compiles, lazily.** The worker is untouched. The first read of a
  complete job with turn data and no compiled row compiles with the defaults
  and stores the result. One implementation of the rules serves both the
  initial compile and re-compiles; no worker deploy or AMI bake.
- **Sliders keep their live preview.** Moving a slider re-scores in the browser
  as now. A **Re-compile** action appears when the slider values differ from
  the embedded settings and posts them to the API. Reloading the page shows the
  stored transcript again.
- **Defaults live in API settings**, initialised to today's client values
  (cosine 0.25, separation 0, quality 0, confidence 0). The client reads the
  settings from the transcript it loads instead of hardcoding them.

## Data model

New table `compiled_transcripts` (Alembic migration, `chat-api`):

| column | type | notes |
|---|---|---|
| `id` | uuid | UUIDMixin |
| `job_id` | uuid, FK → `transcription_jobs.id`, `ON DELETE CASCADE`, **unique** | one row per job |
| `settings` | json | see below |
| `turns` | json | array of turns, see below |
| `compiled_at` | timestamptz | |

`settings`:

```json
{"cosine_dist_threshold": 0.25, "separation_min": 0.0, "quality_min": 0.0, "confidence_min": 0.0}
```

Each turn:

```json
{"start_time": 0.03, "end_time": 7.62, "text": "…", "label": "Jane", "match_type": "high"}
```

`match_type` ∈ `high | medium | low | none`; `label` is the speaker name, or
`"Unknown"` when `match_type` is `none`. This is exactly the shape
`computeTurns` in `chat-vue/src/composables/useMatchingThresholds.ts`
produces today.

`TranscriptSegment` rows and the worker's `anonymous_label` values are
unchanged.

## Compile rules

A pure function in the API, `compile_turns(turns, settings) -> list[Turn]`,
ported line for line from `computeTurns`:

1. No candidates → `Unknown / none`.
2. Best candidate (lowest cosine distance) `<= cosine_dist_threshold` → best's
   name, `high`.
3. Otherwise, with at least two candidates and a runner-up strictly farther
   than the best: `separation = 1 - best/runner_up`,
   `quality = threshold / best`, `confidence = separation * quality`.
   - all three ≥ their minimums → best's name, `medium`
   - only `separation ≥ separation_min` → best's name, `low`
4. Otherwise `Unknown / none`.

The Vue function stays (live preview). To keep the two implementations in
step, both test suites run against **one shared fixture file** of
`(turn distances, settings) → expected turns` cases, checked in once and
referenced from both `chat-api/tests` and `chat-vue/src`.

Settings validation on the API: `0 < cosine_dist_threshold <= 2`, the three
minimums in `[0, 1]`. Out of range → 422.

## API

### `GET /api/v1/transcribe/jobs/{id}/transcript` (existing, extended)

Response gains three fields; `segments` stays for backward compatibility and
for jobs that cannot be compiled.

```json
{
  "segments": [ … as today … ],
  "turns": [ … compiled turns … ] | null,
  "settings": { … } ,
  "compiled_at": "…" | null
}
```

Behaviour, for a job whose transcript is available (same status rules as
today):

- Compiled row exists → return it.
- No compiled row, job has turn-distance rows → compile with the defaults,
  store, return. (Only when the job is `complete`; a `failed` job with partial
  segments is never compiled.)
- No turn-distance rows (older jobs, jobs submitted without speakers) →
  `turns: null`, `compiled_at: null`, `settings` = defaults. The client falls
  back to the static segment view.

### `POST /api/v1/transcribe/jobs/{id}/compile` (new)

Body: the settings object. Validates, requires job `complete` with turn
data (else 409), compiles, replaces the row (`compiled_at = now`), appends a
`transcript.compiled` job event with the settings in `detail`, returns the
same shape as `GET …/transcript`.

### `GET /api/v1/public/transcriptions/{id}` (existing, extended)

`PublicTranscriptionDetail` gains the same `turns`, `settings`, `compiled_at`
fields, read the same way (including the lazy first compile — the public
surface can trigger it; it writes only a derived row). The demo therefore
renders exactly what the owner sees.

### Settings source

`Settings` in `chat-api/app/config.py` gains `compile_cosine_dist_threshold`,
`compile_separation_min`, `compile_quality_min`, `compile_confidence_min`
with the defaults above. The service builds the default settings object from
them.

## Frontend

### Types

`TranscriptResponse` gains `turns: CompiledTurn[] | null`, `settings:
CompileSettings`, `compiled_at: string | null`. `CompiledTurn` is the wire shape with
`match_type` (snake_case, as the API sends it). The store maps stored turns to
the existing `ComputedTurn` (`matchType`) once on load, so components keep a
single turn type whether the turns came from the API or the local preview.

### Run detail page (`RunDetailView.vue`, `MatchingAnalysis.vue`)

- On load, the sliders are seeded from `transcript.settings`. The
  module-level singleton refs in `useMatchingThresholds.ts` become per-job
  state seeded on load (they are currently shared across jobs, which is wrong
  once each job carries its own settings).
- Display: when the sliders equal the embedded settings, render
  `transcript.turns`. When they differ, render the local `computeTurns`
  preview as now.
- A **Re-compile** button is shown only when the sliders differ from the
  embedded settings. It calls the store, which posts to `…/compile` and
  replaces the job's transcript in the store; the button disappears because
  the sliders now equal the embedded settings.
- A **Reset** affordance restores the sliders to the embedded settings
  (cheap, and without it a user who explored has no way back short of a
  reload).
- Jobs with `turns: null` show the static segment view and no sliders, as
  today for jobs without turn data.

### Demo (`DemoView.vue`)

Passes `transcript.turns` as `computedTurns` to `TranscriptDisplay` when
present, so the public transcript renders in dynamic mode with the tier
styling. Falls back to segments otherwise. Read-only; no sliders.

### Download (`TranscriptDisplay.vue`)

When turns are present the file starts with one header line embedding the
settings, then the turn lines as today:

```
# compiled 2026-09-03T12:00:00Z  cosine<=0.25  separation>=0.00  quality>=0.00  confidence>=0.00
[0.03 - 7.62] Jane [high]: Don't worry about it…
```

The download always writes the **displayed** turns (stored or preview) with
the **displayed** settings, so what the user sees is what they get.

## Store (`transcribe.ts`)

- `loadTranscript` stores the extended response as today.
- New `recompile(jobId, settings)` → `api.compileTranscript` → replaces
  `activeTranscript` (and the per-job cache if one exists).
- `publicApi.ts` needs no new call; the detail response simply carries more.

## Error handling

- Compile on a job with no turn data: 409 with a clear message.
- Settings out of range: 422 from schema validation.
- The lazy compile runs inside the transcript read; a failure there is a 500
  like any other read failure, not swallowed. The row is written in the same
  transaction as the read's commit.
- Deleting a job cascades the compiled row.

## Testing

**API (`chat-api/tests/unit`)**
- `compile_turns` against the shared fixture file (every case).
- Transcript read: returns stored row; lazily compiles and stores when missing
  and turn data exists; does not compile `failed` jobs; returns `turns: null`
  with default settings when no turn data.
- Compile endpoint: replaces the row, appends the event, 409 without turn
  data, 422 on bad settings, 404 for another user's job.
- Public detail carries `turns`/`settings`; a private job still 404s.
- Migration is reversible.

**Vue (`chat-vue/src`)**
- `computeTurns` against the same shared fixture file.
- Sliders seed from the loaded settings; Re-compile is hidden when the sliders
  equal the settings and shown when they differ; pressing it calls the store
  and hides itself.
- Download header contains the displayed settings.
- `DemoView` renders dynamic mode when `turns` is present.

## Out of scope

- Worker changes (the `PROBABLY_` labels stay in segment rows).
- Compile history / undo.
- Per-user default settings.
- Migrating existing jobs eagerly; they compile on first read.
