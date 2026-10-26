"""Generates `lemely.toml.example` from current Settings defaults.

Not every settings group is emitted, and the omission is a decision rather
than an oversight: this file is what `CLAUDE.md` tells a developer to copy to
get started, so it carries the knobs someone setting Lemely up actually sets.

`[det_parser]` is the deliberate exclusion. Two of its fields
(``header_keywords``, ``skip_line_tokens``) are ``frozenset[str]``, and
frozenset iteration order for strings varies with the interpreter's hash seed,
which is randomised per process. Emitting them as-is would make this
generator's output differ between runs, so `test_example_matches_generator`
would pass or fail depending on which process regenerated the file last. If
these ever do need emitting, ``sorted()`` them — and decide separately whether
ten internal parser-tuning knobs belong in a getting-started template at all.

Adding a section here without adding it to `Settings` (or the reverse) is
invisible to the drift test, which compares this generator's output to the
file it wrote: an omitted section is self-consistent. That is how
`[storage]` shipped a new `backend` setting that never appeared in the
template developers copy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.runtime.config import NotificationsSettings, Settings

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


def _toml_value(value: str | float | Sequence[str]) -> str:
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, int | float):
        return str(value)
    return "[" + ", ".join(f'"{v}"' for v in value) + "]"


def _toml_inline(mapping: Mapping[str, str | float | Sequence[str]]) -> str:
    """Render a flat str-keyed mapping as a TOML inline table."""
    if not mapping:
        return "{}"
    items = ", ".join(f'"{k}" = {_toml_value(v)}' for k, v in mapping.items())
    return "{ " + items + " }"


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
    lines.append(
        "# Sub-project C: every tag defaults to claude-haiku-5-5 (needs ANTHROPIC_API_KEY),"
    )
    lines.append("# so these are commented out here purely as documentation of what you are")
    lines.append("# overriding if you uncomment one. A gemini- model (e.g. gemini-3.1-flash-lite")
    lines.append("# for correction) needs GEMINI_API_KEY. Run `lemely doctor` to see what")
    lines.append("# model_for() actually resolves for every tag.")
    lines.append(f'# mark_scheme_model    = "{s.gemini.mark_scheme_model}"')
    lines.append(f'# extraction_model     = "{s.gemini.extraction_model}"')
    lines.append(f'# correction_model     = "{s.gemini.correction_model}"')
    lines.append(f'# generation_model     = "{s.gemini.generation_model}"')
    lines.append(f'# scan_metadata_model  = "{s.gemini.scan_metadata_model}"')
    lines.append("")
    lines.append("# Escalation: re-mark with a stronger/thinking-harder model when confidence <")
    lines.append("# threshold. Reachable even when escalation_model == correction_model (F1):")
    lines.append("# the gate compares (model, thinking) tuples, not model names alone. Unset")
    lines.append("# (the default since sub-project C): no escalation.")
    lines.append('# escalation_model = "claude-sonnet-5-5"')
    lines.append(f"# escalation_confidence_threshold = {s.gemini.escalation_confidence_threshold}")
    lines.append(
        "# At most this many escalations per script, most uncertain first (unset: no cap)."
    )
    lines.append("# escalation_cap_per_script = 2")
    lines.append("# Per-model human-review threshold: a final AI mark from a listed model is")
    lines.append("# flagged for teacher review below its value (unlisted models: 0.90). A table")
    lines.append("# you set REPLACES the shipped one (no merge). Applies to the marking step;")
    lines.append("# the review queue and teacher console still read the 0.90 constant.")
    lines.append(
        "# review_confidence_threshold_for = "
        f"{_toml_inline(s.gemini.review_confidence_threshold_for)}"
    )
    lines.append("")
    lines.append("# LLM cost-ladder levers (all default to the pre-ladder behaviour).")
    lines.append("# Per-task cache mode: read_write | bypass | refresh (unlisted tags read_write).")
    lines.append(f"# cache_mode_for = {_toml_inline(s.gemini.cache_mode_for)}")
    lines.append("# False makes forget_cached a no-op so measurement runs keep every cached read.")
    lines.append(f"# cache_forget_enabled = {_toml_bool(s.gemini.cache_forget_enabled)}")
    lines.append("# Cascade: cheap correction pass first, escalate only when it is unsure.")
    lines.append(f"# cascade_enabled = {_toml_bool(s.gemini.cascade_enabled)}")
    lines.append("# Strong model for the cascade (unset = use escalation_model).")
    lines.append('# cascade_strong_model = ""  # unset = use escalation_model')
    lines.append("# Per-model fitted confidence threshold (missing model = escalation threshold).")
    lines.append(f"# cascade_threshold_for = {_toml_inline(s.gemini.cascade_threshold_for)}")
    lines.append("# Escalate when two cheap passes disagree.")
    lines.append(
        f"# cascade_two_pass_disagreement = {_toml_bool(s.gemini.cascade_two_pass_disagreement)}"
    )
    lines.append("# Per-task output-token cap, thinking included (unlisted tags keep the default).")
    lines.append("# A reply cut off at a set cap is billed, recorded unparsed, retried once")
    lines.append("# afresh, then fails. A table you set REPLACES the shipped caps (no merge):")
    lines.append("# list every entry you want kept, both extraction and binding_second_read.")
    lines.append("# Naming binding_second_read here pins Claude's binder cap too: on a claude-")
    lines.append("# model it defaults to 32768 when the tag is not named.")
    lines.append(f"# max_output_tokens_for = {_toml_inline(s.gemini.max_output_tokens_for)}")
    lines.append("# Escalate when the cheap pass leaves mark-scheme points unaddressed.")
    lines.append(
        f"# cascade_unaddressed_points = {_toml_bool(s.gemini.cascade_unaddressed_points)}"
    )
    lines.append("# Put the question-invariant correction prompt first so it can be cached.")
    lines.append(f"# correction_shared_prefix = {_toml_bool(s.gemini.correction_shared_prefix)}")
    lines.append("# How the shared prefix is cached: implicit | explicit.")
    lines.append(f'# correction_prefix_cache = "{s.gemini.correction_prefix_cache}"')
    lines.append("# Claude page images: greyscaled, enhanced and stepped down from 2576 px until")
    lines.append("# under this many estimated tokens (95,000 keeps Haiku 5.5 under its 100k")
    lines.append("# price tier), never below the floor in pixels.")
    lines.append(f"# claude_image_token_budget = {s.gemini.claude_image_token_budget}")
    lines.append(f"# claude_image_floor_px = {s.gemini.claude_image_floor_px}")
    lines.append("# Page images for claude- calls go through Claude's Files API (1 h expiry,")
    lines.append("# deleted at job end; not ZDR-eligible: use a dedicated workspace key).")
    lines.append(f"# claude_files_api = {_toml_bool(s.gemini.claude_files_api)}")
    lines.append("# A script whose model spend passes this logs script_over_cost_target")
    lines.append("# (split by task tag). It never blocks marking.")
    lines.append(f"# paper_cost_target_usd = {s.gemini.paper_cost_target_usd}")
    lines.append("# Claude prompt-cache breakpoints per task tag: system | documents | images |")
    lines.append("# prefix. Unlisted tags mark system and prefix (the A1 behaviour). A changed")
    lines.append("# effort or thinking setting invalidates the cached messages (docs, prompt")
    lines.append(
        "# caching): both binder tags must send the same effort for the second read to hit"
        " (see binding.claude_cache_ignores_effort)."
    )
    lines.append(f"# claude_cache_for = {_toml_inline(s.gemini.claude_cache_for)}")
    lines.append("# Claude effort (none | low | medium | high | xhigh | max) per tag or tag:kind;")
    lines.append('# "none" turns thinking off for the call (levers a1/a2).')
    lines.append('# e.g. { "correction:extended" = "medium" }. Unlisted: thinking_level_for.')
    lines.append(
        "# haiku-5-5, sonnet-5-5, opus-5-5 and fable-5-1 all accept low..max (docs: effort);"
    )
    lines.append('# "none" works on haiku-5-5 only: sonnet-5-5, opus-5-5 and fable-5-1 reject it.')
    lines.append("# A model that rejects a level fails the call. Higher effort spends more of")
    lines.append("# max_output_tokens_for (thinking counts toward max_tokens).")
    lines.append(f"# claude_effort_for = {_toml_inline(s.gemini.claude_effort_for)}")
    lines.append("# The marker quotes the mark scheme for every awarded mark; an unquoted or")
    lines.append("# misquoted mark goes to review as uncited_mark.")
    lines.append(f"# correction_citations = {_toml_bool(s.gemini.correction_citations)}")
    lines.append("# Ask the marker for a rationale of at most 25 words (cut at 300 chars).")
    lines.append(
        f"# correction_terse_rationale = {_toml_bool(s.gemini.correction_terse_rationale)}"
    )
    lines.append("# false skips the borderline thinking retry (lever c1).")
    lines.append(
        f"# correction_borderline_enabled = {_toml_bool(s.gemini.correction_borderline_enabled)}"
    )
    lines.append("# Lever c2: a stronger model re-marks the least certain leaves of a script")
    lines.append(
        "# from their page crops. On by default (claude-haiku-5-5); needs the scan's pages."
    )
    lines.append(f'# adjudication_model = "{s.gemini.adjudication_model}"')
    lines.append(f"# adjudication_max_leaves = {s.gemini.adjudication_max_leaves}")
    lines.append(
        f"# adjudication_confidence_threshold = {s.gemini.adjudication_confidence_threshold}"
    )
    lines.append(
        "# Lever H2a: keep the higher of the first and the borderline-retry mark below this "
        "confidence."
    )
    lines.append(
        f"# correction_retry_keep_higher = {_toml_bool(s.gemini.correction_retry_keep_higher)}"
    )
    lines.append(
        f"# correction_retry_keep_higher_below = {s.gemini.correction_retry_keep_higher_below}"
    )
    lines.append(
        "# Lever H2b: per-point verdicts and rationale before the mark "
        "(not with correction_citations)."
    )
    lines.append(f"# correction_reason_first = {_toml_bool(s.gemini.correction_reason_first)}")
    lines.append("# Lever H2c: printed 0625 Paper 4 marking conventions in the marking prompt.")
    lines.append(
        f"# correction_syllabus_conventions = "
        f"{_toml_bool(s.gemini.correction_syllabus_conventions)}"
    )
    lines.append(
        "# Lever H2d: adjudicate the reader's Drawing: leaves from their crops "
        "(needs adjudication_model)."
    )
    lines.append(
        f"# adjudication_drawing_leaves = {_toml_bool(s.gemini.adjudication_drawing_leaves)}"
    )
    lines.append(f"# adjudication_drawing_max_leaves = {s.gemini.adjudication_drawing_max_leaves}")
    lines.append(
        "# Lever H4a: adjudicate leaves whose crop re-read disagreed with the first read "
        "(needs adjudication_model)."
    )
    lines.append(
        f"# adjudication_reread_disagreed = {_toml_bool(s.gemini.adjudication_reread_disagreed)}"
    )
    lines.append(f"# adjudication_reread_max_leaves = {s.gemini.adjudication_reread_max_leaves}")
    lines.append("# Lever H4c: median of three marks below this confidence (not with keep_higher).")
    lines.append(f"# correction_retry_median = {_toml_bool(s.gemini.correction_retry_median)}")
    lines.append(f"# correction_retry_median_below = {s.gemini.correction_retry_median_below}")
    lines.append(
        "# Greyscale pages are enhanced for readability; false sends plain greyscale (A/B)."
    )
    lines.append(f"# claude_image_enhance = {_toml_bool(s.gemini.claude_image_enhance)}")
    lines.append("")
    lines.append(f"max_retries = {s.gemini.max_retries}")
    lines.append(f"backoff_seconds = {s.gemini.backoff_seconds}")
    lines.append("# Persistent cumulative-USD hard cap (survives process restarts). $14 is the")
    lines.append("# shipped default (raised from $8 by the user 2026-09-17, F1/D4).")
    lines.append(f"# total_usd_ceiling = {s.gemini.total_usd_ceiling}")
    lines.append(f"# usd_warning_thresholds = {s.gemini.usd_warning_thresholds}")
    lines.append("# Budgets one RUN — every sweep that run drives, not each sweep separately.")
    lines.append("# A golden sweep is ~70 calls / ~115k tokens, so 200000 (the old example value)")
    lines.append("# was under two sweeps and would abort a legitimate A/B run mid-flight. Size it")
    lines.append("# for the whole run; the accuracy programme uses 2000000 (~17 sweeps).")
    lines.append("# per_run_token_ceiling = 2000000")
    lines.append("")

    lines.append("# I1 crop-and-re-read stage (spec 2026-09-26 §4-5): per-paper cap on the")
    lines.append("# zoomed re-read calls (0 disables the stage), worker threads for the stage,")
    lines.append("# and its wall-clock budget in seconds -- no re-read STARTS after the budget.")
    lines.append(f"max_rereads_per_paper = {s.gemini.max_rereads_per_paper}")
    lines.append(f"reread_concurrency = {s.gemini.reread_concurrency}")
    lines.append(f"reread_budget_seconds = {s.gemini.reread_budget_seconds}")
    lines.append("# Parallel Files API uploads of page images before the extraction call")
    lines.append("# (spec 2026-09-26 §7).")
    lines.append(f"upload_concurrency = {s.gemini.upload_concurrency}")
    lines.append("")

    lines.append("# gemini_api_key is a secret — prefer the GEMINI_API_KEY env var instead.")
    lines.append('# gemini_api_key = "sk-..."')
    lines.append("# anthropic_api_key is a secret too — use the ANTHROPIC_API_KEY env var.")
    lines.append("")

    lines.append("# Thinking budget per task (tokens; 0 = disabled) — 2.5-and-earlier models")
    lines.append("# only. 3.x models read [gemini.thinking_level_for] instead (see below). NOTE:")
    lines.append("# TOML table headers stay open until the next one, so every scalar [gemini]")
    lines.append("# key must come before this point in the file — [gemini] cannot be reopened")
    lines.append("# after a subtable like this one starts.")
    lines.append("[gemini.thinking_budget_for]")
    for tag, budget in s.gemini.thinking_budget_for.items():
        lines.append(f"{tag} = {budget}")
    lines.append("# correction_borderline = 2000  # retry borderline marks before Pro escalation")
    lines.append("")

    lines.append('# Thinking level per task ("minimal"/"low"/"medium"/"high") — 3.x models')
    lines.append("# only; a 2.5-and-earlier model ignores this table entirely. Shipped")
    lines.append('# defaults shown; "minimal" is only honoured on gemini-3.6-flash /')
    lines.append('# gemini-3.5-flash-lite and falls back to "low" on any other 3.x model.')
    lines.append("# This table REPLACES the defaults: a key left out here falls back to")
    lines.append('# "low". Leaving out binding_second_read makes the binding step\'s second')
    lines.append("# read the same call as its first (see [binding]); `lemely doctor` says so.")
    lines.append('# binding_second_read is safe at "low" only because max_output_tokens_for caps')
    lines.append('# it: at "medium" second reads reached 47-65k tokens, so raise that cap first.')
    lines.append("[gemini.thinking_level_for]")
    comments = {
        "correction_borderline": "  # Step-1 retry before Step-2 escalation",
        "binding_second_read": "  # the label binder's second read, see [binding]",
    }
    for tag, level in s.gemini.thinking_level_for.items():
        lines.append(f'{tag} = "{level}"{comments.get(tag, "")}')
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

    lines.append("[storage]")
    lines.append("# Object storage for self-mark uploads (P2.5) and profile pictures.")
    lines.append('# "local" (the default) writes under `paths.output_dir/storage` — right for')
    lines.append('# dev, Compose and CI, and needs no credentials. "gcs" uses Google Cloud')
    lines.append("# Storage via Application Default Credentials; no key belongs in this file")
    lines.append("# for that path. See docs/deployment.md and scripts/gcp-bootstrap.sh.")
    lines.append("#")
    lines.append("# There is no Supabase Storage backend — DS7 removed it.")
    lines.append("#")
    lines.append("# Note that signed URLs (avatar downloads) need a real service-account")
    lines.append("# credential (a JSON key, or an attached/workload-identity service account)")
    lines.append("# — plain user ADC from `gcloud auth application-default login` can")
    lines.append("# upload/download but cannot sign a URL at all. For local signing, add")
    lines.append("# `--impersonate-service-account=<runtime SA>` to that login command. The")
    lines.append('# "local" backend sidesteps this: it returns the bytes inline instead.')
    lines.append("#")
    lines.append("# GCS bucket names are ONE GLOBAL namespace across all of Google Cloud, so")
    lines.append("# these defaults carry a project-ish prefix. The deployed pipeline overrides")
    lines.append("# both per environment (see .github/workflows/deploy.yml), so staging and")
    lines.append("# production never share a bucket; `scripts/gcp-bootstrap.sh` creates them.")
    lines.append(f'backend = "{s.storage.backend}"')
    lines.append(f'bucket = "{s.storage.bucket}"')
    lines.append("# Profile pictures live in their own bucket: different retention and access")
    lines.append("# shape from scans, and no reason to share a namespace.")
    lines.append(f'avatar_bucket = "{s.storage.avatar_bucket}"')
    lines.append(f"signed_url_ttl_seconds = {s.storage.signed_url_ttl_seconds}")
    avatar_max_mib = s.storage.avatar_max_bytes // (1024 * 1024)
    lines.append(f"avatar_max_bytes = {s.storage.avatar_max_bytes}  # {avatar_max_mib} MiB")
    lines.append('# gcs_project = "my-gcp-project"  # only if ADC can\'t infer one')
    lines.append("")

    lines.append("[push]")
    lines.append("# Web push (VAPID, RFC 8292). All three absent is a SUPPORTED state (D5.9 §4):")
    lines.append("# the transport reports itself unavailable, the notification inbox keeps")
    lines.append("# working, and every developer machine and CI run is in that state.")
    lines.append("#")
    lines.append("# Generate a pair with `lemely push-keygen` (prints, writes nothing). The")
    lines.append("# public key is handed to every browser and is not a secret; the private key")
    lines.append("# is. Deployed, both arrive from GitHub Actions (a repository variable and a")
    lines.append("# repository secret) as LEMELY_PUSH__VAPID_PUBLIC_KEY / __VAPID_PRIVATE_KEY.")
    lines.append("# ROTATING THE PAIR INVALIDATES EVERY STORED SUBSCRIPTION - the public key is")
    lines.append("# baked into each one, so every browser must re-subscribe. See")
    lines.append("# docs/push-notifications.md before changing it.")
    lines.append('# vapid_public_key = "BASE64URL-65-BYTE-POINT"')
    lines.append('# vapid_private_key = "BASE64URL-32-BYTE-SCALAR"')
    lines.append('# vapid_subject = "mailto:support@lemelyig.com"')
    lines.append(f"ttl_seconds = {s.push.ttl_seconds}")
    lines.append(f"timeout_seconds = {s.push.timeout_seconds}")
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
    lines.append("# OTP challenge lifecycle, shared by channel. The phone channel backs a")
    lines.append("# kept-but-unused seam (BUILD/DECISIONS.md D-2026-09-08) for a possible future")
    lines.append("# paid SMS channel; no route mints a phone code today.")
    lines.append(f"otp_ttl_seconds = {s.auth.otp_ttl_seconds}")
    lines.append(f"otp_max_attempts = {s.auth.otp_max_attempts}")
    lines.append(f"otp_length = {s.auth.otp_length}")
    lines.append(f"otp_min_resend_seconds = {s.auth.otp_min_resend_seconds}")
    lines.append("# Email-channel OTP challenge lifecycle (spec §4.4). This is the channel that")
    lines.append("# ships: parent sign-up codes and email verification codes both use it.")
    lines.append("# Longer-lived than the phone lifecycle above; length, attempt cap and resend")
    lines.append("# cooldown are shared.")
    lines.append(f"email_otp_ttl_seconds = {s.auth.email_otp_ttl_seconds}")
    lines.append("")

    lines.append("[grading]")
    lines.append("# A teacher_papers row stuck in `processing` past this many seconds is a")
    lines.append("# dead run (its instance died) and may be reclaimed by the next regrade.")
    lines.append(f"stale_run_after_seconds = {s.grading.stale_run_after_seconds}")
    lines.append("")
    lines.append("# US-005b's marking gate (US-040, closed by `08df9302`): read by every")
    lines.append("# marking path -- the CLI, student paper uploads, the teacher grading job,")
    lines.append("# quiz marking, the accuracy harness and Gradio. Enabling it CHANGES HOW")
    lines.append("# PAPERS ARE MARKED, on every one of those paths at once. This branch ships")
    lines.append("# no accuracy evidence that the verdict path marks better than the legacy")
    lines.append("# path -- that evidence needs a label campaign that has not started. Not a")
    lines.append("# safe default to flip; leave commented out until that evidence exists.")
    lines.append("# Deployed, it is set by LEMELY_GRADING__EQUIVALENCE_GATE; see docs/ci-cd.md.")
    lines.append("# equivalence_gate = true")
    lines.append("# Error-carried-forward by substitution (I7/US-013). Threaded independently")
    lines.append("# of `equivalence_gate` above -- neither flag implies the other -- but it has")
    lines.append("# no observable effect unless `equivalence_gate` is ALSO true. Deployed, it")
    lines.append("# is set by LEMELY_GRADING__ECF_SUBSTITUTION.")
    lines.append(f"ecf_substitution = {str(s.grading.ecf_substitution).lower()}")
    lines.append("# Crop re-read substitution (spec 2026-09-26 §4): when on, an answer whose")
    lines.append("# zoomed re-read disagrees with the first read is marked on the re-read text.")
    lines.append("# It CHANGES HOW PAPERS ARE MARKED on every path and there is no accuracy")
    lines.append("# evidence yet that the re-read is the better reading, so leave it off. The")
    lines.append("# teacher-review flag fires on a disagreement whether or not this is on.")
    lines.append("# Deployed, it is set by LEMELY_GRADING__REREAD_SUBSTITUTION; see docs/ci-cd.md.")
    lines.append("# reread_substitution = true")
    lines.append("")

    lines.append("[binding]")
    lines.append("# How the answers on a scanned script are tied to questions, and how far")
    lines.append("# that is checked before marking (lemely.io.binding.orchestrate).")
    lines.append("#")
    lines.append('# binder: "label" -- the model lists the question labels and the writing it')
    lines.append("# sees, with no question ids, and code binds that list to the mark scheme.")
    lines.append('# "legacy" -- the model hands out the question ids itself, as extraction')
    lines.append("# did before; kept as a way back, not as an equal choice.")
    lines.append(f'binder = "{s.binding.binder}"')
    lines.append('# gate: "enforce" -- a paper whose binding cannot be trusted is held.')
    lines.append('# The label binder REQUIRES "enforce": its checks are part of reading a')
    lines.append("# script safely, and config does not load with any other value beside it.")
    lines.append('# "observe" and "off" are for binder = "legacy" only. "observe" -- the')
    lines.append("# legacy answers are checked and the result is published (the")
    lines.append("# binding_gate_result event); the answers go on as they are, no paper is")
    lines.append('# held, and the check made after marking does not run. "off" -- no')
    lines.append('# checks and no report: binder = "legacy" with gate = "off" is extraction')
    lines.append("# exactly as it was before either existed.")
    lines.append(f'gate = "{s.binding.gate}"')
    lines.append("# The label binder's model, passed on every one of its calls. It is NOT")
    lines.append("# gemini.extraction_model: on Gemini only gemini-3.8-flash returned a usable")
    lines.append("# list when this was measured; since sub-project C it is claude-haiku-5-5.")
    lines.append("# COST: with the label binder every extraction makes its calls on this")
    lines.append("# model in place of one call on extraction_model.")
    lines.append(f'read_model = "{s.binding.read_model}"')
    lines.append("# Read the script a second time on the same model, at the thinking level")
    lines.append("# [gemini.thinking_level_for] gives binding_second_read, so that the two")
    lines.append("# reads can be compared and a bad first read replaced. Doubles the cost of")
    lines.append("# the binding step. Read by the label binder only.")
    lines.append(f"second_read = {str(s.binding.second_read).lower()}")
    lines.append('# When the second read is made. "always" -- on every script, at the same')
    lines.append('# time as the first. "on_trigger" -- the first read alone, then the second')
    lines.append("# only when the first gives a reason: a part not bound or left blank, a")
    lines.append("# label missing, out of place or seen twice, or a gate check that fails")
    lines.append("# on it. With no reason the paper goes on with the first read, as with")
    lines.append("# second_read off.")
    lines.append("# Unsafe as shipped: a first read with every label present but writing")
    lines.append("# under the wrong labels fires no trigger, so the G9 cross-read check is")
    lines.append("# lost and those answers go out verified. Not screened; keep `always`.")
    lines.append("# COST: its blank_leaf trigger fires on every script with a genuinely")
    lines.append("# skipped part (5/5 reads of the one real scan on disk), so on real")
    lines.append("# scripts it saves far less than on the golden set (0/20 reads).")
    lines.append(f'second_read_mode = "{s.binding.second_read_mode}"')
    lines.append("# The second read's model. Unset: read_model reads twice. A claude- model")
    lines.append("# (e.g. claude-haiku-5-5) makes it a cross-model read under the")
    lines.append("# binding_second_read task tag: its thinking level is the Anthropic effort")
    lines.append("# and its max_output_tokens_for cap applies. Claude gets the pages fitted")
    lines.append("# under gemini.claude_image_token_budget, never below")
    lines.append("# gemini.claude_image_floor_px. Needs ANTHROPIC_API_KEY; `lemely doctor`")
    lines.append("# checks for it.")
    lines.append('# second_read_model = "claude-haiku-5-5"')
    lines.append("# A claude- read still over the token budget at the image floor is read as")
    lines.append("# an overview pass plus page chunks under the budget (off until screened).")
    lines.append(
        "# The binding_overview call (the 768 px map pass) uses the effort, output cap and"
    )
    lines.append("# cache defaults of its tag unless set. Chunk calls send their pages inline, not")
    lines.append("# through the Files API: input tokens are unchanged, bandwidth is higher.")
    lines.append(f"# claude_chunked_read = {_toml_bool(s.binding.claude_chunked_read)}")
    lines.append("# Make the two claude- binder reads in turn even when their efforts differ")
    lines.append("# (lever a3; the second read hits the first's cache only if the API allows).")
    lines.append(
        f"# claude_cache_ignores_effort = {_toml_bool(s.binding.claude_cache_ignores_effort)}"
    )
    lines.append("# The model the legacy binder's one retry uses, when the gate is on.")
    lines.append(f'retry_model = "{s.binding.retry_model}"')
    lines.append("")

    lines.append("[integrity]")
    lines.append("# Plagiarism detection needs no Gemini key (stdlib difflib only). F4 removed")
    lines.append("# the AI-generated-answer detector that used to live here — no evidence base,")
    lines.append("# JCQ guidance says a detector must never be sole evidence.")
    lines.append(f"plagiarism_enabled = {str(s.integrity.plagiarism_enabled).lower()}")
    lines.append(f"plagiarism_threshold = {s.integrity.plagiarism_threshold}")
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

    lines.append("")

    lines.append("[notifications]")
    lines.append("# The in-process sweeper that publishes scheduled announcements and sends the")
    lines.append("# two daily engagement notifications (streak_warning at streak_warning_hour,")
    lines.append("# study_plan_reminder at study_plan_reminder_hour) in each recipient's OWN")
    lines.append("# time zone. It runs inside the API process, started by create_app's lifespan;")
    lines.append("# there is no separate worker to deploy. On Cloud Run, timely delivery needs")
    lines.append("# --min-instances=1: at zero instances nothing is running to sweep, and a")
    lines.append("# 19:00 warning may be missed for that day entirely. See docs/deployment.md.")
    lines.append("# The test suite sets LEMELY_NOTIFICATIONS__SWEEPER_ENABLED=0.")
    # The shipped default, deliberately not ``s.notifications.sweeper_enabled``:
    # the test suite sets LEMELY_NOTIFICATIONS__SWEEPER_ENABLED=0 for every
    # test, so reading the live value would make this generator emit "false"
    # under pytest and "true" everywhere else — and
    # tests/test_settings_example_drift.py would fail on a file that is
    # correct. An example file documents what ships, not what this process's
    # environment happens to say.
    lines.append(f"sweeper_enabled = {str(NotificationsSettings().sweeper_enabled).lower()}")
    lines.append(f"sweep_poll_seconds = {s.notifications.sweep_poll_seconds}")
    lines.append(f"streak_warning_hour = {s.notifications.streak_warning_hour}")
    lines.append(f"study_plan_reminder_hour = {s.notifications.study_plan_reminder_hour}")

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
