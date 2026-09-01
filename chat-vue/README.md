# chat-vue

Vue 3 · TypeScript · Tailwind CSS · Pinia · AWS Cognito (PKCE) · Vite · vitest

The browser app for **aitools.peaslee.org** (alias: chat.peaslee.org): three tabs — **Chat** (Claude via Bedrock), **Transcribe**
(audio → transcript with speaker diarization) and **Scan** (photos → textured 3D mesh). A `/profile`
page and an `/admin` area (user list) round it out. End-user documentation: [docs/user-guide.md](../docs/user-guide.md).

## Quick start (local)

```bash
cp .env.example .env.local    # fill in values
npm install
npm run dev                    # Vite dev server on http://localhost:5173
```

For feature work run the backend too (`../chat-api`, with its mocks and `DEV_AUTH_BYPASS=true`) and set
`VITE_DEV_AUTH_BYPASS=true` here — no Cognito needed. Open **http://localhost:5173** (not `127.0.0.1`,
which is outside the API's CORS allow-list). Against a real Cognito pool, add
`http://localhost:5173/callback` to the App Client's allowed callback URLs.

## Environment variables

| Variable | Example |
|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` (empty → Vite proxies `/api/*` to `localhost:8000`) |
| `VITE_COGNITO_DOMAIN` | `myapp.auth.us-east-1.amazoncognito.com` |
| `VITE_COGNITO_CLIENT_ID` | `abc123xyz` |
| `VITE_COGNITO_REDIRECT_URI` | `http://localhost:5173/callback` |
| `VITE_COGNITO_SCOPE` | `openid email profile` |
| `VITE_DEV_AUTH_BYPASS` | `true` — dev builds only: skip Cognito, send no `Authorization` header |
| `VITE_MOCK_API` | `true` — replay recorded traffic through MSW (see below) |
| `VITE_PHOTOGRAMMETRY_POLL_INTERVAL_MS` | `3000` — scan job polling interval |

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Vite dev server |
| `npm run test` | vitest (unit/component specs under `src/**/__tests__/`) |
| `npm run build` | `vue-tsc` + production build → `dist/` |
| `npm run preview` | serve `dist/` on http://localhost:4173 |
| `npm run lint` | eslint `--fix` |
| `npm run type-check` | `vue-tsc --noEmit` — currently checks nothing (solution-style root tsconfig); use `npx vue-tsc -p tsconfig.app.json --noEmit` |

## Deploy

Pushing to `main` with changes under `chat-vue/` runs `.github/workflows/deploy.yml`, which deploys
the API first (if it changed) and then this app via the reusable `vue.yml`: build with the `VITE_*`
secrets → `aws s3 sync dist/ --delete` to the frontend bucket → CloudFront invalidation. To redeploy
without a code change: `gh workflow run Deploy -f vue=true`. Details: [docs/runbooks/deploy.md](../docs/runbooks/deploy.md).

Manual fallback: `npm run build && aws s3 sync dist/ s3://<frontend-bucket> --delete && aws cloudfront
create-invalidation --distribution-id <id> --paths "/*"`. CloudFront must return `index.html` for
403/404 responses so SPA routes (and the `/callback` redirect) work.

## Mock API (traffic capture + replay)

Record API traffic from any running build, then replay it locally without a backend:

```js
// In browser console on any build:
localStorage.setItem('__recordTraffic', 'true'); location.reload()
window.__traffic.count()   // entries so far
window.__traffic.export()  // downloads traffic.json
localStorage.removeItem('__recordTraffic'); location.reload()  // stop
```

Copy `traffic.json` → `src/mocks/traffic.json`, add `VITE_MOCK_API=true` to `.env.local`, then `npm run dev`. MSW intercepts matched requests; unmatched ones (e.g. Cognito) pass through. Presigned S3 PUTs are always stubbed `200 OK`. Replay is static — jobs don't progress; for that use the API's own mocks (see [docs/mock-api.md](../docs/mock-api.md)).

## Debugging (local dev)

Runtime errors (API failures, auth errors) are surfaced in the UI via the `error` state in each Pinia store and as toasts (top-right of the body pane) for job failures and new scan warnings. The axios interceptor logs the user out on any `401`.

Polling: transcribe jobs 5 s, speaker samples 3 s, scan jobs 3 s (60 s while the GPU worker is off), GPU state 30 s. All resume on page reload.

## Logs and monitoring

The frontend is a static SPA — there is no server-side process and no application logs. CloudFront access logs can be enabled on the distribution (not enabled by default). API-side errors are logged by chat-api — see its [README](../chat-api/README.md). No client-side error tracking (Sentry, LogRocket, etc.) is configured.

## Project layout

```
src/
  main.ts / App.vue    App entry (Pinia + Router) and <RouterView>
  types/index.ts       Shared TypeScript interfaces (chat, transcribe, photogrammetry, gpu, admin)
  config/              cognito.ts (OAuth URL builders), models.ts (Bedrock model list)
  lib/                 axios.ts, pkce.ts, transcribeApi.ts, photogrammetryApi.ts, gpuApi.ts,
                       workerState.ts (GPU labels), trafficRecorder.ts
  stores/              auth, chat, models, transcribe, photogrammetry, gpu, profile, admin
  router/index.ts      / · /transcribe · /photogrammetry · /profile · /admin · /callback
  views/               ChatView, TranscribeView, PhotogrammetryView, CallbackView, profile/, admin/
  components/          chat (ConversationSidebar, MessageList, MessageBubble, MessageInput)
    transcribe/        GpuStatusBar (shared), RunSidebar, RunDetailView, NewJobForm, AudioFileDropzone,
                       AudioPlayer, TranscribeJobCard, JobStatusBadge, JobPanel, TranscriptDisplay,
                       MatchingAnalysis, SpeakerPanel, SpeakerProfileCard, SpeakerSampleRow, SampleStatusBadge
    photogrammetry/    ScanSidebar, ScanJobCard, ScanStatusBadge, StageStrip, ImageDropzone, NewScanForm,
                       PhotoGrid, ScanDetailView, MeshViewer
  mocks/               MSW handlers built from traffic.json, worker setup
```

See [CLAUDE.md](CLAUDE.md) for the component-by-component map and the auth flow.
