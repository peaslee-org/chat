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
