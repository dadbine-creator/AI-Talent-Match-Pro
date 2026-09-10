# Paddle Sandbox Setup — AI Talent Match Pro

This turns on the **card-required 7-day trial** and the **Business / Corporate** checkouts.
The code is already deployed and waiting — it stays a graceful no-op until the env vars below
are set. Nothing here touches Stripe or requires a code change.

**Time needed:** ~20–30 minutes. **Cost:** free (sandbox uses test cards, no real money).

---

## What the app already does (so you know what you're wiring)

| Piece | Where | Behaviour |
|---|---|---|
| Public config | `GET /api/paddle/config` | Returns `configured:false` until keys are set; never exposes secrets |
| Checkout | `openPaddleCheckout('business'/'corporate')` | Opens Paddle overlay for that plan's price |
| Trial | Business price with a **7-day trial** in Paddle | Card captured up front, no charge for 7 days |
| Webhook | `POST /api/paddle/webhook` | Verifies signature, then upgrades/downgrades the company |
| Day-6 reminder | in-app scheduler + `/api/cron/trial-reminders` | Emails the day before the trial converts |

Webhook events the app handles: `subscription.trialing`, `subscription.created`,
`transaction.completed`, `transaction.paid`, `subscription.activated`,
`subscription.canceled`, `subscription.cancelled`.

---

## Step 1 — Create a Paddle sandbox account

1. Go to **https://sandbox-login.paddle.com/signup** (sandbox is a separate account from live).
2. Verify your email and sign in to the **sandbox** dashboard. The URL bar will say `sandbox-vendors.paddle.com` — make sure you're in sandbox, not live.

---

## Step 2 — Get the two credentials

In the sandbox dashboard → **Developer Tools → Authentication**:

1. **Client-side token** → *Client-side tokens* → **Generate**. It starts with `test_`.
   → this becomes **`PADDLE_CLIENT_TOKEN`** (public — it's used in the browser, that's fine).
2. **API key** → *API keys* → **Generate**. Copy it once (you can't see it again).
   → this becomes **`PADDLE_SANDBOX_API_KEY`** (secret — server-side only).

---

## Step 3 — Create the products and prices

In **Catalog → Products**:

### Business (this one carries the trial)
1. **New product** → name `Business` → Save.
2. Add a **price**: type **Recurring**, billing period **Monthly**, amount **$99.00 USD**.
3. In that price's settings, set a **Free trial** of **7 days**. ← this is what makes the card-required trial work.
4. Save. Copy the **price ID** (looks like `pri_01h...`).
   → this becomes **`PADDLE_PRICE_BUSINESS`**.

### Corporate
1. **New product** → name `Corporate` → Save.
2. Add a **price**: **Recurring**, **Monthly**, **$299.00 USD**. (Trial optional — the "Start trial"
   button uses Business; add a 7-day trial here too if you want Corporate trials.)
3. Save. Copy the **price ID**.
   → this becomes **`PADDLE_PRICE_CORPORATE`**.

> Enterprise is **not** a Paddle product — it's invoice/bank-transfer via the "Contact Us" email flow.

---

## Step 4 — Set up the webhook (notification destination)

In **Developer Tools → Notifications**:

1. **New destination** → type **Webhook**.
2. **URL:** `https://aitmp.io/api/paddle/webhook`
3. Select these events (at minimum):
   - `subscription.trialing`
   - `subscription.activated`
   - `subscription.canceled`
   - `transaction.completed`
   - `transaction.paid`
4. Save, then open the destination and copy its **secret key** (starts with `pdl_ntfset_...` or similar).
   → this becomes **`PADDLE_WEBHOOK_SECRET`**.

---

## Step 5 — Set the env vars on Azure

Run this from the repo (fill in your five values). This restarts the app automatically:

```bash
az webapp config appsettings set -g ai-talent-grade-engine -n aitmp-io --settings \
  PADDLE_ENV="sandbox" \
  PADDLE_CLIENT_TOKEN="test_xxxxxxxxxxxxxxxx" \
  PADDLE_SANDBOX_API_KEY="pdl_sdbx_apikey_xxxxxxxx" \
  PADDLE_WEBHOOK_SECRET="pdl_ntfset_xxxxxxxx" \
  PADDLE_PRICE_BUSINESS="pri_xxxxxxxxxxxx" \
  PADDLE_PRICE_CORPORATE="pri_xxxxxxxxxxxx"
```

(You can also put these in `.env` for local testing — see `.env.example`.)

---

## Step 6 — Verify it's live

1. **Config check** (should now say `configured:true`, and show your prices — never the secret):
   ```bash
   curl -s https://aitmp.io/api/paddle/config
   ```
2. **Checkout check:** open https://aitmp.io/plans → click **Start 7-Day Trial** (or **Upgrade** on
   Business). The Paddle overlay should open. Pay with the **test card**:
   - Card: `4242 4242 4242 4242` · any future expiry · any CVC · any name/postcode.
3. **Trial started:** after checkout, Paddle fires `subscription.trialing` → the company's plan flips
   to `business` and a "trial started" email is attempted (email only sends if `RESEND_API_KEY` is set).
4. **Webhook delivery:** in Paddle → **Notifications → your destination → Logs**, confirm the events
   show **200 OK**. A non-200 means the signature/secret is wrong — recheck `PADDLE_WEBHOOK_SECRET`.

---

## Step 7 — Test the trial converting to a charge (optional but recommended)

Paddle sandbox has a **Time simulator / test clock** (or you can set a very short trial temporarily):

1. Advance time past the 7-day trial, or set the Business price trial to 1 day for a quick test.
2. Paddle charges the test card → fires `transaction.completed` → the app keeps the plan active and
   sends a receipt email.
3. Cancel the subscription in Paddle → fires `subscription.canceled` → the app downgrades to `free`.

The **day-6 reminder** email is driven by the app's own scheduler (runs daily) or by an external cron
hitting `POST /api/cron/trial-reminders` with the `X-Cron-Secret` header — already configured.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Button shows "Checkout is being set up…" | `configured:false` — a key or price ID is missing/blank. Recheck Step 5. |
| Overlay opens but "price not found" | Wrong `PADDLE_PRICE_*` ID, or you copied a **live** ID into the sandbox app. |
| Webhook logs show 400 | `PADDLE_WEBHOOK_SECRET` doesn't match the destination's secret. |
| Plan doesn't upgrade after paying | Check the webhook destination has the events from Step 4 and shows 200 in its logs. |
| Trial doesn't appear | The 7-day trial must be set **on the Business price** (Step 3.3), not the product. |

---

## When you're ready to go LIVE

Do **not** reuse sandbox values. In your **live** Paddle account, repeat Steps 2–4 to get live
credentials (client token starts with `live_`), then set on Azure:

```bash
az webapp config appsettings set -g ai-talent-grade-engine -n aitmp-io --settings \
  PADDLE_ENV="production" \
  PADDLE_CLIENT_TOKEN="live_..." \
  PADDLE_SANDBOX_API_KEY="<live API key>" \
  PADDLE_WEBHOOK_SECRET="<live destination secret>" \
  PADDLE_PRICE_BUSINESS="pri_<live>" \
  PADDLE_PRICE_CORPORATE="pri_<live>"
```

`PADDLE_ENV=production` switches the API base to `api.paddle.com`. Point the **live** webhook
destination at the same `https://aitmp.io/api/paddle/webhook` URL. Test one real (small) transaction
before announcing. Follow the non-destructive rules agreed for the live migration.
