/**
 * Forge GBG Farmer — licence-key issuer (Cloudflare Worker, free tier).
 *
 * Runs on a store webhook (Lemon Squeezy `order_created` / `subscription_payment_success`),
 * generates the SAME offline HMAC key our app verifies (mirrors `bap/forge/licensing.py`), and
 * emails it to the buyer. No server, no database required.
 *
 * Env vars (Worker → Settings → Variables):
 *   LICENSE_SECRET   — MUST equal the app's FOE_LICENSE_SECRET (keeps keys verifiable offline).
 *   LS_WEBHOOK_SECRET— Lemon Squeezy webhook signing secret (verifies the request is real).
 *   RESEND_API_KEY   — Resend.com API key (free tier) for sending the email. Swap for any sender.
 *   FROM_EMAIL       — verified sender address, e.g. "keys@yourdomain.com".
 *   VARIANT_TIERS    — JSON mapping store variant id → tier, e.g. {"111":"solo","222":"quad"}.
 *
 * Test locally: GET /?tier=quad&days=30&name=Radek&secret=LICENSE_SECRET → prints a key.
 */

const B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
const enc = (s) => new TextEncoder().encode(s);

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

function toHex(bytes) {
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Generate a licence key identical to licensing.generate_key(). */
async function generateKey(secret, tier, { days = 30, name = "" } = {}) {
  const expires = days <= 0 ? 0 : Math.floor(Date.now() / 1000) + days * 86400;
  const body = `${tier}|${expires}|${name}`;
  const payload = base32(enc(body));
  const sig = base32(await hmacBytes(secret, payload)).slice(0, 16);
  return `FOE-${payload}-${sig}`;
}

/** Constant-time-ish compare for the webhook signature. */
function safeEqual(a, b) {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

async function sendEmail(env, to, key, tier) {
  if (!env.RESEND_API_KEY) return; // configure a sender to actually deliver
  const html =
    `<p>Thanks for buying the <b>${tier}</b> plan of Forge GBG Farmer!</p>` +
    `<p>Your licence key:</p><p style="font:16px monospace;background:#f3f3f3;padding:10px;` +
    `border-radius:8px">${key}</p>` +
    `<p>Open the app, paste it into <b>Licence key</b>, and press <b>Save</b>.</p>`;
  await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { "Authorization": `Bearer ${env.RESEND_API_KEY}`,
               "Content-Type": "application/json" },
    body: JSON.stringify({ from: env.FROM_EMAIL, to, subject: "Your Forge GBG Farmer licence",
                           html }),
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // --- test/preview endpoint (guarded by the secret) ---------------------
    if (request.method === "GET") {
      const tier = url.searchParams.get("tier");
      if (!tier) return new Response("Forge GBG Farmer key issuer. POST store webhooks here.");
      if (url.searchParams.get("secret") !== env.LICENSE_SECRET) {
        return new Response("forbidden", { status: 403 });
      }
      const key = await generateKey(env.LICENSE_SECRET, tier, {
        days: parseInt(url.searchParams.get("days") || "30", 10),
        name: url.searchParams.get("name") || "",
      });
      return new Response(key + "\n");
    }

    // --- store webhook -----------------------------------------------------
    const raw = await request.text();
    const sig = request.headers.get("X-Signature") || "";
    const expect = toHex(await hmacBytes(env.LS_WEBHOOK_SECRET, raw));
    if (!safeEqual(sig, expect)) return new Response("bad signature", { status: 401 });

    let payload;
    try { payload = JSON.parse(raw); } catch { return new Response("bad json", { status: 400 }); }

    const attrs = payload?.data?.attributes || {};
    const variant = String(attrs.variant_id ?? attrs.first_order_item?.variant_id ?? "");
    const map = JSON.parse(env.VARIANT_TIERS || "{}");
    const tier = map[variant];
    if (!tier) return new Response("no tier for variant " + variant, { status: 200 });

    const email = attrs.user_email || attrs.customer_email || "";
    // Monthly plan: valid to the next renewal (+2 days grace), else 32 days from now.
    const renews = attrs.renews_at ? Math.floor(new Date(attrs.renews_at).getTime() / 1000) : 0;
    const days = renews ? Math.ceil((renews - Date.now() / 1000) / 86400) + 2 : 32;

    const key = await generateKey(env.LICENSE_SECRET, tier, { days, name: email });
    await sendEmail(env, email, key, tier);
    // Return the key too, so you can also read it from the store's webhook log.
    return new Response(JSON.stringify({ ok: true, tier, key }), {
      headers: { "Content-Type": "application/json" },
    });
  },
};
