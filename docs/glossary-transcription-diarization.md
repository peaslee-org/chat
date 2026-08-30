# Transcription & Speaker Diarization Glossary

Terms used across `transcription-worker/` and `chat-api/` for audio transcription and speaker diarization.

---

## Entities & Data Models

### TranscriptionJob
A record tracking one end-to-end audio processing task, from upload through completed transcript. Stored in the `transcription_jobs` table.

Key fields:
- `audio_s3_key` — S3 path to the uploaded audio file
- `aws_transcribe_job_name` — identifier for the AWS Transcribe job
- `speaker_count_hint` — optional user-supplied estimate of speaker count (1–30)
- `language` — BCP-47 language code (default `en-US`)
- `speaker_ids` — UUIDs of speaker profiles to attempt matching against
- `result_s3_key` — S3 path to the final `transcript.txt`
- `matched_speaker_count` / `total_segment_count` — match quality counters

### TranscriptSegment
One time-stamped span of speech attributed to a speaker. Produced by the word alignment step and stored in the `transcript_segments` table.

Key fields:
- `anonymous_label` — raw label from diarization (e.g. `"spk_0"`, `"Speaker 1"`)
- `speaker_profile_id` — FK to a matched `SpeakerProfile`; `NULL` when unmatched
- `start_time` / `end_time` — seconds from the start of the audio
- `text` — transcribed words for this segment

### TranscriptionJobEvent
Append-only audit log of state transitions and worker milestones for a job. Stored in `transcription_job_events`.

Key fields:
- `source` — `"api"` or `"worker"`
- `event` — dot-namespaced name (e.g. `"diarization.complete"`, `"job.failed"`)
- `detail` — optional JSON metadata (e.g. `{"count": 12}` for segment count)

### SpeakerProfile
A named, enrolled voice identity owned by a user (keyed by Cognito `sub`). Has zero or more `SpeakerSample` records.

### SpeakerSample
A reference audio clip used to generate a voice embedding for a speaker profile. Stored in `speaker_samples`.

Key fields:
- `s3_key` — S3 path to the audio file
- `embedding` — `vector(192)` pgvector column; the 192-dim L2-normalized ECAPA-TDNN embedding
- `status` — `processing` → `ready` | `failed`
- `error_message` — reason for failure if status is `failed`
- `duration_seconds` — clip duration; must be 10–60 seconds

---

## Job & Sample Statuses

### Job Status

| Status | Meaning |
|---|---|
| `pending` | Job created; awaiting audio upload and confirmation |
| `transcribing` | AWS Transcribe job running; worker polling for completion |
| `matching` | Word alignment and speaker embedding matching in progress |
| `complete` | Processing finished; `result_s3_key` is populated |
| `failed` | Processing failed; see `error_message` |

### Sample Status

| Status | Meaning |
|---|---|
| `processing` | Embedding generation in progress |
| `ready` | Embedding computed; sample is usable for matching |
| `failed` | Embedding failed; `error_message` contains the reason |

---

## Pipeline Concepts

### Diarization
Partitioning an audio stream into time spans, each attributed to a single speaker label. This project uses **pyannote-audio 4.x** (`pyannote/speaker-diarization-community-1`) running on CUDA — not AWS Transcribe's built-in diarization.

Output: a list of *turns*.

### Turn
A single time-stamped speaker segment produced by pyannote. Structure: `{speaker_label, start, end}`.

Pyannote produces two sets:
- **turns** — may include overlapping spans (multiple speakers active simultaneously)
- **exclusive_turns** — each timestamp assigned to exactly one speaker; used for word alignment

### Word Alignment
Mapping AWS Transcribe word-level timestamps onto pyannote speaker turns to produce `TranscriptSegment` records. Implemented in `services/aligner.py`.

Algorithm:
1. Compute each word's midpoint: `(start_time + end_time) / 2`
2. Binary-search (`bisect_right`) to find the exclusive turn containing the midpoint
3. Words that fall in a gap (silence) are assigned to the nearest turn by endpoint distance
4. Consecutive same-speaker words are merged into one segment

### Overlap Detection
Identifying audio regions where two or more speakers are active simultaneously. Implemented via a sweep-line algorithm in `aligner.find_overlaps()`:
- Events: each turn's start and end are sorted and swept in order
- When `len(active_speakers) > 1`, an overlap interval is recorded

Overlap metadata is logged but not persisted in the database; exclusive turns are used for segment assignment.

### Voice Embedding
A fixed-dimensional vector representation of a speaker's voice, used for identity comparison. Computed by the ECAPA-TDNN model.

Properties:
- **Dimensionality:** 192
- **Normalization:** L2 (unit norm)
- **Model:** SpeechBrain `speechbrain/spkrec-ecapa-voxceleb` at revision `3c54e95`
- **Input:** 16 kHz mono audio
- Stored in `speaker_samples.embedding` as a `pgvector` `vector(192)` column

### ECAPA-TDNN
**Emphasized Channel Attention, Propagation and Aggregation – Temporal Dense Network.** The SpeechBrain speaker recognition model used to compute voice embeddings. The checkpoint used here (`3c54e95`) outputs **192-dimensional** vectors.

### Speaker Matching
Comparing a segment's embedding against enrolled `SpeakerSample` embeddings to identify who is speaking. Implemented in `services/matcher.py`.

Algorithm:
1. Group candidate samples by `SpeakerProfile`
2. Compute each profile's average embedding (across all `ready` samples)
3. Compute cosine distance from the segment embedding to each average
4. Return the profile with the lowest distance **if distance ≤ threshold** (default `0.25`), otherwise return `None` (unmatched)

### Cosine Distance
The distance metric used for embedding comparison: `1 − cosine_similarity`. Lower is more similar.

**Matching threshold:** ≤ 0.25 (equivalently, similarity ≥ 0.75). At this operating point: ~3% false acceptance rate, ~8% false rejection rate (biased toward avoiding incorrect assignments).

### Anonymous Label
The raw speaker identifier assigned by diarization before any profile matching (e.g. `"spk_0"`, `"Speaker 1"`). Stored in `TranscriptSegment.anonymous_label`. Displayed in the UI when a segment has no matched profile.

### Unmatched Segment
A `TranscriptSegment` where `speaker_profile_id IS NULL` — either no candidate profiles were provided, all samples were `failed`, or the closest embedding was above the cosine distance threshold. The `anonymous_label` is shown instead of a speaker name.

### Transcribe Poller
`services/transcribe_poller.py` — polls AWS Transcribe every 30 s until the job reaches `COMPLETED` or `FAILED`. On success, parses word-level timestamps from the JSON output.

### Parse Words
`transcribe_poller.parse_words()` — extracts `{word, start_time, end_time}` items from AWS Transcribe JSON. Punctuation tokens (which lack timestamps) are appended to the preceding word's text.

---

## SQS Message Types

### `transcription_job`
Enqueued by the API when a job is confirmed. Carries `job_id`, `aws_transcribe_job_name`, and the list of `speaker_ids` to attempt matching against.

### `sample_embedding`
Enqueued by the API when a speaker sample upload is confirmed. Carries `sample_id` and `s3_key`. The worker computes and stores the embedding.

---

## S3 Key Conventions

| Artifact | Key Pattern |
|---|---|
| Uploaded audio | `audio/{user_id}/{job_id}/source` |
| AWS Transcribe raw output | `audio/{user_id}/{job_id}/transcript_raw.json` |
| Final transcript | `audio/{user_id}/{job_id}/transcript.txt` |
| Speaker sample audio | `audio/{user_id}/speakers/{speaker_id}/samples/{sample_id}` |

---

## Infrastructure & Operations

### Speaker Count Hint
User-provided estimate of the number of speakers in the audio (1–30). Passed to pyannote as `max_speakers` and to AWS Transcribe. Accuracy degrades if the hint is significantly wrong.

### Language Code
BCP-47 identifier for the spoken language (default `en-US`). Passed to AWS Transcribe's `LanguageCode` parameter.

### Worker State
`worker_state` (`off` | `starting` | `running`) is derived by the API from ECS `ListTasks` against the worker's task family on the shared `gpu-<env>` capacity provider — there is no stored flag. The API launches the worker with `RunTask` on job confirm, on `POST /api/v1/gpu/warm`, or when a status poll finds an active job with the worker off. Surfaced in `JobStatusResponse.worker_state` for jobs in `transcribing` or `matching`. Replaces the old S3 pause flag (removed with ADR 004).

### Visibility Extension
A background thread in the worker that calls `sqs.change_message_visibility()` every 300 s, resetting the timeout to 600 s. Prevents a long-running job from having its SQS message become visible to another consumer.

### Spot Watcher
`services/spot_watcher.py` — daemon thread that polls the EC2 instance metadata endpoint every 5 s for a Spot termination notice. On notice, immediately releases the SQS message (sets `VisibilityTimeout=0`) so another worker can pick it up. No-op in local (non-EC2) environments.

### Partial Transcript
When a job fails after AWS Transcribe has already completed, `JobStatusResponse.partial_transcript_available` is `true`. The API can return whatever segments were written before failure.

---

## API Response Shapes

### `JobStatusResponse`
Returned by `GET /api/v1/transcription/jobs/{job_id}`. Includes status, match quality counters (`matched_speaker_count`, `total_segment_count`), and `worker_state`.

### `TranscriptResponse`
Returned by `GET /api/v1/transcription/jobs/{job_id}/transcript`. Contains a list of `SegmentResponse` objects and an optional pre-signed S3 URL for `transcript.txt`.

### `SegmentResponse`
One transcript segment in the API response: `anonymous_label`, `speaker_name` (if matched), `start_time`, `end_time`, `text`. The frontend shows `speaker_name` when available and falls back to `anonymous_label`.

### `SpeakerResponse` / `SampleResponse`
Speaker profile and sample details returned by the speaker management endpoints, including sample `status` and `error_message`.

---

## Key Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Diarization engine | pyannote-audio 4.x on CUDA | Better accuracy than AWS Transcribe; handles overlapping speech |
| AWS Transcribe role | Word timestamps only (`ShowSpeakerLabels` not set) | pyannote handles diarization; Transcribe provides word positions |
| Embedding model | SpeechBrain ECAPA-TDNN `3c54e95` | 192-dim output (not 256); pre-downloaded into Docker image |
| Embedding dimension | 192 | Actual output of checkpoint `3c54e95` (see `speaker_samples.embedding`) |
| Cosine distance threshold | 0.25 | ~EER operating point; biased toward avoiding false speaker assignments |
| Alignment algorithm | Bisect midpoint → nearest gap fallback | Deterministic; handles silences without dropping words |

## Photogrammetry (Scan)

| Term | Meaning |
|---|---|
| **SfM / sparse model** | Structure-from-Motion: COLMAP extracts SIFT features, matches photos exhaustively and solves camera poses + a sparse point cloud (`colmap mapper`). The model with the most registered images wins. |
| **Registered image** | A photo whose camera pose the mapper could solve. The job fails when fewer than 60 % of usable photos register ("Only N of M photos could be matched"). The worker records each photo as `registered` / `unregistered` / `skipped:<reason>` in `photo_status`; the scan page marks the tiles. |
| **Dense cloud** | OpenMVS `DensifyPointCloud` (resolution level 2 for the 16 GB T4) after `colmap image_undistorter`. |
| **Reconstruct / Delaunay** | `ReconstructMesh`: Delaunay tetrahedralisation + graph cut → the first mesh (≈680 k faces on a 51-photo set). |
| **Refine** | `RefineMesh`: photo-consistent subdivision — roughly doubles faces at a ~16 GB virtual peak. Run only when ≤ 100 images **and** ≤ 400 k faces. |
| **Decimate / face budget** | `TextureMesh --decimate r` simplifies to about 500 k faces (`FACE_BUDGET`) before texturing; the job carries the warning "Mesh simplified from N to about 500,000 faces to fit the viewer". |
| **Texture atlas** | The 8192² image(s) TextureMesh packs per-face patches into; seam leveling is disabled in our build (it blackened faces). Exported per material without re-packing — hence large GLBs (`docs/TODO.md`). |
| **GLB** | Binary glTF loaded by `<model-viewer>`; rotated into glTF's y-up frame from COLMAP's. `mesh.glb` + `preview.png` under `output/`. |
| **Checkpoint / resume** | `<stage>.done` markers in the job's scratch dir (host-path volume `/var/lib/photogrammetry` → `/tmp/pg`); a redelivered job resumes at the first incomplete stage; a stage that crashed mid-run fails the job instead of cycling. Attempt 5 (the queue's `maxReceiveCount`) fails the row. |
| **Thumbnail** | 256 px JPEG made by the API on first request and cached beside the inputs (`…/thumbs/`), so the Photos pane never loads originals until one is clicked. |
| **Cold start** | The GPU pool was at zero: RunTask → capacity provider → EC2 launch → boot → image pull → container → worker's first claim. 6–7 min measured; the estimate is the median of recent cold starts. |
| **Warm start** | A worker exited (idle) but its instance is still up — ECS scales in ~15 min later — so a new task only needs the container start (~1 min). Quoted when the last session ended within `GPU_SCALE_IN_SECONDS`. |
| **Startup stages** | Per launch in the usage panel: **capacity** (RunTask → instance boot), **boot** (→ image pull starts), **pull**, **container** (→ task running), **init** (→ first job claimed). Cold/warm is decided by whether the instance booted after the launch. |

