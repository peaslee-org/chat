# chat-vue

Vue 3 · TypeScript · Tailwind CSS · AWS Cognito · Vite

## Quick start (local)

```bash
cp .env.example .env.local    # fill in values
npm install
npm run dev                    # Vite dev server on http://localhost:5173
```

Add `http://localhost:5173/callback` to your Cognito App Client's allowed callback URLs.

## Environment variables

| Variable | Example |
|---|---|
| `VITE_API_BASE_URL` | `https://api.example.com` |
| `VITE_COGNITO_DOMAIN` | `myapp.auth.us-east-1.amazoncognito.com` |
| `VITE_COGNITO_CLIENT_ID` | `abc123xyz` |
| `VITE_COGNITO_REDIRECT_URI` | `https://app.example.com/callback` |
| `VITE_COGNITO_SCOPE` | `openid email profile` |

Set `VITE_API_BASE_URL=http://localhost:8000` to call the backend directly, or leave it empty to use the Vite dev server proxy.

## Other commands

```bash
npm run type-check    # vue-tsc --noEmit
npm run lint
npm run build         # production build → dist/
npm run preview       # serve dist/ on http://localhost:4173
```

## Deploy to S3 + CloudFront

```bash
npm run build
aws s3 sync dist/ s3://your-bucket-name --delete
aws cloudfront create-invalidation --distribution-id YOUR_DIST_ID --paths "/*"
```

CloudFront must return `index.html` for 403/404 responses for SPA routing to work.

## Mock API (traffic capture + replay)

Record API traffic from any running build, then replay it locally without a backend:

```js
// In browser console on any build:
localStorage.setItem('__recordTraffic', 'true'); location.reload()
window.__traffic.count()   // entries so far
window.__traffic.export()  // downloads traffic.json
localStorage.removeItem('__recordTraffic'); location.reload()  // stop
```

Copy `traffic.json` → `src/mocks/traffic.json`, add `VITE_MOCK_API=true` to `.env.local`, then `npm run dev`. MSW intercepts matched requests; unmatched ones (e.g. Cognito) pass through. Presigned S3 PUTs are always stubbed `200 OK`.

See [docs/mock-api.md](../docs/mock-api.md) for the full guide including the fully-offline backend mode.

## Debugging (local dev)

Runtime errors (API failures, auth errors) are surfaced in the UI via the `error` state in each Pinia store. The axios interceptor automatically logs out the user on any `401` response.

Transcribe job polling uses 5 s intervals; sample status polling uses 3 s intervals. Both resume on page reload. The `transcribe` store emits toast notifications (auto-dismiss 8 s) on `processing → failed` sample transitions, rendered via `Teleport` in `TranscribeView`.

## Logs and monitoring

The frontend is a static SPA — there is no server-side process and no application logs. Observability comes from two sources:

**CloudFront** — access logs (requests, cache hits/misses, error rates) can be enabled on the distribution via the AWS Console or Terraform. Not enabled by default.

**chat-api** — all API errors are logged server-side with structured JSON fields (`user_id`, `conversation_id`, stack traces). See the [chat-api README](../chat-api/README.md#logs) for log group locations and example CloudWatch Logs Insights queries.

No client-side error tracking (Sentry, LogRocket, etc.) is currently configured.

## Project layout

```
src/
  main.ts              App entry: creates Vue app, installs Pinia + Router
  App.vue              Root component — just <RouterView>
  types/index.ts       Shared TypeScript interfaces (chat + transcribe types)
  config/cognito.ts    Cognito OAuth URL builders
  config/models.ts     Static Bedrock model list and DEFAULT_MODEL_ID
  lib/
    pkce.ts            PKCE code_verifier + code_challenge (WebCrypto)
    axios.ts           Axios instance with auth interceptor and 401 handler
    transcribeApi.ts   Transcribe feature API calls (speakers, samples, jobs, transcripts)
    trafficRecorder.ts Axios interceptor for recording/replaying API traffic (mock dev)
  stores/
    auth.ts            Authentication state: token, login(), handleCallback(), logout()
    chat.ts            Conversation list + active thread, sendMessage(), deleteConversation()
    models.ts          Fetches available models from GET /api/v1/models
    transcribe.ts      Speaker profiles + samples + jobs; job/sample polling; toast system
  router/index.ts      Routes: / (ChatView), /transcribe (TranscribeView), /callback (CallbackView)
  views/
    ChatView.vue       Main layout: sidebar + message thread
    CallbackView.vue   OAuth callback handler
    TranscribeView.vue Transcribe layout: resizable sidebar + detail panel; toast overlay
  components/
    ConversationSidebar.vue
    MessageList.vue
    MessageBubble.vue
    MessageInput.vue
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
  mocks/
    handlers.ts        MSW handlers built from traffic.json (deduplicates by method+path)
    browser.ts         MSW worker setup
```
