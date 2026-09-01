# aiTools rename + public demo — design

**Date:** 2026-09-01
**Status:** approved in discussion; awaiting implementation plan

## Goal

Present the project publicly as **aiTools** — one product with three features
(chat, transcribe, photogrammetry) — and add a public, read-only demo so the
running system can be shown off as a portfolio piece. Two work packages,
landed in order: the rename first, then the demo (so the demo ships under the
new name).

## Part 1: chat → aiTools (product layer only)

### Scope rule

Rename the *product-facing* layer. The word "chat" survives only where it
names the chat feature itself. AWS resource names, repo directory names, the
tfstate bucket, and the DB schema are explicitly **not** renamed — they are
internal, and renaming them is a migration with no user-visible payoff.

### GitHub repo

- Rename `peaslee-org/chat` → `peaslee-org/aiTools`. GitHub redirects the old
  URL for clones, PRs, and API calls.
- Update the local `origin` fetch/push URLs. The Henry push remote is already
  `ssh://henry/srv/data/git/aiTools/chat.git` and stays.
- **Ordering constraint:** the GitHub Actions OIDC deploy roles (prod, plus
  the transcription and photogrammetry worker roles) trust
  `repo:peaslee-org/chat:ref:refs/heads/main`. The Terraform `github_repo`
  variable must be changed and applied in **both** environments *before* the
  next push to `main` after the rename, or CI cannot assume the roles. Role
  ARNs do not change, so repo secrets are untouched.

### Domain

- `aitools.peaslee.org` becomes the primary; `chat.peaslee.org` stays as an
  alias indefinitely (both served by the same CloudFront distribution).
- `infra/modules/acm`: add a `subject_alternative_names` input. A cert cannot
  be amended, so this is a **replacement cert** covering both names, with DNS
  validation records for both, after which CloudFront swaps to it.
- `infra/modules/cloudfront`: `aliases` becomes a list (both domains).
- DNS (manual): add the `aitools` CNAME to the distribution domain.
- Cognito app client: allowlist `https://aitools.peaslee.org/callback` and
  the matching logout URL alongside the existing production + localhost
  entries. Terraform declares the app client but not its OAuth block — the
  Hosted UI callback/logout allowlist is console-managed — so this is a
  manual console step, not part of the Terraform applies.
- `CORS_ORIGINS` in chat-api gains `https://aitools.peaslee.org`.

### Branding

- chat-vue: app title, header, and product naming become **aiTools**, with
  chat / transcribe / photogrammetry presented as its features.
- README and public-track docs updated the same way (placeholder rules for
  `docs/` unchanged; `docs/private/` handled separately if needed).

### Rollout order

1. Terraform: cert SANs + CloudFront aliases + OIDC `github_repo` var; apply
   both environments (`prod`, `transcription-prod`).
2. DNS: add the `aitools` CNAME (plus the new cert's validation records).
3. Cognito callbacks (console-managed, manual step) + CORS (Terraform-managed;
   part of the same applies).
4. Rename the GitHub repo; update local remotes.
5. Branding/docs PR through normal CI.
6. Verify: login works on both domains; a push to `main` deploys green.

## Part 2: Public demo — live read-only showcase

Visitors get a no-login demo page rendering real results through real API
endpoints. Nothing is public unless explicitly flagged.

### Data model

One Alembic migration adds `is_public` (boolean, not null, server default
false) to:

- `conversations` (`Conversation`)
- `transcription_jobs` (`TranscriptionJob`)
- `photogrammetry_jobs` (`PhotogrammetryJob`)

Child rows (messages, transcript segments, speaker labels, photo status)
inherit visibility through their parent; they carry no flag of their own.

### Public API

A new unauthenticated, read-only router mounted at `/api/v1/public`, serving
only `is_public` rows. A non-public id and a nonexistent id return the same
404, so ids cannot be probed.

| Endpoint | Returns |
|---|---|
| `GET /public/showcase` | One bootable payload: public photogrammetry jobs (name, preview URL, photo count), public transcriptions (title, duration), public conversations (title, model). |
| `GET /public/photogrammetry/{id}` | Job detail: warnings, photo_status summary, short-lived presigned GETs for `output/mesh.glb` and `output/preview.png`. |
| `GET /public/transcriptions/{id}` | Segments with speaker labels and timestamps. |
| `GET /public/conversations/{id}` | Messages, role + content only. |

**Scrubbing rule:** public responses never include `user_id`, S3 keys or
prefixes, cost fields, or queue/session internals. Presigned URLs expire in
~15 minutes. Abuse exposure is bounded to S3 GET bandwidth on the flagged
objects — acceptable for a portfolio.

**Ruling on presigned URL paths:** presigned URLs are themselves served on
the public surface, and their path necessarily reveals the storage bucket
name, the owning user's opaque Cognito `sub`, and the job id (the object key
is `photogrammetry/<cognito-sub>/<job-id>/output/…`). This is an accepted
disclosure, not a violation of the scrubbing rule above: nothing in the URL
grants access beyond what the signature already scopes and time-limits, and
a Cognito `sub` is an opaque identifier with no PII value on its own. If this
ever needs tightening, the noted alternative is a `public/<job_id>/` output
prefix (populated by copying or symlinking flagged job output) so presigned
paths carry no user identifier at all.

### Owner toggle

The existing authenticated detail endpoints for each of the three types gain
a `PATCH`-able `is_public` field (owner only). The SPA shows a "Public"
toggle on jobs and conversations the signed-in user owns. Demo content is
curated live, with no redeploy.

### SPA

A no-auth `/demo` route in chat-vue:

- Landing frame: "aiTools — chat · transcribe · photogrammetry", one section
  per feature.
- Reuses the existing model-viewer, transcript, and message components in
  read-only mode, fed by `/api/v1/public/*`.
- The login page links to it ("View the demo"); `/demo` is the shareable
  portfolio link.

### Testing

- API: flagged rows served; unflagged and nonexistent ids → identical 404;
  scrubbed fields absent from every public schema; `is_public` PATCH requires
  ownership.
- Vue: `/demo` renders from a mocked showcase payload and never triggers the
  auth guard.

### Out of scope (YAGNI)

No visitor-triggered jobs, no new rate limiting, no CloudFront cache tuning,
no analytics.
