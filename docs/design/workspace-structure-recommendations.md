# Workspace Structure Recommendations

*Updated 2026-03-12; status refreshed 2026-08-29. Applies to the `chat` monorepo.*

---

## Status: All Items Complete

All recommendations from the 2026-03-08 review and the subsequent 2026-03-12 review have been addressed.

### Original recommendations (2026-03-08)

| # | Recommendation | Status |
|---|---|---|
| 1 | Hoist `chat-api/infra/` → `infra/` | ✅ Done |
| 2 | Restructure `docs/` | ✅ Done |
| 3 | Create `docs/aws/` SSOT | ✅ Done |
| 4 | Organise `scripts/` | ✅ Done |
| 5 | Admin/profile in `chat-vue/` + `chat-api/` | ✅ Done |
| 6 | Consolidate CI/CD on GitHub Actions | ✅ Done |
| 7 | Root `.gitignore`, README, housekeeping | ✅ Done |
| 8 | GPU dev box (`docker-compose.dev.yml`, `gpu-dev.sh`) | ✅ Done |

### Follow-up items (2026-03-12)

| # | Item | Status |
|---|---|---|
| 1 | Fix `.terraform.lock.hcl` exclusion in `.gitignore` | ✅ Done |
| 2 | Add `secrets.tfvars.example` + update `.gitignore` | ✅ Done |
| 3 | Delete `docs/migration-plan.md` (migration complete) | ✅ Done |
| 4 | Write `scripts/deploy/migrate.sh` | ✅ Done |
| 5 | Remove architecture diagram exclusions from `.gitignore` | ✅ Done |
| 6 | Complete `scripts/` population | ✅ Done |
| 7 | Improve root `README.md` | ✅ Done |
| 8 | Remove `chat-api/buildspec.yml` (CodePipeline migration complete) | ✅ Done |
| 9 | Delete `docs/design/audio_transcription_spec.docx` | ✅ Done |

---

## Current `scripts/` Layout

```
scripts/
├── local/
│   ├── setup.sh          — first-time setup: install deps, copy .env files
│   ├── seed-db.sh         — seed local Postgres with test conversations and speakers
│   └── gpu-dev.sh         — start/stop/ssh to the EC2 g4dn.xlarge GPU dev box
├── dev/
│   └── make-photogrammetry-sample.py — build the bundled sample photo set
├── deploy/
│   ├── migrate.sh         — manual Alembic re-run; migrations normally run in the API
│   │                         container entrypoint at every deploy (script needs the venv
│   │                         python, see docs/TODO.md)
│   ├── build-api.sh       — build + push chat-api Docker image to ECR
│   ├── build-worker.sh    — build + push transcription-worker image to ECR
│   ├── build-gpu-ami.sh   — bake both worker images into the ECS GPU AMI (rebuild when
│   │                         base/model layers change; see ADR 004 and the deploy runbook)
│   └── gpu-status.sh      — ASG, worker tasks, queue depth on one screen
└── ci/
    └── validate-tf.sh     — terraform fmt check + validate across all environments
```

---

## Open Questions / Future Work (status 2026-08-29)

- **CloudWatch alarms** — `infra/modules/monitoring/` is still empty, but the feature modules
  carry their own: DLQ depth (both queues), a GPU instance running > 4 h, and a monthly GPU
  budget. Still missing: ALB 5xx rate and ECS task restart count.
- **No staging environment** — `dev`/`staging` Terraform environments were removed; only
  `prod` and `transcription-prod` exist. Local dev runs fully mocked instead (`docs/mock-api.md`).
- **Integration tests are stubs** — `chat-api/tests/integration/` is still empty; unit suites
  are substantial (chat-api 259, photogrammetry-worker 106, gpu-worker 43, chat-vue 47 as of
  2026-08-29).
- **Admin/profile backend** — check `chat-api/app/api/v1/admin/` and `profile/` for coverage.
- **Backlog** — `docs/TODO.md`, grouped by deploy surface.
