"""Generates `lemely.toml.example` from current Settings defaults."""

from __future__ import annotations

from lemely.runtime.config import Settings

_HEADER = """\
# lemely.toml — configuration template
#
# Precedence (highest wins): environment variables (LEMELY_*) > .env > this TOML > defaults.
# Nested keys use double-underscore in env vars (e.g. LEMELY_GRADIO__PORT=9000).
# All sections use extra='forbid'; unknown keys raise a validation error at startup.
"""


def render_example_toml() -> str:
    s = Settings()
    lines: list[str] = [_HEADER.rstrip(), ""]

    lines.append("[gradio]")
    lines.append(f'host = "{s.gradio.host}"')
    lines.append(f"port = {s.gradio.port}")
    lines.append(f"max_file_size_mb = {s.gradio.max_file_size_mb}")
    lines.append("")

    lines.append("[paths]")
    lines.append(f'sources_dir = "{s.paths.sources_dir}"')
    lines.append(f'output_dir = "{s.paths.output_dir}"')
    lines.append(f'cache_dir = "{s.paths.cache_dir}"')
    lines.append("")

    lines.append("[logging]")
    lines.append(f'level = "{s.logging.level}"')
    lines.append(f'format = "{s.logging.format}"')
    lines.append("")

    lines.append("[gemini]")
    lines.append(f'model = "{s.gemini.model}"')
    lines.append("")
    lines.append("# Per-task model overrides (omit a key to use the global `model` above).")
    lines.append('# mark_scheme_model = "gemini-2.5-pro"   # one-off parse; accuracy matters')
    lines.append('# extraction_model  = "gemini-2.5-flash" # vision-heavy, per paper')
    lines.append('# correction_model  = "gemini-2.5-flash" # per question; highest call volume')
    lines.append("")
    lines.append("# Escalation: re-mark with a stronger model when confidence < threshold.")
    lines.append('# escalation_model = "gemini-2.5-pro"')
    lines.append(f"# escalation_confidence_threshold = {s.gemini.escalation_confidence_threshold}")
    lines.append("")
    lines.append("# Thinking budget per task (tokens; 0 = disabled).")
    lines.append("[gemini.thinking_budget_for]")
    for tag, budget in s.gemini.thinking_budget_for.items():
        lines.append(f"{tag} = {budget}")
    lines.append("# correction_borderline = 2000  # retry borderline marks before Pro escalation")
    lines.append("")
    lines.append(f"max_retries = {s.gemini.max_retries}")
    lines.append(f"backoff_seconds = {s.gemini.backoff_seconds}")
    lines.append("# Persistent cumulative-USD hard cap (survives process restarts).")
    lines.append(f"# total_usd_ceiling = {s.gemini.total_usd_ceiling}")
    lines.append(f"# usd_warning_thresholds = {s.gemini.usd_warning_thresholds}")
    lines.append("# Budgets one RUN — every sweep that run drives, not each sweep separately.")
    lines.append("# A golden sweep is ~70 calls / ~115k tokens, so 200000 (the old example value)")
    lines.append("# was under two sweeps and would abort a legitimate A/B run mid-flight. Size it")
    lines.append("# for the whole run; the accuracy programme uses 2000000 (~17 sweeps).")
    lines.append("# per_run_token_ceiling = 2000000")
    lines.append("")

    lines.append("# gemini_api_key is a secret — prefer the GEMINI_API_KEY env var instead.")
    lines.append('# gemini_api_key = "sk-..."')
    lines.append("")

    lines.append("[accuracy_eval]")
    lines.append(f"mark_accuracy_target = {s.accuracy_eval.mark_accuracy_target}")
    lines.append(f"id_match_rate_target = {s.accuracy_eval.id_match_rate_target}")
    lines.append(f"flag_precision_target = {s.accuracy_eval.flag_precision_target}")
    lines.append(f"flag_recall_target = {s.accuracy_eval.flag_recall_target}")
    lines.append("# M0.9 (#33) review-rate two-part ratchet gate (spec §4 M0.9, §5).")
    lines.append(f"review_rate_signal_target = {s.accuracy_eval.review_rate_signal_target}")
    lines.append(f"review_rate_total_target = {s.accuracy_eval.review_rate_total_target}")
    lines.append(f"review_rate_p95_target = {s.accuracy_eval.review_rate_p95_target}")
    lines.append("# Unarmed at M0 — a breach is recorded but does not fail the gate.")
    ratchet_armed = str(s.accuracy_eval.review_rate_ratchet_armed).lower()
    lines.append(f"review_rate_ratchet_armed = {ratchet_armed}")
    lines.append(f"review_rate_last_merged = {s.accuracy_eval.review_rate_last_merged}")
    lines.append("")

    lines.append("[database]")
    lines.append("# Full SQLAlchemy URL. Default targets the local Supabase Postgres")
    lines.append("# (`supabase start`). Override via LEMELY_DATABASE__URL in production.")
    lines.append(f'url = "{s.database.url}"')
    lines.append(f"echo = {str(s.database.echo).lower()}")
    lines.append(f"pool_size = {s.database.pool_size}")
    lines.append(f"max_overflow = {s.database.max_overflow}")
    lines.append(f"pool_pre_ping = {str(s.database.pool_pre_ping).lower()}")
    lines.append("# Bound how long a connect may block. libpq's own connect_timeout default is")
    lines.append("# unlimited, which lets a dropped-packet outage (firewall/security-group")
    lines.append("# change) hang every request instead of failing them.")
    lines.append(f"connect_timeout_seconds = {s.database.connect_timeout_seconds}")
    lines.append(f"pool_timeout_seconds = {s.database.pool_timeout_seconds}")
    lines.append("")

    lines.append("[supabase]")
    lines.append("# Local Supabase Auth (GoTrue). Defaults are the well-known local-dev")
    lines.append("# values printed by `supabase status`; override for real deploys.")
    lines.append(f'url = "{s.supabase.url}"')
    lines.append(f'jwt_audience = "{s.supabase.jwt_audience}"')
    lines.append("# Secrets — prefer LEMELY_SUPABASE__* env vars over this file:")
    lines.append('# jwt_secret = "super-secret-jwt-token-with-at-least-32-characters-long"')
    lines.append('# anon_key = "..."')
    lines.append('# service_role_key = "..."')
    lines.append("")

    lines.append("[auth]")
    lines.append("# How long a minted access token is accepted for. Short on purpose: it is a")
    lines.append("# bearer credential with no revocation of its own, so this bounds the window")
    lines.append("# in which a leaked one is useful. The SPA renews silently in the background")
    lines.append("# (POST /api/auth/refresh), so shortening it does not sign anyone out.")
    lines.append(f"access_token_ttl_seconds = {s.auth.access_token_ttl_seconds}")
    lines.append("# How long a signed-in device stays signed in without re-entering a")
    lines.append("# credential. Long by design — the security is not the expiry but the")
    lines.append("# binding: a refresh token names a row in `devices`, so signing that device")
    lines.append("# out from the device list, or evicting it past the 3-device cap, kills it")
    lines.append("# immediately.")
    lines.append(
        f"refresh_token_ttl_seconds = {s.auth.refresh_token_ttl_seconds}"
        f"  # {s.auth.refresh_token_ttl_seconds // 86400} days"
    )
    lines.append("# Parent phone-OTP challenge lifecycle.")
    lines.append(f"otp_ttl_seconds = {s.auth.otp_ttl_seconds}")
    lines.append(f"otp_max_attempts = {s.auth.otp_max_attempts}")
    lines.append(f"otp_length = {s.auth.otp_length}")
    lines.append(f"otp_min_resend_seconds = {s.auth.otp_min_resend_seconds}")
    lines.append("")

    lines.append("[email]")
    lines.append("# Transactional mail for account verification and password reset (D7.7).")
    lines.append("#")
    lines.append("# Leave `api_key` unset and lemely.web.deps wires MockEmailProvider: the link")
    lines.append("# is logged to the `lemely.auth.email` logger instead of sent, and the auth")
    lines.append("# routes keep returning it so a local signup completes with no mail service at")
    lines.append("# all. That is the supported default for development and CI, not a broken")
    lines.append("# state. Setting a key flips both halves at once — mail is really sent, and the")
    lines.append("# routes stop returning the live link, because a real sender makes the inbox")
    lines.append("# the only place a bearer credential belongs.")
    lines.append("#")
    lines.append("# NEVER put the key in this file. `lemely.toml` is gitignored, but the key still")
    lines.append("# does not belong on disk. Deployed, it is the `RESEND_API_KEY` GitHub Actions")
    lines.append("# environment secret, which `deploy.yml` passes to Cloud Run as")
    lines.append("# LEMELY_EMAIL__API_KEY. Locally, export LEMELY_EMAIL__API_KEY in your shell.")
    lines.append('# api_key = "re_..."')
    lines.append("#")
    lines.append("# The origin emailed links are built on. AuthService mints links as frontend")
    lines.append("# routes (`/verify-email/<token>`), which the SPA can navigate to but an inbox")
    lines.append("# cannot resolve — a mail client with no base turns that into")
    lines.append("# `http:///verify-email/<token>`. A real provider joins this origin on first.")
    lines.append("# deploy.yml sets it per environment; this default is the production site.")
    lines.append(f'app_base_url = "{s.email.app_base_url}"')
    lines.append("#")
    lines.append("# Must be on a domain verified with the provider AND carrying that sender's")
    lines.append("# SPF/DKIM records in the Cloudflare DNS zone — see docs/email-delivery.md.")
    lines.append(f'from_address = "{s.email.from_address}"')
    lines.append(f'from_name = "{s.email.from_name}"')
    lines.append("# Where replies go. Unset means they return to `from_address`, an unattended")
    lines.append("# mailbox; point it at a real inbox once one exists.")
    lines.append('# reply_to = "support@lemelyig.com"')
    lines.append("# Short on purpose: verification mail is a best-effort side effect of an")
    lines.append("# already-created account and must never make a signup hang.")
    lines.append(f"timeout_seconds = {s.email.timeout_seconds}")

    # No trailing blank line: pre-commit's end-of-file-fixer collapses a double
    # trailing newline in lemely.toml.example, which would drift from this
    # generator. Emit exactly one trailing newline to match.
    return "\n".join(lines) + "\n"


def main() -> None:
    from pathlib import Path

    target = Path("lemely.toml.example")
    target.write_text(render_example_toml(), encoding="utf-8")
    print(f"wrote {target}")  # noqa: T201


if __name__ == "__main__":
    main()
