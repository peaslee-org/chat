# aiTools Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Present the product as **aiTools** — repo `peaslee-org/aiTools`, primary domain `aitools.peaslee.org` (keeping `chat.peaslee.org` as an alias), rebranded UI/docs — without renaming any AWS resource.

**Architecture:** Terraform changes make the cert/CloudFront dual-domain and repoint the four GitHub-OIDC trust policies at the renamed repo; a branding sweep renames the product in the SPA title and docs. All applies are manual (operator); code merges under the old repo name, then the operator applies + renames in one sitting (Task 6).

**Tech Stack:** Terraform (AWS provider), Vite/Vue 3, GitHub.

**Spec:** `docs/superpowers/specs/2026-09-01-aitools-rename-and-public-demo-design.md` (Part 1)

## Global Constraints

- Product name is exactly **aiTools** (lowercase a, capital T). The GitHub repo is renamed to exactly `aiTools` — OIDC `sub` conditions are case-sensitive, so the Terraform literals and the rename must match character-for-character.
- The word "chat" stays wherever it names the chat feature (tab labels, route name `chat`, `POST /api/v1/chat`, directory names `chat-api`/`chat-vue`).
- **No AWS resource is renamed**: cluster `chat-api-prod`, bucket `chat-audio-prod-*`, Cognito pool/client `chat-api-prod`, IAM role names, log groups, tfstate keys all keep their names.
- `chat.peaslee.org` keeps working (alias, not redirect).
- Public-track files under `docs/` use placeholder values only (the commit hook rejects real account ids); `aitools.peaslee.org` / `chat.peaslee.org` domain names themselves are fine — they already appear in public docs.
- Terraform validation is run offline: `terraform init -backend=false` then `terraform validate`; never `plan`/`apply` from this session (applies are the operator's, with admin credentials).
- Commit after every task.

---

### Task 1: ACM module — subject alternative names

**Files:**
- Modify: `infra/modules/acm/main.tf` (8 lines, whole resource shown below)
- Modify: `infra/modules/acm/variables.tf`
- Modify: `infra/environments/prod/main.tf:73-76`
- Modify: `infra/environments/prod/variables.tf` (append)
- Modify: `infra/environments/prod/terraform.tfvars.example`

**Interfaces:**
- Produces: module input `subject_alternative_names` (list(string), default `[]`); prod root variable `alternate_domain_names` (list(string), default `[]`) — Task 2 reuses the same root variable for CloudFront aliases.

- [ ] **Step 1: Add the SAN input to the module**

`infra/modules/acm/variables.tf` — append:

```hcl
variable "subject_alternative_names" {
  type        = list(string)
  description = "Additional domain names on the certificate (e.g. the aitools alias). Changing this replaces the certificate."
  default     = []
}
```

`infra/modules/acm/main.tf` — the resource becomes:

```hcl
resource "aws_acm_certificate" "this" {
  domain_name               = var.domain_name
  subject_alternative_names = var.subject_alternative_names
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}
```

(The existing `validation_records` output already iterates `domain_validation_options`, so the SAN's validation CNAME appears in it automatically — no output change.)

- [ ] **Step 2: Wire it from prod**

`infra/environments/prod/variables.tf` — append:

```hcl
variable "alternate_domain_names" {
  type        = list(string)
  description = "Extra hostnames served by CloudFront and added to the certificate as SANs (e.g. [\"aitools.example.com\"])."
  default     = []
}
```

`infra/environments/prod/main.tf:73-76` becomes:

```hcl
module "acm" {
  source                    = "../../modules/acm"
  domain_name               = var.domain_name
  subject_alternative_names = var.alternate_domain_names
}
```

`infra/environments/prod/terraform.tfvars.example` — under the `domain_name` line add:

```hcl
alternate_domain_names       = ["aitools.example.com"]
```

- [ ] **Step 3: Validate**

Run: `cd infra/environments/prod && terraform init -backend=false -input=false && terraform validate && terraform fmt -check -recursive ../..`
Expected: `Success! The configuration is valid.` and no fmt diffs. (If `terraform` is missing or init cannot download providers, note it and rely on CI's `tf-validate.yml` on the PR.)

- [ ] **Step 4: Commit**

```bash
git add infra/modules/acm infra/environments/prod
git commit -m "feat(infra): SAN support on the ACM cert for the aitools alias"
```

---

### Task 2: CloudFront aliases + bucket CORS for the new origin

**Files:**
- Modify: `infra/modules/cloudfront/main.tf:80` and `:169`
- Modify: `infra/modules/cloudfront/variables.tf`
- Modify: `infra/environments/prod/main.tf:146-157`
- Modify: `infra/environments/transcription-prod/terraform.tfvars:2`

**Interfaces:**
- Consumes: prod root variable `alternate_domain_names` from Task 1.
- Produces: CloudFront serves both hostnames; audio-bucket CORS allows `https://aitools.peaslee.org` (needed by `<model-viewer>` GLB fetches and presigned PUT uploads from the new origin).

- [ ] **Step 1: Module change**

`infra/modules/cloudfront/variables.tf` — append:

```hcl
variable "alternate_domain_names" {
  type        = list(string)
  description = "Extra CloudFront aliases; each must be on the ACM certificate."
  default     = []
}
```

`infra/modules/cloudfront/main.tf:80` becomes:

```hcl
  aliases             = concat([var.domain_name], var.alternate_domain_names)
```

`infra/modules/cloudfront/main.tf:169` (stale repo in comment) becomes:

```hcl
# ── IAM role for frontend GitHub Actions (repo: var.github_org/var.frontend_github_repo) ──────
```

- [ ] **Step 2: Wire from prod**

In `infra/environments/prod/main.tf` module `"cloudfront"` block (lines 146-157), add one line after `domain_name`:

```hcl
  alternate_domain_names   = var.alternate_domain_names
```

- [ ] **Step 3: Bucket CORS**

`infra/environments/transcription-prod/terraform.tfvars:2` becomes:

```hcl
cors_allowed_origins         = ["http://localhost:5173", "https://chat.peaslee.org", "https://aitools.peaslee.org"]
```

- [ ] **Step 4: Validate**

Run: `cd infra/environments/prod && terraform validate && cd ../transcription-prod && terraform init -backend=false -input=false && terraform validate`
Expected: both `Success!`.

- [ ] **Step 5: Commit**

```bash
git add infra/modules/cloudfront infra/environments/prod infra/environments/transcription-prod/terraform.tfvars
git commit -m "feat(infra): serve aitools.peaslee.org — CloudFront alias + bucket CORS"
```

---

### Task 3: OIDC trust — repo `chat` → `aiTools`

**Files:**
- Modify: `infra/environments/prod/main.tf:156,168`
- Modify: `infra/environments/transcription-prod/main.tf:35,49`

**Interfaces:**
- Produces: all four trust policies (`github-actions-prod`, `github-actions-frontend-prod`, `transcription-prod-worker-github-actions`, `photogrammetry-prod-worker-github-actions`) will, once applied, accept `repo:peaslee-org/aiTools:ref:refs/heads/main` and nothing else. **Applying this before the GitHub rename breaks CI; the operator sequence in Task 6 handles the ordering.**

- [ ] **Step 1: Change the four literals**

- `infra/environments/prod/main.tf:156`: `frontend_github_repo     = "chat"` → `frontend_github_repo     = "aiTools"`
- `infra/environments/prod/main.tf:168`: `github_repo    = "chat"` → `github_repo    = "aiTools"`
- `infra/environments/transcription-prod/main.tf:35`: `github_repo                  = "chat"` → `"aiTools"`
- `infra/environments/transcription-prod/main.tf:49`: `github_repo             = "chat"` → `"aiTools"`

(Exact whitespace may differ; change only the string value, keep alignment.)

- [ ] **Step 2: Validate both environments**

Run: `cd infra/environments/prod && terraform validate && cd ../transcription-prod && terraform validate`
Expected: both `Success!`.

- [ ] **Step 3: Commit**

```bash
git add infra/environments/prod/main.tf infra/environments/transcription-prod/main.tf
git commit -m "feat(infra): OIDC deploy trust moves to peaslee-org/aiTools"
```

---

### Task 4: Branding sweep

**Files:**
- Modify: `chat-vue/index.html:7`
- Modify: `chat-vue/vite.config.ts:30-36`
- Modify: `chat-vue/README.md:1,5`
- Modify: `docs/user-guide.md:3`
- Modify: `photogrammetry-worker/pyproject.toml:4`
- Modify: `docs/architecture/network-map.puml:39`
- Test: existing suite `chat-vue` (vitest) — no new tests; the build is the check.

**Interfaces:** none consumed or produced.

- [ ] **Step 1: Title — three strings that must change together**

`chat-vue/index.html:7`: `<title>Chat</title>` → `<title>aiTools</title>`

`chat-vue/vite.config.ts:30-36` — the `html-title` plugin replaces the tag it finds in index.html, so its search string must match the new tag:

```ts
      name: 'html-title',
      transformIndexHtml(html) {
        const title = mode === 'production' ? 'aiTools' : 'aiTools-dev'
        return html.replace('<title>aiTools</title>', `<title>${title}</title>`)
      },
```

(Keep the surrounding plugin object exactly as it is; only the two title literals and the `replace` search string change.)

- [ ] **Step 2: Docs and descriptions**

- `chat-vue/README.md:1` `# chat-vue` stays (directory name); line 5: reword `The browser app for **chat.peaslee.org**` → `The browser app for **aitools.peaslee.org** (alias: chat.peaslee.org)` — rest of the sentence unchanged.
- `docs/user-guide.md:3`: `What you can do at **chat.peaslee.org**, tab by tab.` → `What you can do at **aitools.peaslee.org** (also reachable at chat.peaslee.org), tab by tab.`
- `photogrammetry-worker/pyproject.toml:4`: `description = "GPU worker: COLMAP → OpenMVS → GLB for chat.peaslee.org photogrammetry jobs"` → `… for aitools.peaslee.org photogrammetry jobs"`
- `docs/architecture/network-map.puml:39`: `peaslee-org/chat\n(main branch)` → `peaslee-org/aiTools\n(main branch)`

- [ ] **Step 3: Verify the frontend still builds and tests pass**

Run: `cd chat-vue && npm run test && npm run build`
Expected: all specs pass; build emits `dist/index.html` containing `<title>aiTools</title>`. Check with: `grep -o "<title>[^<]*</title>" dist/index.html` → `<title>aiTools</title>`.

- [ ] **Step 4: Commit**

```bash
git add chat-vue/index.html chat-vue/vite.config.ts chat-vue/README.md docs/user-guide.md photogrammetry-worker/pyproject.toml docs/architecture/network-map.puml
git commit -m "feat: rebrand product as aiTools (chat stays the feature name)"
```

---

### Task 5: Rename runbook

**Files:**
- Create: `docs/runbooks/rename-aitools.md`

**Interfaces:** none; this documents Task 6's operator sequence.

- [ ] **Step 1: Write the runbook** with exactly this content:

```markdown
# Runbook: chat → aiTools cutover

One sitting. Steps 4–6 open a window where CI cannot deploy (OIDC trust and the
repo name disagree) — do them back-to-back.

1. Merge the rename branch to `main` under the OLD repo name; let Deploy finish
   (the SPA now titles itself aiTools; Terraform is not applied by CI).
2. `cd infra/environments/prod` (admin credentials exported). Set in
   `terraform.tfvars`: `alternate_domain_names = ["aitools.peaslee.org"]`.
   `terraform apply -target=module.acm` — creates the replacement cert
   (create_before_destroy keeps the old one working).
3. DNS: from the `acm_validation_records` output add the validation CNAME(s);
   also add `aitools.peaslee.org CNAME <cloudfront_domain_name output>`.
   Wait until the ACM console shows the new cert **Issued**.
4. `terraform apply` (full, prod) — CloudFront gets both aliases + the new
   cert, and the prod OIDC trust moves to `aiTools`. CI under the old name is
   now broken.
5. GitHub → repo Settings → rename `chat` → `aiTools` (exact case). Old URLs
   redirect. Then locally:
   `git remote set-url origin https://github.com/peaslee-org/aiTools.git`
   `git remote set-url --add --push origin https://github.com/peaslee-org/aiTools.git`
   `git remote set-url --add --push origin ssh://henry/srv/data/git/aiTools/chat.git`
6. `cd ../transcription-prod && terraform apply` — worker OIDC trust + audio
   bucket CORS for the new origin.
7. Cognito console → user pool `chat-api-prod` → App client → Hosted UI:
   add callback `https://aitools.peaslee.org/callback` and sign-out
   `https://aitools.peaslee.org` (keep the existing chat.* and localhost
   entries).
8. GitHub repo secrets: set `VITE_COGNITO_REDIRECT_URI` to
   `https://aitools.peaslee.org/callback`. Note: after this, signing in from
   chat.peaslee.org lands you on aitools.peaslee.org — intended (the alias
   still serves the app; auth migrates users to the new name).
9. `gh workflow run Deploy -f vue=true` — rebuild the SPA with the new
   redirect URI. Confirm the run is green (proves the renamed-repo OIDC trust).
10. Verify: open https://aitools.peaslee.org and https://chat.peaslee.org
    (both load); sign in on aitools (round-trips through Cognito); run a
    photogrammetry scan or open an existing mesh from the aitools origin
    (proves bucket CORS).
```

- [ ] **Step 2: Commit**

```bash
git add docs/runbooks/rename-aitools.md
git commit -m "docs: aiTools cutover runbook"
```

---

### Task 6: Operator cutover (manual — Neil)

Not an agent task. Execute `docs/runbooks/rename-aitools.md` top to bottom. The agent's involvement ends at the merged PR; report the runbook path and stop.
