### `chat-vue`

> **Status (2026-08-29).** Summary of the original Transcribe UI design; built as described. See the
> status block in `chat-vue-spec.md` for what changed since, and `chat-vue/CLAUDE.md` for the current
> component map.


Implements the frontend for the transcription feature at a new `/transcribe` route.

#### New Modules

- **TypeScript interfaces** mirroring backend schemas
- **`transcribeApi.ts`** — API calls via the existing `apiClient`; direct S3 uploads via bare `fetch`
- **`transcribe` Pinia store** — manages speaker and job state with automatic 5-second polling for in-flight jobs

#### UI Layout

A two-panel view:

| Panel | Responsibility |
|---|---|
| **Speaker Panel** (left) | Create speaker profiles; upload 10–60 s reference audio samples |
| **Job Panel** (right) | Submit audio files (language/speaker-hint options), track job status, render the resolved transcript |

#### New Components

Adds 10 components under `src/components/transcribe/`.

#### Navigation

Adds **Chat / Transcribe** nav tabs to the existing `ConversationSidebar`.

---

**Spec:** `docs/transcribe/chat-vue-spec.md`
