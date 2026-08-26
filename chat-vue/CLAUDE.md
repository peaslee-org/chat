# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Local dev:**
```bash
cp .env.example .env.local    # fill in values
npm install
npm run dev                    # Vite dev server on http://localhost:5173
```

**Type check:**
```bash
npm run type-check             # vue-tsc --noEmit
```

**Lint:**
```bash
npm run lint
```

**Production build (for S3):**
```bash
npm run build                  # outputs to dist/
```

**Preview production build locally:**
```bash
npm run preview                # serves dist/ on http://localhost:4173
```

There are no tests.

## Mock API (traffic capture + replay)

**Record traffic from any deployed build:**
```js
// In browser console on production (or any build):
localStorage.setItem('__recordTraffic', 'true')
location.reload()

window.__traffic.count()   // how many entries captured
window.__traffic.export()  // downloads traffic.json
window.__traffic.clear()   // reset
localStorage.removeItem('__recordTraffic'); location.reload()  // stop recording
```

**Replay in dev:**
1. Copy downloaded `traffic.json` → `src/mocks/traffic.json` (gitignored)
2. Add to `.env.local`: `VITE_MOCK_API=true`
3. `npm run dev` — MSW intercepts matched requests; unmatched (e.g. Cognito) pass through

**Key files:**
- `src/lib/trafficRecorder.ts` — axios interceptor, localStorage store, console helpers
- `src/mocks/traffic.json` — paste export here (gitignored)
- `src/mocks/handlers.ts` — converts traffic.json → MSW handlers (deduplicates by method+path, last capture wins)
- `src/mocks/browser.ts` — MSW worker setup
- `public/mockServiceWorker.js` — MSW service worker (committed, required at runtime)
- `vite.config.ts` — `mock-traffic` plugin provides `virtual:mock-traffic`; returns `[]` if file absent (safe for CI)

## Architecture

Layered: **router (Vue Router) → views → components → stores (Pinia) → lib/axios → backend API**

```
src/
  main.ts              App entry: creates Vue app, installs Pinia + Router
  App.vue              Root component — just <RouterView>
  env.d.ts             Vite env var type augmentation
  types/index.ts       Shared TypeScript interfaces (mirrors backend Pydantic schemas);
                       includes chat types (Conversation, Message, Model) and transcribe
                       types (SpeakerProfile, SpeakerSample, TranscriptionJob, TranscriptResponse, etc.)
  config/cognito.ts    Cognito OAuth URL builders from VITE_ env vars
  config/models.ts     Static Bedrock model list (AVAILABLE_MODELS) and DEFAULT_MODEL_ID
  lib/
    pkce.ts            PKCE code_verifier + code_challenge generation (WebCrypto)
    axios.ts           Axios instance with auth interceptor and 401 handler
    transcribeApi.ts   Transcribe feature API calls (speakers, samples, jobs, transcripts)
    photogrammetryApi.ts   Photogrammetry API calls (jobs, uploads, mesh URL)
  stores/
    auth.ts            Authentication state: token, login(), handleCallback(), logout()
    chat.ts            Conversation list + active thread, sendMessage(), deleteConversation()
    models.ts          Fetches available models from GET /api/v1/models; falls back to
                       static AVAILABLE_MODELS list on error
    transcribe.ts      Speaker profiles + samples + transcription jobs state; polling for
                       in-flight jobs (5 s interval) and processing samples (3 s interval)
    photogrammetry.ts   Scan jobs state, concurrent uploads, 3 s polling, presigned mesh URL cache
  router/index.ts      Four routes: / (ChatView), /transcribe (TranscribeView), /photogrammetry
                       (PhotogrammetryView), /callback (CallbackView)
  views/
    ChatView.vue       Main layout: sidebar + message thread
    CallbackView.vue   OAuth callback handler — exchanges code for tokens
    TranscribeView.vue Transcribe layout: resizable sidebar (RunSidebar) + detail panel (RunDetailView)
    PhotogrammetryView.vue  Scan layout: resizable ScanSidebar + ScanDetailView, GpuStatusBar on top
  components/
    ConversationSidebar.vue              Left panel: conversation list, new/delete, logout
    MessageList.vue                      Scrollable message thread with typing indicator
    MessageBubble.vue                    Single message (user = right/indigo, assistant = left/white)
    MessageInput.vue                     Textarea + send button; shows model selector above input
                                         when isNewConversation is true; Enter to send, Shift+Enter for newline
    transcribe/
      RunSidebar.vue           Left panel: job list + new job form toggle
      RunDetailView.vue        Right panel: job detail, transcript, speaker panel
      NewJobForm.vue           Audio file dropzone + job params (language, speaker count, speaker IDs)
      AudioFileDropzone.vue    Drag-and-drop / click-to-upload audio file picker
      TranscribeJobCard.vue    Job summary card in the sidebar list
      JobStatusBadge.vue       Status chip (pending / transcribing / matching / complete / failed)
      JobPanel.vue             Job metadata + activity log for the selected job
      TranscriptDisplay.vue    Rendered transcript segments with speaker labels
      SpeakerPanel.vue         Speaker profile management panel
      SpeakerProfileCard.vue   Expandable card: speaker name, samples list, upload
      SpeakerSampleRow.vue     Single sample row with status and delete action
      SampleStatusBadge.vue    Status chip (processing / ready / failed) for a sample
    photogrammetry/
      ScanSidebar.vue          Left panel: job list + New/Sample buttons
      ScanJobCard.vue          Job summary card in the sidebar list
      ScanStatusBadge.vue      Status chip (pending / queued / processing / complete / failed)
      StageStrip.vue           Four-step strip (sfm · dense · mesh · texture), current step highlighted
      ImageDropzone.vue        Multi-file drag/drop image picker with thumbnails
      NewScanForm.vue          Name + dropzone + Start scan, shows uploadProgress
      ScanDetailView.vue       Header + form/preview/stage-strip/viewer/error body for the selected job
      MeshViewer.vue           <model-viewer> web component; registered as a custom element in
                               vite.config.ts
```

All imports use the `@` alias which maps to `src/`.

## Auth Flow

1. Router guard detects unauthenticated → calls `auth.login()`
2. `login()` generates PKCE verifier/challenge, stores verifier in `sessionStorage`, redirects to Cognito Hosted UI
3. Cognito redirects to `/callback?code=...`
4. `CallbackView` calls `auth.handleCallback(code)` → POST to Cognito `/oauth2/token`
5. `id_token` stored in `localStorage`; user redirected to `/`
6. All API calls via `apiClient` (lib/axios.ts) include `Authorization: Bearer <id_token>`
7. On logout: `localStorage` cleared, browser redirected to Cognito `/logout`

The logout URL is derived from `VITE_COGNITO_REDIRECT_URI` by stripping `/callback` to get the app root.

Both `/` and `/transcribe` routes require auth; the guard calls `auth.login()` and returns `false` to abort navigation for unauthenticated users.

## Environment Variables

All env vars use the `VITE_` prefix (required by Vite for client-side exposure).

| Variable | Example |
|---|---|
| `VITE_API_BASE_URL` | `https://api.example.com` |
| `VITE_COGNITO_DOMAIN` | `myapp.auth.us-east-1.amazoncognito.com` |
| `VITE_COGNITO_CLIENT_ID` | `abc123xyz` |
| `VITE_COGNITO_REDIRECT_URI` | `https://app.example.com/callback` |
| `VITE_COGNITO_SCOPE` | `openid email profile` |

**Local dev API connectivity:** Two options:
- Set `VITE_API_BASE_URL=http://localhost:8000` — axios calls the backend directly (default in `.env.example`)
- Set `VITE_API_BASE_URL=` (empty) — axios uses relative paths, Vite dev server proxies `/api/*` → `http://localhost:8000`

## S3 Deployment

```bash
npm run build
aws s3 sync dist/ s3://your-bucket-name --delete
aws cloudfront create-invalidation --distribution-id YOUR_DIST_ID --paths "/*"
```

CloudFront must serve `index.html` for all 403/404 responses (required for SPA routing — especially for the `/callback` redirect).

## Backend

The chat-api is at `/var/www/chat/chat-api`. Key endpoints:

**Chat:**

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/models` | List available Bedrock models |
| POST | `/api/v1/chat` | `{conversation_id?, message, model_id?}` → `{conversation_id, reply}`; `model_id` only used when creating a new conversation |
| GET | `/api/v1/conversations` | List conversations for current user |
| GET | `/api/v1/conversations/{id}/messages` | Fetch message history for a conversation |
| DELETE | `/api/v1/conversations/{id}` | 204 |

**Transcribe (`/api/v1/transcribe/`):**

| Method | Path | Notes |
|---|---|---|
| POST | `/speakers` | Create speaker profile; `{speaker_name?}` → `SpeakerProfile` |
| GET | `/speakers` | Paginated list; `?cursor&limit` → `{items, next_cursor}` |
| GET | `/speakers/{id}` | Get speaker with samples |
| PATCH | `/speakers/{id}` | Rename; `{speaker_name}` |
| DELETE | `/speakers/{id}` | 204 |
| POST | `/speakers/{id}/samples` | Initiate upload → `{sample_id, upload_url}` |
| POST | `/speakers/{id}/samples/{sid}/confirm` | Confirm S3 upload → `SpeakerSample` with actual status |
| DELETE | `/speakers/{id}/samples/{sid}` | 204 |
| POST | `/jobs` | Create job; `{speaker_count_hint?, speaker_ids?, language?}` → `{job_id, upload_url}` |
| POST | `/jobs/{id}/confirm` | Confirm audio uploaded; transitions job → `transcribing` |
| GET | `/jobs` | Paginated list; `?cursor&limit` → `{items, next_cursor}` |
| GET | `/jobs/{id}` | Get job status (`TranscriptionJob`) |
| GET | `/jobs/{id}/transcript` | Get transcript → `{segments, transcript_url}` |
| DELETE | `/jobs/{id}` | 204 |

**Transcribe upload flow (two-phase S3 presigned PUT):**
1. Call POST to create job/sample → get `upload_url`
2. PUT file directly to S3 using the presigned URL (no auth header — use plain `fetch`, not `apiClient`)
3. Call confirm endpoint → backend transitions status and begins processing

**Photogrammetry (`/api/v1/photogrammetry/`):**

| Method | Path | Notes |
|---|---|---|
| POST | `/jobs` | `{name, filenames[]}` → `{job_id, uploads[{filename,key,url}]}` |
| POST | `/jobs/{id}/confirm` | Confirm photos uploaded; transitions job → `queued` |
| GET | `/jobs` | Paginated list; `?cursor&limit` → `{items, next_cursor}` |
| GET | `/jobs/{id}` | Get job status |
| DELETE | `/jobs/{id}` | 204 |
| POST | `/jobs/sample` | Seed a job from the bundled sample photo set and confirm it |
| GET | `/jobs/{id}/mesh` | `{url, expires_at}` — presigned GLB URL |

## Notes

- No Dockerfile — static site deployed to S3 + CloudFront
- Tailwind CSS 3 with PostCSS + autoprefixer
- `vue-tsc` runs as part of `npm run build` — type errors block the build
- PKCE flow uses native `window.crypto.subtle` — no external auth SDK
- Switching conversations calls `GET /api/v1/conversations/{id}/messages` and merges the result into the store; previously loaded messages are preserved in-memory across switches
- Add `http://localhost:5173/callback` to Cognito App Client allowed callback URLs for local dev
- Set `CORS_ORIGINS` in chat-api to include the CloudFront domain in production
- Transcribe sidebar width is persisted to `localStorage` under `transcribeSidebarWidth`
- Transcribe job polling uses 5 s intervals; sample status polling uses 3 s intervals; both resume on page reload via `resumePollingForActiveJobs()` / `resumePollingForProcessingSamples()`; polling has a cutoff so jobs that stay in a terminal state stop being polled
- Job statuses: `pending → transcribing → matching → complete | failed`; `partial_transcript_available` may be true before `complete`
- Sample statuses: `processing → ready | failed`; `SpeakerSample.error_message` holds the worker error reason when `failed`
- When sample polling detects a `processing → failed` transition, `transcribe` store pushes a toast (auto-dismisses after 8 s); `TranscribeView` renders toasts via `Teleport` bottom-right overlay; store exports `toasts` and `dismissToast`
- S3 uploads must use plain `fetch` (not `apiClient`) — no Authorization header allowed on presigned PUT requests
- Scan sidebar width is persisted under `scanSidebarWidth`; job polling every 3 s (`VITE_PHOTOGRAMMETRY_POLL_INTERVAL_MS`), 60 s while the GPU worker is off; resumes on reload via `resumePollingForActiveJobs()`
- The `GpuStatusBar` on `/photogrammetry` is the transcribe component reused unchanged: it reflects the *transcription* worker (`/api/v1/gpu/*`, `GPU_WORKER_TASK_FAMILY`) and its Warm button launches that worker; with only `USE_MOCK_PHOTOGRAMMETRY=true` it shows "off". Parameterising it by task family is part of the worker spec.
