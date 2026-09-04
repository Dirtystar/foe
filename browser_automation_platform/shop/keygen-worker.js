/**
 * Forge GBG Farmer — licence issuer + verifier (Cloudflare Worker, free tier).
 *
 * Three jobs, one Worker:
 *  1. Store webhook (Lemon Squeezy) → mint the SAME offline HMAC key our app verifies
 *     (mirrors `bap/forge/licensing.py`), record it in KV, and email it to the buyer.
 *  2. `GET /verify?key=…&email=…` → tell the app whether a key is active / revoked (online
 *     revocation; see `bap/forge/license_online.py`). Optionally checks the buyer's email.
 *  3. `POST /revoke?secret=…` (and `/reinstate`) → flip a key's status. Your kill switch.
 *
 * Bindings / vars (Worker → Settings):
 *   KV namespace  LICENSES   — the key registry.
 *   LICENSE_SECRET    — MUST equal the app's FOE_LICENSE_SECRET (offline verification).
 *   LS_WEBHOOK_SECRET — Lemon Squeezy webhook signing secret.
 *   RESEND_API_KEY + FROM_EMAIL — to email the key (Resend free tier; swap for any sender).
 *   VARIANT_TIERS — JSON map store variant id → tier, e.g. {"111":"solo","555":"lifetime"}.
 *
 * Test: GET /?tier=quad&days=30&secret=<LICENSE_SECRET> → prints a key.
 */

const B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
const enc = (s) => new TextEncoder().encode(s);
const ONE_TIME = new Set(["lifetime"]);              // one-time tiers → never-expiring key

function base32(bytes) {
  let bits = 0, val = 0, out = "";
  for (const b of bytes) {
    val = (val << 8) | b; bits += 8;
    while (bits >= 5) { out += B32[(val >>> (bits - 5)) & 31]; bits -= 5; }
  }
  if (bits > 0) out += B32[(val << (5 - bits)) & 31];
  return out; // RFC4648, no padding — matches Python b32encode(...).rstrip("=")
}

async function hmacBytes(secret, msg) {
  const key = await crypto.subtle.importKey(
    "raw", enc(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", key, enc(msg)));
}
const toHex = (b) => [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
const json = (o, status = 200) =>
  new Response(JSON.stringify(o), { status, headers: { "Content-Type": "application/json" } });

/** Identical to licensing.generate_key(). */
async function generateKey(secret, tier, { days = 30, name = "" } = {}) {
  const expires = days <= 0 ? 0 : Math.floor(Date.now() / 1000) + days * 86400;
  const payload = base32(enc(`${tier}|${expires}|${name}`));
  const sig = base32(await hmacBytes(secret, payload)).slice(0, 16);
  return `FOE-${payload}-${sig}`;
}

function safeEqual(a, b) {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

async function mail(env, to, subject, html) {
  if (!env.RESEND_API_KEY || !to) return;
  await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { "Authorization": `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ from: env.FROM_EMAIL, to, subject, html }),
  });
}

async function sendEmail(env, to, key, tier) {
  await mail(env, to, "Your Forge GBG Farmer licence",
    `<p>Thanks for buying the <b>${tier}</b> plan of Forge GBG Farmer!</p>` +
    `<p>Your licence key:</p><p style="font:16px monospace;background:#f3f3f3;padding:10px;` +
    `border-radius:8px">${key}</p>` +
    `<p>Open the app, paste it into <b>Licence key</b>, and press <b>Save</b>.</p>`);
}

/** Renewal "massage": one email per stage (7 days / 1 day left / expired). */
async function sendReminder(env, to, stage, daysLeft) {
  const url = env.RENEW_URL || "#";
  const cta = `<p><a href="${url}" style="background:#4f46e5;color:#fff;padding:10px 18px;` +
    `border-radius:10px;text-decoration:none;font-weight:600">Renew now</a></p>`;
  const M = {
    "7": ["Your Forge GBG Farmer licence expires in 7 days",
          `<p>Heads up — your licence expires in <b>7 days</b>. Renew to keep farming without a break.</p>`],
    "1": ["⏳ 1 day left on your Forge GBG Farmer licence",
          `<p>Last call — your licence expires <b>tomorrow</b>. Renew now so your worlds keep running.</p>`],
    "expired": ["Your Forge GBG Farmer licence has expired",
          `<p>Your licence has expired and the app dropped to the free tier. Come back anytime:</p>`],
  };
  const [subject, body] = M[stage] || M["7"];
  await mail(env, to, subject, body + cta +
    `<p style="color:#888;font-size:12px">You get this because you bought Forge GBG Farmer.</p>`);
}

async function setStatus(env, key, status) {
  if (!env.LICENSES) return false;
  const rec = (await env.LICENSES.get(key, { type: "json" })) || {};
  rec.status = status;
  await env.LICENSES.put(key, JSON.stringify(rec));
  return true;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "");

    // 2) verify — called by the app; no secret (the full key is the credential).
    if (path === "/verify") {
      const key = url.searchParams.get("key") || "";
      const rec = env.LICENSES ? await env.LICENSES.get(key, { type: "json" }) : null;
      if (!rec) return json({ status: "unknown" });
      if (rec.status === "revoked") return json({ status: "revoked" });
      const email = (url.searchParams.get("email") || "").toLowerCase();
      if (email && rec.email && email !== String(rec.email).toLowerCase()) {
        return json({ status: "email_mismatch" });
      }
      return json({ status: "active", tier: rec.tier });
    }

    // 3) revoke / reinstate — your kill switch (guarded by the licence secret).
    if (path === "/revoke" || path === "/reinstate") {
      if (url.searchParams.get("secret") !== env.LICENSE_SECRET) {
        return new Response("forbidden", { status: 403 });
      }
      let key = url.searchParams.get("key");
      if (!key && request.method === "POST") {
        try { key = (await request.json()).key; } catch { /* ignore */ }
      }
      if (!key) return json({ error: "key required" }, 400);
      const ok = await setStatus(env, key, path === "/revoke" ? "revoked" : "active");
      return json({ ok, key, status: path === "/revoke" ? "revoked" : "active" });
    }

    // test/preview key generation (guarded).
    if (request.method === "GET") {
      const tier = url.searchParams.get("tier");
      if (!tier) return new Response("Forge GBG Farmer key service. /verify, /revoke, webhook POST.");
      if (url.searchParams.get("secret") !== env.LICENSE_SECRET) {
        return new Response("forbidden", { status: 403 });
      }
      const key = await generateKey(env.LICENSE_SECRET, tier, {
        days: parseInt(url.searchParams.get("days") || "30", 10),
        name: url.searchParams.get("name") || "",
      });
      return new Response(key + "\n");
    }

    // 1) store webhook → issue + register + email.
    const raw = await request.text();
    const sig = request.headers.get("X-Signature") || "";
    const expect = toHex(await hmacBytes(env.LS_WEBHOOK_SECRET, raw));
    if (!safeEqual(sig, expect)) return new Response("bad signature", { status: 401 });

    let payload;
    try { payload = JSON.parse(raw); } catch { return new Response("bad json", { status: 400 }); }
    const attrs = payload?.data?.attributes || {};
    const variant = String(attrs.variant_id ?? attrs.first_order_item?.variant_id ?? "");
    const tier = JSON.parse(env.VARIANT_TIERS || "{}")[variant];
    if (!tier) return json({ ok: false, reason: "no tier for variant " + variant });

    const email = attrs.user_email || attrs.customer_email || "";
    let days;
    if (ONE_TIME.has(tier)) {
      days = 0;                                          // lifetime: never expires
    } else {
      const renews = attrs.renews_at ? Math.floor(new Date(attrs.renews_at).getTime() / 1000) : 0;
      days = renews ? Math.ceil((renews - Date.now() / 1000) / 86400) + 2 : 32;
    }
    const key = await generateKey(env.LICENSE_SECRET, tier, { days, name: email });
    if (env.LICENSES) {
      const expires = days <= 0 ? 0 : Math.floor(Date.now() / 1000) + days * 86400;
      await env.LICENSES.put(key, JSON.stringify(
        { tier, email, status: "active", ts: Date.now(), expires }));
    }
    await sendEmail(env, email, key, tier);
    return json({ ok: true, tier, key });
  },

  /**
   * Daily renewal reminders (Cloudflare Cron Trigger). Walks the registry and emails one message
   * per stage — 7 days left, 1 day left, expired — with dedupe flags so nobody is spammed.
   * Lifetime (expires=0) and revoked keys are skipped. Set RENEW_URL to your pricing page.
   */
  async scheduled(event, env) {
    if (!env.LICENSES) return;
    const now = Math.floor(Date.now() / 1000);
    let cursor;
    do {
      const page = await env.LICENSES.list({ cursor });
      for (const k of page.keys) {
        const rec = await env.LICENSES.get(k.name, { type: "json" });
        if (!rec || rec.status !== "active" || !rec.expires) continue;  // skip lifetime/revoked
        const daysLeft = Math.ceil((rec.expires - now) / 86400);
        let stage = null;
        if (daysLeft <= 0 && !rec.rExp) stage = "expired";
        else if (daysLeft <= 1 && daysLeft > 0 && !rec.r1) stage = "1";
        else if (daysLeft <= 7 && daysLeft > 1 && !rec.r7) stage = "7";
        if (!stage) continue;
        await sendReminder(env, rec.email, stage, daysLeft);
        if (stage === "expired") rec.rExp = true;
        else if (stage === "1") rec.r1 = true;
        else rec.r7 = true;
        await env.LICENSES.put(k.name, JSON.stringify(rec));
      }
      cursor = page.list_complete ? null : page.cursor;
    } while (cursor);
  },
};
