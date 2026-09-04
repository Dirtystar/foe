# Shop setup — sell licences for (almost) free

The whole shop is a static page + a store's checkout + one tiny serverless function. No server to
run, no monthly hosting bill — you only pay the store's per-sale fee.

```
 Buyer → one-page shop (Cloudflare Pages, free)
       → checkout (Lemon Squeezy: payment + EU VAT + installer hosting)
       → webhook → Cloudflare Worker (free) → generates OUR licence key → emails it
       → buyer pastes the key into the app (verified offline)
```

The key the Worker makes is byte-for-byte identical to `bap.forge.licensing` (verified), so the
app accepts it with no online check.

## 1. The signing secret (do this first)

Pick one strong secret and use it in **both** places — this is what ties the store to the app:

- The app: build/ship it with `FOE_LICENSE_SECRET` set to your secret (change `_DEFAULT_SECRET`
  in `licensing.py` before you build).
- The Worker: env var `LICENSE_SECRET` = the same value.

Keep it private. Anyone with it can mint keys.

## 2. Host the page (free)

`shop/index.html` is self-contained. Host it on **Cloudflare Pages** or **GitHub Pages**:

1. Put `shop/index.html` in a repo (or drag-drop into Cloudflare Pages).
2. Edit the `EDIT THESE` block at the top: `DOWNLOAD_URL` (installer link) and each plan's
   `CHECKOUT` URL (from step 3).

## 3. Store: Lemon Squeezy (payment + VAT + installer)

Lemon Squeezy is a *merchant of record* — it collects payment and handles EU VAT for you.

1. Create a store, then a **product** with the **variants**: Solo, Duo, Quad, Octa, Unlimited
   priced $4/$7/$12/$20/$30 per month (subscriptions), plus a **Lifetime** variant at $199 as a
   **one-time** (non-subscription) purchase. Map `lifetime` in `VARIANT_TIERS`; the Worker's
   `ONE_TIME` set already issues it a never-expiring key.
2. Upload the installer as the product's file, or just host it publicly and use `DOWNLOAD_URL`.
3. Copy each variant's **checkout URL** into `CHECKOUT` in `index.html`.
4. Note each variant's **id** (Settings → API, or the variant page) for step 4.

> Gumroad works too — same idea (product per tier, webhook on sale). Adjust the Worker's payload
> field names if you switch.

## 4. The key issuer (Cloudflare Worker, free)

1. Create a Worker, paste `shop/keygen-worker.js`, deploy.
2. Set its variables:
   - `LICENSE_SECRET` — your secret from step 1.
   - `LS_WEBHOOK_SECRET` — the signing secret you set on the Lemon Squeezy webhook (step 5).
   - `VARIANT_TIERS` — JSON map of variant id → tier, e.g.
     `{"111":"solo","222":"duo","333":"quad","444":"octa","555":"unlimited"}`.
   - `RESEND_API_KEY` + `FROM_EMAIL` — a [Resend](https://resend.com) free-tier key and a
     verified sender, to email the key. (Swap for any email API you like.)
3. Test it: open `https://<your-worker>/?tier=quad&days=30&secret=<LICENSE_SECRET>` — it should
   print a `FOE-…` key. Paste that into the app to confirm it's accepted.

## 5. Wire the webhook

In Lemon Squeezy → Settings → Webhooks: add your Worker URL, set a signing secret (put the same
value in the Worker's `LS_WEBHOOK_SECRET`), and subscribe to `order_created` and
`subscription_payment_success`. On each payment the Worker mints a key valid until the next
renewal (+2 days grace) and emails it.

## 5b. Online revocation (your kill switch — recommended for Lifetime)

Offline keys can't be taken back, so a leaked lifetime key would unlock forever. The Worker doubles
as a tiny key registry + verifier so you can revoke.

1. **KV:** create a KV namespace and bind it to the Worker as `LICENSES`. The issuer already
   records every sold key there (`{tier, email, status:"active"}`).
2. **App:** ship it with `FOE_VERIFY_URL` set to `https://<your-worker>/verify`. The app then
   checks each key online, caches the result, and tolerates being offline for 7 days before a paid
   key drops to the free tier (see `bap/forge/license_online.py`). If `FOE_VERIFY_URL` is unset,
   the app stays offline-only (no revocation) — so turn it on by shipping that one env value.
3. **Revoke a key:** `POST https://<your-worker>/revoke?secret=<LICENSE_SECRET>` with body
   `{"key":"FOE-…"}` (or `?key=…`). Reinstate with `/reinstate`. Next time that app verifies, it
   drops to the free tier.
4. **Email binding (optional):** the app sends the buyer's email to `/verify`; if it doesn't match
   the key's recorded email the key is treated as invalid. Light anti-sharing, no passwords.

## 6. Renewals & cancellations

- Monthly keys expire at period end; `subscription_payment_success` issues a fresh key each
  renewal, so paying customers always have a valid key.
- If you want hard cut-off on cancellation, also handle `subscription_cancelled` (e.g. stop
  issuing) — expiry already covers the common case.

## Costs

| Piece | Cost |
|---|---|
| Page hosting (Cloudflare/GitHub Pages) | free |
| Key Worker (Cloudflare Workers) | free (100k req/day) |
| Email (Resend free tier) | free (low volume) |
| Payments (Lemon Squeezy) | ~5% + fees per sale, $0 monthly |

That's it — no fixed costs, keys verified offline, installer delivered by the store.
