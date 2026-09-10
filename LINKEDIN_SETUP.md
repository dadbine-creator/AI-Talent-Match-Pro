# LinkedIn Sign-In Setup — AI Talent Match Pro

This turns on **"Sign in with LinkedIn"** on the login and register pages.
The code is already built and deployed (real OpenID Connect flow) — it stays a friendly
"coming soon" notice until the two keys below are set. No code change needed.

**Important:** this uses **"Sign In with LinkedIn using OpenID Connect"**, a **free** product on any
LinkedIn Developer app. It does **NOT** require Talent Solutions Partner approval. It returns the
person's **name + email** (used to sign them in / pre-fill registration). It does **not** return job
title — so the HR job-title gate stays on the registration form.

**Time:** ~10–15 min.

---

## Step 1 — You need a LinkedIn Company Page (one-time)
LinkedIn requires every app to be attached to a Company Page you administer.
- If AI Talent Match Pro already has one, you're set.
- If not: linkedin.com → **For Business → Create a Company Page** (free, ~2 min). You can polish it later.

## Step 2 — Create the app
1. Go to **https://developer.linkedin.com/** → **My apps** → **Create app**.
2. Fill in:
   - **App name:** `AI Talent Match Pro`
   - **LinkedIn Page:** select your Company Page from Step 1
   - **App logo:** upload your logo (the one in `app/static/`)
   - Accept the legal terms → **Create app**.

## Step 3 — Verify the app with your Page
On the app's **Settings** tab there's a **"Verify"** button under the associated Company Page.
Click it → it generates a verification link → open it as a **Page admin** → confirm. (Instant.)

## Step 4 — Add the Sign-In product
1. Open the **Products** tab.
2. Find **"Sign In with LinkedIn using OpenID Connect"** → **Request access**.
   It's free and usually granted **immediately** (no review).

## Step 5 — Set the redirect URL (must match EXACTLY)
1. Open the **Auth** tab.
2. Under **OAuth 2.0 settings → Authorized redirect URLs for your app**, add exactly:
   ```
   https://aitmp.io/auth/linkedin/callback
   ```
   - Must be `https`, no trailing slash, no `www`. An exact-match mismatch is the #1 cause of failures.

## Step 6 — Copy the two keys
Still on the **Auth** tab, under **Application credentials**, copy:
- **Client ID**
- **Primary Client Secret** (click to reveal)

## Step 7 — Send them to me
Paste both here and I'll:
1. Set `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, and `LINKEDIN_REDIRECT_URI` as Azure app settings
   (setting them restarts the app — no redeploy needed, the code is already live).
2. Verify `/auth/linkedin` now redirects to LinkedIn's real consent screen instead of the "coming soon" notice.

> Security: the **Client Secret** is sensitive. I'll store it only as an Azure app setting, never in the
> repo. If you ever share this transcript, rotate the secret in the LinkedIn Auth tab afterward.

---

## What happens once it's live
- **Login page → "Continue with LinkedIn"** → LinkedIn consent → back to your workspace (existing account) or
  pre-filled registration (new account, they finish company + HR title).
- **Register page → "Continue with LinkedIn"** → same, pre-filling name + email.
- If LinkedIn is ever unreachable or the user cancels, they get a clean message and can use email instead.

## Verify checklist (I'll run these after wiring the keys)
- `GET https://aitmp.io/auth/linkedin` → **302 to `https://www.linkedin.com/oauth/v2/authorization?...`** (not to `/login?notice=linkedin_soon`)
- `GET https://aitmp.io/api/... ` unaffected
- A real sign-in round-trip creates/logs in the account
