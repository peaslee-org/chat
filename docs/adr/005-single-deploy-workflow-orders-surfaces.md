# ADR 005 — One Deploy workflow orders the surfaces

**Status:** Accepted 2026-08-29.

## Context
Each surface (API, frontend, two workers) had its own GitHub Actions workflow with a `paths:`
filter. One push touching several directories fired them all in parallel. The API carries the
Alembic migrations (run by the container entrypoint), and a worker whose ORM model selects a new
column raises on every SQS receipt until that migration lands — the ordering held only when the
GPU pool happened to be idle. Pushing surfaces one at a time was a runbook rule people had to
remember.

## Decision
A single `deploy.yml` runs on push to `main`. A `changes` job (`dorny/paths-filter`) reports which
directories changed; the per-surface workflows become reusable (`workflow_call`) and run as jobs
with `needs:` — `chat-api` first, then `chat-vue` and both workers. A skipped API job (nothing
under `chat-api/`) does not hold the others (`!cancelled() && needs.api.result != 'failure'`); a
failed one stops them. `workflow_dispatch` inputs redeploy one surface by hand. Deploys queue
behind each other (`concurrency: deploy-prod`, never cancelled — a cancelled API deploy could be
mid-migration).

## Consequences
- "Schema before readers" and "API before frontend" are enforced by CI, not by push discipline.
- A failed API job leaves the surfaces behind it *skipped, not retried*; a fix that touches only
  `chat-api/` redeploys only the API, and the rest need `gh workflow run Deploy -f vue=true` etc.
  (documented in `docs/runbooks/deploy.md`).
- Changing a per-surface workflow file redeploys that surface (the file is in its own filter);
  changing `deploy.yml` alone deploys nothing.
- Terraform stays manual and outside this ordering: task-definition shape changes (volumes,
  memory) must be applied before pushing a worker that needs them.
