# Transcribe fixes — temporary punch list (2026-09-02)

Findings from live debugging of the "Try the sample" transcription flow on prod.
Work each item in order; delete this file when the list is done. Evidence dates:
worker log group `/ecs/transcription-worker-prod`, 2026-09-02 11:41–11:48 UTC.

**Status 2026-09-02:** items 1–3 implemented on `worktree-fix+transcribe-punch-list`
(worker inline embed + no-op guard; store speaker refresh after seeding jobs; rerun
endpoint/button with concurrent-cap, terminal-state, and audio-copy guards). Item 4
remains — it needs a deployed post-fix run where both sample runs log
`Loaded 2 candidate sample(s)` (which is also item 1's prod verification).

## Background (what happened)

The sample flow seeds two speaker profiles + one voice sample each, then
confirms the transcription job. All three SQS messages land on the same queue
and the single worker consumes them in the order *sample #1 → job → sample #2*
— reproduced identically on two consecutive runs, the second sample's embedding
finishing ~0.3 s **after** the job's matching ran. Matching therefore always
sees exactly one candidate ("Loaded 1 candidate sample(s)" with a 2-id
`speaker_ids` filter). Separately, even the loaded candidate never matches:
best cosine distance 0.3532 vs threshold 0.25, deterministic across runs.

## 1. Worker: embed pending samples inline before matching (the race)

**Bug.** `transcription-worker` matching runs while samples belonging to the
job's `speaker_ids` are still `processing` (their `sample_embedding` messages
queued behind the job).

**Fix (preferred).** In the transcription handler, after loading candidate
samples: for any sample of the filtered speakers with status `processing`,
generate its embedding inline — the ECAPA model is already loaded on the GPU —
then proceed with the full candidate set. The later `sample_embedding` message
becomes a harmless no-op (handler must tolerate an already-`ready` sample).

**Where.** `transcription-worker/handlers/` (transcription handler's candidate
loading; embedding handler for the no-op path). Alternative considered and
rejected: making job-confirm wait on sample status in the API — adds latency
and still races with uploads from other tabs.

**Verify.** Run the sample twice; both runs must log
`Loaded 2 candidate sample(s)`.

## 2. SPA: refresh speaker list after the sample job seeds profiles

**Bug.** Each sample run creates *fresh* speaker profiles (new UUIDs per run).
The job panel filters `store.speakers` by the job's `speaker_ids`
(`chat-vue/src/components/transcribe/RunDetailView.vue`, `jobSpeakers`
computed), and the store hasn't refetched — the panel shows no speakers until
a manual refresh.

**Fix.** After `createSampleJob()` resolves in the transcribe store, call
`loadSpeakers()` (and consider the same after any job creation that passes
`speaker_ids`).

**Where.** `chat-vue/src/stores/transcribe.ts` (`createSampleJob` /
`loadSpeakers`).

## 3. SPA/API: "Re-run" on a completed transcription job

**Gap.** After a failed or unmatched run there is no re-run affordance; the
only path is creating a new job and re-uploading. The audio object
(`audio_s3_key`) is still in S3, so a re-run can reuse it.

**Sketch.** `POST /transcribe/jobs/{id}/rerun` → creates a new job row copying
`audio_s3_key`, `language`, `speaker_count_hint`, `speaker_ids`; publishes the
SQS message; returns the new job. SPA: a "Re-run" button on completed/failed
jobs in `RunDetailView`/`TranscribeJobCard`. Mind the bucket lifecycle —
objects under the audio prefix expire; 404 the rerun cleanly if the audio is
gone.

## 4. Matching threshold vs the curated sample (investigate before tuning)

**Observation.** The seeded sample's own audio never matches its enrolled
speakers: best cosine distance 0.3532 (other turns 0.39–1.02) against the 0.25
threshold — identical numbers across runs, so it's deterministic, not noise.
Either the threshold is too strict for the sample clips or the clips don't
resemble the sample recording's speakers.

**First step is analysis, not tuning:** use the existing turn-distances data
(`GET /transcribe/jobs/{id}/turn-distances`, MatchingAnalysis panel) on a
post-fix run where both candidates load. If the *right* speaker is
consistently nearest at ~0.35, consider a per-env threshold (settings-driven)
or better sample clips; if not, the seeded clips are the problem.

## Notes for the fresh session

- Item 1 is worker-only → deploys via `worker.yml` (new task-def revision;
  next `RunTask` picks it up — no service roll, no AMI rebake needed).
- Items 2–3 touch `chat-vue` (+ `chat-api` for the rerun endpoint).
- Related context: the demo/final-review parked list also wants service-layer
  tests for `set_visibility` and a real-DB integration test story — separate
  concerns, not part of this list.
