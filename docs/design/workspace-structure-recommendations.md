# Workspace Structure Recommendations

*Updated 2026-03-12. Applies to `/var/www/chat` monorepo.*

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
├── deploy/
│   ├── migrate.sh         — run Alembic upgrade head via ECS exec (prod)
│   ├── build-api.sh       — build + push chat-api Docker image to ECR
│   ├── build-worker.sh    — build + push transcription-worker image to ECR
│   └── transcription-worker.sh  — start/stop/pause/unpause GPU worker service
└── ci/
    └── validate-tf.sh     — terraform fmt check + validate across all environments
```

---

## Open Questions / Future Work

These items are not immediate concerns but are worth revisiting as the project scales:

- **No CloudWatch alarms yet** — `infra/modules/monitoring/` is a placeholder. First candidates: 5xx error rate on the ALB, ECS task restart count, RDS free storage below threshold, DLQ depth.
- **No staging deployment pipeline** — `infra/environments/staging/` exists in Terraform but there are no GitHub Actions workflows targeting staging. Useful before adding the admin/profile features.
- **Integration tests are stubs** — `chat-api/tests/integration/` exists but contains no tests. Worth adding at least a happy-path test for the transcription job flow once a test environment is stable.
- **Admin/profile backend** — endpoints scaffolded but not yet fully implemented. Check `chat-api/app/api/v1/admin/` and `chat-api/app/api/v1/profile/` for current coverage.
