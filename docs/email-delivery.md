# Email delivery

How Lemely sends the two account-lifecycle mails — email verification and
password reset — and how `lemelyig.com` is authorised to send them.

## Why not Cloudflare

The obvious answer, given the domain's DNS is already on Cloudflare and the SPA
already deploys as a Cloudflare Worker, is Cloudflare Email Service. It does not
work on our plan:

| | Workers Free | Workers Paid |
| --- | --- | --- |
| Outbound (Email Sending) | **Not available** | 3,000/month included, then $0.35/1,000 |
| Inbound (Email Routing) | Unlimited | Unlimited |

Source: [Cloudflare Email Service pricing](https://developers.cloudflare.com/email-service/platform/pricing/).

The Free plan's one outbound allowance is sending to *destination addresses
already verified inside the account*, which a stranger signing up never is. So
Cloudflare cannot deliver a verification mail to a new user on the Free plan at
any volume, including one. Cloudflare Email Sending requires the Workers Paid
plan at **$5/month minimum**, which the brief ruled out.

MailChannels — the free Workers relay that used to fill this gap — discontinued
its free Cloudflare integration in 2024 and is not an option either.

**What we do instead:** send over [Resend](https://resend.com)'s free tier
(3,000 mails/month, 100/day) with the `From:` domain still `lemelyig.com`,
authorised by SPF/DKIM records that live in the Cloudflare zone. Cloudflare
remains the DNS authority for the sending domain; only the SMTP hop is
elsewhere. Recipients see `noreply@lemelyig.com` either way.

## Code

| Piece | Where |
| --- | --- |
| Provider seam (`EmailProvider` protocol) | `lemely/auth/email.py` |
| Offline provider (logs the link) | `MockEmailProvider` |
| Real sender | `ResendEmailProvider` |
| Provider selection | `_build_email_provider` in `lemely/web/deps.py` |
| Settings | `EmailSettings`, `[email]` section in `lemely/runtime/config.py` |
| Tests | `tests/test_auth_email.py` |

The provider is chosen by **the presence of a credential, never an environment
name** — the same rule `lemely/web/push.py` applies to VAPID keys. No key wired
means `MockEmailProvider`, which logs the link and reports
`delivers_out_of_band = False`, so the auth routes keep surfacing the dev link
and a local signup completes end to end with no mail service running.

Configuring a key flips both halves at once: mail is really sent, *and*
`delivers_out_of_band = True` stops the routes returning the live link through
the API. That coupling is deliberate — a verification link is a bearer
credential, and the two facts must never disagree.

## Setup

### 1. Resend account and domain

1. Create a free account at [resend.com](https://resend.com).
2. **Domains → Add Domain → `lemelyig.com`**, and pick a region.
3. Resend generates the DNS records below. **The DKIM value is unique to your
   domain and is not reproducible here — copy it from that screen.**

### 2. DNS records in Cloudflare

Add these in the Cloudflare dashboard under **`lemelyig.com` → DNS → Records**.

| Type | Name | Value | Priority |
| --- | --- | --- | --- |
| `MX` | `send` | *(from Resend, e.g. `feedback-smtp.<region>.amazonses.com`)* | `10` |
| `TXT` | `send` | `v=spf1 include:amazonses.com ~all` | — |
| `TXT` | `resend._domainkey` | *(from Resend — long `p=MIGf…` DKIM key)* | — |
| `TXT` | `_dmarc` | `v=DMARC1; p=none;` | — |

Four things bite specifically on Cloudflare:

- **Set every record to "DNS only" (grey cloud), never proxied (orange).**
  A proxied record is not readable by Resend and verification silently never
  completes. This is the single most common failure.
- **Enter the name as `send`, not `send.lemelyig.com`.** Cloudflare appends the
  zone automatically; typing the full name yields `send.lemelyig.com.lemelyig.com`.
- **The MX goes on the `send` subdomain, not the root.** If Cloudflare Email
  Routing is ever enabled on this zone it puts its own MX records on the root —
  keeping Resend's on `send` means inbound routing and outbound sending coexist
  rather than clobber each other.
- **Do not add a second root SPF record.** A domain may have only one; if the
  root already has `v=spf1`, merge rather than duplicate. The record above is on
  `send`, so it does not collide with a root SPF.

Then click **Verify DNS Records** in Resend. It is usually minutes, though the
documented ceiling is 72 hours.

### 3. API key

**Resend → API Keys → Create**, with **Sending access** only.

The key never gets typed on a server or into a file. Deployed secrets live in
GitHub Actions and reach Cloud Run through `deploy.yml`, so adding it is one
step in the GitHub UI:

**Repo → Settings → Secrets and variables → Actions → Environments →
`staging` / `production` → New secret**, named **`RESEND_API_KEY`**.

`deploy.yml` already passes it through as
`LEMELY_EMAIL__API_KEY=${{ secrets.RESEND_API_KEY }}`, so the next deploy to
that environment picks it up. Nothing else to wire.

Two consequences of that indirection worth stating plainly:

- **An unset secret is not a broken deploy.** GitHub renders a missing secret
  as the empty string, `_blank_to_none` in `lemely/runtime/config.py` maps that
  to `None`, and `_build_email_provider` then wires the mock. The pipeline is
  green either way; the difference is whether mail is sent.
- **Adding the secret does nothing until the next deploy.** Cloud Run env vars
  are baked into a revision. Re-run the deploy workflow, or push, to get a
  revision that carries the key.

Free-tier Resend allows **one domain**, so a single key shared by staging and
production also shares one 100/day allowance — a staging smoke test spends
production's quota. Either leave `RESEND_API_KEY` unset in staging (mail falls
back to the logged mock, which is usually what you want there) or use a
separate Resend account for it.

**For a local run**, the same variable works as an ordinary env var — but
`lemely.toml` is the wrong place for it even though that file is gitignored:

```bash
export LEMELY_EMAIL__API_KEY="re_..."
```

Everything else has a working default. To override, in `lemely.toml`'s
`[email]` section locally or as `env_vars` in `deploy.yml` when deployed:

```bash
export LEMELY_EMAIL__FROM_ADDRESS="noreply@lemelyig.com"
export LEMELY_EMAIL__FROM_NAME="Lemely"
export LEMELY_EMAIL__REPLY_TO="support@lemelyig.com"
```

### 4. Confirm

With the key set and a revision deployed that carries it, a signup should send
a real mail *and* stop returning the dev link in the API response. Both halves
matter — if the link still comes back, the mock is still wired, which means the
key did not reach the process: either the secret is on the wrong environment or
the running revision predates it.

## Free-tier limits

| | Resend free |
| --- | --- |
| Per month | 3,000 |
| Per day | 100 |
| Domains | 1 |

At 100/day the ceiling is roughly 100 signups plus resets per day. `AuthService`
already rate-limits the routes that trigger a send
(`signup_and_reset_cooldown_seconds`, `resend_verification_cooldown_seconds`),
which is what stops a single abusive caller burning the daily allowance.

A send that fails is swallowed at both call sites by design — see
`_try_send_verification` (never strand a just-created account) and
`_try_send_password_reset` (preserve anti-enumeration) in
`lemely/auth/service.py`. So exhausting the quota degrades to "no mail arrived",
never to a failed signup. It is logged at `ERROR` on the `lemely.auth.service`
logger, which is the thing to alert on.

## If the account ever goes Workers Paid

Cloudflare Email Sending becomes available and is then the better home: the
Worker already exists, and 3,000 mails/month are included in the $5 already
being spent. The swap is one class — implement `CloudflareEmailProvider`
against the same `EmailProvider` protocol, either `env.EMAIL.send()` from
`web/worker/index.ts` or the Email Service REST API from the Python backend, and
change `_build_email_provider`. The DNS work is not wasted: the domain would be
onboarded to Cloudflare Email Service with its own SPF/DKIM records added to the
same zone. Nothing in `AuthService` changes — that is what the seam is for.
