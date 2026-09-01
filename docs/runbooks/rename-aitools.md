# Runbook: chat → aiTools cutover

One sitting. Steps 4–6 open a window where CI cannot deploy (OIDC trust and the
repo name disagree) — do them back-to-back.

1. Merge the rename branch to `main` under the OLD repo name; let Deploy finish
   (the SPA now titles itself aiTools; Terraform is not applied by CI).
2. `cd infra/environments/prod` (admin credentials exported). Set in
   `terraform.tfvars`: `alternate_domain_names = ["aitools.peaslee.org"]`.
   `terraform apply -target=module.acm` — creates the replacement cert
   (create_before_destroy keeps the old one working).
   Expect this targeted apply to end with `Error: deleting ACM Certificate …:
   ResourceInUseException`. That is benign: the replacement cert has been
   created; the old cert is still attached to CloudFront and is removed by
   the full apply in step 4. Take the validation CNAMEs from the ACM console
   (or re-run `terraform output acm_validation_records` after
   `terraform refresh`) rather than trusting the failed apply's output.
3. DNS: from the `acm_validation_records` output add the validation CNAME(s);
   also add `aitools.peaslee.org CNAME <cloudfront_domain_name output>`.
   Wait until the ACM console shows the new cert **Issued**.
4. First save the app client's current Hosted UI settings:
   `aws cognito-idp describe-user-pool-client --user-pool-id <pool>
   --client-id <client> > /tmp/appclient-before.json`. Run
   `terraform plan -out=tfplan` and READ it: if any
   `aws_cognito_user_pool_client` change appears, abort and investigate
   before applying (the Hosted UI/OAuth config is console-managed and a
   full-replace update would wipe it). Then `terraform apply tfplan` (full,
   prod) — CloudFront gets both aliases + the new cert, and the prod OIDC
   trust moves to `aiTools`. CI under the old name is now broken.
5. GitHub → repo Settings → rename `chat` → `aiTools` (exact case). Old URLs
   redirect. Then locally:
   ```
   git remote set-url origin https://github.com/peaslee-org/aiTools.git
   git remote set-url --push --delete origin https://github.com/peaslee-org/chat.git
   git remote set-url --add --push origin https://github.com/peaslee-org/aiTools.git
   ```
   (the Henry pushurl already exists and stays; do not re-add it). Verify:
   `git remote -v` should show one fetch URL (aiTools) and exactly two push
   URLs (aiTools, henry).
6. `cd ../transcription-prod`. In the local (gitignored) `terraform.tfvars`,
   add `https://aitools.peaslee.org` to `cors_allowed_origins` (matching the
   updated `terraform.tfvars.example`). Then `terraform apply` — worker OIDC
   trust + audio bucket CORS for the new origin.
7. Cognito console → user pool `chat-api-prod` → App client → Hosted UI:
   add callback `https://aitools.peaslee.org/callback` and sign-out
   `https://aitools.peaslee.org` (keep the existing chat.* and localhost
   entries). Note: the callback/sign-out entries may need restoring from
   `/tmp/appclient-before.json` (saved in step 4), not just extending, if
   anything upstream touched the app client.
8. GitHub repo secrets: set `VITE_COGNITO_REDIRECT_URI` to
   `https://aitools.peaslee.org/callback`. Note: after this, signing in from
   chat.peaslee.org lands you on aitools.peaslee.org — intended (the alias
   still serves the app; auth migrates users to the new name). Also check
   `VITE_API_BASE_URL`: if it is an absolute chat.peaslee.org URL, repoint or
   blank it (blank = same-origin `/api/*` through CloudFront).
9. `gh workflow run Deploy -f vue=true` — rebuild the SPA with the new
   redirect URI. Confirm the run is green (proves the renamed-repo OIDC trust).
10. Verify: open https://aitools.peaslee.org and https://chat.peaslee.org
    (both load); sign in on aitools (round-trips through Cognito); run a
    photogrammetry scan or open an existing mesh from the aitools origin
    (proves bucket CORS).

## Rollback

- **Domain:** empty `alternate_domain_names` and re-apply — CloudFront drops
  the `aitools.peaslee.org` alias and the replacement cert, reverting to
  `chat.peaslee.org` only.
- **OIDC trust:** reverses only by renaming the repo back to `chat` (undoing
  step 5) or by re-applying Terraform with the old literal
  (`repo:peaslee-org/chat:ref:refs/heads/main`) in the `github_repo` var —
  simply reverting the Terraform diff without the repo rename will not
  restore CI, since the two must agree.
- **DNS:** the `aitools` CNAME and validation records can simply be removed.
