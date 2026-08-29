# Mock API — Traffic Capture & Replay

The frontend has a two-phase offline dev mode: **record** real API traffic from any running build, then **replay** it locally via [MSW](https://mswjs.io/) so you can develop without a live backend.

---

## How it works

```
Record phase (any deployed build)
  Browser → axios interceptor (trafficRecorder.ts)
           → localStorage[__trafficLog]

Replay phase (local dev)
  src/mocks/traffic.json ──(vite plugin)──► virtual:mock-traffic
                                              └─► handlers.ts → MSW service worker
                                                    └─► intercepts fetch/XHR in-browser
```

- **[src/lib/trafficRecorder.ts](../chat-vue/src/lib/trafficRecorder.ts)** — axios request/response interceptors that log each API call (method, path, status, response body) to `localStorage`.
- **[src/mocks/traffic.json](../chat-vue/src/mocks/traffic.json)** — paste your export here (gitignored). Absent in CI — the Vite plugin returns `[]` so the build still succeeds.
- **[src/mocks/handlers.ts](../chat-vue/src/mocks/handlers.ts)** — converts the traffic log into MSW route handlers. Deduplicates by `method + path`; the last captured entry wins.
- **[src/mocks/browser.ts](../chat-vue/src/mocks/browser.ts)** — sets up the MSW browser worker.
- **[public/mockServiceWorker.js](../chat-vue/public/mockServiceWorker.js)** — MSW service worker (committed; required at runtime).
- **[vite.config.ts](../chat-vue/vite.config.ts)** — `mock-traffic` Vite plugin that bundles `traffic.json` as `virtual:mock-traffic`.

---

## Step 1 — Record traffic

Run this against any build that has a live backend (production, staging, or a local `npm run dev` pointed at a real API).

```js
// In the browser DevTools console:

// Start recording
localStorage.setItem('__recordTraffic', 'true')
location.reload()

// Check progress
window.__traffic.count()   // → number of entries captured

// Download traffic.json when done
window.__traffic.export()

// Optional: clear and start over
window.__traffic.clear()

// Stop recording
localStorage.removeItem('__recordTraffic')
location.reload()
```

The recorder captures every axios call made through `apiClient` — chat, transcribe jobs, speakers, samples, etc. It does **not** capture presigned S3 PUTs (those bypass axios).

> **Tip:** Walk through the full UI flow you want to mock before exporting — each distinct `method + path` pair needs at least one captured entry.

---

## Step 2 — Enable replay

1. Move the downloaded `traffic.json` into `chat-vue/src/mocks/traffic.json`.
2. Add the flag to your local env:

   ```
   # chat-vue/.env.local
   VITE_MOCK_API=true
   ```

3. (Optional, no Cognito needed) add `VITE_DEV_AUTH_BYPASS=true` here too and set `DEV_AUTH_BYPASS=true`, `ENVIRONMENT=dev` in `chat-api/.env` — see *Local dev auth bypass* in `chat-vue/CLAUDE.md`.
4. Start the dev server:

   ```bash
   npm run dev
   ```

MSW registers a service worker on startup. In DevTools → Network you'll see requests returning from `(ServiceWorker)` instead of hitting the network.

**Unmatched requests** (e.g. Cognito token exchange, anything not in `traffic.json`) pass through to the real network unchanged — the worker is started with `onUnhandledRequest: 'bypass'`.

Presigned S3 PUTs are always stubbed with `200 OK` regardless of traffic.json, so the audio upload flow works without real S3 credentials.

---

## Auth in mock mode

Cognito requests are **not** intercepted — they still hit the real Cognito endpoint. This means:

- You still need valid Cognito credentials and an app client with `http://localhost:5173/callback` in its allowed callback URLs.
- The `id_token` is stored in `localStorage` and attached to every API request as normal — MSW simply ignores the `Authorization` header when replaying responses.

If you want to skip auth entirely, use the backend auth bypass described in the offline mode section below.

---

## Updating the traffic snapshot

Re-record and re-export whenever:

- You add new API endpoints that your dev flow needs.
- Response shapes change and the old snapshot causes type errors or broken UI.

Because `traffic.json` is gitignored, each developer maintains their own local snapshot.

---

## Fully offline local dev mode (transcription)

The MSW layer mocks the frontend against static responses, but the transcription pipeline also involves audio uploads, a worker process, and speaker embedding. A separate offline mode lets you run the full transcription loop locally — no AWS, no Cognito, no ML models required.

### Architecture

```
Browser (chat-vue)
  → chat-api (local, USE_MOCK_TRANSCRIPTION=true, DEV_AUTH_BYPASS=true)
      → PUT /api/v1/transcribe/dev-upload/<s3_key>   ← writes body to LOCAL_STORAGE_PATH
      → PostgreSQL (local)
  ← job left in "transcribing" state (MOCK_WORKER_EXTERNAL=true)

dev_worker.py (separate process)
  ← polls PostgreSQL for "transcribing" jobs / "processing" samples
  → reads audio from LOCAL_STORAGE_PATH
  → loads per-job fixture JSON from DEV_FIXTURES_DIR (if present)
  → writes TranscriptSegment rows → PostgreSQL
  → marks job "complete"
```

### chat-api environment variables

Add these to `chat-api/.env` (see `.env.example` for the full block):

```env
USE_MOCK_TRANSCRIPTION=true       # enables LocalTranscriptionService + local file storage

DEV_AUTH_BYPASS=true              # skip Cognito JWT validation — never set in prod
DEV_AUTH_USER_SUB=dev-user-001    # sub claim injected for all requests under bypass

LOCAL_STORAGE_PATH=/tmp/mock-audio  # where uploaded audio files are stored on disk

MOCK_WORKER_EXTERNAL=true         # leave job in "transcribing" state for dev_worker.py
                                  # (when false, chat-api simulates the job in-process)
```

> `DEV_AUTH_BYPASS` is guarded by `environment != "prod"` in [app/dependencies.py](../chat-api/app/dependencies.py) and will never activate in production even if accidentally set.

### Running dev_worker.py

```bash
cd transcription-worker

DATABASE_URL=postgresql+psycopg2://user:pass@localhost/chat-api \
LOCAL_STORAGE_PATH=/tmp/mock-audio \
DEV_FIXTURES_DIR=/tmp/mock-fixtures \
AUDIO_BUCKET_NAME=unused \
TRANSCRIBE_SQS_QUEUE_URL=unused \
python dev_worker.py
```

The worker polls PostgreSQL every 2 seconds (configurable via `DEV_WORKER_POLL_INTERVAL`). It does not use SQS, torch, pyannote, or SpeechBrain.

**What it does for each job:**

1. Picks up any `TranscriptionJob` in `transcribing` state
2. Loads fixture JSON from `DEV_FIXTURES_DIR/<job_id>/` if present; otherwise generates synthetic data
3. Aligns words to diarization turns using the same `services/aligner.py` as the real worker
4. Writes `TranscriptSegment` rows and marks the job `complete`

**What it does for each sample:**

Finds `SpeakerSample` rows in `processing` state and marks them `ready` with a random 192-dim unit vector (same dimension as the real ECAPA-TDNN embeddings).

### Fixture files

Fixtures let you inject real captured pipeline data at any stage. Place them at `DEV_FIXTURES_DIR/<job_id>/<stage>.json`:

| File | Format | Effect |
|---|---|---|
| `transcribe.json` | AWS Transcribe output (same as `transcript_raw.json`) | Used for word timestamps instead of synthetic words |
| `diarize.json` | `[{"speaker_label": "SPEAKER_00", "start": 0.5, "end": 3.2}, ...]` | Used for diarization turns instead of synthetic turns |
| `matcher.json` | `[{"start": 0.5, "end": 3.2, "speaker_profile_id": "<uuid>\|null", "cosine_dist": 0.18}, ...]` | Injects speaker-match results; also used to derive turns if `diarize.json` is absent |

Any missing fixture stage falls back to synthetic data — you can mix and match.

### Capturing real fixtures from production

The production transcription worker can write fixtures automatically if `DEV_CAPTURE_FIXTURES_DIR` is set:

```env
# transcription-worker environment (ECS task definition or local .env)
DEV_CAPTURE_FIXTURES_DIR=/tmp/captured-fixtures
```

This writes `transcribe.json`, `diarize.json`, and `matcher.json` after each pipeline stage for every job processed. Copy the output directory to your local `DEV_FIXTURES_DIR` to replay that exact job without ML models.

### Tuning synthetic output

When no fixtures are present, `dev_worker.py` generates data from these env vars:

| Variable | Default | Description |
|---|---|---|
| `DEV_WORKER_POLL_INTERVAL` | `2` | Seconds between DB polls |
| `DEV_WORKER_SEGMENTS` | `6` | Number of synthetic diarization turns per job |

---

## Photogrammetry mock

`USE_MOCK_PHOTOGRAMMETRY=true` in `chat-api/.env` swaps in `LocalPhotogrammetryService`:

- `POST /api/v1/photogrammetry/jobs` returns one dev-upload sink URL per photo; the browser PUTs
  them there (4 at a time), then confirms.
- Confirmed jobs walk `queued → processing (sfm → dense → mesh → texture) → complete`, one
  `MOCK_PHOTOGRAMMETRY_STAGE_DELAY_SECONDS` (default 2 s) per step, then the committed placeholder
  `chat-api/app/assets/photogrammetry/{mesh.glb,preview.png}` is copied into the sink under the job's
  `output/` keys and served back by the sink's GET — `<model-viewer>` loads the GLB from there.
- `GET /samples` seeds the bundled photo set into the sink on first call and lists it with
  thumbnails (`thumbs/` beside `images/`, generated by the same Pillow code as prod); `GET
  /jobs/{id}/photos` lists a job's uploaded photos the same way.
- **Sample** in the sidebar (`POST /jobs/sample`) copies the bundled photo set into the sink and runs
  the same walk, so the page works with nothing uploaded.
- Every status response carries `mock: true`; the viewer labels the mesh as a placeholder.
- `<model-viewer>` and the preview `<img>` fetch from `MOCK_UPLOAD_BASE_URL` (default
  `http://localhost:8000`) cross-origin from the Vite dev server, so `CORS_ORIGINS` in
  `chat-api/.env` must include `http://localhost:5173` — or set
  `MOCK_UPLOAD_BASE_URL=http://localhost:5173` so the sink URLs ride the Vite `/api` proxy.

Regenerate the sample assets with `scripts/dev/make-photogrammetry-sample.py` (see its docstring).

---

## Key files at a glance

| File | Purpose |
|---|---|
| [chat-vue/src/lib/trafficRecorder.ts](../chat-vue/src/lib/trafficRecorder.ts) | Axios interceptors + `window.__traffic` console helpers |
| [chat-vue/src/mocks/traffic.json](../chat-vue/src/mocks/traffic.json) | Captured traffic (gitignored; paste export here) |
| [chat-vue/src/mocks/handlers.ts](../chat-vue/src/mocks/handlers.ts) | Converts traffic log → MSW handlers |
| [chat-vue/src/mocks/browser.ts](../chat-vue/src/mocks/browser.ts) | MSW worker setup |
| [chat-vue/public/mockServiceWorker.js](../chat-vue/public/mockServiceWorker.js) | MSW service worker (committed) |
| [chat-vue/vite.config.ts](../chat-vue/vite.config.ts) | `mock-traffic` virtual module plugin |
| [chat-vue/src/main.ts](../chat-vue/src/main.ts) | Conditionally starts MSW when `VITE_MOCK_API=true` |
| [chat-api/app/services/audio_storage.py](../chat-api/app/services/audio_storage.py) | `LocalAudioStorageService` — filesystem-backed upload/read/delete |
| [chat-api/app/api/v1/transcribe/dev.py](../chat-api/app/api/v1/transcribe/dev.py) | `PUT`/`GET /dev-upload/*` sink — writes uploads to `LOCAL_STORAGE_PATH` and serves stored files back (mock mesh/preview) |
| [chat-api/app/dependencies.py](../chat-api/app/dependencies.py) | `DEV_AUTH_BYPASS` guard in `get_current_user` |
| [chat-vue/src/stores/auth.ts](../chat-vue/src/stores/auth.ts) | `VITE_DEV_AUTH_BYPASS` — dev-build-only counterpart: no Cognito redirect, no `Authorization` header |
| [chat-api/app/config.py](../chat-api/app/config.py) | `dev_auth_bypass`, `local_storage_path`, `mock_worker_external` settings |
| [transcription-worker/dev_worker.py](../transcription-worker/dev_worker.py) | Standalone DB-polling worker — no ML, no SQS |
| [transcription-worker/handlers/transcription.py](../transcription-worker/handlers/transcription.py) | `_maybe_capture()` — writes fixture JSON when `DEV_CAPTURE_FIXTURES_DIR` is set |
| [chat-api/app/services/photogrammetry_service.py](../chat-api/app/services/photogrammetry_service.py) | `LocalPhotogrammetryService` — timed stage walk, placeholder outputs |
| [chat-api/app/assets/photogrammetry/](../chat-api/app/assets/photogrammetry/) | Sample photo set (EXIF-stripped) + placeholder `mesh.glb` / `preview.png` |
| [scripts/dev/make-photogrammetry-sample.py](../scripts/dev/make-photogrammetry-sample.py) | Regenerates those assets from a photo folder (or `--synthetic`) |
