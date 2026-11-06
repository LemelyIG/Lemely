# Paymob billing phase 02: payments core. Implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take real card payments for credit packs through Paymob Unified Checkout. Payments are recorded before Paymob is called, verified by HMAC webhook or by transaction inquiry, granted exactly once through the Phase 01 usage ledger, and listed as receipts.

**Architecture:** `lemely/io/paymob/` holds a thin `httpx` client and pure HMAC functions with no business logic. `lemely/db/billing_repo.py` holds `BillingService`, the only place where Paymob and the ledger meet. A verified payment moves to `paid` and is passed to a handler registered per purpose; Phase 02 registers only `credit_pack`. Two routers expose it. `/api/billing` serves the catalogue, pack checkout, payment status and receipts. `/api/webhooks/paymob` takes the transaction and card-token callbacks. The existing in-process sweeper runs `billing.reconcile_pending` for missed callbacks.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, Alembic, Postgres, httpx (tests use `httpx.MockTransport`, the pattern already in `tests/test_notify_email.py`), `cryptography` AES-GCM (already installed through `pyjwt[crypto]`, already used by `lemely/runtime/vapid.py`), pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-11-02-paymob-billing-design.md` (rev 2). Names, files, migration numbers and interfaces: `docs/superpowers/plans/2026-11-05-paymob-billing-00-index.md`.
- This phase consumes Phase 01 (`0052_usage_ledger`, `lemely/db/models/usage.py`, `lemely/db/usage_ledger_repo.py`). Do not start until Phase 01 is merged into the branch.
- Work only in the worktree `/home/sico/Code/Lemely/.claude/worktrees/paymob-integration` (branch `feat/paymob-integration`). Never `cd` to `/home/sico/Code/Lemely`.
- Signed commits only, scoped by path: `git add <paths> && git commit -S -m "<msg>" -- <paths>`. Use conventional scopes such as `feat(paymob):`, `feat(billing):` or `test(billing):`.
- Before each commit, run `/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files`. The ruff hook autofixes, so if it changed files, `git add` them and run it again until it passes clean.
- Tests: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest <touched test files> -v --no-cov`. Every pytest command carries `--no-cov`: the repo's `--cov-fail-under=70` fails any subset run (index R2). Never run the full suite, `make test` or bare `pytest`. When a task adds a module under `lemely/`, also run `tests/architecture/`.
- Money is integer minor units (piasters, `BIGINT`). Usage is integer units (`BIGINT`).
- UUID primary keys use `server_default=sa.text("gen_random_uuid()")`, with Postgres enums and `TimestampMixin`. Enum member names equal their values (`tests/test_db_schema.py::test_every_enum_column_binds_its_value_not_its_member_name`).
- Paymob secret key, API key, HMAC secret and card-token key are read on the server only. They are never logged and never sent to the browser. Only the public key and the per-intention client secret reach the browser.
- Every webhook state change happens in one DB transaction (`sessionmaker.begin()`), and the 200 goes out only after commit.
- Webhook: a HMAC mismatch is 401 and logged at error level. A duplicate `dedupe_key` is 200 with no change. An unknown `special_reference` is 200 and logged.
- Amount or currency mismatch: set `failed_mismatch`, issue no grant, log at error level (`paymob_amount_mismatch`).
- No idempotency keys at Paymob: insert our payment row and commit it before calling Paymob. After a timeout, never retry. The reconcile job checks inquiry first.
- No placeholder code: no `TODO`, no `pass` bodies, no `pytest.skip` beyond the existing "Postgres not reachable" fixtures, no stub tests.

## Contract deviations

1. **Route prefixes are `/api/billing` and `/api/webhooks/paymob`, not `/billing` and `/webhooks/paymob`** (confirmed by index R1). Every Lemely router carries the `/api` prefix itself (`lemely/web/routers/parent.py`: `APIRouter(prefix="/api/parent")`), and `create_app` adds none. The Cloudflare Worker proxies only `/api/*` to Cloud Run (`web/worker/index.ts`). Without the prefix, Paymob's callbacks would never reach the backend.
2. **One webhook route serves both transaction and card-token callbacks: `POST /api/webhooks/paymob/transaction?hmac=…`.** Paymob sends the card-token callback (`"type": "TOKEN"`) to the same intention `notification_url` as the transaction callback (research 02 §2.2, §5). The route dispatches on `type`. No separate token path exists, because Paymob would never call one.
3. **`PaymobSettings` gains three fields beyond the index:** `card_token_key` (the AES-GCM key for saved-card tokens; spec §7 requires encryption at rest and the repo has no encryption helper), `timeout_seconds`, and the read-only property `checkout_configured`. Every index field keeps its name and default.
4. **`payments` gains four columns beyond spec §4.2:**
   - `grant_units`: the units snapshotted at checkout, so an admin edit to a pack between checkout and callback cannot change what was bought.
   - `reconcile_attempts` and `next_reconcile_at`: the backoff schedule required by spec §5.10.
   - `saved_cards.token_fingerprint` (HMAC-SHA256 of the token): a ciphertext is non-deterministic, so the same card arriving twice can only be matched by a keyed fingerprint.

   `saved_cards.paymob_token_id` is also added. All of these are additive.
5. **The live-subscription partial unique index, `uq_subscriptions_one_live_per_user`, is per beneficiary (`user_id`), restricted to paid-path rows (`payer_user_id IS NOT NULL`).** Index R8 makes 0053 its only creator; Phase 05 consumes it and `LIVE_SUBSCRIPTION_STATUSES`. A user has exactly one role, and a tier's audience follows the role, so "per beneficiary per audience" equals "per beneficiary". The `payer_user_id IS NOT NULL` filter leaves the existing manual-activation path (`lemely/db/admin_repo.py`), which never sets a payer, unconstrained, as it is today. The predicate compares `status::text`, so the migration can use the two new enum labels in the same transaction that adds them.
6. **`BillingService.__init__` gains keyword-only optional arguments `cipher` and `now`** (test seams). The positional contract `(session, client, settings)` is unchanged.
7. **`BillingService` commits in two methods.** `create_intention_checkout` and `create_pack_checkout` commit, because spec §6 requires the payment row to exist before Paymob is called. `reconcile_pending` commits after each payment. `apply_transaction_callback` and `apply_token_callback` never commit; the webhook route's `sessionmaker.begin()` owns that transaction.
8. **`billing.reconcile_pending` gets its idempotency from row state, not from a notification dedupe key.** The safeguards are `FOR UPDATE SKIP LOCKED` on the payment row, the `paymob_events.dedupe_key` unique constraint, and status transitions that only move forward. The job is a new optional collaborator on the existing `Sweeper` dataclass, using the same pattern as `email_provider`.
9. **`subscriptions.version` is added as a plain column. It is not wired as SQLAlchemy's `version_id_col`.** Wiring it would change how every existing ORM update to `subscriptions` behaves, including manual activation. Phase 05, which owns the webhook race, decides how to use it.

## File structure

| File | Status | Responsibility |
|---|---|---|
| `lemely/runtime/config.py` | modify | `PaymobSettings`, `Settings.paymob` |
| `.github/workflows/deploy.yml` | modify | `LEMELY_PAYMOB__*` env for Cloud Run |
| `lemely/runtime/token_cipher.py` | create | AES-GCM encrypt/decrypt and keyed fingerprint for card tokens |
| `lemely/io/paymob/__init__.py` | create | package marker |
| `lemely/io/paymob/hmac.py` | create | transaction / token / subscription HMAC verification |
| `lemely/io/paymob/client.py` | create | `PaymobClient`, `PaymobError`, `PaymobNotConfigured` |
| `lemely/db/models/enums.py` | modify | two new `SubscriptionStatus` labels |
| `lemely/db/models/billing.py` | modify | new enums and models; new `PlanTier` / `Subscription` columns |
| `lemely/db/models/usage.py` | modify | FK on `UsageGrant.payment_id` |
| `lemely/db/migrations/versions/0053_billing_payments.py` | create | the migration |
| `lemely/db/billing_repo.py` | create | `BillingService`, paid-handler registry, credit-pack handler, read queries |
| `lemely/web/billing_jobs.py` | create | `reconcile_pending_payments` sweeper job |
| `lemely/web/deps_billing.py` | create | Paymob client, sessionmaker, checkout limiter and reconcile-job providers |
| `lemely/web/deps.py` | modify | sweeper wiring, singleton reset |
| `lemely/web/scheduled_notifications.py` | modify | `Sweeper.billing_reconcile` |
| `lemely/web/schemas_billing.py` | create | billing DTOs |
| `lemely/web/routers/billing.py` | create | `/api/billing` |
| `lemely/web/routers/paymob_webhooks.py` | create | `/api/webhooks/paymob` |
| `lemely/web/app.py` | modify | register both routers |
| `tests/paymob_fixtures.py` | create (grown per task) | handwritten Paymob payloads, signer, fake client, DB seeders |
| `tests/test_authz_matrix_complete.py` | modify | declare the five new routes |

---

### Task 1: Paymob settings and deploy wiring

**Files:**
- Modify: `lemely/runtime/config.py` (add `PaymobSettings` after `EmailSettings`, before `_RemovedKeysDotEnvSource`; add `paymob` to `Settings` after `tutoring`)
- Modify: `.github/workflows/deploy.yml` (deploy step `env_vars` block, after `LEMELY_PUSH__VAPID_SUBJECT`, plus a comment paragraph above `env_vars:`)
- Test: `tests/test_paymob_settings.py`
- Test: `tests/test_deploy_paymob_env.py`

**Interfaces:**
- Consumes: `OptionalSecret`, `OptionalCredential`, `AbsoluteOrigin`, `_blank_to_none` (already in `config.py`).
- Produces: `lemely.runtime.config.PaymobSettings` with fields `secret_key: SecretStr | None`, `public_key: str | None`, `api_key: SecretStr | None`, `hmac_secret: SecretStr | None`, `card_integration_id: int | None`, `moto_integration_id: int | None`, `apple_pay_integration_id: int | None`, `card_token_key: SecretStr | None`, `api_base: str = "https://accept.paymob.com"`, `checkout_base: str = "https://eg.checkout.paymob.com"`, `notification_base_url: str = "https://lemelyig.com"`, `redirection_base_url: str = "https://lemelyig.com"`, `timeout_seconds: float = 20.0`, and the property `checkout_configured -> bool`. Also produces `Settings.paymob: PaymobSettings`.

- [ ] **Step 1: Write the failing settings test**

Create `tests/test_paymob_settings.py`:

```python
"""PaymobSettings: env-driven, secrets stay secret, blank means unset (spec §3, §7)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lemely.runtime.config import PaymobSettings, Settings


def test_defaults_are_unconfigured_with_the_egypt_hosts() -> None:
    paymob = Settings().paymob
    assert paymob.api_base == "https://accept.paymob.com"
    assert paymob.checkout_base == "https://eg.checkout.paymob.com"
    assert paymob.notification_base_url == "https://lemelyig.com"
    assert paymob.redirection_base_url == "https://lemelyig.com"
    assert paymob.timeout_seconds == 20.0
    assert paymob.secret_key is None
    assert paymob.checkout_configured is False


def test_env_vars_populate_every_field(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEMELY_PAYMOB__SECRET_KEY", "egy_sk_test_abc")
    monkeypatch.setenv("LEMELY_PAYMOB__PUBLIC_KEY", "egy_pk_test_abc")
    monkeypatch.setenv("LEMELY_PAYMOB__API_KEY", "api_key_abc")
    monkeypatch.setenv("LEMELY_PAYMOB__HMAC_SECRET", "hmac_abc")
    monkeypatch.setenv("LEMELY_PAYMOB__CARD_INTEGRATION_ID", "4569876")
    monkeypatch.setenv("LEMELY_PAYMOB__MOTO_INTEGRATION_ID", "4569877")
    monkeypatch.setenv("LEMELY_PAYMOB__NOTIFICATION_BASE_URL", "https://staging.lemelyig.com/")
    paymob = Settings().paymob
    assert paymob.secret_key is not None
    assert paymob.secret_key.get_secret_value() == "egy_sk_test_abc"
    assert paymob.public_key == "egy_pk_test_abc"
    assert paymob.card_integration_id == 4569876
    assert paymob.moto_integration_id == 4569877
    assert paymob.apple_pay_integration_id is None
    assert paymob.notification_base_url == "https://staging.lemelyig.com"
    assert paymob.checkout_configured is True


def test_blank_env_values_read_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """deploy.yml renders an unregistered secret or variable as "" (as for RESEND_API_KEY)."""
    for name in (
        "SECRET_KEY",
        "PUBLIC_KEY",
        "API_KEY",
        "HMAC_SECRET",
        "CARD_INTEGRATION_ID",
        "MOTO_INTEGRATION_ID",
        "APPLE_PAY_INTEGRATION_ID",
        "CARD_TOKEN_KEY",
    ):
        monkeypatch.setenv(f"LEMELY_PAYMOB__{name}", "")
    paymob = Settings().paymob
    assert paymob.secret_key is None
    assert paymob.public_key is None
    assert paymob.card_integration_id is None
    assert paymob.card_token_key is None
    assert paymob.checkout_configured is False


def test_checkout_needs_all_five_credentials() -> None:
    full = {
        "secret_key": "sk",
        "public_key": "pk",
        "api_key": "ak",
        "hmac_secret": "hs",
        "card_integration_id": 1,
    }
    assert PaymobSettings.model_validate(full).checkout_configured is True
    for missing in full:
        partial = {k: v for k, v in full.items() if k != missing}
        assert PaymobSettings.model_validate(partial).checkout_configured is False, missing


def test_secrets_never_appear_in_repr() -> None:
    paymob = PaymobSettings.model_validate(
        {"secret_key": "sk_live_SECRET", "api_key": "API_SECRET", "hmac_secret": "HMAC_SECRET"}
    )
    rendered = repr(paymob) + str(paymob.model_dump())
    assert "sk_live_SECRET" not in rendered
    assert "API_SECRET" not in rendered
    assert "HMAC_SECRET" not in rendered


def test_a_relative_callback_origin_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PaymobSettings.model_validate({"notification_base_url": "lemelyig.com"})


def test_integration_ids_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        PaymobSettings.model_validate({"card_integration_id": 0})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_paymob_settings.py -v --no-cov`
Expected: collection error, `ImportError: cannot import name 'PaymobSettings' from 'lemely.runtime.config'`.

- [ ] **Step 3: Implement `PaymobSettings`**

In `lemely/runtime/config.py`, insert this class directly after `EmailSettings` (before `class _RemovedKeysDotEnvSource`):

```python
#: An optional positive integer id where a blank env var means "not set".
OptionalId = Annotated[int | None, BeforeValidator(_blank_to_none)]


class PaymobSettings(BaseModel):
    """Paymob (Egypt) credentials and endpoints (billing spec §3, §7).

    Overrides via ``LEMELY_PAYMOB__*`` env vars (``lemely.toml`` ``[paymob]`` also
    works but is not emitted in ``lemely.toml.example``: every field here is a
    credential or a deploy-time origin, never a knob someone sets up locally).

    **Every credential defaults to ``None`` and that is a supported state**, as for
    :class:`EmailSettings` and :class:`PushSettings`: an unregistered GitHub secret
    renders as ``""``, ``_blank_to_none`` maps it to ``None``, ``checkout_configured``
    is ``False``, checkout answers 503 and the webhook answers 503. Metering never
    calls Paymob, so allowances and credits keep working (spec §6).

    ``secret_key`` (``Authorization: Token``) authorises intentions, refunds and voids;
    ``api_key`` mints the one-hour auth token used for inquiry and subscriptions;
    ``hmac_secret`` verifies callbacks; ``card_token_key`` (urlsafe base64 of 32
    bytes) encrypts saved-card tokens at rest. All four are server-only and typed
    :class:`SecretStr`. ``public_key`` is handed to the browser inside the Unified
    Checkout URL and is deliberately a plain ``str``, like ``vapid_public_key``.

    ``notification_base_url`` / ``redirection_base_url`` are the public origins the
    webhook route and the SPA return page are joined onto; ``deploy.yml`` sets them
    per environment so a staging intention never calls back into production.
    """

    model_config = ConfigDict(extra="forbid")
    secret_key: OptionalSecret = None
    public_key: OptionalCredential = None
    api_key: OptionalSecret = None
    hmac_secret: OptionalSecret = None
    card_integration_id: OptionalId = Field(default=None, ge=1)
    moto_integration_id: OptionalId = Field(default=None, ge=1)
    apple_pay_integration_id: OptionalId = Field(default=None, ge=1)
    card_token_key: OptionalSecret = None
    api_base: AbsoluteOrigin = "https://accept.paymob.com"
    checkout_base: AbsoluteOrigin = "https://eg.checkout.paymob.com"
    notification_base_url: AbsoluteOrigin = "https://lemelyig.com"
    redirection_base_url: AbsoluteOrigin = "https://lemelyig.com"
    timeout_seconds: float = Field(default=20.0, gt=0)

    @property
    def checkout_configured(self) -> bool:
        """True when a one-off card checkout can be created and its callback verified."""
        return all(
            value is not None
            for value in (
                self.secret_key,
                self.public_key,
                self.api_key,
                self.hmac_secret,
                self.card_integration_id,
            )
        )
```

In `class Settings(BaseSettings)`, add this line directly after `tutoring: TutoringSettings = TutoringSettings()`:

```python
    paymob: PaymobSettings = PaymobSettings()
```

- [ ] **Step 4: Run the settings test to verify it passes**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_paymob_settings.py tests/test_settings_example_drift.py -v --no-cov`
Expected: all PASS. The drift test still passes because `[paymob]` is not emitted.

- [ ] **Step 5: Write the failing deploy test**

Create `tests/test_deploy_paymob_env.py`:

```python
"""deploy.yml hands every Paymob setting to Cloud Run, secrets from secrets (spec §3, §7)."""

from __future__ import annotations

from pathlib import Path

import yaml

from lemely.runtime.config import PaymobSettings

_DEPLOY = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "deploy.yml"
_PREFIX = "LEMELY_PAYMOB__"

#: Server-only credentials: must come from repository/environment SECRETS.
_SECRETS = {
    "SECRET_KEY": "PAYMOB_SECRET_KEY",
    "API_KEY": "PAYMOB_API_KEY",
    "HMAC_SECRET": "PAYMOB_HMAC_SECRET",
    "CARD_TOKEN_KEY": "PAYMOB_CARD_TOKEN_KEY",
}
#: Non-secret values: repository/environment VARIABLES.
_VARIABLES = {
    "PUBLIC_KEY": "PAYMOB_PUBLIC_KEY",
    "CARD_INTEGRATION_ID": "PAYMOB_CARD_INTEGRATION_ID",
    "MOTO_INTEGRATION_ID": "PAYMOB_MOTO_INTEGRATION_ID",
    "APPLE_PAY_INTEGRATION_ID": "PAYMOB_APPLE_PAY_INTEGRATION_ID",
}
#: Fields that keep their code default in every environment.
_DEFAULTED = {"api_base", "checkout_base", "timeout_seconds"}


def _env_vars() -> dict[str, str]:
    workflow = yaml.safe_load(_DEPLOY.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["deploy-backend"]["steps"]
    deploy = next(step for step in steps if step.get("id") == "deploy")
    pairs = (line.split("=", 1) for line in deploy["with"]["env_vars"].splitlines() if line)
    return {name: value for name, value in pairs}


def test_server_only_credentials_come_from_secrets() -> None:
    env = _env_vars()
    for field, secret in _SECRETS.items():
        assert env[_PREFIX + field] == "${{ secrets.%s }}" % secret, field


def test_public_values_come_from_variables_never_secrets() -> None:
    env = _env_vars()
    for field, variable in _VARIABLES.items():
        assert env[_PREFIX + field] == "${{ vars.%s }}" % variable, field


def test_every_paymob_field_is_deployed_or_deliberately_defaulted() -> None:
    env = _env_vars()
    deployed = {name.removeprefix(_PREFIX).lower() for name in env if name.startswith(_PREFIX)}
    assert deployed == set(PaymobSettings.model_fields) - _DEFAULTED


def test_callback_origins_follow_the_environment_like_the_email_links() -> None:
    env = _env_vars()
    origin = env["LEMELY_EMAIL__APP_BASE_URL"]
    assert env[_PREFIX + "NOTIFICATION_BASE_URL"] == origin
    assert env[_PREFIX + "REDIRECTION_BASE_URL"] == origin
```

- [ ] **Step 6: Run it to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_deploy_paymob_env.py -v --no-cov`
Expected: FAIL with `KeyError: 'LEMELY_PAYMOB__SECRET_KEY'`.

- [ ] **Step 7: Wire the env vars in `deploy.yml`**

In `.github/workflows/deploy.yml`, find the comment paragraph that ends `# invalidates every stored subscription (docs/push-notifications.md).` directly above `env_vars: |-`. Append this paragraph after it:

```yaml
          #
          # Paymob (billing spec §3, §7). The secret key, API key, HMAC secret
          # and card-token key are repository SECRETS; the public key and the
          # integration ids are VARIABLES (the public key is handed to every
          # browser inside the checkout URL). Unset ones render as "", which
          # `_blank_to_none` maps to None, so this is safe to merge before
          # Paymob credentials exist: checkout and the webhook answer 503 and
          # nothing else changes. The two origins follow the environment like
          # LEMELY_EMAIL__APP_BASE_URL, so a staging intention never calls
          # back into production. Generate the card-token key with
          # `python -c "from lemely.runtime.token_cipher import TokenCipher; print(TokenCipher.generate_key())"`;
          # rotating it makes every stored card token undecryptable.
```

At the end of the `env_vars: |-` block, after `LEMELY_PUSH__VAPID_SUBJECT=mailto:support@lemelyig.com`, append these lines with the same 12-space indentation:

```yaml
            LEMELY_PAYMOB__SECRET_KEY=${{ secrets.PAYMOB_SECRET_KEY }}
            LEMELY_PAYMOB__API_KEY=${{ secrets.PAYMOB_API_KEY }}
            LEMELY_PAYMOB__HMAC_SECRET=${{ secrets.PAYMOB_HMAC_SECRET }}
            LEMELY_PAYMOB__CARD_TOKEN_KEY=${{ secrets.PAYMOB_CARD_TOKEN_KEY }}
            LEMELY_PAYMOB__PUBLIC_KEY=${{ vars.PAYMOB_PUBLIC_KEY }}
            LEMELY_PAYMOB__CARD_INTEGRATION_ID=${{ vars.PAYMOB_CARD_INTEGRATION_ID }}
            LEMELY_PAYMOB__MOTO_INTEGRATION_ID=${{ vars.PAYMOB_MOTO_INTEGRATION_ID }}
            LEMELY_PAYMOB__APPLE_PAY_INTEGRATION_ID=${{ vars.PAYMOB_APPLE_PAY_INTEGRATION_ID }}
            LEMELY_PAYMOB__NOTIFICATION_BASE_URL=https://${{ needs.resolve-env.outputs.environment == 'production' && 'lemelyig.com' || 'staging.lemelyig.com' }}
            LEMELY_PAYMOB__REDIRECTION_BASE_URL=https://${{ needs.resolve-env.outputs.environment == 'production' && 'lemelyig.com' || 'staging.lemelyig.com' }}
```

- [ ] **Step 8: Run both tests and the existing deploy tests**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_paymob_settings.py tests/test_deploy_paymob_env.py tests/test_deploy_evidence_bucket.py tests/test_deploy_headers.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 9: Pre-commit and commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/runtime/config.py .github/workflows/deploy.yml tests/test_paymob_settings.py tests/test_deploy_paymob_env.py
git commit -S -m "feat(paymob): add Paymob settings and deploy their env vars to Cloud Run" -- lemely/runtime/config.py .github/workflows/deploy.yml tests/test_paymob_settings.py tests/test_deploy_paymob_env.py
```

---

### Task 2: Card-token encryption at rest

The repo has no encryption helper. `lemely/runtime/vapid.py` uses `cryptography` only for keys. This task adds one, keyed from `PaymobSettings.card_token_key`.

**Files:**
- Create: `lemely/runtime/token_cipher.py`
- Test: `tests/test_token_cipher.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `lemely.runtime.token_cipher.TokenCipher(key_b64: str)` with methods `encrypt(plaintext: str) -> str` (format `"v1:" + urlsafe-b64(nonce‖ciphertext)`), `decrypt(ciphertext: str) -> str` (raises `ValueError` on tamper, wrong key or bad format), `fingerprint(plaintext: str) -> str` (64 hex chars, deterministic per key), and the static method `generate_key() -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_token_cipher.py`:

```python
"""TokenCipher: saved-card tokens encrypted at rest (billing spec §4.2, §7)."""

from __future__ import annotations

import base64

import pytest

from lemely.runtime.token_cipher import TokenCipher

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
OTHER_KEY = base64.urlsafe_b64encode(b"o" * 32).decode()
TOKEN = "3f22ce8a4e5b6c7d8e9f0a1b2c3d4e5f"


def test_round_trip() -> None:
    cipher = TokenCipher(KEY)
    sealed = cipher.encrypt(TOKEN)
    assert sealed.startswith("v1:")
    assert TOKEN not in sealed
    assert cipher.decrypt(sealed) == TOKEN


def test_each_encryption_uses_a_fresh_nonce() -> None:
    cipher = TokenCipher(KEY)
    assert cipher.encrypt(TOKEN) != cipher.encrypt(TOKEN)


def test_tampering_is_detected() -> None:
    cipher = TokenCipher(KEY)
    sealed = cipher.encrypt(TOKEN)
    raw = bytearray(base64.urlsafe_b64decode(sealed[3:]))
    raw[-1] ^= 0x01
    with pytest.raises(ValueError, match="could not be decrypted"):
        cipher.decrypt("v1:" + base64.urlsafe_b64encode(bytes(raw)).decode())


def test_the_wrong_key_cannot_decrypt() -> None:
    sealed = TokenCipher(KEY).encrypt(TOKEN)
    with pytest.raises(ValueError, match="could not be decrypted"):
        TokenCipher(OTHER_KEY).decrypt(sealed)


@pytest.mark.parametrize("bad", ["", "v2:abcd", "v1:", "v1:!!!", "plain"])
def test_malformed_ciphertext_is_a_value_error(bad: str) -> None:
    with pytest.raises(ValueError):
        TokenCipher(KEY).decrypt(bad)


def test_a_key_that_is_not_32_bytes_is_refused() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        TokenCipher(base64.urlsafe_b64encode(b"short").decode())


def test_unpadded_keys_are_accepted() -> None:
    assert TokenCipher(KEY.rstrip("=")).decrypt(TokenCipher(KEY).encrypt(TOKEN)) == TOKEN


def test_fingerprint_is_deterministic_and_keyed() -> None:
    a, b = TokenCipher(KEY), TokenCipher(OTHER_KEY)
    assert a.fingerprint(TOKEN) == a.fingerprint(TOKEN)
    assert len(a.fingerprint(TOKEN)) == 64
    assert a.fingerprint(TOKEN) != b.fingerprint(TOKEN)
    assert a.fingerprint(TOKEN) != a.fingerprint(TOKEN + "x")
    assert TOKEN not in a.fingerprint(TOKEN)


def test_generated_keys_work() -> None:
    key = TokenCipher.generate_key()
    assert TokenCipher(key).decrypt(TokenCipher(key).encrypt(TOKEN)) == TOKEN
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_token_cipher.py -v --no-cov`
Expected: collection error, `ModuleNotFoundError: No module named 'lemely.runtime.token_cipher'`.

- [ ] **Step 3: Implement**

Create `lemely/runtime/token_cipher.py`:

```python
"""Authenticated encryption for Paymob saved-card tokens (billing spec §4.2, §7).

A card token lets Lemely charge a card without the customer present (Phase 06
merchant-initiated charges), so a database dump must not yield usable tokens.
Tokens are sealed with AES-256-GCM under ``PaymobSettings.card_token_key`` (urlsafe
base64 of 32 random bytes, a deploy secret), with a fresh 96-bit nonce per seal.
The stored form is ``"v1:" + urlsafe_b64(nonce || ciphertext||tag)``; the version
prefix leaves room for a key rotation scheme without guessing at old rows.

Because sealing is randomised, the same card arriving twice cannot be matched on
ciphertext. :meth:`TokenCipher.fingerprint` is an HMAC-SHA256 of the token under a
key derived from the same secret: deterministic, useless without the key.

Lives in ``lemely.runtime`` (stdlib + ``cryptography`` only), so the ``db`` layer
can use it without importing ``io`` or ``web``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = "v1:"
_NONCE_BYTES = 12
_KEY_BYTES = 32
_FINGERPRINT_CONTEXT = b"lemely-card-token-fingerprint-v1"


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class TokenCipher:
    """Seal, open and fingerprint card tokens under one 32-byte key."""

    def __init__(self, key_b64: str) -> None:
        try:
            key = _b64decode(key_b64.strip())
        except (binascii.Error, ValueError) as exc:
            raise ValueError("card token key is not valid urlsafe base64") from exc
        if len(key) != _KEY_BYTES:
            raise ValueError("card token key must decode to exactly 32 bytes")
        self._aead = AESGCM(key)
        self._mac_key = hashlib.sha256(_FINGERPRINT_CONTEXT + key).digest()

    @staticmethod
    def generate_key() -> str:
        """A fresh random key in the form ``card_token_key`` expects."""
        return base64.urlsafe_b64encode(os.urandom(_KEY_BYTES)).decode()

    def encrypt(self, plaintext: str) -> str:
        """Seal ``plaintext``; every call yields a different string."""
        nonce = os.urandom(_NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, plaintext.encode("utf-8"), None)
        return _VERSION + base64.urlsafe_b64encode(nonce + sealed).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Open a value produced by :meth:`encrypt`; ``ValueError`` on any failure."""
        if not ciphertext.startswith(_VERSION):
            raise ValueError("unknown card token ciphertext format")
        try:
            raw = _b64decode(ciphertext[len(_VERSION) :])
        except (binascii.Error, ValueError) as exc:
            raise ValueError("card token ciphertext is not valid base64") from exc
        if len(raw) <= _NONCE_BYTES:
            raise ValueError("card token ciphertext is truncated")
        try:
            plain = self._aead.decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], None)
        except InvalidTag as exc:
            raise ValueError("card token could not be decrypted") from exc
        return plain.decode("utf-8")

    def fingerprint(self, plaintext: str) -> str:
        """Deterministic keyed digest used to recognise the same card twice."""
        return hmac.new(self._mac_key, plaintext.encode("utf-8"), hashlib.sha256).hexdigest()


__all__ = ["TokenCipher"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_token_cipher.py tests/architecture/ -v --no-cov`
Expected: all PASS.

- [ ] **Step 5: Pre-commit and commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/runtime/token_cipher.py tests/test_token_cipher.py
git commit -S -m "feat(billing): encrypt saved-card tokens at rest with AES-GCM" -- lemely/runtime/token_cipher.py tests/test_token_cipher.py
```

---

### Task 3: Paymob HMAC verification

**Files:**
- Create: `lemely/io/paymob/__init__.py`
- Create: `lemely/io/paymob/hmac.py`
- Create: `tests/paymob_fixtures.py` (first part; later tasks append to it)
- Test: `tests/test_paymob_hmac.py`

**Interfaces:**
- Consumes: `PaymobSettings` (Task 1), for the shared test settings.
- Produces (all in `lemely.io.paymob.hmac`):
  - `TRANSACTION_HMAC_FIELDS: tuple[str, ...]`
  - `TOKEN_HMAC_FIELDS: tuple[str, ...]`
  - `transaction_hmac_message(obj: Mapping[str, Any]) -> str`
  - `token_hmac_message(obj: Mapping[str, Any]) -> str`
  - `subscription_hmac_message(trigger_type: str, sub_id: int) -> str`
  - `sign(message: str, secret: str) -> str`
  - `verify_transaction_hmac(obj: Mapping, received: str, secret: str) -> bool`
  - `verify_token_hmac(obj: Mapping, received: str, secret: str) -> bool`
  - `verify_subscription_hmac(trigger_type: str, sub_id: int, received: str, secret: str) -> bool`
- Produces (test helpers in `tests/paymob_fixtures.py`): `TEST_HMAC_SECRET`, `TEST_CARD_TOKEN_KEY`, `PAYMOB_SETTINGS`, `transaction_obj(...)`, `token_obj(...)`, `transaction_callback(obj)`, `token_callback(obj)`, `sign_transaction(obj, secret=TEST_HMAC_SECRET)`, `sign_token(obj, secret=TEST_HMAC_SECRET)`.

- [ ] **Step 1: Create the shared fixtures module (first part)**

Create `tests/paymob_fixtures.py`:

```python
"""Handwritten Paymob payloads and helpers shared by the billing tests.

Shapes follow the research notes (docs/billing/research/01, 02, 04): the
transaction object is the ``obj`` of a Transaction Processed callback, which has
the same shape as a transaction-inquiry response; the token object is the ``obj``
of a ``"type": "TOKEN"`` callback. They are handwritten from the documented field
lists until the live test account supplies recorded ones (spec §9 "Live test
account"). The HMAC secret is a test value: Paymob does not publish the secret
behind its worked example, so callbacks here are signed with it.
"""

from __future__ import annotations

import base64
from typing import Any

from lemely.io.paymob.hmac import sign, token_hmac_message, transaction_hmac_message
from lemely.runtime.config import PaymobSettings

TEST_HMAC_SECRET = "test_hmac_secret_0123456789abcdef"
TEST_CARD_TOKEN_KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
CARD_INTEGRATION_ID = 4569876
MOTO_INTEGRATION_ID = 4569877

PAYMOB_SETTINGS = PaymobSettings.model_validate(
    {
        "secret_key": "egy_sk_test_secret",
        "public_key": "egy_pk_test_public",
        "api_key": "api_key_test",
        "hmac_secret": TEST_HMAC_SECRET,
        "card_integration_id": CARD_INTEGRATION_ID,
        "moto_integration_id": MOTO_INTEGRATION_ID,
        "card_token_key": TEST_CARD_TOKEN_KEY,
    }
)


def transaction_obj(
    *,
    txn_id: int = 192036465,
    order_id: int = 265715202,
    merchant_order_id: str = "unknown-reference",
    amount_cents: int = 10000,
    currency: str = "EGP",
    success: bool = True,
    pending: bool = False,
    is_voided: bool = False,
    is_refunded: bool = False,
    refunded_amount_cents: int = 0,
    error_occured: bool = False,
    has_parent_transaction: bool = False,
    is_refund: bool = False,
    is_void: bool = False,
    source_type: str = "card",
) -> dict[str, Any]:
    """A card transaction ``obj`` (research 02 §1.2), success by default."""
    paid = success and not pending
    return {
        "id": txn_id,
        "pending": pending,
        "amount_cents": amount_cents,
        "success": success,
        "is_auth": False,
        "is_capture": False,
        "is_standalone_payment": not has_parent_transaction,
        "is_voided": is_voided,
        "is_refunded": is_refunded,
        "is_3d_secure": True,
        "integration_id": CARD_INTEGRATION_ID,
        "profile_id": 106,
        "has_parent_transaction": has_parent_transaction,
        "order": {
            "id": order_id,
            "created_at": "2026-11-05T10:00:00.000000",
            "delivery_needed": False,
            "amount_cents": amount_cents,
            "currency": currency,
            "merchant_order_id": merchant_order_id,
            "paid_amount_cents": amount_cents if paid else 0,
            "payment_status": "PAID" if paid else "UNPAID",
            "items": [
                {
                    "name": "Credit pack",
                    "description": "100 credits",
                    "amount_cents": amount_cents,
                    "quantity": 1,
                }
            ],
        },
        "created_at": "2026-11-05T10:00:05.123456",
        "currency": currency,
        "source_data": {"type": source_type, "pan": "2346", "sub_type": "MasterCard", "tenure": None},
        "api_source": "OTHER",
        "is_void": is_void,
        "is_refund": is_refund,
        "error_occured": error_occured,
        "is_live": False,
        "refunded_amount_cents": refunded_amount_cents,
        "is_captured": False,
        "captured_amount": 0,
        "owner": 302852,
        "parent_transaction": None,
        "data": {
            "message": "Approved" if success else "Do not honour",
            "txn_response_code": "APPROVED" if success else "DECLINED",
            "acq_response_code": "00" if success else "05",
        },
    }


def token_obj(
    *,
    token_id: int = 15978654,
    order_id: str = "265715202",
    token: str = "3f22ce8a4e5b6c7d8e9f",
    masked_pan: str = "xxxx-xxxx-xxxx-2346",
    card_subtype: str = "MasterCard",
    email: str = "kiyedi3052@claspira.com",
) -> dict[str, Any]:
    """A card-token callback ``obj`` (research 02 §2.2, create-card-token sample)."""
    return {
        "id": token_id,
        "token": token,
        "masked_pan": masked_pan,
        "merchant_id": 1053928,
        "card_subtype": card_subtype,
        "created_at": "2026-08-24T13:28:31.015314",
        "email": email,
        "order_id": order_id,
        "user_added": False,
        "next_payment_intention": "pi_test_0001",
        "cardholder_name": "TEST ACCOUNT",
        "expiry_month": "01",
        "expiry_year": "39",
    }


def transaction_callback(obj: dict[str, Any]) -> dict[str, Any]:
    return {"type": "TRANSACTION", "obj": obj}


def token_callback(obj: dict[str, Any]) -> dict[str, Any]:
    return {"type": "TOKEN", "obj": obj}


def sign_transaction(obj: dict[str, Any], secret: str = TEST_HMAC_SECRET) -> str:
    return sign(transaction_hmac_message(obj), secret)


def sign_token(obj: dict[str, Any], secret: str = TEST_HMAC_SECRET) -> str:
    return sign(token_hmac_message(obj), secret)
```

- [ ] **Step 2: Write the failing HMAC test**

Create `tests/test_paymob_hmac.py`:

```python
"""Paymob callback HMACs (research 02 §2; spec §9 "HMAC" unit tests)."""

from __future__ import annotations

import hashlib
import hmac as std_hmac
import re

import pytest

from lemely.io.paymob.hmac import (
    TOKEN_HMAC_FIELDS,
    TRANSACTION_HMAC_FIELDS,
    sign,
    subscription_hmac_message,
    token_hmac_message,
    transaction_hmac_message,
    verify_subscription_hmac,
    verify_token_hmac,
    verify_transaction_hmac,
)
from tests.paymob_fixtures import TEST_HMAC_SECRET, token_obj, transaction_obj

#: The docs' worked example (DOC-HMAC): field values and their concatenation.
DOCS_OBJ = {
    "amount_cents": 100000,
    "created_at": "2024-06-13T11:33:44.592345",
    "currency": "EGP",
    "error_occured": False,
    "has_parent_transaction": False,
    "id": 192036465,
    "integration_id": 4097558,
    "is_3d_secure": True,
    "is_auth": False,
    "is_capture": False,
    "is_refunded": False,
    "is_standalone_payment": True,
    "is_voided": False,
    "order": {"id": 217503754},
    "owner": 302852,
    "pending": False,
    "source_data": {"pan": "2346", "sub_type": "MasterCard", "type": "card"},
    "success": True,
}
DOCS_MESSAGE = (
    "1000002024-06-13T11:33:44.592345EGPfalsefalse1920364654097558truefalsefalsefalse"
    "truefalse217503754302852false2346MasterCardcardtrue"
)
#: The docs' sample digest. Its secret is unpublished, so it only pins the format.
DOCS_DIGEST = (
    "fa8ac0b7f3852e60c50e7fdd4ea5ef0bda96030c19dea1d55df8c76d6c08ab18"
    "77774662cbb04981dc84839ad4da560bcc8cb53b8973548657f7e8f8d2e79930"
)


def test_field_order_is_the_documented_lexicographic_list() -> None:
    assert TRANSACTION_HMAC_FIELDS == (
        "amount_cents",
        "created_at",
        "currency",
        "error_occured",
        "has_parent_transaction",
        "id",
        "integration_id",
        "is_3d_secure",
        "is_auth",
        "is_capture",
        "is_refunded",
        "is_standalone_payment",
        "is_voided",
        "order.id",
        "owner",
        "pending",
        "source_data.pan",
        "source_data.sub_type",
        "source_data.type",
        "success",
    )
    assert TOKEN_HMAC_FIELDS == (
        "card_subtype",
        "created_at",
        "email",
        "id",
        "masked_pan",
        "merchant_id",
        "order_id",
        "token",
    )


def test_the_docs_worked_example_concatenates_exactly() -> None:
    assert transaction_hmac_message(DOCS_OBJ) == DOCS_MESSAGE


def test_sign_is_hmac_sha512_lowercase_hex_like_the_docs_digest() -> None:
    digest = sign(DOCS_MESSAGE, TEST_HMAC_SECRET)
    expected = std_hmac.new(
        TEST_HMAC_SECRET.encode(), DOCS_MESSAGE.encode(), hashlib.sha512
    ).hexdigest()
    assert digest == expected
    assert re.fullmatch(r"[0-9a-f]{128}", digest)
    assert re.fullmatch(r"[0-9a-f]{128}", DOCS_DIGEST)


def test_a_correct_signature_verifies() -> None:
    received = sign(DOCS_MESSAGE, TEST_HMAC_SECRET)
    assert verify_transaction_hmac(DOCS_OBJ, received, TEST_HMAC_SECRET) is True


def test_uppercase_and_padded_hex_still_verifies() -> None:
    received = "  " + sign(DOCS_MESSAGE, TEST_HMAC_SECRET).upper() + "\n"
    assert verify_transaction_hmac(DOCS_OBJ, received, TEST_HMAC_SECRET) is True


@pytest.mark.parametrize(
    ("field", "value"),
    [("amount_cents", 100001), ("success", False), ("pending", True), ("currency", "USD")],
)
def test_any_tampered_field_fails(field: str, value: object) -> None:
    received = sign(DOCS_MESSAGE, TEST_HMAC_SECRET)
    assert verify_transaction_hmac({**DOCS_OBJ, field: value}, received, TEST_HMAC_SECRET) is False


def test_a_tampered_order_id_fails() -> None:
    received = sign(DOCS_MESSAGE, TEST_HMAC_SECRET)
    tampered = {**DOCS_OBJ, "order": {"id": 1}}
    assert verify_transaction_hmac(tampered, received, TEST_HMAC_SECRET) is False


@pytest.mark.parametrize("received", ["", "abc", "0" * 128, "z" * 128, "é" * 128])
def test_missing_short_wrong_or_non_hex_signatures_fail(received: str) -> None:
    assert verify_transaction_hmac(DOCS_OBJ, received, TEST_HMAC_SECRET) is False


def test_the_wrong_secret_fails() -> None:
    received = sign(DOCS_MESSAGE, "another-secret")
    assert verify_transaction_hmac(DOCS_OBJ, received, TEST_HMAC_SECRET) is False


def test_an_empty_secret_never_verifies() -> None:
    assert verify_transaction_hmac(DOCS_OBJ, sign(DOCS_MESSAGE, ""), "") is False


def test_none_becomes_empty_string_and_wallet_shaped_source_data_works() -> None:
    wallet = {
        **DOCS_OBJ,
        "source_data": {"type": "wallet", "pan": "01010101010", "sub_type": None},
    }
    message = transaction_hmac_message(wallet)
    assert message.endswith("false01010101010wallettrue")
    assert "None" not in message
    assert verify_transaction_hmac(wallet, sign(message, TEST_HMAC_SECRET), TEST_HMAC_SECRET)


def test_absent_nested_objects_contribute_empty_strings() -> None:
    bare = {k: v for k, v in DOCS_OBJ.items() if k not in {"source_data", "order"}}
    message = transaction_hmac_message(bare)
    # is_standalone(true) is_voided(false) order.id("") owner pending(false) 3x"" success
    assert message.endswith("truefalse302852falsetrue")


def test_the_shared_fixture_round_trips() -> None:
    obj = transaction_obj(merchant_order_id="ref-1")
    assert verify_transaction_hmac(obj, sign(transaction_hmac_message(obj), "s"), "s")


def test_token_message_matches_the_docs_sample_prefix() -> None:
    obj = token_obj(token="3f22ce8a4e", order_id="593881581")
    assert token_hmac_message(obj) == (
        "MasterCard2026-08-24T13:28:31.015314kiyedi3052@claspira.com15978654"
        "xxxx-xxxx-xxxx-234610539285938815813f22ce8a4e"
    )


def test_token_signature_verifies_and_detects_a_swapped_token() -> None:
    obj = token_obj()
    received = sign(token_hmac_message(obj), TEST_HMAC_SECRET)
    assert verify_token_hmac(obj, received, TEST_HMAC_SECRET) is True
    assert verify_token_hmac({**obj, "token": "other"}, received, TEST_HMAC_SECRET) is False


def test_subscription_message_is_trigger_for_id() -> None:
    assert subscription_hmac_message("suspended", 1264) == "suspendedfor1264"
    assert subscription_hmac_message("Successful Transaction", 1264) == (
        "Successful Transactionfor1264"
    )


def test_subscription_signature_verifies_and_binds_the_trigger() -> None:
    received = sign("suspendedfor1264", TEST_HMAC_SECRET)
    assert verify_subscription_hmac("suspended", 1264, received, TEST_HMAC_SECRET) is True
    assert verify_subscription_hmac("resumed", 1264, received, TEST_HMAC_SECRET) is False
    assert verify_subscription_hmac("suspended", 1265, received, TEST_HMAC_SECRET) is False
```

- [ ] **Step 3: Run it to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_paymob_hmac.py -v --no-cov`
Expected: collection error, `ModuleNotFoundError: No module named 'lemely.io.paymob'`.

- [ ] **Step 4: Implement**

Create `lemely/io/paymob/__init__.py`:

```python
"""Paymob (Egypt) payment gateway adapter: HTTP client and callback HMACs (billing spec §3)."""
```

Create `lemely/io/paymob/hmac.py`:

```python
"""Pure verification of Paymob callback HMACs (billing spec §3; research 02 §2).

All three are HMAC-SHA512 under the account HMAC secret, hex digest, compared in
constant time:

* **Transaction** callbacks: the values of 20 fixed keys of ``obj``, concatenated
  with no separator in the documented (lexicographic) order; ``hmac`` arrives in
  the query string.
* **Card-token** callbacks: 8 fixed keys of ``obj``, same rules.
* **Subscription** callbacks: the string ``"{trigger_type}for{subscription id}"``;
  ``hmac`` arrives in the body. It covers neither amount nor state, so callers
  re-fetch from Paymob before acting (spec §5.2).

Stringification follows every reference implementation (research 02 §2.1):
``None`` -> ``""``, booleans -> ``"true"``/``"false"``, everything else ``str()``
with no reformatting (``created_at`` is used verbatim). A missing nested object
(wallet callbacks can omit ``source_data`` fields) contributes empty strings.
"""

from __future__ import annotations

import hashlib
import hmac as std_hmac
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

TRANSACTION_HMAC_FIELDS: Final[tuple[str, ...]] = (
    "amount_cents",
    "created_at",
    "currency",
    "error_occured",
    "has_parent_transaction",
    "id",
    "integration_id",
    "is_3d_secure",
    "is_auth",
    "is_capture",
    "is_refunded",
    "is_standalone_payment",
    "is_voided",
    "order.id",
    "owner",
    "pending",
    "source_data.pan",
    "source_data.sub_type",
    "source_data.type",
    "success",
)

TOKEN_HMAC_FIELDS: Final[tuple[str, ...]] = (
    "card_subtype",
    "created_at",
    "email",
    "id",
    "masked_pan",
    "merchant_id",
    "order_id",
    "token",
)


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _lookup(obj: Mapping[str, Any], dotted: str) -> object:
    current: object = obj
    for part in dotted.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _message(obj: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    return "".join(_stringify(_lookup(dict(obj), field)) for field in fields)


def transaction_hmac_message(obj: Mapping[str, Any]) -> str:
    """The string Paymob signs for a transaction callback ``obj``."""
    return _message(obj, TRANSACTION_HMAC_FIELDS)


def token_hmac_message(obj: Mapping[str, Any]) -> str:
    """The string Paymob signs for a card-token callback ``obj``."""
    return _message(obj, TOKEN_HMAC_FIELDS)


def subscription_hmac_message(trigger_type: str, sub_id: int) -> str:
    """The string Paymob signs for a subscription callback."""
    return f"{trigger_type}for{sub_id}"


def sign(message: str, secret: str) -> str:
    """HMAC-SHA512 of ``message`` under ``secret``, lowercase hex."""
    return std_hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha512).hexdigest()


def _matches(message: str, received: str, secret: str) -> bool:
    if not secret or not received:
        return False
    expected = sign(message, secret).encode("ascii")
    return std_hmac.compare_digest(expected, received.strip().lower().encode("utf-8"))


def verify_transaction_hmac(obj: Mapping[str, Any], received: str, secret: str) -> bool:
    """True when ``received`` is Paymob's signature of transaction ``obj``."""
    return _matches(transaction_hmac_message(obj), received, secret)


def verify_token_hmac(obj: Mapping[str, Any], received: str, secret: str) -> bool:
    """True when ``received`` is Paymob's signature of card-token ``obj``."""
    return _matches(token_hmac_message(obj), received, secret)


def verify_subscription_hmac(trigger_type: str, sub_id: int, received: str, secret: str) -> bool:
    """True when ``received`` is Paymob's signature of a subscription callback."""
    return _matches(subscription_hmac_message(trigger_type, sub_id), received, secret)


__all__ = [
    "TOKEN_HMAC_FIELDS",
    "TRANSACTION_HMAC_FIELDS",
    "sign",
    "subscription_hmac_message",
    "token_hmac_message",
    "transaction_hmac_message",
    "verify_subscription_hmac",
    "verify_token_hmac",
    "verify_transaction_hmac",
]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_paymob_hmac.py tests/architecture/ -v --no-cov`
Expected: all PASS.

- [ ] **Step 6: Pre-commit and commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/io/paymob/__init__.py lemely/io/paymob/hmac.py tests/paymob_fixtures.py tests/test_paymob_hmac.py
git commit -S -m "feat(paymob): verify transaction, card-token and subscription callback HMACs" -- lemely/io/paymob/__init__.py lemely/io/paymob/hmac.py tests/paymob_fixtures.py tests/test_paymob_hmac.py
```

---

### Task 4: Paymob HTTP client

**Files:**
- Create: `lemely/io/paymob/client.py`
- Modify: `tests/paymob_fixtures.py` (append response payloads)
- Test: `tests/test_paymob_client.py`

**Interfaces:**
- Consumes: `PaymobSettings` (Task 1); `lemely.runtime.errors.ExternalServiceError`.
- Produces (in `lemely.io.paymob.client`):
  - `PaymobError(ExternalServiceError)` with attributes `status_code: int | None`, `timeout: bool`, `body: dict[str, Any]`.
  - `PaymobNotConfigured(PaymobError)`.
  - `SUBSCRIPTION_FREQUENCIES: frozenset[int]`.
  - `PaymobClient(settings: PaymobSettings, *, http: httpx.Client | None = None, clock: Callable[[], float] = time.monotonic)` with these methods:
    - `create_intention(body: Mapping[str, Any]) -> dict[str, Any]`
    - `inquire_by_order_ref(merchant_order_id: str) -> dict[str, Any] | None`
    - `inquire_by_transaction(transaction_id: int) -> dict[str, Any] | None`
    - `refund(*, transaction_id: int, amount_cents: int) -> dict[str, Any]`
    - `void(*, transaction_id: int) -> dict[str, Any]`
    - `create_plan(*, name: str, frequency_days: int, amount_cents: int, integration_id: int, webhook_url: str, retrial_days: int | None = None, reminder_days: int | None = None, use_transaction_amount: bool = False) -> dict[str, Any]`
    - `get_subscription(subscription_id: int) -> dict[str, Any]`
    - `update_subscription(subscription_id: int, *, amount_cents: int | None = None, ends_at: str | None = None, next_billing: str | None = None) -> dict[str, Any]`
    - `suspend_subscription(subscription_id: int) -> dict[str, Any]`
    - `resume_subscription(subscription_id: int) -> dict[str, Any]`
    - `cancel_subscription(subscription_id: int) -> dict[str, Any]`
    - `last_transaction(subscription_id: int) -> dict[str, Any]`
    - `pay_with_token(*, card_token: str, payment_token: str) -> dict[str, Any]`
    - `close() -> None`
- Produces (test helpers): `INTENTION_RESPONSE`, `AUTH_TOKEN_RESPONSE`, `SUBSCRIPTION_RESPONSE`, `PLAN_RESPONSE`.

- [ ] **Step 1: Append response payloads to `tests/paymob_fixtures.py`**

Append to the end of `tests/paymob_fixtures.py`:

```python
#: ``POST v1/intention/`` 201 body (research 01 §2.1 sample, with our test ids).
INTENTION_RESPONSE: dict[str, Any] = {
    "payment_keys": [
        {
            "integration": CARD_INTEGRATION_ID,
            "key": "ZXlKaGJHY2lPaUpJVXpVeE1pSjkuZXlKMWMyVnlYMmxrSWpveE1EVXpPVEk0ZlE.payment-key",
            "gateway_type": "MIGS",
            "iframe_id": None,
            "order_id": 265715202,
        }
    ],
    "intention_order_id": 265715202,
    "id": "pi_test_bd49bb7fb4da48cfac4ec71ab4d8c433",
    "intention_detail": {
        "amount": 10000,
        "items": [{"name": "Credit pack", "amount": 10000, "description": "100 credits", "quantity": 1}],
        "currency": "EGP",
        "billing_data": {
            "apartment": "NA",
            "floor": "NA",
            "first_name": "Sara",
            "last_name": "Ali",
            "street": "NA",
            "building": "NA",
            "phone_number": "+201234567890",
            "shipping_method": None,
            "city": "NA",
            "country": "EGY",
            "state": "NA",
            "email": "payer@example.com",
            "postal_code": None,
        },
    },
    "client_secret": "egy_csk_test_94042f793419c5a0f14a4cadfda9d626",
    "payment_methods": [
        {
            "integration_id": CARD_INTEGRATION_ID,
            "alias": None,
            "name": "Card",
            "method_type": "online",
            "currency": "EGP",
            "live": False,
            "use_cvc_with_moto": False,
        }
    ],
    "special_reference": "set-per-test",
    "extras": {"creation_extras": {}, "confirmation_extras": None},
    "confirmed": False,
    "status": "intended",
    "created": "2026-11-05T10:00:00.000000",
    "card_detail": None,
    "card_tokens": [],
    "object": "paymentintention",
}

#: ``POST api/auth/tokens`` body, trimmed (the real one carries the merchant profile).
AUTH_TOKEN_RESPONSE: dict[str, Any] = {"token": "auth_token_test_1", "profile": {"id": 302852}}

#: ``GET api/acceptance/subscriptions/{id}`` (research 02 §2.3/§6 field list).
SUBSCRIPTION_RESPONSE: dict[str, Any] = {
    "id": 1264,
    "client_info": {"email": "payer@example.com", "full_name": "Sara Ali", "phone_number": "+201234567890"},
    "frequency": 30,
    "created_at": "2026-11-05T10:00:00",
    "updated_at": "2026-11-05T10:00:00",
    "name": "Student monthly",
    "reminder_days": None,
    "retrial_days": 3,
    "plan_id": 1186,
    "state": "active",
    "amount_cents": 9900,
    "starts_at": "2026-11-05",
    "next_billing": "2026-12-05",
    "reminder_date": None,
    "ends_at": None,
    "resumed_at": None,
    "suspended_at": None,
    "webhook_url": "https://lemelyig.com/api/webhooks/paymob/subscription",
    "integration": MOTO_INTEGRATION_ID,
    "initial_transaction": 241322967,
}

#: ``POST api/acceptance/subscription-plans`` body.
PLAN_RESPONSE: dict[str, Any] = {
    "id": 1186,
    "frequency": 30,
    "name": "Student monthly",
    "reminder_days": None,
    "retrial_days": 3,
    "plan_type": "rent",
    "number_of_deductions": None,
    "amount_cents": 9900,
    "use_transaction_amount": False,
    "is_active": True,
    "webhook_url": "https://lemelyig.com/api/webhooks/paymob/subscription",
    "integration": MOTO_INTEGRATION_ID,
    "fee": None,
}
```

- [ ] **Step 2: Write the failing client test**

Create `tests/test_paymob_client.py`:

```python
"""PaymobClient against handwritten fixtures through httpx.MockTransport (spec §3)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from lemely.io.paymob.client import PaymobClient, PaymobError, PaymobNotConfigured
from lemely.runtime.config import PaymobSettings
from tests.paymob_fixtures import (
    AUTH_TOKEN_RESPONSE,
    INTENTION_RESPONSE,
    PAYMOB_SETTINGS,
    PLAN_RESPONSE,
    SUBSCRIPTION_RESPONSE,
    transaction_obj,
)

if TYPE_CHECKING:
    from collections.abc import Callable

BASE = "https://accept.paymob.com"


class Recorder:
    """Route table for MockTransport: (method, path) -> (status, json body)."""

    def __init__(self, routes: dict[tuple[str, str], tuple[int, Any]]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.path)
        if key not in self.routes:
            return httpx.Response(599, json={"detail": f"unrouted {key}"})
        status, body = self.routes[key]
        return httpx.Response(status, json=body)

    def bodies(self, path: str) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.url.path == path]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


AUTH = ("POST", "/api/auth/tokens")


def _client(
    routes: dict[tuple[str, str], tuple[int, Any]],
    *,
    settings: PaymobSettings = PAYMOB_SETTINGS,
    clock: Callable[[], float] | None = None,
) -> tuple[PaymobClient, Recorder]:
    recorder = Recorder({AUTH: (200, AUTH_TOKEN_RESPONSE), **routes})
    client = PaymobClient(
        settings,
        http=httpx.Client(transport=httpx.MockTransport(recorder)),
        clock=clock or Clock(),
    )
    return client, recorder


def test_create_intention_posts_with_the_secret_key_token_header() -> None:
    client, rec = _client({("POST", "/v1/intention/"): (201, INTENTION_RESPONSE)})
    body = {"amount": 10000, "currency": "EGP", "payment_methods": [4569876]}
    response = client.create_intention(body)
    assert response["client_secret"] == INTENTION_RESPONSE["client_secret"]
    (request,) = rec.requests
    assert str(request.url) == f"{BASE}/v1/intention/"
    assert request.headers["authorization"] == "Token egy_sk_test_secret"
    assert json.loads(request.content) == body


def test_unconfigured_secret_key_fails_before_any_request() -> None:
    client, rec = _client({}, settings=PaymobSettings())
    with pytest.raises(PaymobNotConfigured):
        client.create_intention({"amount": 1})
    with pytest.raises(PaymobNotConfigured):
        client.inquire_by_order_ref("ref")
    assert rec.requests == []


def test_inquiry_by_reference_sends_the_auth_token_in_body_and_header() -> None:
    path = "/api/ecommerce/orders/transaction_inquiry"
    obj = transaction_obj(merchant_order_id="ref-1")
    client, rec = _client({("POST", path): (200, obj)})
    assert client.inquire_by_order_ref("ref-1") == obj
    assert rec.bodies("/api/auth/tokens") == [{"api_key": "api_key_test"}]
    assert rec.bodies(path) == [{"auth_token": "auth_token_test_1", "merchant_order_id": "ref-1"}]
    inquiry = rec.requests[-1]
    assert inquiry.headers["authorization"] == "Bearer auth_token_test_1"


def test_inquiry_by_reference_404_means_no_transaction_yet() -> None:
    path = "/api/ecommerce/orders/transaction_inquiry"
    client, _ = _client({("POST", path): (404, {"detail": "Not found."})})
    assert client.inquire_by_order_ref("ref-1") is None


def test_inquiry_by_transaction_id() -> None:
    obj = transaction_obj(txn_id=77)
    client, rec = _client({("GET", "/api/acceptance/transactions/77"): (200, obj)})
    assert client.inquire_by_transaction(77) == obj
    assert rec.requests[-1].headers["authorization"] == "Bearer auth_token_test_1"


def test_the_auth_token_is_cached_under_an_hour_then_renewed() -> None:
    clock = Clock()
    path = "/api/ecommerce/orders/transaction_inquiry"
    client, rec = _client({("POST", path): (200, transaction_obj())}, clock=clock)
    client.inquire_by_order_ref("a")
    clock.now += 49 * 60
    client.inquire_by_order_ref("b")
    assert len(rec.bodies("/api/auth/tokens")) == 1
    clock.now += 2 * 60
    client.inquire_by_order_ref("c")
    assert len(rec.bodies("/api/auth/tokens")) == 2


def test_a_401_on_a_bearer_call_drops_the_cached_token() -> None:
    path = "/api/acceptance/subscriptions/1264"
    client, rec = _client({("GET", path): (401, {"detail": "incorrect credentials"})})
    with pytest.raises(PaymobError) as caught:
        client.get_subscription(1264)
    assert caught.value.status_code == 401
    rec.routes[("GET", path)] = (200, SUBSCRIPTION_RESPONSE)
    assert client.get_subscription(1264)["id"] == 1264
    assert len(rec.bodies("/api/auth/tokens")) == 2


def test_refund_and_void_use_the_secret_key() -> None:
    client, rec = _client(
        {
            ("POST", "/api/acceptance/void_refund/refund"): (200, transaction_obj(is_refund=True)),
            ("POST", "/api/acceptance/void_refund/void"): (200, transaction_obj(is_void=True)),
        }
    )
    client.refund(transaction_id=192036465, amount_cents=4000)
    client.void(transaction_id=192036465)
    assert rec.bodies("/api/acceptance/void_refund/refund") == [
        {"transaction_id": 192036465, "amount_cents": 4000}
    ]
    assert rec.bodies("/api/acceptance/void_refund/void") == [{"transaction_id": 192036465}]
    assert all(r.headers["authorization"] == "Token egy_sk_test_secret" for r in rec.requests)


def test_an_error_status_raises_with_code_and_body_but_no_secret() -> None:
    error = {"message": "Requested Refund Amount is greater than the maximum refund amount"}
    client, _ = _client({("POST", "/api/acceptance/void_refund/refund"): (400, error)})
    with pytest.raises(PaymobError) as caught:
        client.refund(transaction_id=1, amount_cents=99999)
    assert caught.value.status_code == 400
    assert caught.value.body == error
    assert caught.value.timeout is False
    assert "egy_sk_test_secret" not in str(caught.value)


def test_a_timeout_is_flagged_so_callers_inquire_instead_of_retrying() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = PaymobClient(PAYMOB_SETTINGS, http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(PaymobError) as caught:
        client.create_intention({"amount": 1})
    assert caught.value.timeout is True
    assert caught.value.status_code is None


def test_a_network_failure_is_a_paymob_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = PaymobClient(PAYMOB_SETTINGS, http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(PaymobError) as caught:
        client.void(transaction_id=1)
    assert caught.value.timeout is False


def test_create_plan_posts_the_documented_body() -> None:
    path = "/api/acceptance/subscription-plans"
    client, rec = _client({("POST", path): (201, PLAN_RESPONSE)})
    plan = client.create_plan(
        name="Student monthly",
        frequency_days=30,
        amount_cents=9900,
        integration_id=4569877,
        webhook_url="https://lemelyig.com/api/webhooks/paymob/subscription",
        retrial_days=3,
    )
    assert plan["id"] == 1186
    assert rec.bodies(path) == [
        {
            "frequency": 30,
            "name": "Student monthly",
            "integration": 4569877,
            "amount_cents": 9900,
            "webhook_url": "https://lemelyig.com/api/webhooks/paymob/subscription",
            "use_transaction_amount": False,
            "plan_type": "rent",
            "is_active": True,
            "number_of_deductions": None,
            "reminder_days": None,
            "retrial_days": 3,
        }
    ]
    assert rec.requests[-1].headers["authorization"] == "Bearer auth_token_test_1"


def test_create_plan_refuses_an_undocumented_frequency_without_calling() -> None:
    client, rec = _client({})
    with pytest.raises(ValueError, match="frequency"):
        client.create_plan(
            name="x", frequency_days=31, amount_cents=1, integration_id=1, webhook_url="https://x.y"
        )
    assert rec.requests == []


@pytest.mark.parametrize(
    ("call", "method", "path"),
    [
        (lambda c: c.get_subscription(1264), "GET", "/api/acceptance/subscriptions/1264"),
        (lambda c: c.suspend_subscription(1264), "POST", "/api/acceptance/subscriptions/1264/suspend"),
        (lambda c: c.resume_subscription(1264), "POST", "/api/acceptance/subscriptions/1264/resume"),
        (lambda c: c.cancel_subscription(1264), "POST", "/api/acceptance/subscriptions/1264/cancel"),
        (
            lambda c: c.last_transaction(1264),
            "GET",
            "/api/acceptance/subscriptions/1264/last-transaction",
        ),
    ],
)
def test_subscription_actions_hit_the_documented_paths(
    call: Callable[[PaymobClient], dict[str, Any]], method: str, path: str
) -> None:
    client, rec = _client({(method, path): (200, SUBSCRIPTION_RESPONSE)})
    assert call(client)["id"] == 1264
    assert (rec.requests[-1].method, rec.requests[-1].url.path) == (method, path)
    assert rec.requests[-1].headers["authorization"] == "Bearer auth_token_test_1"


def test_update_subscription_sends_only_the_given_fields() -> None:
    path = "/api/acceptance/subscriptions/1264"
    client, rec = _client({("PUT", path): (200, SUBSCRIPTION_RESPONSE)})
    client.update_subscription(1264, amount_cents=12900)
    assert rec.bodies(path) == [{"amount_cents": 12900}]


def test_update_subscription_with_nothing_to_change_is_refused() -> None:
    client, rec = _client({})
    with pytest.raises(ValueError, match="nothing to update"):
        client.update_subscription(1264)
    assert rec.requests == []


def test_pay_with_token_sends_the_mit_body_with_no_auth_header() -> None:
    path = "/api/acceptance/payments/pay"
    client, rec = _client({("POST", path): (200, transaction_obj())})
    client.pay_with_token(card_token="tok_abc", payment_token="pk_abc")
    assert rec.bodies(path) == [
        {"source": {"identifier": "tok_abc", "subtype": "TOKEN"}, "payment_token": "pk_abc"}
    ]
    assert "authorization" not in rec.requests[-1].headers


def test_an_empty_success_body_is_an_empty_dict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/tokens":
            return httpx.Response(200, json=AUTH_TOKEN_RESPONSE)
        return httpx.Response(200, content=b"")

    client = PaymobClient(PAYMOB_SETTINGS, http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.cancel_subscription(1264) == {}
```

- [ ] **Step 3: Run it to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_paymob_client.py -v --no-cov`
Expected: collection error, `ModuleNotFoundError: No module named 'lemely.io.paymob.client'`.

- [ ] **Step 4: Implement**

Create `lemely/io/paymob/client.py`:

```python
"""Thin ``httpx`` client for the Paymob Egypt APIs (billing spec §3).

No business logic: it builds requests, authenticates them and turns transport
failures and error statuses into :class:`PaymobError`. Callers decide what a
result means.

Three auth styles exist across the API (research 01 §1.3), and each method uses
the one Paymob documents for it:

* ``Authorization: Token <secret key>``: create intention, refund, void.
* ``Authorization: Bearer <auth token>``: inquiry, subscription plans and
  subscriptions. The token comes from ``POST api/auth/tokens`` with the API key,
  lives one hour, and is cached here for 50 minutes; a 401 drops the cache.
* None: ``POST api/acceptance/payments/pay`` (the payment token in the body
  authorises it).

**Never retried.** Paymob has no idempotency keys (research 02 §8). A timeout is
raised with ``timeout=True`` so the caller inquires before doing anything else
(spec §6). Error messages carry method, path and status only, never a key or a
request body.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, Final

import httpx

from lemely.runtime.errors import ExternalServiceError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from lemely.runtime.config import PaymobSettings

#: Plan frequencies (days) Paymob accepts (research 02 §6).
SUBSCRIPTION_FREQUENCIES: Final[frozenset[int]] = frozenset({7, 15, 30, 60, 90, 180, 360})
#: The auth token lives an hour; renew well before.
AUTH_TOKEN_TTL_SECONDS: Final = 50 * 60


class PaymobError(ExternalServiceError):
    """A Paymob call failed: transport error, timeout or error status."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        timeout: bool = False,
        body: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.timeout = timeout
        self.body: dict[str, Any] = dict(body or {})


class PaymobNotConfigured(PaymobError):
    """A credential this call needs is not set (see ``PaymobSettings``)."""


class PaymobClient:
    """One process-wide client; thread-safe for the auth-token cache."""

    def __init__(
        self,
        settings: PaymobSettings,
        *,
        http: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._http = http if http is not None else httpx.Client(timeout=settings.timeout_seconds)
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._lock = threading.Lock()

    # -- plumbing -------------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def _url(self, path: str) -> str:
        return f"{self._settings.api_base}/{path.lstrip('/')}"

    def _secret_header(self) -> dict[str, str]:
        if self._settings.secret_key is None:
            raise PaymobNotConfigured("Paymob secret key is not configured")
        return {"Authorization": f"Token {self._settings.secret_key.get_secret_value()}"}

    def _auth_token(self) -> str:
        with self._lock:
            now = self._clock()
            if self._token is not None and now < self._token_expires_at:
                return self._token
            if self._settings.api_key is None:
                raise PaymobNotConfigured("Paymob API key is not configured")
            data = self._request(
                "POST",
                "api/auth/tokens",
                headers={},
                json={"api_key": self._settings.api_key.get_secret_value()},
            )
            token = data.get("token")
            if not isinstance(token, str) or not token:
                raise PaymobError("Paymob auth response carried no token")
            self._token = token
            self._token_expires_at = now + AUTH_TOKEN_TTL_SECONDS
            return token

    def _bearer_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._auth_token()}"}

    def _send(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, Any] | None = None,
        allow_404: bool = False,
    ) -> dict[str, Any] | None:
        try:
            response = self._http.request(
                method,
                self._url(path),
                headers=dict(headers),
                json=dict(json) if json is not None else None,
                timeout=self._settings.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise PaymobError(f"Paymob {method} {path} timed out", timeout=True) from exc
        except httpx.HTTPError as exc:
            raise PaymobError(f"Paymob {method} {path} failed: {type(exc).__name__}") from exc
        if allow_404 and response.status_code == 404:
            return None
        if response.status_code == 401 and headers.get("Authorization", "").startswith("Bearer "):
            self._token = None
        try:
            body: object = response.json() if response.content else {}
        except ValueError:
            body = {}
        if response.status_code >= 400:
            raise PaymobError(
                f"Paymob {method} {path} returned {response.status_code}",
                status_code=response.status_code,
                body=body if isinstance(body, dict) else None,
            )
        if not isinstance(body, dict):
            raise PaymobError(f"Paymob {method} {path} returned a non-object body")
        return body

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self._send(method, path, headers=headers, json=json)
        if result is None:  # only possible with allow_404, never passed here
            raise PaymobError(f"Paymob {method} {path} returned 404", status_code=404)
        return result

    # -- intentions -----------------------------------------------------------

    def create_intention(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """``POST v1/intention/`` (one-off, or with ``subscription_plan_id``)."""
        return self._request("POST", "v1/intention/", headers=self._secret_header(), json=body)

    # -- inquiry --------------------------------------------------------------

    def inquire_by_order_ref(self, merchant_order_id: str) -> dict[str, Any] | None:
        """Last transaction for our ``special_reference``; ``None`` when there is none."""
        token = self._auth_token()
        return self._send(
            "POST",
            "api/ecommerce/orders/transaction_inquiry",
            headers={"Authorization": f"Bearer {token}"},
            json={"auth_token": token, "merchant_order_id": merchant_order_id},
            allow_404=True,
        )

    def inquire_by_transaction(self, transaction_id: int) -> dict[str, Any] | None:
        """``GET api/acceptance/transactions/{id}``; ``None`` when unknown."""
        return self._send(
            "GET",
            f"api/acceptance/transactions/{int(transaction_id)}",
            headers=self._bearer_header(),
            allow_404=True,
        )

    # -- refund / void --------------------------------------------------------

    def refund(self, *, transaction_id: int, amount_cents: int) -> dict[str, Any]:
        return self._request(
            "POST",
            "api/acceptance/void_refund/refund",
            headers=self._secret_header(),
            json={"transaction_id": int(transaction_id), "amount_cents": int(amount_cents)},
        )

    def void(self, *, transaction_id: int) -> dict[str, Any]:
        return self._request(
            "POST",
            "api/acceptance/void_refund/void",
            headers=self._secret_header(),
            json={"transaction_id": int(transaction_id)},
        )

    # -- subscriptions --------------------------------------------------------

    def create_plan(
        self,
        *,
        name: str,
        frequency_days: int,
        amount_cents: int,
        integration_id: int,
        webhook_url: str,
        retrial_days: int | None = None,
        reminder_days: int | None = None,
        use_transaction_amount: bool = False,
    ) -> dict[str, Any]:
        """``POST api/acceptance/subscription-plans`` (``integration`` must be MOTO)."""
        if frequency_days not in SUBSCRIPTION_FREQUENCIES:
            raise ValueError(
                f"frequency {frequency_days} is not one of {sorted(SUBSCRIPTION_FREQUENCIES)}"
            )
        body = {
            "frequency": frequency_days,
            "name": name[:200],
            "integration": int(integration_id),
            "amount_cents": int(amount_cents),
            "webhook_url": webhook_url,
            "use_transaction_amount": use_transaction_amount,
            "plan_type": "rent",
            "is_active": True,
            "number_of_deductions": None,
            "reminder_days": reminder_days,
            "retrial_days": retrial_days,
        }
        return self._request(
            "POST", "api/acceptance/subscription-plans", headers=self._bearer_header(), json=body
        )

    def get_subscription(self, subscription_id: int) -> dict[str, Any]:
        return self._request(
            "GET",
            f"api/acceptance/subscriptions/{int(subscription_id)}",
            headers=self._bearer_header(),
        )

    def update_subscription(
        self,
        subscription_id: int,
        *,
        amount_cents: int | None = None,
        ends_at: str | None = None,
        next_billing: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if amount_cents is not None:
            body["amount_cents"] = int(amount_cents)
        if ends_at is not None:
            body["ends_at"] = ends_at
        if next_billing is not None:
            body["next_billing"] = next_billing
        if not body:
            raise ValueError("nothing to update on the subscription")
        return self._request(
            "PUT",
            f"api/acceptance/subscriptions/{int(subscription_id)}",
            headers=self._bearer_header(),
            json=body,
        )

    def _subscription_action(self, subscription_id: int, action: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"api/acceptance/subscriptions/{int(subscription_id)}/{action}",
            headers=self._bearer_header(),
        )

    def suspend_subscription(self, subscription_id: int) -> dict[str, Any]:
        return self._subscription_action(subscription_id, "suspend")

    def resume_subscription(self, subscription_id: int) -> dict[str, Any]:
        return self._subscription_action(subscription_id, "resume")

    def cancel_subscription(self, subscription_id: int) -> dict[str, Any]:
        return self._subscription_action(subscription_id, "cancel")

    def last_transaction(self, subscription_id: int) -> dict[str, Any]:
        return self._request(
            "GET",
            f"api/acceptance/subscriptions/{int(subscription_id)}/last-transaction",
            headers=self._bearer_header(),
        )

    # -- merchant-initiated (MOTO) --------------------------------------------

    def pay_with_token(self, *, card_token: str, payment_token: str) -> dict[str, Any]:
        """``POST api/acceptance/payments/pay`` with a saved-card token (research 02 §5)."""
        return self._request(
            "POST",
            "api/acceptance/payments/pay",
            headers={},
            json={
                "source": {"identifier": card_token, "subtype": "TOKEN"},
                "payment_token": payment_token,
            },
        )


__all__ = [
    "AUTH_TOKEN_TTL_SECONDS",
    "SUBSCRIPTION_FREQUENCIES",
    "PaymobClient",
    "PaymobError",
    "PaymobNotConfigured",
]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_paymob_client.py tests/test_paymob_hmac.py tests/architecture/ -v --no-cov`
Expected: all PASS.

- [ ] **Step 6: Pre-commit and commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/io/paymob/client.py tests/paymob_fixtures.py tests/test_paymob_client.py
git commit -S -m "feat(paymob): add the Paymob HTTP client for intentions, inquiry, refunds, subscriptions and MOTO" -- lemely/io/paymob/client.py tests/paymob_fixtures.py tests/test_paymob_client.py
```

---

### Task 5: Billing models and migration `0053_billing_payments`

**Files:**
- Modify: `lemely/db/models/enums.py` (`SubscriptionStatus`)
- Modify: `lemely/db/models/billing.py` (full replacement below)
- Modify: `lemely/db/models/usage.py` (`UsageGrant.payment_id` gains its FK)
- Create: `lemely/db/migrations/versions/0053_billing_payments.py`
- Test: `tests/test_migration_billing_payments.py`

**Interfaces:**
- Consumes: `UsageGrant` (Phase 01), `TimestampMixin`, `PlanInterval`, `SubscriptionStatus`.
- Produces (in `lemely.db.models.billing`):
  - Enums `PlanAudience` (`student`, `teacher`), `PaymentPurpose` (`subscription_first`, `subscription_renewal`, `upgrade_proration`, `extra_seats`, `credit_pack`, `auto_topup`), `PaymentStatus` (`created`, `pending`, `paid`, `failed`, `failed_mismatch`, `refunded`, `partially_refunded`, `voided`), `PaymobEventKind` (`transaction`, `token`, `subscription`).
  - Models `CreditPack`, `Payment`, `PaymobEvent`, `SavedCard`.
  - New `PlanTier` columns: `audience`, `allowance_units`, `paymob_plan_id`, `is_active`, `included_seats`, `seat_allowance_units`, `extra_seat_price_minor`.
  - New `Subscription` columns: `payer_user_id`, `cancel_at_period_end`, `pending_plan_tier_id`, `current_period_start`, `grace_until`, `extra_seats`, `pending_extra_seats`, `paymob_subscription_id`, `version`.
  - The constant `LIVE_SUBSCRIPTION_STATUSES: Final = (SubscriptionStatus.pending_first_payment, SubscriptionStatus.active, SubscriptionStatus.past_due)`. Phase 05 imports it and must not redefine it.
  - The index `uq_subscriptions_one_live_per_user` (index R8: only 0053 creates it).
  - `SubscriptionStatus.pending_first_payment` and `SubscriptionStatus.past_due`.

- [ ] **Step 1: Write the failing migration test**

Create `tests/test_migration_billing_payments.py`:

```python
"""Migration 0053_billing_payments: payments, events, saved cards, packs; catalogue columns.

Expected object names come from the ORM (``lemely/db/models/billing.py``), an
independent declaration of the same schema. The downgrade removes everything this
migration added except the two ``subscriptionstatus`` labels: Postgres cannot drop an
enum label, so rows holding them are moved to ``expired`` and the labels stay.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from lemely.db.base import Base
from lemely.db.models import import_all_models
from tests.test_migration_tutoring_enums import (
    column_names,
    current_revision,
    enum_labels,
    head_revision,
    object_names,
    public_tables,
    type_exists,
    upgrade_head,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0053_billing_payments"
DOWN_REVISION = "0052_usage_ledger"
NEW_TABLES = ("credit_packs", "payments", "paymob_events", "saved_cards")
NEW_TYPES = ("planaudience", "paymentpurpose", "paymentstatus", "paymobeventkind")
PLAN_TIER_COLUMNS = {
    "audience",
    "allowance_units",
    "paymob_plan_id",
    "is_active",
    "included_seats",
    "seat_allowance_units",
    "extra_seat_price_minor",
}
SUBSCRIPTION_COLUMNS = {
    "payer_user_id",
    "cancel_at_period_end",
    "pending_plan_tier_id",
    "current_period_start",
    "grace_until",
    "extra_seats",
    "pending_extra_seats",
    "paymob_subscription_id",
    "version",
}
PLAN_TIER_OBJECTS = {
    "uq_plan_tiers_paymob_plan_id",
    "ck_plan_tiers_allowance_nonneg",
    "ck_plan_tiers_seats_nonneg",
    "ck_plan_tiers_seat_allowance_nonneg",
    "ck_plan_tiers_extra_seat_price_nonneg",
}
SUBSCRIPTION_OBJECTS = {
    "fk_subscriptions_payer_user_id_users",
    "fk_subscriptions_pending_plan_tier_id_plan_tiers",
    "uq_subscriptions_paymob_subscription_id",
    "ck_subscriptions_extra_seats_nonneg",
    "ck_subscriptions_pending_extra_seats_nonneg",
    "uq_subscriptions_one_live_per_user",
}
GRANT_FK = "fk_usage_grants_payment_id_payments"


def _orm_names(table: str) -> set[str]:
    t = Base.metadata.tables[table]
    return {str(c.name) for c in t.constraints} | {str(i.name) for i in t.indexes}


def _seed_user(session: Session) -> uuid.UUID:
    uid = uuid.uuid4()
    session.execute(
        sa.text("INSERT INTO users (id, email, role) VALUES (:u, :e, 'student')"),
        {"u": uid, "e": f"{uid}@example.com"},
    )
    return uid


def _seed_tier(session: Session) -> uuid.UUID:
    return session.execute(
        sa.text("INSERT INTO plan_tiers (code, name) VALUES (:c, 'Tier') RETURNING id"),
        {"c": f"tier_{uuid.uuid4().hex[:8]}"},
    ).scalar_one()


def test_orm_declares_the_named_objects_of_the_new_tables() -> None:
    assert _orm_names("credit_packs") == {
        "pk_credit_packs",
        "uq_credit_packs_code",
        "ck_credit_packs_units_nonneg",
        "ck_credit_packs_price_nonneg",
    }
    assert _orm_names("saved_cards") == {
        "pk_saved_cards",
        "fk_saved_cards_user_id_users",
        "uq_saved_cards_user_id",
    }
    assert _orm_names("paymob_events") == {"pk_paymob_events", "uq_paymob_events_dedupe_key"}
    assert {
        "pk_payments",
        "fk_payments_payer_user_id_users",
        "fk_payments_beneficiary_user_id_users",
        "fk_payments_plan_tier_id_plan_tiers",
        "fk_payments_credit_pack_id_credit_packs",
        "fk_payments_subscription_id_subscriptions",
        "uq_payments_special_reference",
        "uq_payments_paymob_order_id",
        "uq_payments_paymob_txn_id",
        "ck_payments_amount_positive",
        "ck_payments_seat_quantity_positive",
        "ck_payments_grant_units_positive",
        "ck_payments_credit_pack_link",
        "ix_payments_status_next_reconcile_at",
        "ix_payments_payer_user_id_paid_at",
    } == _orm_names("payments")
    assert PLAN_TIER_OBJECTS <= _orm_names("plan_tiers")
    assert SUBSCRIPTION_OBJECTS <= _orm_names("subscriptions")
    assert GRANT_FK in _orm_names("usage_grants")


def test_revision_chains_from_0052_and_is_in_the_head_lineage() -> None:
    """Index R10: assert lineage, never head, so later migrations do not break this."""
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32
    lineage = {r.revision for r in script_dir.iterate_revisions(head_revision(), "base")}
    assert REVISION in lineage


def test_new_tables_match_the_orm(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        for table in NEW_TABLES:
            assert object_names(session, [table]) == _orm_names(table), table


def test_extended_tables_gain_columns_and_constraints(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        assert PLAN_TIER_COLUMNS <= column_names(session, "plan_tiers")
        assert SUBSCRIPTION_COLUMNS <= column_names(session, "subscriptions")
        assert PLAN_TIER_OBJECTS <= object_names(session, ["plan_tiers"])
        assert SUBSCRIPTION_OBJECTS <= object_names(session, ["subscriptions"])
        assert GRANT_FK in object_names(session, ["usage_grants"])


def test_subscription_status_gains_the_two_lifecycle_labels(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        labels = enum_labels(session, "subscriptionstatus")
    assert {"pending_first_payment", "past_due"} <= set(labels)
    assert {"inactive", "active", "cancelled", "expired", "rejected"} <= set(labels)


def test_existing_tiers_default_to_student_and_active(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker.begin() as session:
        tier = _seed_tier(session)
        row = session.execute(
            sa.text(
                "SELECT audience::text, allowance_units, is_active, included_seats "
                "FROM plan_tiers WHERE id = :t"
            ),
            {"t": tier},
        ).one()
    assert tuple(row) == ("student", 0, True, 0)


def test_one_live_paid_subscription_per_beneficiary(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    insert = sa.text(
        "INSERT INTO subscriptions (user_id, plan_tier_id, status, payer_user_id) "
        "VALUES (:u, :t, CAST(:s AS subscriptionstatus), :p)"
    )
    with migrated_sessionmaker.begin() as session:
        user, tier = _seed_user(session), _seed_tier(session)
        session.execute(insert, {"u": user, "t": tier, "s": "active", "p": user})
        # Not live: a cancelled paid row and manual (payer-less) rows never collide.
        session.execute(insert, {"u": user, "t": tier, "s": "cancelled", "p": user})
        session.execute(insert, {"u": user, "t": tier, "s": "active", "p": None})
        session.execute(insert, {"u": user, "t": tier, "s": "active", "p": None})
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        session.execute(insert, {"u": user, "t": tier, "s": "past_due", "p": user})


def test_a_credit_pack_payment_must_name_its_pack(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
        user = _seed_user(session)
        ref = str(uuid.uuid4())
        session.execute(
            sa.text(
                "INSERT INTO payments (payer_user_id, beneficiary_user_id, purpose, "
                "amount_minor, special_reference) VALUES (:u, :u, 'credit_pack', 100, :r)"
            ),
            {"u": user, "r": ref},
        )


def test_credit_packs_allow_zero_price_and_units_but_not_negative(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Index R11: Phase 04's inactive signup rows have price 0; units 0 disables one."""
    insert = sa.text(
        "INSERT INTO credit_packs (code, name, units, price_minor, is_active) "
        "VALUES (:c, 'Signup', :u, :p, false)"
    )
    with migrated_sessionmaker.begin() as session:
        session.execute(insert, {"c": "signup_student", "u": 200, "p": 0})
        session.execute(insert, {"c": "signup_teacher", "u": 0, "p": 0})
    for units, price in ((-1, 0), (1, -1)):
        with pytest.raises(IntegrityError), migrated_sessionmaker.begin() as session:
            session.execute(insert, {"c": f"bad_{uuid.uuid4().hex[:6]}", "u": units, "p": price})


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm.begin() as session:
        user, tier = _seed_user(session), _seed_tier(session)
        sub = session.execute(
            sa.text(
                "INSERT INTO subscriptions (user_id, plan_tier_id, status, payer_user_id) "
                "VALUES (:u, :t, 'past_due', :u) RETURNING id"
            ),
            {"u": user, "t": tier},
        ).scalar_one()

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert not set(NEW_TABLES) & public_tables(session)
        assert not PLAN_TIER_COLUMNS & column_names(session, "plan_tiers")
        assert not SUBSCRIPTION_COLUMNS & column_names(session, "subscriptions")
        assert GRANT_FK not in object_names(session, ["usage_grants"])
        assert not any(type_exists(session, name) for name in NEW_TYPES)
        status = session.execute(
            sa.text("SELECT status::text FROM subscriptions WHERE id = :s"), {"s": sub}
        ).scalar_one()
        assert status == "expired"
        assert "past_due" in enum_labels(session, "subscriptionstatus")

    upgrade_head()

    with sm() as session:
        assert current_revision(session) == head_revision()
        for table in NEW_TABLES:
            assert object_names(session, [table]) == _orm_names(table)
        assert SUBSCRIPTION_OBJECTS <= object_names(session, ["subscriptions"])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_migration_billing_payments.py -v --no-cov`
Expected: FAIL with `KeyError: 'credit_packs'` in `test_orm_declares_the_named_objects_of_the_new_tables`, and further failures because the revision is missing. Tests that need Postgres are skipped if local Postgres is not reachable; start it (`make up` or the local Supabase stack) so they run.

- [ ] **Step 3: Extend `SubscriptionStatus`**

In `lemely/db/models/enums.py`, replace the `SubscriptionStatus` class body members:

```python
    inactive = "inactive"
    active = "active"
    cancelled = "cancelled"
    expired = "expired"
    rejected = "rejected"
```

with:

```python
    inactive = "inactive"
    active = "active"
    cancelled = "cancelled"
    expired = "expired"
    rejected = "rejected"
    #: Paid path (billing spec §4.3, migration 0053): checkout created, first
    #: payment not yet verified.
    pending_first_payment = "pending_first_payment"
    #: Paid path: a renewal failed and the 3-day grace is running.
    past_due = "past_due"
```

Also append this paragraph to the class docstring, before its closing `"""`:

```python
    ``pending_first_payment`` and ``past_due`` belong to the Paymob paid path
    (billing spec §4.3). ``inactive`` and ``rejected`` remain the manual
    activation path's states.
```

- [ ] **Step 4: Replace `lemely/db/models/billing.py`**

Replace the whole file with:

```python
"""ORM models for the billing catalogue, subscriptions and payments (billing spec §4.1-§4.3).

Money is integer minor units (piasters). A ``paid`` :class:`Payment` *is* the
receipt; no other receipt record exists (spec §4.2). Lifecycle code for the new
subscription columns lands in Phase 05; this module only declares them.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lemely.db.base import Base
from lemely.db.models.enums import PlanInterval, SubscriptionStatus, TimestampMixin

#: The statuses ``uq_subscriptions_one_live_per_user`` allows at most one of, per
#: user, among paid-path rows (spec §4.3; index R8). Phase 05 imports this and adds
#: ``PLAN_LIVE_STATUSES`` beside it.
LIVE_SUBSCRIPTION_STATUSES: Final = (
    SubscriptionStatus.pending_first_payment,
    SubscriptionStatus.active,
    SubscriptionStatus.past_due,
)

#: ``status::text`` (not the enum) so migration 0053 can create the index in the
#: same transaction that adds two of these labels to ``subscriptionstatus``.
_LIVE_PAID_PREDICATE = (
    "status::text IN ('pending_first_payment', 'active', 'past_due') "
    "AND payer_user_id IS NOT NULL"
)


class PlanAudience(enum.Enum):
    """Which role a plan tier is sold to."""

    student = "student"
    teacher = "teacher"


class PaymentPurpose(enum.Enum):
    """What a payment buys (spec §4.2)."""

    subscription_first = "subscription_first"
    subscription_renewal = "subscription_renewal"
    upgrade_proration = "upgrade_proration"
    extra_seats = "extra_seats"
    credit_pack = "credit_pack"
    auto_topup = "auto_topup"


class PaymentStatus(enum.Enum):
    """Lifecycle of one payment attempt (spec §4.2)."""

    created = "created"
    pending = "pending"
    paid = "paid"
    failed = "failed"
    failed_mismatch = "failed_mismatch"
    refunded = "refunded"
    partially_refunded = "partially_refunded"
    voided = "voided"


class PaymobEventKind(enum.Enum):
    """Which Paymob callback a stored event came from."""

    transaction = "transaction"
    token = "token"
    subscription = "subscription"


class PlanTier(TimestampMixin, Base):
    """One purchasable tier at one interval (spec §4.1); monthly and yearly are two rows."""

    __tablename__ = "plan_tiers"
    __table_args__ = (
        sa.CheckConstraint("allowance_units >= 0", name="allowance_nonneg"),
        sa.CheckConstraint("included_seats >= 0", name="seats_nonneg"),
        sa.CheckConstraint("seat_allowance_units >= 0", name="seat_allowance_nonneg"),
        sa.CheckConstraint("extra_seat_price_minor >= 0", name="extra_seat_price_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    code: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    price_minor: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(0)
    )
    currency: Mapped[str] = mapped_column(
        sa.String, nullable=False, server_default=sa.literal("EGP")
    )
    interval: Mapped[PlanInterval | None] = mapped_column(
        sa.Enum(PlanInterval, name="planinterval"),
        nullable=True,
    )
    max_devices: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(3)
    )
    features: Mapped[dict] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    audience: Mapped[PlanAudience] = mapped_column(
        sa.Enum(PlanAudience, name="planaudience"),
        nullable=False,
        server_default=sa.text("'student'::planaudience"),
    )
    #: Usage units granted per period; hidden from users (spec §2.1).
    allowance_units: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.literal(0)
    )
    paymob_plan_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, unique=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    #: Teacher tiers only (zero on student tiers).
    included_seats: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(0)
    )
    seat_allowance_units: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.literal(0)
    )
    extra_seat_price_minor: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.literal(0)
    )

    subscriptions: Mapped[list[Subscription]] = relationship(
        "Subscription", back_populates="plan_tier", foreign_keys="Subscription.plan_tier_id"
    )


class Subscription(TimestampMixin, Base):
    """A user's subscription to a :class:`PlanTier`.

    ``user_id`` is the beneficiary; ``payer_user_id`` is who pays (a parent for a
    child) and is ``NULL`` on the manual-activation path. A user may hold a
    personal subscription *and* a school seat simultaneously.
    """

    __tablename__ = "subscriptions"
    __table_args__ = (
        sa.Index("ix_subscriptions_user_id_status", "user_id", "status"),
        sa.Index(
            "uq_subscriptions_one_live_per_user",
            "user_id",
            unique=True,
            postgresql_where=sa.text(_LIVE_PAID_PREDICATE),
        ),
        sa.CheckConstraint("extra_seats >= 0", name="extra_seats_nonneg"),
        sa.CheckConstraint(
            "pending_extra_seats IS NULL OR pending_extra_seats >= 0",
            name="pending_extra_seats_nonneg",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_tier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("plan_tiers.id"),
        nullable=False,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        sa.Enum(SubscriptionStatus, name="subscriptionstatus"),
        nullable=False,
        server_default=sa.text("'inactive'::subscriptionstatus"),
    )
    is_manually_activated: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    activated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    activation_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """Why a platform admin activated or rejected this subscription (X-02).

    Nullable because a note is a human sentence with no honest default; see
    migration ``0019`` for why it is not ``NOT NULL DEFAULT ''``."""
    current_period_end: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    payer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    pending_plan_tier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("plan_tiers.id"), nullable=True
    )
    current_period_start: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    grace_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    extra_seats: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(0)
    )
    pending_extra_seats: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    paymob_subscription_id: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True, unique=True
    )
    #: Optimistic-lock counter for webhook races; Phase 05 decides its use.
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.literal(1))

    plan_tier: Mapped[PlanTier] = relationship(
        "PlanTier", back_populates="subscriptions", foreign_keys=[plan_tier_id]
    )


class CreditPack(TimestampMixin, Base):
    """A prepaid credit pack (spec §4.1).

    Both CHECKs allow zero (index R11): Phase 04 stores the free signup allowances
    as inactive ``signup_student`` / ``signup_teacher`` rows with ``price_minor = 0``,
    and ``units = 0`` disables one. Checkout refuses any pack that is inactive or
    has a zero price or zero units.
    """

    __tablename__ = "credit_packs"
    __table_args__ = (
        sa.CheckConstraint("units >= 0", name="units_nonneg"),
        sa.CheckConstraint("price_minor >= 0", name="price_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(sa.String, nullable=False)
    units: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    price_minor: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(
        sa.String(3), nullable=False, server_default=sa.literal("EGP")
    )
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())


class Payment(TimestampMixin, Base):
    """One payment attempt; when ``paid`` it is the payer's receipt (spec §4.2).

    ``special_reference`` is ``str(id)``, sent to Paymob and returned as
    ``order.merchant_order_id``. ``grant_units`` snapshots what a credit purchase
    buys at checkout. ``next_reconcile_at`` / ``reconcile_attempts`` drive the
    inquiry backoff for a missed callback (spec §5.10).
    """

    __tablename__ = "payments"
    __table_args__ = (
        sa.CheckConstraint("amount_minor > 0", name="amount_positive"),
        sa.CheckConstraint(
            "seat_quantity IS NULL OR seat_quantity > 0", name="seat_quantity_positive"
        ),
        sa.CheckConstraint("grant_units IS NULL OR grant_units > 0", name="grant_units_positive"),
        sa.CheckConstraint(
            "purpose <> 'credit_pack' OR credit_pack_id IS NOT NULL", name="credit_pack_link"
        ),
        sa.Index("ix_payments_status_next_reconcile_at", "status", "next_reconcile_at"),
        sa.Index("ix_payments_payer_user_id_paid_at", "payer_user_id", "paid_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    payer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
    )
    beneficiary_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
    )
    purpose: Mapped[PaymentPurpose] = mapped_column(
        sa.Enum(PaymentPurpose, name="paymentpurpose"), nullable=False
    )
    plan_tier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("plan_tiers.id"), nullable=True
    )
    credit_pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("credit_packs.id"), nullable=True
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("subscriptions.id"), nullable=True
    )
    seat_quantity: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    grant_units: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    amount_minor: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(
        sa.String(3), nullable=False, server_default=sa.literal("EGP")
    )
    status: Mapped[PaymentStatus] = mapped_column(
        sa.Enum(PaymentStatus, name="paymentstatus"),
        nullable=False,
        server_default=sa.text("'created'::paymentstatus"),
    )
    special_reference: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    paymob_intention_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    paymob_order_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, unique=True)
    paymob_txn_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, unique=True)
    method: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    last_callback: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    reconcile_attempts: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(0)
    )
    next_reconcile_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class PaymobEvent(TimestampMixin, Base):
    """Every verified Paymob callback (and inquiry result), stored once (spec §4.2)."""

    __tablename__ = "paymob_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    kind: Mapped[PaymobEventKind] = mapped_column(
        sa.Enum(PaymobEventKind, name="paymobeventkind"), nullable=False
    )
    dedupe_key: Mapped[str] = mapped_column(sa.String, nullable=False, unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class SavedCard(TimestampMixin, Base):
    """A card token for merchant-initiated charges; ``token`` is AES-GCM ciphertext (§7)."""

    __tablename__ = "saved_cards"
    __table_args__ = (sa.UniqueConstraint("user_id", "token_fingerprint"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(sa.Text, nullable=False)
    token_fingerprint: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    masked_pan: Mapped[str] = mapped_column(sa.String, nullable=False)
    brand: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    paymob_token_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())


__all__ = [
    "LIVE_SUBSCRIPTION_STATUSES",
    "CreditPack",
    "PaymentPurpose",
    "PaymentStatus",
    "Payment",
    "PaymobEvent",
    "PaymobEventKind",
    "PlanAudience",
    "PlanTier",
    "SavedCard",
    "Subscription",
]
```

- [ ] **Step 5: Add the FK to `UsageGrant.payment_id`**

In `lemely/db/models/usage.py` (Phase 01), find the `payment_id` column on `UsageGrant`. Phase 01 declares it as a plain nullable UUID column. Change it so the line reads exactly:

```python
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("payments.id"), nullable=True
    )
```

Keep any comment Phase 01 wrote above it, but change "foreign key added by 0053" wording to say it is now declared. The naming convention names this FK `fk_usage_grants_payment_id_payments`.

- [ ] **Step 6: Write the migration**

Create `lemely/db/migrations/versions/0053_billing_payments.py`:

```python
"""billing payments: payments, paymob events, saved cards, credit packs; catalogue columns

Revision ID: 0053_billing_payments
Revises: 0052_usage_ledger
Create Date: 2026-11-05 00:00:00.000000

Billing spec §4.1-§4.3 (Phase 02 of the Paymob plan). Additive except for two
enum labels.

* ``subscriptionstatus`` gains ``pending_first_payment`` and ``past_due``.
* ``plan_tiers`` gains the catalogue columns (audience, allowance, Paymob plan,
  seats); existing rows become active student tiers with zero allowance.
* ``subscriptions`` gains payer, period, grace, seat and Paymob-link columns and
  ``uq_subscriptions_one_live_per_user``: one live paid subscription per beneficiary.
  Its predicate compares ``status::text`` so it can name the two new labels in
  this same transaction, and it ignores payer-less (manual-activation) rows.
* New ``credit_packs``, ``payments``, ``paymob_events`` and ``saved_cards``.
* ``usage_grants.payment_id`` (a plain column since 0052) gets its foreign key.

``downgrade`` drops all of it. Postgres cannot drop enum labels, so rows in the
two new states move to ``expired`` and the labels stay in the type (re-upgrading
uses ``ADD VALUE IF NOT EXISTS``).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0053_billing_payments"
down_revision: str | Sequence[str] | None = "0052_usage_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_ENUMS: dict[str, tuple[str, ...]] = {
    "planaudience": ("student", "teacher"),
    "paymentpurpose": (
        "subscription_first",
        "subscription_renewal",
        "upgrade_proration",
        "extra_seats",
        "credit_pack",
        "auto_topup",
    ),
    "paymentstatus": (
        "created",
        "pending",
        "paid",
        "failed",
        "failed_mismatch",
        "refunded",
        "partially_refunded",
        "voided",
    ),
    "paymobeventkind": ("transaction", "token", "subscription"),
}

_LIVE_PAID_PREDICATE = (
    "status::text IN ('pending_first_payment', 'active', 'past_due') "
    "AND payer_user_id IS NOT NULL"
)


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*_NEW_ENUMS[name], name=name, create_type=False)


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE subscriptionstatus ADD VALUE IF NOT EXISTS 'pending_first_payment'")
    op.execute("ALTER TYPE subscriptionstatus ADD VALUE IF NOT EXISTS 'past_due'")
    bind = op.get_bind()
    for name, labels in _NEW_ENUMS.items():
        postgresql.ENUM(*labels, name=name).create(bind, checkfirst=False)

    # -- plan_tiers -----------------------------------------------------------
    op.add_column(
        "plan_tiers",
        sa.Column(
            "audience",
            _enum("planaudience"),
            server_default=sa.text("'student'::planaudience"),
            nullable=False,
        ),
    )
    op.add_column(
        "plan_tiers",
        sa.Column("allowance_units", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("plan_tiers", sa.Column("paymob_plan_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "plan_tiers",
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "plan_tiers",
        sa.Column("included_seats", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "plan_tiers",
        sa.Column(
            "seat_allowance_units", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.add_column(
        "plan_tiers",
        sa.Column(
            "extra_seat_price_minor", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.create_unique_constraint(
        op.f("uq_plan_tiers_paymob_plan_id"), "plan_tiers", ["paymob_plan_id"]
    )
    op.create_check_constraint(
        op.f("ck_plan_tiers_allowance_nonneg"), "plan_tiers", "allowance_units >= 0"
    )
    op.create_check_constraint(
        op.f("ck_plan_tiers_seats_nonneg"), "plan_tiers", "included_seats >= 0"
    )
    op.create_check_constraint(
        op.f("ck_plan_tiers_seat_allowance_nonneg"), "plan_tiers", "seat_allowance_units >= 0"
    )
    op.create_check_constraint(
        op.f("ck_plan_tiers_extra_seat_price_nonneg"), "plan_tiers", "extra_seat_price_minor >= 0"
    )

    # -- subscriptions --------------------------------------------------------
    op.add_column("subscriptions", sa.Column("payer_user_id", sa.UUID(), nullable=True))
    op.add_column(
        "subscriptions",
        sa.Column("cancel_at_period_end", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("subscriptions", sa.Column("pending_plan_tier_id", sa.UUID(), nullable=True))
    op.add_column(
        "subscriptions",
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "subscriptions", sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "subscriptions",
        sa.Column("extra_seats", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("subscriptions", sa.Column("pending_extra_seats", sa.Integer(), nullable=True))
    op.add_column(
        "subscriptions", sa.Column("paymob_subscription_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "subscriptions",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.create_foreign_key(
        op.f("fk_subscriptions_payer_user_id_users"),
        "subscriptions",
        "users",
        ["payer_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_subscriptions_pending_plan_tier_id_plan_tiers"),
        "subscriptions",
        "plan_tiers",
        ["pending_plan_tier_id"],
        ["id"],
    )
    op.create_unique_constraint(
        op.f("uq_subscriptions_paymob_subscription_id"),
        "subscriptions",
        ["paymob_subscription_id"],
    )
    op.create_check_constraint(
        op.f("ck_subscriptions_extra_seats_nonneg"), "subscriptions", "extra_seats >= 0"
    )
    op.create_check_constraint(
        op.f("ck_subscriptions_pending_extra_seats_nonneg"),
        "subscriptions",
        "pending_extra_seats IS NULL OR pending_extra_seats >= 0",
    )
    op.create_index(
        "uq_subscriptions_one_live_per_user",
        "subscriptions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(_LIVE_PAID_PREDICATE),
    )

    # -- credit_packs ---------------------------------------------------------
    op.create_table(
        "credit_packs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("units", sa.BigInteger(), nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), server_default=sa.text("'EGP'"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("units >= 0", name=op.f("ck_credit_packs_units_nonneg")),
        sa.CheckConstraint("price_minor >= 0", name=op.f("ck_credit_packs_price_nonneg")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_packs")),
        sa.UniqueConstraint("code", name=op.f("uq_credit_packs_code")),
    )

    # -- payments -------------------------------------------------------------
    op.create_table(
        "payments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("payer_user_id", sa.UUID(), nullable=False),
        sa.Column("beneficiary_user_id", sa.UUID(), nullable=False),
        sa.Column("purpose", _enum("paymentpurpose"), nullable=False),
        sa.Column("plan_tier_id", sa.UUID(), nullable=True),
        sa.Column("credit_pack_id", sa.UUID(), nullable=True),
        sa.Column("subscription_id", sa.UUID(), nullable=True),
        sa.Column("seat_quantity", sa.Integer(), nullable=True),
        sa.Column("grant_units", sa.BigInteger(), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), server_default=sa.text("'EGP'"), nullable=False),
        sa.Column(
            "status",
            _enum("paymentstatus"),
            server_default=sa.text("'created'::paymentstatus"),
            nullable=False,
        ),
        sa.Column("special_reference", sa.String(), nullable=False),
        sa.Column("paymob_intention_id", sa.String(), nullable=True),
        sa.Column("paymob_order_id", sa.BigInteger(), nullable=True),
        sa.Column("paymob_txn_id", sa.BigInteger(), nullable=True),
        sa.Column("method", sa.String(), nullable=True),
        sa.Column("last_callback", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconcile_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_reconcile_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("amount_minor > 0", name=op.f("ck_payments_amount_positive")),
        sa.CheckConstraint(
            "seat_quantity IS NULL OR seat_quantity > 0",
            name=op.f("ck_payments_seat_quantity_positive"),
        ),
        sa.CheckConstraint(
            "grant_units IS NULL OR grant_units > 0", name=op.f("ck_payments_grant_units_positive")
        ),
        sa.CheckConstraint(
            "purpose <> 'credit_pack' OR credit_pack_id IS NOT NULL",
            name=op.f("ck_payments_credit_pack_link"),
        ),
        sa.ForeignKeyConstraint(
            ["payer_user_id"], ["users.id"], name=op.f("fk_payments_payer_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["beneficiary_user_id"],
            ["users.id"],
            name=op.f("fk_payments_beneficiary_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["plan_tier_id"], ["plan_tiers.id"], name=op.f("fk_payments_plan_tier_id_plan_tiers")
        ),
        sa.ForeignKeyConstraint(
            ["credit_pack_id"],
            ["credit_packs.id"],
            name=op.f("fk_payments_credit_pack_id_credit_packs"),
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_payments_subscription_id_subscriptions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("special_reference", name=op.f("uq_payments_special_reference")),
        sa.UniqueConstraint("paymob_order_id", name=op.f("uq_payments_paymob_order_id")),
        sa.UniqueConstraint("paymob_txn_id", name=op.f("uq_payments_paymob_txn_id")),
    )
    op.create_index(
        "ix_payments_status_next_reconcile_at", "payments", ["status", "next_reconcile_at"]
    )
    op.create_index("ix_payments_payer_user_id_paid_at", "payments", ["payer_user_id", "paid_at"])

    # -- paymob_events --------------------------------------------------------
    op.create_table(
        "paymob_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kind", _enum("paymobeventkind"), nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paymob_events")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_paymob_events_dedupe_key")),
    )

    # -- saved_cards ----------------------------------------------------------
    op.create_table(
        "saved_cards",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("token_fingerprint", sa.String(64), nullable=False),
        sa.Column("masked_pan", sa.String(), nullable=False),
        sa.Column("brand", sa.String(), nullable=True),
        sa.Column("paymob_token_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_saved_cards_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_cards")),
        sa.UniqueConstraint("user_id", "token_fingerprint", name=op.f("uq_saved_cards_user_id")),
    )

    # -- usage_grants.payment_id FK (column created by 0052) -------------------
    op.create_foreign_key(
        op.f("fk_usage_grants_payment_id_payments"),
        "usage_grants",
        "payments",
        ["payment_id"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema: drop everything above; the two enum labels stay."""
    op.drop_constraint(
        op.f("fk_usage_grants_payment_id_payments"), "usage_grants", type_="foreignkey"
    )
    op.drop_table("saved_cards")
    op.drop_table("paymob_events")
    op.drop_table("payments")
    op.drop_table("credit_packs")

    op.execute(
        "UPDATE subscriptions SET status = 'expired' "
        "WHERE status::text IN ('pending_first_payment', 'past_due')"
    )
    op.drop_index("uq_subscriptions_one_live_per_user", table_name="subscriptions")
    op.drop_constraint(
        op.f("ck_subscriptions_pending_extra_seats_nonneg"), "subscriptions", type_="check"
    )
    op.drop_constraint(op.f("ck_subscriptions_extra_seats_nonneg"), "subscriptions", type_="check")
    op.drop_constraint(
        op.f("uq_subscriptions_paymob_subscription_id"), "subscriptions", type_="unique"
    )
    op.drop_constraint(
        op.f("fk_subscriptions_pending_plan_tier_id_plan_tiers"),
        "subscriptions",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_subscriptions_payer_user_id_users"), "subscriptions", type_="foreignkey"
    )
    for column in (
        "version",
        "paymob_subscription_id",
        "pending_extra_seats",
        "extra_seats",
        "grace_until",
        "current_period_start",
        "pending_plan_tier_id",
        "cancel_at_period_end",
        "payer_user_id",
    ):
        op.drop_column("subscriptions", column)

    for check in (
        "ck_plan_tiers_extra_seat_price_nonneg",
        "ck_plan_tiers_seat_allowance_nonneg",
        "ck_plan_tiers_seats_nonneg",
        "ck_plan_tiers_allowance_nonneg",
    ):
        op.drop_constraint(op.f(check), "plan_tiers", type_="check")
    op.drop_constraint(op.f("uq_plan_tiers_paymob_plan_id"), "plan_tiers", type_="unique")
    for column in (
        "extra_seat_price_minor",
        "seat_allowance_units",
        "included_seats",
        "is_active",
        "paymob_plan_id",
        "allowance_units",
        "audience",
    ):
        op.drop_column("plan_tiers", column)

    bind = op.get_bind()
    for name in reversed(list(_NEW_ENUMS)):
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)
```

- [ ] **Step 7: Leave the earlier migration tests alone (index R10)**

Phase 01 already replaced every "is head" assertion with a lineage check, and `tests/test_migration_usage_ledger.py` asserts lineage only. Do not edit either file. Run them unchanged in Step 8. They must still pass, because 0053 adds the `usage_grants` FK both to the ORM (Step 5) and to the DB, so Phase 01's `object_names(session, TABLES) == _orm_names()` check still matches.

Phase 01's round-trip test downgrades to `0051`, which also runs this migration's downgrade and drops `credit_packs`, `payments`, `paymob_events` and `saved_cards`. If its `public_tables(session) == before - set(TABLES)` assertion fails for that reason, stop and report it to the coordinator as a Phase 01 test bug. Do not change Phase 01's test from this task.

- [ ] **Step 8: Run the migration tests, the schema tests and the existing billing users**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_migration_billing_payments.py tests/test_migration_usage_ledger.py tests/test_migration_tutor_evidence_uploads.py tests/test_db_schema.py tests/test_web_platform_admin.py tests/test_seat_repo.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 9: Pre-commit and commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/models/enums.py lemely/db/models/billing.py lemely/db/models/usage.py lemely/db/migrations/versions/0053_billing_payments.py tests/test_migration_billing_payments.py
git commit -S -m "feat(billing): add payments, paymob events, saved cards and credit packs (migration 0053)" -- lemely/db/models/enums.py lemely/db/models/billing.py lemely/db/models/usage.py lemely/db/migrations/versions/0053_billing_payments.py tests/test_migration_billing_payments.py
```

---

### Task 6: BillingService checkout, paid-handler registry and credit-pack grant

**Files:**
- Create: `lemely/db/billing_repo.py`
- Modify: `tests/paymob_fixtures.py` (append fake client and DB seeders)
- Test: `tests/test_billing_checkout.py`

**Interfaces:**
- Consumes:
  - `PaymobClient`, `PaymobError` (Task 4).
  - `PaymobSettings` (Task 1).
  - `TokenCipher` (Task 2).
  - The Task 5 models.
  - `UsageLedger.issue_grant(*, owner_user_id, kind, units, idempotency_key, expires_at, visible, effective_at=None, payment_id=None, subscription_period_id=None, teacher_member_id=None) -> UsageGrant` and `GrantKind.credit_pack` (Phase 01).
- Produces (in `lemely.db.billing_repo`):
  - `PaidHandler = Callable[[Session, Payment, Mapping[str, Any]], None]`
  - `register_paid_handler(purpose: PaymentPurpose, handler: PaidHandler) -> None`, which raises `ValueError` when a different handler is already registered for the purpose.
  - `paid_handler_for(purpose: PaymentPurpose) -> PaidHandler | None`
  - `@dataclass(frozen=True) CheckoutResult(payment_id: uuid.UUID, checkout_url: str)`
  - Exceptions `BillingError`, `CheckoutUnavailable(BillingError)`, `UnknownCreditPack(BillingError)`, `MalformedCallback(BillingError)`.
  - `add_months(moment: datetime, months: int) -> datetime`
  - `billing_data_for(user: User) -> dict[str, str]`
  - `grant_credit_pack(session, payment, obj) -> None`, registered for `PaymentPurpose.credit_pack` on import.
  - Constants `CREDIT_EXPIRY_MONTHS = 12`, `INTENTION_EXPIRATION_SECONDS = 3600`, `RECONCILE_AFTER = timedelta(minutes=15)`, `WEBHOOK_PATH = "/api/webhooks/paymob/transaction"`, `RETURN_PATH = "/billing/return"`.
  - `BillingService(session, client, settings, *, cipher: TokenCipher | None = None, now: Callable[[], datetime] = ...)`.
  - Methods `create_pack_checkout(*, payer_user_id, beneficiary_user_id, credit_pack_id) -> CheckoutResult` and `create_intention_checkout(*, payment, items, billing_data, subscription_plan_id) -> CheckoutResult`.
  - Tasks 7 and 8 add `apply_transaction_callback`, `apply_token_callback` and `reconcile_pending` to the same class.
  - The SPA return page is `{redirection_base_url}/billing/return?payment=<payment_id>` (Phase 08 builds it).
- Produces (test helpers): `FakePaymobClient`, `seed_user`, `seed_pack`, `link_parent`, `seed_payment`, `FIXED_NOW`.

- [ ] **Step 1: Append the fake client and DB seeders to `tests/paymob_fixtures.py`**

Append to the end of `tests/paymob_fixtures.py`:

```python
# ---------------------------------------------------------------------------
# Fake client and DB seeders (Task 6 onward).
# ---------------------------------------------------------------------------

import uuid  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402

import httpx  # noqa: E402

from lemely.db.models import ParentChildLink, User  # noqa: E402
from lemely.db.models.billing import CreditPack, Payment, PaymentPurpose, PaymentStatus  # noqa: E402
from lemely.db.models.enums import Role  # noqa: E402
from lemely.io.paymob.client import PaymobClient  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

FIXED_NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def _refuse(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected Paymob HTTP call: {request.method} {request.url}")


class FakePaymobClient(PaymobClient):
    """A PaymobClient whose HTTP layer is never reached; each call is scripted."""

    def __init__(self, settings: PaymobSettings = PAYMOB_SETTINGS) -> None:
        super().__init__(settings, http=httpx.Client(transport=httpx.MockTransport(_refuse)))
        self.intentions: list[dict[str, Any]] = []
        self.intention_response: dict[str, Any] | Exception = dict(INTENTION_RESPONSE)
        self.on_intention: Callable[[dict[str, Any]], None] | None = None
        self.inquiries: list[str] = []
        self.inquiry_response: dict[str, Any] | None | Exception = None

    def create_intention(self, body: Any) -> dict[str, Any]:
        self.intentions.append(dict(body))
        if self.on_intention is not None:
            self.on_intention(dict(body))
        if isinstance(self.intention_response, Exception):
            raise self.intention_response
        return dict(self.intention_response)

    def inquire_by_order_ref(self, merchant_order_id: str) -> dict[str, Any] | None:
        self.inquiries.append(merchant_order_id)
        if isinstance(self.inquiry_response, Exception):
            raise self.inquiry_response
        return self.inquiry_response


def seed_user(
    sm: sessionmaker[Session],
    role: Role = Role.student,
    *,
    display_name: str | None = "Sara Ali",
    phone: str | None = "+201234567890",
) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            User(
                id=uid,
                email=f"{uid}@example.com",
                role=role,
                display_name=display_name,
                phone=phone,
            )
        )
    return uid


def seed_pack(
    sm: sessionmaker[Session],
    *,
    code: str | None = None,
    name: str = "100 credits",
    units: int = 100,
    price_minor: int = 10000,
    is_active: bool = True,
) -> uuid.UUID:
    pack_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            CreditPack(
                id=pack_id,
                code=code or f"pack_{pack_id.hex[:8]}",
                name=name,
                units=units,
                price_minor=price_minor,
                currency="EGP",
                is_active=is_active,
            )
        )
    return pack_id


def link_parent(sm: sessionmaker[Session], *, parent_id: uuid.UUID, child_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(ParentChildLink(parent_id=parent_id, child_id=child_id))


def seed_payment(
    sm: sessionmaker[Session],
    *,
    payer: uuid.UUID,
    beneficiary: uuid.UUID,
    pack_id: uuid.UUID,
    amount_minor: int = 10000,
    grant_units: int = 100,
    status: PaymentStatus = PaymentStatus.created,
    created_at: datetime | None = None,
    next_reconcile_at: datetime | None = None,
    paymob_order_id: int | None = None,
    paid_at: datetime | None = None,
) -> uuid.UUID:
    payment_id = uuid.uuid4()
    created = created_at or FIXED_NOW
    with sm.begin() as session:
        payment = Payment(
            id=payment_id,
            payer_user_id=payer,
            beneficiary_user_id=beneficiary,
            purpose=PaymentPurpose.credit_pack,
            credit_pack_id=pack_id,
            grant_units=grant_units,
            amount_minor=amount_minor,
            currency="EGP",
            status=status,
            special_reference=str(payment_id),
            paymob_order_id=paymob_order_id,
            paid_at=paid_at,
            next_reconcile_at=next_reconcile_at or created + timedelta(minutes=15),
        )
        payment.created_at = created
        session.add(payment)
    return payment_id
```

- [ ] **Step 2: Write the failing checkout test**

Create `tests/test_billing_checkout.py`:

```python
"""BillingService checkout, paid-handler registry and the credit-pack grant (spec §5.5, §6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa

from lemely.db.billing_repo import (
    BillingService,
    CheckoutUnavailable,
    UnknownCreditPack,
    add_months,
    billing_data_for,
    grant_credit_pack,
    paid_handler_for,
    register_paid_handler,
)
from lemely.db.models import User
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageGrant
from lemely.io.paymob.client import PaymobError
from lemely.runtime.config import PaymobSettings
from tests.paymob_fixtures import (
    FIXED_NOW,
    INTENTION_RESPONSE,
    PAYMOB_SETTINGS,
    FakePaymobClient,
    seed_pack,
    seed_payment,
    seed_user,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def _service(session: Session, client: FakePaymobClient, settings: PaymobSettings = PAYMOB_SETTINGS) -> BillingService:
    return BillingService(session, client, settings, now=lambda: FIXED_NOW)


def test_pack_checkout_inserts_the_payment_and_returns_the_unified_checkout_url(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm, display_name="Sara Ali")
    pack = seed_pack(sm, name="100 credits", units=100, price_minor=10000)
    client = FakePaymobClient()
    with sm() as session:
        result = _service(session, client).create_pack_checkout(
            payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack
        )
    assert result.checkout_url == (
        "https://eg.checkout.paymob.com/?publicKey=egy_pk_test_public"
        f"&clientSecret={INTENTION_RESPONSE['client_secret']}"
    )
    (body,) = client.intentions
    assert body["amount"] == 10000
    assert body["currency"] == "EGP"
    assert body["payment_methods"] == [4569876]
    assert body["special_reference"] == str(result.payment_id)
    assert body["expiration"] == 3600
    assert body["notification_url"] == "https://lemelyig.com/api/webhooks/paymob/transaction"
    assert body["redirection_url"] == (
        f"https://lemelyig.com/billing/return?payment={result.payment_id}"
    )
    assert sum(item["amount"] for item in body["items"]) == body["amount"]
    assert body["billing_data"]["first_name"] == "Sara"
    assert body["billing_data"]["last_name"] == "Ali"
    assert body["billing_data"]["phone_number"] == "+201234567890"
    assert "subscription_plan_id" not in body
    with sm() as session:
        payment = session.get(Payment, result.payment_id)
        assert payment is not None
        assert payment.status is PaymentStatus.created
        assert payment.purpose is PaymentPurpose.credit_pack
        assert payment.payer_user_id == payment.beneficiary_user_id == payer
        assert payment.amount_minor == 10000
        assert payment.grant_units == 100
        assert payment.special_reference == str(payment.id)
        assert payment.paymob_order_id == INTENTION_RESPONSE["intention_order_id"]
        assert payment.paymob_intention_id == INTENTION_RESPONSE["id"]
        assert payment.next_reconcile_at == FIXED_NOW + timedelta(minutes=15)


def test_the_payment_row_is_committed_before_paymob_is_called(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    seen: list[PaymentStatus] = []

    def check(body: dict[str, Any]) -> None:
        with sm() as other:  # a separate connection sees only committed rows
            row = other.get(Payment, uuid.UUID(body["special_reference"]))
            assert row is not None
            seen.append(row.status)

    client = FakePaymobClient()
    client.on_intention = check
    with sm() as session:
        _service(session, client).create_pack_checkout(
            payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack
        )
    assert seen == [PaymentStatus.created]


@pytest.mark.parametrize(
    "error",
    [
        PaymobError("Paymob POST v1/intention/ timed out", timeout=True),
        PaymobError("Paymob POST v1/intention/ returned 500", status_code=500),
    ],
)
def test_a_paymob_failure_marks_the_payment_failed_and_never_retries(
    migrated_sessionmaker: sessionmaker[Session], error: PaymobError
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    client = FakePaymobClient()
    client.intention_response = error
    with sm() as session, pytest.raises(CheckoutUnavailable):
        _service(session, client).create_pack_checkout(
            payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack
        )
    assert len(client.intentions) == 1
    with sm() as session:
        (payment,) = session.scalars(sa.select(Payment)).all()
        assert payment.status is PaymentStatus.failed
        assert payment.next_reconcile_at is None
        assert payment.last_callback is not None
        assert payment.last_callback["source"] == "create_intention"


def test_a_response_without_a_client_secret_is_a_failure(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    client = FakePaymobClient()
    client.intention_response = {**INTENTION_RESPONSE, "client_secret": None}
    with sm() as session, pytest.raises(CheckoutUnavailable):
        _service(session, client).create_pack_checkout(
            payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack
        )
    with sm() as session:
        assert session.scalars(sa.select(Payment.status)).one() is PaymentStatus.failed


def test_unconfigured_paymob_refuses_before_inserting_anything(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    pack = seed_pack(sm)
    client = FakePaymobClient()
    with sm() as session, pytest.raises(CheckoutUnavailable):
        _service(session, client, PaymobSettings()).create_pack_checkout(
            payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack
        )
    assert client.intentions == []
    with sm() as session:
        assert session.scalars(sa.select(Payment)).all() == []


def test_unknown_inactive_and_zero_value_packs_are_refused(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    payer = seed_user(sm)
    inactive = seed_pack(sm, is_active=False)
    free = seed_pack(sm, price_minor=0)  # an active zero-price row is still never sold
    empty = seed_pack(sm, units=0)
    client = FakePaymobClient()
    for pack_id in (inactive, free, empty, uuid.uuid4()):
        with sm() as session, pytest.raises(UnknownCreditPack):
            _service(session, client).create_pack_checkout(
                payer_user_id=payer, beneficiary_user_id=payer, credit_pack_id=pack_id
            )
    assert client.intentions == []


def test_the_credit_pack_handler_is_registered_on_import() -> None:
    assert paid_handler_for(PaymentPurpose.credit_pack) is grant_credit_pack


def test_registering_a_second_different_handler_for_a_purpose_is_refused() -> None:
    register_paid_handler(PaymentPurpose.credit_pack, grant_credit_pack)  # same: fine

    def other(session: Session, payment: Payment, obj: Any) -> None:
        raise AssertionError("never called")

    with pytest.raises(ValueError, match="already registered"):
        register_paid_handler(PaymentPurpose.credit_pack, other)
    assert paid_handler_for(PaymentPurpose.credit_pack) is grant_credit_pack


def test_grant_credit_pack_issues_one_visible_grant_expiring_in_twelve_months(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    child = seed_user(sm)
    pack = seed_pack(sm, units=250)
    paid_at = datetime(2028, 2, 29, 9, 30, tzinfo=UTC)
    payment_id = seed_payment(
        sm, payer=parent, beneficiary=child, pack_id=pack, grant_units=250,
        status=PaymentStatus.paid, paid_at=paid_at,
    )
    for _ in range(2):  # idempotent on the payment
        with sm.begin() as session:
            payment = session.get(Payment, payment_id)
            assert payment is not None
            grant_credit_pack(session, payment, {})
    with sm() as session:
        (grant,) = session.scalars(
            sa.select(UsageGrant).where(UsageGrant.payment_id == payment_id)
        ).all()
    assert grant.owner_user_id == child
    assert grant.kind is GrantKind.credit_pack
    assert grant.units == 250
    assert grant.visible is True
    assert grant.expires_at == datetime(2029, 2, 28, 9, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("moment", "months", "expected"),
    [
        (datetime(2026, 11, 5, tzinfo=UTC), 12, datetime(2027, 11, 5, tzinfo=UTC)),
        (datetime(2028, 2, 29, tzinfo=UTC), 12, datetime(2029, 2, 28, tzinfo=UTC)),
        (datetime(2026, 1, 31, tzinfo=UTC), 1, datetime(2026, 2, 28, tzinfo=UTC)),
        (datetime(2026, 12, 15, tzinfo=UTC), 1, datetime(2027, 1, 15, tzinfo=UTC)),
    ],
)
def test_add_months_clamps_to_the_last_day(moment: datetime, months: int, expected: datetime) -> None:
    assert add_months(moment, months) == expected


def test_billing_data_falls_back_when_the_profile_is_sparse() -> None:
    user = User(id=uuid.uuid4(), email="x@example.com", role=Role.teacher, display_name=None, phone=None)
    data = billing_data_for(user)
    assert data["first_name"] == "Lemely"
    assert data["last_name"] == "Customer"
    assert data["email"] == "x@example.com"
    assert data["phone_number"] == "NA"
    assert data["country"] == "EGY"


def test_billing_data_truncates_long_names_to_paymobs_limit() -> None:
    user = User(id=uuid.uuid4(), email="y@example.com", role=Role.student, display_name="A" * 80 + " " + "B" * 80)
    data = billing_data_for(user)
    assert len(data["first_name"]) == 50
    assert len(data["last_name"]) == 50
```

- [ ] **Step 3: Run it to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_billing_checkout.py -v --no-cov`
Expected: collection error, `ModuleNotFoundError: No module named 'lemely.db.billing_repo'`.

- [ ] **Step 4: Implement `lemely/db/billing_repo.py`**

Create `lemely/db/billing_repo.py`:

```python
"""Billing service: payments, Paymob callbacks and paid handlers (billing spec §3-§6).

The only module that joins Paymob to the usage ledger. ``PaymobClient`` knows
nothing about credits and ``UsageLedger`` knows nothing about Paymob; a payment
verified here is handed to the handler registered for its purpose, which
issues the grant.

**Transactions.** Read methods and the callback appliers never commit: the
webhook route owns one ``sessionmaker.begin()`` transaction and answers 200 only
after it commits (spec §6). Two methods commit on purpose:
``create_intention_checkout`` commits the payment row *before* calling Paymob
(Paymob has no idempotency keys; our row must exist first) and again after;
``reconcile_pending`` commits after each payment it settles.

**Paid handlers.** Each purpose registers exactly one handler at import time
(``register_paid_handler``). Phase 02 registers ``credit_pack``; Phases 05 and 06
register the subscription and merchant-charge purposes from their own modules.
A paid payment whose purpose has no handler raises, which rolls the webhook
transaction back so Paymob retries and reconciliation tries again.
"""

from __future__ import annotations

import calendar
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlencode

import structlog
from sqlalchemy import select

from lemely.db.models import ParentChildLink, User
from lemely.db.models.billing import (
    CreditPack,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    PlanTier,
)
from lemely.db.models.usage import GrantKind
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.paymob.client import PaymobError
from lemely.runtime.token_cipher import TokenCipher

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

log = structlog.get_logger(__name__)

CREDIT_EXPIRY_MONTHS: Final = 12
INTENTION_EXPIRATION_SECONDS: Final = 3600
RECONCILE_AFTER: Final = timedelta(minutes=15)
WEBHOOK_PATH: Final = "/api/webhooks/paymob/transaction"
RETURN_PATH: Final = "/billing/return"

_PURPOSE_LABELS: Final[Mapping[PaymentPurpose, str]] = {
    PaymentPurpose.subscription_first: "Subscription",
    PaymentPurpose.subscription_renewal: "Subscription renewal",
    PaymentPurpose.upgrade_proration: "Plan upgrade",
    PaymentPurpose.extra_seats: "Extra student seats",
    PaymentPurpose.credit_pack: "Credit pack",
    PaymentPurpose.auto_topup: "Credit auto top-up",
}


# ---------------------------------------------------------------------------
# Errors and results.
# ---------------------------------------------------------------------------


class BillingError(Exception):
    """Base class for billing failures a route maps to an HTTP status."""


class CheckoutUnavailable(BillingError):
    """Paymob is not configured or did not create the intention (503)."""


class UnknownCreditPack(BillingError):
    """No active credit pack with that id (404)."""


class MalformedCallback(BillingError):
    """A verified callback lacks a field we need (400)."""


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    payment_id: uuid.UUID
    checkout_url: str


# ---------------------------------------------------------------------------
# Paid-handler registry.
# ---------------------------------------------------------------------------

PaidHandler = Callable[["Session", Payment, Mapping[str, Any]], None]
_PAID_HANDLERS: dict[PaymentPurpose, PaidHandler] = {}


def register_paid_handler(purpose: PaymentPurpose, handler: PaidHandler) -> None:
    """Register the one handler a verified payment of ``purpose`` is passed to."""
    existing = _PAID_HANDLERS.get(purpose)
    if existing is not None and existing is not handler:
        raise ValueError(f"a paid handler is already registered for {purpose.value}")
    _PAID_HANDLERS[purpose] = handler


def paid_handler_for(purpose: PaymentPurpose) -> PaidHandler | None:
    return _PAID_HANDLERS.get(purpose)


# ---------------------------------------------------------------------------
# Pure helpers.
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def add_months(moment: datetime, months: int) -> datetime:
    """``moment`` plus ``months`` calendar months, clamped to the month's last day."""
    index = moment.month - 1 + months
    year = moment.year + index // 12
    month = index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def billing_data_for(user: User) -> dict[str, str]:
    """Paymob ``billing_data`` from the payer's profile (research 01 §2.1).

    First name, last name, email and phone are required by Paymob; address
    fields are not collected by Lemely and are sent as ``"NA"``, as Paymob's own
    samples send placeholders. Whether Paymob validates the ``"NA"`` phone
    fallback is an open question for the live test account (research 01 §8 q5).
    """
    first, _, last = (user.display_name or "").strip().partition(" ")
    return {
        "first_name": (first or "Lemely")[:50],
        "last_name": (last.strip() or "Customer")[:50],
        "email": user.email,
        "phone_number": user.phone or "NA",
        "apartment": "NA",
        "floor": "NA",
        "street": "NA",
        "building": "NA",
        "city": "NA",
        "state": "NA",
        "country": "EGY",
    }


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _is_true(value: object) -> bool:
    return value is True or value == "true"


def _flag(value: object) -> str:
    return "1" if _is_true(value) else "0"


def transaction_dedupe_key(obj: Mapping[str, Any]) -> str:
    """Transaction id plus the state flags (spec §4.2): a new state is a new event."""
    return (
        f"txn:{obj.get('id')}:s{_flag(obj.get('success'))}p{_flag(obj.get('pending'))}"
        f"v{_flag(obj.get('is_voided'))}r{_flag(obj.get('is_refunded'))}"
        f":{_as_int(obj.get('refunded_amount_cents')) or 0}"
    )


# ---------------------------------------------------------------------------
# Paid handler: credit packs (spec §5.5).
# ---------------------------------------------------------------------------


def grant_credit_pack(session: Session, payment: Payment, obj: Mapping[str, Any]) -> None:
    """Issue the beneficiary's visible credit grant, expiring 12 months after payment."""
    if payment.grant_units is None:
        raise RuntimeError(f"credit pack payment {payment.id} has no grant_units snapshot")
    paid_at = payment.paid_at or _utcnow()
    UsageLedger(session).issue_grant(
        owner_user_id=payment.beneficiary_user_id,
        kind=GrantKind.credit_pack,
        units=payment.grant_units,
        idempotency_key=f"payment:{payment.id}",
        expires_at=add_months(paid_at, CREDIT_EXPIRY_MONTHS),
        visible=True,
        effective_at=paid_at,
        payment_id=payment.id,
    )


register_paid_handler(PaymentPurpose.credit_pack, grant_credit_pack)


# ---------------------------------------------------------------------------
# Read queries used by the billing router.
# ---------------------------------------------------------------------------


def is_linked_parent(session: Session, parent_id: uuid.UUID, child_id: uuid.UUID) -> bool:
    """True when ``parent_child_links`` links the two (spec §2.1, §7)."""
    return (
        session.scalar(
            select(ParentChildLink.id).where(
                ParentChildLink.parent_id == parent_id, ParentChildLink.child_id == child_id
            )
        )
        is not None
    )


def active_catalogue(
    session: Session, *, audience: PlanAudience
) -> tuple[list[PlanTier], list[CreditPack]]:
    tiers = session.scalars(
        select(PlanTier)
        .where(PlanTier.is_active.is_(True), PlanTier.audience == audience)
        .order_by(PlanTier.price_minor, PlanTier.code)
    ).all()
    packs = session.scalars(
        select(CreditPack)
        .where(CreditPack.is_active.is_(True))
        .order_by(CreditPack.price_minor, CreditPack.code)
    ).all()
    return list(tiers), list(packs)


def payment_for_viewer(
    session: Session, *, payment_id: uuid.UUID, user_id: uuid.UUID
) -> Payment | None:
    """The payment if ``user_id`` is its payer or beneficiary, else ``None`` (no oracle)."""
    payment = session.get(Payment, payment_id)
    if payment is None or user_id not in (payment.payer_user_id, payment.beneficiary_user_id):
        return None
    return payment


def receipts_for(session: Session, payer_user_id: uuid.UUID) -> list[Payment]:
    """Every payment this user paid for, newest first: the receipts (spec §2.5)."""
    return list(
        session.scalars(
            select(Payment)
            .where(Payment.payer_user_id == payer_user_id, Payment.paid_at.is_not(None))
            .order_by(Payment.paid_at.desc(), Payment.id)
        ).all()
    )


def describe_payment(session: Session, payment: Payment) -> str:
    if payment.purpose is PaymentPurpose.credit_pack and payment.credit_pack_id is not None:
        pack = session.get(CreditPack, payment.credit_pack_id)
        if pack is not None:
            return pack.name
    return _PURPOSE_LABELS[payment.purpose]


# ---------------------------------------------------------------------------
# The service.
# ---------------------------------------------------------------------------


class BillingService:
    """Payments and Paymob callbacks over one SQLAlchemy session."""

    def __init__(
        self,
        session: Session,
        client: PaymobClient,
        settings: PaymobSettings,
        *,
        cipher: TokenCipher | None = None,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._session = session
        self._client = client
        self._settings = settings
        if cipher is None and settings.card_token_key is not None:
            cipher = TokenCipher(settings.card_token_key.get_secret_value())
        self._cipher = cipher
        self._now = now

    # -- checkout -------------------------------------------------------------

    @property
    def notification_url(self) -> str:
        return f"{self._settings.notification_base_url}{WEBHOOK_PATH}"

    def redirection_url(self, payment_id: uuid.UUID) -> str:
        return f"{self._settings.redirection_base_url}{RETURN_PATH}?payment={payment_id}"

    def create_pack_checkout(
        self,
        *,
        payer_user_id: uuid.UUID,
        beneficiary_user_id: uuid.UUID,
        credit_pack_id: uuid.UUID,
    ) -> CheckoutResult:
        """Price a pack on the server, insert the payment, create the intention (§5.5)."""
        if not self._settings.checkout_configured:
            raise CheckoutUnavailable("Paymob checkout is not configured")
        pack = self._session.get(CreditPack, credit_pack_id)
        if pack is None or not pack.is_active or pack.price_minor <= 0 or pack.units <= 0:
            # Inactive signup-allowance rows (Phase 04) and zero-value packs are never sold.
            raise UnknownCreditPack(str(credit_pack_id))
        payer = self._session.get(User, payer_user_id)
        if payer is None:
            raise BillingError(f"unknown payer {payer_user_id}")
        payment_id = uuid.uuid4()
        payment = Payment(
            id=payment_id,
            payer_user_id=payer_user_id,
            beneficiary_user_id=beneficiary_user_id,
            purpose=PaymentPurpose.credit_pack,
            credit_pack_id=pack.id,
            grant_units=pack.units,
            amount_minor=pack.price_minor,
            currency=pack.currency,
            status=PaymentStatus.created,
            special_reference=str(payment_id),
        )
        items = [
            {
                "name": pack.name[:50],
                "amount": pack.price_minor,
                "description": f"{pack.units} Lemely credits"[:255],
                "quantity": 1,
            }
        ]
        return self.create_intention_checkout(
            payment=payment,
            items=items,
            billing_data=billing_data_for(payer),
            subscription_plan_id=None,
        )

    def create_intention_checkout(
        self,
        *,
        payment: Payment,
        items: Sequence[Mapping[str, Any]],
        billing_data: Mapping[str, Any],
        subscription_plan_id: int | None,
    ) -> CheckoutResult:
        """Commit ``payment``, create its Paymob intention, return the checkout URL.

        Shared with Phase 05 (subscriptions pass ``subscription_plan_id``). On any
        Paymob failure the payment is marked ``failed`` and committed, and
        ``CheckoutUnavailable`` is raised. The call is never retried: a timed-out
        intention gave the customer no client secret, so nothing can be paid on it.
        """
        if not self._settings.checkout_configured:
            raise CheckoutUnavailable("Paymob checkout is not configured")
        if payment.next_reconcile_at is None:
            payment.next_reconcile_at = self._now() + RECONCILE_AFTER
        self._session.add(payment)
        self._session.commit()

        assert self._settings.card_integration_id is not None  # checkout_configured  # noqa: S101
        body: dict[str, Any] = {
            "amount": payment.amount_minor,
            "currency": payment.currency,
            "payment_methods": [self._settings.card_integration_id],
            "items": [dict(item) for item in items],
            "billing_data": dict(billing_data),
            "special_reference": payment.special_reference,
            "expiration": INTENTION_EXPIRATION_SECONDS,
            "notification_url": self.notification_url,
            "redirection_url": self.redirection_url(payment.id),
            "extras": {"payment_id": str(payment.id), "purpose": payment.purpose.value},
        }
        if subscription_plan_id is not None:
            body["subscription_plan_id"] = subscription_plan_id
        try:
            response = self._client.create_intention(body)
        except PaymobError as exc:
            self._fail_checkout(payment, str(exc), exc.status_code)
            log.warning(
                "paymob_intention_failed",
                payment_id=str(payment.id),
                status_code=exc.status_code,
                timeout=exc.timeout,
            )
            raise CheckoutUnavailable("Paymob is unavailable") from exc
        client_secret = response.get("client_secret")
        if not isinstance(client_secret, str) or not client_secret:
            self._fail_checkout(payment, "intention response had no client_secret", None)
            log.warning("paymob_intention_without_secret", payment_id=str(payment.id))
            raise CheckoutUnavailable("Paymob returned no client secret")
        intention_id = response.get("id")
        payment.paymob_intention_id = str(intention_id) if intention_id else None
        payment.paymob_order_id = _as_int(response.get("intention_order_id"))
        self._session.commit()
        query = urlencode(
            {"publicKey": self._settings.public_key or "", "clientSecret": client_secret}
        )
        log.info("paymob_checkout_created", payment_id=str(payment.id), purpose=payment.purpose.value)
        return CheckoutResult(payment_id=payment.id, checkout_url=f"{self._settings.checkout_base}/?{query}")

    def _fail_checkout(self, payment: Payment, error: str, status_code: int | None) -> None:
        payment.status = PaymentStatus.failed
        payment.next_reconcile_at = None
        payment.last_callback = {
            "source": "create_intention",
            "error": error,
            "status_code": status_code,
        }
        self._session.commit()


__all__ = [
    "CREDIT_EXPIRY_MONTHS",
    "INTENTION_EXPIRATION_SECONDS",
    "RECONCILE_AFTER",
    "RETURN_PATH",
    "WEBHOOK_PATH",
    "BillingError",
    "BillingService",
    "CheckoutResult",
    "CheckoutUnavailable",
    "MalformedCallback",
    "PaidHandler",
    "UnknownCreditPack",
    "active_catalogue",
    "add_months",
    "billing_data_for",
    "describe_payment",
    "grant_credit_pack",
    "is_linked_parent",
    "paid_handler_for",
    "payment_for_viewer",
    "receipts_for",
    "register_paid_handler",
    "transaction_dedupe_key",
]
```

Task 7 adds `pg_insert`, `PaymobEvent`, `PaymobEventKind`, `SavedCard`, `_OPEN`, `_SETTLED` and `_REDACTED`. Task 8 adds the `RECONCILE_*` backoff constants. Each name lands in the task that first uses it, so ruff sees no unused names at any commit.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_billing_checkout.py tests/architecture/ -v --no-cov`
Expected: all PASS.

- [ ] **Step 6: Pre-commit and commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/billing_repo.py tests/paymob_fixtures.py tests/test_billing_checkout.py
git commit -S -m "feat(billing): create pack checkouts and grant credits through registered paid handlers" -- lemely/db/billing_repo.py tests/paymob_fixtures.py tests/test_billing_checkout.py
```

---

### Task 7: Apply transaction and card-token callbacks

**Files:**
- Modify: `lemely/db/billing_repo.py` (add imports, constants and four methods to `BillingService`)
- Test: `tests/test_billing_callbacks.py`

**Interfaces:**
- Consumes: everything from Task 6; `TokenCipher` (Task 2); `transaction_obj`, `token_obj` and the seeders (`tests/paymob_fixtures.py`).
- Produces:
  - `BillingService.apply_transaction_callback(obj: Mapping[str, Any]) -> None`
  - `BillingService.apply_token_callback(obj: Mapping[str, Any]) -> None`
  - `BillingService.card_token(card: SavedCard) -> str`, which decrypts for Phase 06 and raises `BillingError` when no key is configured.
  - The internal `BillingService._apply_transaction(obj, *, source: str, payment: Payment | None = None) -> None`, which Task 8 reuses.
  - Dedupe keys: `txn:<id>:s?p?v?r?:<refunded_cents>` for transactions and `token:<id>:<order_id>` for tokens.

- [ ] **Step 1: Write the failing callback test**

Create `tests/test_billing_callbacks.py`:

```python
"""BillingService.apply_*_callback: verify, dedupe, grant once (spec §5.1 step 4, §5.5, §6)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db import billing_repo
from lemely.db.billing_repo import BillingService, MalformedCallback
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus, PaymobEvent, SavedCard
from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageGrant
from lemely.runtime.config import PaymobSettings
from lemely.runtime.token_cipher import TokenCipher
from tests.paymob_fixtures import (
    FIXED_NOW,
    PAYMOB_SETTINGS,
    TEST_CARD_TOKEN_KEY,
    FakePaymobClient,
    seed_pack,
    seed_payment,
    seed_user,
    token_obj,
    transaction_obj,
)

if TYPE_CHECKING:
    import uuid
    from typing import Any

    from sqlalchemy.orm import Session, sessionmaker


def _apply(sm: sessionmaker[Session], obj: dict[str, Any], settings: PaymobSettings = PAYMOB_SETTINGS) -> None:
    with sm.begin() as session:
        BillingService(session, FakePaymobClient(), settings, now=lambda: FIXED_NOW).apply_transaction_callback(obj)


def _apply_token(sm: sessionmaker[Session], obj: dict[str, Any], settings: PaymobSettings = PAYMOB_SETTINGS) -> None:
    with sm.begin() as session:
        BillingService(session, FakePaymobClient(), settings, now=lambda: FIXED_NOW).apply_token_callback(obj)


def _setup(sm: sessionmaker[Session], **kwargs: Any) -> tuple[uuid.UUID, uuid.UUID]:
    payer = seed_user(sm)
    pack = seed_pack(sm)
    payment = seed_payment(sm, payer=payer, beneficiary=payer, pack_id=pack, paymob_order_id=265715202, **kwargs)
    return payer, payment


def _payment(sm: sessionmaker[Session], payment_id: uuid.UUID) -> Payment:
    with sm() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        return payment


def _grants(sm: sessionmaker[Session], payment_id: uuid.UUID) -> list[UsageGrant]:
    with sm() as session:
        return list(session.scalars(sa.select(UsageGrant).where(UsageGrant.payment_id == payment_id)))


def _events(sm: sessionmaker[Session]) -> list[PaymobEvent]:
    with sm() as session:
        return list(session.scalars(sa.select(PaymobEvent).order_by(PaymobEvent.created_at)))


def test_a_successful_callback_marks_paid_and_grants_once(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    payer, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.paid
    assert payment.paid_at == FIXED_NOW
    assert payment.paymob_txn_id == 192036465
    assert payment.method == "card"
    assert payment.next_reconcile_at is None
    assert payment.last_callback is not None and payment.last_callback["id"] == 192036465
    (grant,) = _grants(sm, pid)
    assert grant.owner_user_id == payer
    assert grant.units == 100
    (event,) = _events(sm)
    assert event.dedupe_key == "txn:192036465:s1p0v0r0:0"
    assert event.processed_at == FIXED_NOW


def test_a_duplicate_callback_is_a_no_op(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    obj = transaction_obj(merchant_order_id=str(pid))
    _apply(sm, obj)
    _apply(sm, obj)
    assert len(_grants(sm, pid)) == 1
    assert len(_events(sm)) == 1


def test_pending_then_success(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid), success=False, pending=True))
    assert _payment(sm, pid).status is PaymentStatus.pending
    assert _grants(sm, pid) == []
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    assert _payment(sm, pid).status is PaymentStatus.paid
    assert len(_grants(sm, pid)) == 1
    assert len(_events(sm)) == 2


def test_a_declined_callback_fails_without_a_grant(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid), success=False))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.failed
    assert payment.next_reconcile_at is None
    assert _grants(sm, pid) == []


def test_a_late_success_after_failure_is_honoured(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm, status=PaymentStatus.failed)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    assert _payment(sm, pid).status is PaymentStatus.paid
    assert len(_grants(sm, pid)) == 1


@pytest.mark.parametrize(
    "overrides",
    [{"error_occured": True}, {"is_voided": True}, {"is_refunded": True, "refunded_amount_cents": 10000}],
)
def test_success_with_a_bad_flag_is_not_paid(migrated_sessionmaker: sessionmaker[Session], overrides: dict[str, Any]) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid), **overrides))
    assert _payment(sm, pid).status is PaymentStatus.failed
    assert _grants(sm, pid) == []


@pytest.mark.parametrize("overrides", [{"amount_cents": 9999}, {"currency": "USD"}])
def test_amount_or_currency_mismatch_is_failed_mismatch_with_no_grant(
    migrated_sessionmaker: sessionmaker[Session], overrides: dict[str, Any]
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid), **overrides))
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.failed_mismatch
    assert payment.next_reconcile_at is None
    assert _grants(sm, pid) == []
    # A later correct callback cannot revive a mismatched payment.
    _apply(sm, transaction_obj(merchant_order_id=str(pid), txn_id=999))
    assert _payment(sm, pid).status is PaymentStatus.failed_mismatch
    assert _grants(sm, pid) == []


@pytest.mark.parametrize("reference", ["not-a-uuid", "6f1c5d1e-0000-4000-8000-000000000000"])
def test_an_unknown_reference_is_recorded_and_ignored(
    migrated_sessionmaker: sessionmaker[Session], reference: str
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=reference))
    assert _payment(sm, pid).status is PaymentStatus.created
    assert len(_events(sm)) == 1


def test_refund_and_void_flags_on_a_paid_payment(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    _apply(sm, transaction_obj(merchant_order_id=str(pid), is_refunded=True, refunded_amount_cents=4000))
    assert _payment(sm, pid).status is PaymentStatus.partially_refunded
    _apply(sm, transaction_obj(merchant_order_id=str(pid), is_refunded=True, refunded_amount_cents=10000))
    assert _payment(sm, pid).status is PaymentStatus.refunded
    assert len(_grants(sm, pid)) == 1  # clawback of unspent units is an admin action (Phase 07)


def test_void_on_a_paid_payment(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    _apply(sm, transaction_obj(merchant_order_id=str(pid), is_voided=True))
    assert _payment(sm, pid).status is PaymentStatus.voided


def test_a_child_refund_transaction_changes_nothing(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    _apply(
        sm,
        transaction_obj(
            merchant_order_id=str(pid), txn_id=192036466, is_refund=True, has_parent_transaction=True,
            amount_cents=4000,
        ),
    )
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.paid
    assert payment.paymob_txn_id == 192036465
    assert len(_events(sm)) == 2


def test_a_missing_handler_rolls_the_whole_callback_back(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    sm = migrated_sessionmaker
    _, pid = _setup(sm)
    monkeypatch.delitem(billing_repo._PAID_HANDLERS, PaymentPurpose.credit_pack)
    with pytest.raises(RuntimeError, match="no paid handler"):
        _apply(sm, transaction_obj(merchant_order_id=str(pid)))
    assert _payment(sm, pid).status is PaymentStatus.created
    assert _events(sm) == []


def test_a_callback_without_an_id_is_malformed(migrated_sessionmaker: sessionmaker[Session]) -> None:
    obj = transaction_obj()
    del obj["id"]
    with pytest.raises(MalformedCallback):
        _apply(migrated_sessionmaker, obj)


# -- card-token callbacks ------------------------------------------------------


def _cards(sm: sessionmaker[Session]) -> list[SavedCard]:
    with sm() as session:
        return list(session.scalars(sa.select(SavedCard)))


def test_a_token_callback_stores_the_card_encrypted_for_the_payer(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    child = seed_user(sm)
    pack = seed_pack(sm)
    seed_payment(sm, payer=parent, beneficiary=child, pack_id=pack, paymob_order_id=265715202)
    _apply_token(sm, token_obj(token="tok-secret-123"))
    (card,) = _cards(sm)
    assert card.user_id == parent
    assert card.masked_pan == "xxxx-xxxx-xxxx-2346"
    assert card.brand == "MasterCard"
    assert card.paymob_token_id == 15978654
    assert "tok-secret-123" not in card.token
    assert TokenCipher(TEST_CARD_TOKEN_KEY).decrypt(card.token) == "tok-secret-123"
    with sm() as session:
        service = BillingService(session, FakePaymobClient(), PAYMOB_SETTINGS)
        assert service.card_token(card) == "tok-secret-123"
    (event,) = _events(sm)
    assert event.payload["token"] == "[redacted]"
    assert "tok-secret-123" not in str(event.payload)


def test_the_same_card_twice_refreshes_one_row(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    _apply_token(sm, token_obj(token_id=1, token="tok-a", masked_pan="xxxx-xxxx-xxxx-1111"))
    _apply_token(sm, token_obj(token_id=2, token="tok-a", masked_pan="xxxx-xxxx-xxxx-2222"))
    (card,) = _cards(sm)
    assert card.masked_pan == "xxxx-xxxx-xxxx-2222"
    assert card.paymob_token_id == 2


def test_a_duplicate_token_callback_is_a_no_op(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    _apply_token(sm, token_obj())
    _apply_token(sm, token_obj())
    assert len(_cards(sm)) == 1
    assert len(_events(sm)) == 1


def test_a_token_for_an_unknown_order_is_ignored(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    _apply_token(sm, token_obj(order_id="1"))
    assert _cards(sm) == []


def test_without_a_card_key_the_token_is_not_stored(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _setup(sm)
    no_key = PAYMOB_SETTINGS.model_copy(update={"card_token_key": None})
    _apply_token(sm, token_obj(), settings=no_key)
    assert _cards(sm) == []
    with sm() as session:
        service = BillingService(session, FakePaymobClient(), no_key)
        with pytest.raises(billing_repo.BillingError):
            service.card_token(SavedCard(token="v1:x", token_fingerprint="f", masked_pan="m"))


def test_a_token_callback_without_a_token_is_malformed(migrated_sessionmaker: sessionmaker[Session]) -> None:
    obj = token_obj()
    del obj["token"]
    with pytest.raises(MalformedCallback):
        _apply_token(migrated_sessionmaker, obj)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_billing_callbacks.py -v --no-cov`
Expected: FAIL with `AttributeError: 'BillingService' object has no attribute 'apply_transaction_callback'`.

- [ ] **Step 3: Implement**

In `lemely/db/billing_repo.py`:

(a) Add to the imports:

```python
from sqlalchemy.dialects.postgresql import insert as pg_insert
```

and extend the `lemely.db.models.billing` import list with `PaymobEvent`, `PaymobEventKind` and `SavedCard`.

(b) Directly below `RETURN_PATH`, add these constants:

```python
_OPEN: Final = (PaymentStatus.created, PaymentStatus.pending)
_SETTLED: Final = (PaymentStatus.paid, PaymentStatus.partially_refunded, PaymentStatus.refunded)
_REDACTED: Final = "[redacted]"
```

(c) Append these methods to `class BillingService`, after `_fail_checkout`:

```python
    # -- callbacks ------------------------------------------------------------

    def apply_transaction_callback(self, obj: Mapping[str, Any]) -> None:
        """Apply a HMAC-verified transaction callback ``obj`` (spec §5.1 step 4, §6)."""
        self._apply_transaction(obj, source="callback")

    def _record_event(
        self, kind: PaymobEventKind, dedupe_key: str, payload: Mapping[str, Any]
    ) -> bool:
        """Insert the event once; False when ``dedupe_key`` was already recorded."""
        inserted = self._session.execute(
            pg_insert(PaymobEvent)
            .values(kind=kind, dedupe_key=dedupe_key, payload=dict(payload), processed_at=self._now())
            .on_conflict_do_nothing(index_elements=[PaymobEvent.dedupe_key])
            .returning(PaymobEvent.id)
        ).scalar_one_or_none()
        return inserted is not None

    def _payment_for_reference(self, reference: object) -> Payment | None:
        if not isinstance(reference, str) or not reference:
            return None
        return self._session.scalars(
            select(Payment).where(Payment.special_reference == reference).with_for_update()
        ).one_or_none()

    def _apply_transaction(
        self, obj: Mapping[str, Any], *, source: str, payment: Payment | None = None
    ) -> None:
        txn_id = _as_int(obj.get("id"))
        if txn_id is None:
            raise MalformedCallback("transaction callback has no integer id")
        if not self._record_event(PaymobEventKind.transaction, transaction_dedupe_key(obj), obj):
            log.info("paymob_duplicate_transaction", txn_id=txn_id, source=source)
            return
        order = obj.get("order")
        order_map: Mapping[str, Any] = order if isinstance(order, dict) else {}
        if payment is None:
            payment = self._payment_for_reference(order_map.get("merchant_order_id"))
        if payment is None:
            log.warning(
                "paymob_unknown_reference",
                merchant_order_id=str(order_map.get("merchant_order_id"))[:64],
                txn_id=txn_id,
                source=source,
            )
            return
        if (
            _is_true(obj.get("is_refund"))
            or _is_true(obj.get("is_void"))
            or _is_true(obj.get("has_parent_transaction"))
        ):
            # A refund/void child; the parent's own callback carries the state.
            log.info("paymob_child_transaction", payment_id=str(payment.id), txn_id=txn_id)
            return
        if payment.status in _SETTLED:
            self._apply_post_payment_flags(payment, obj, txn_id=txn_id)
            return
        if payment.status in (PaymentStatus.failed_mismatch, PaymentStatus.voided):
            log.warning(
                "paymob_callback_for_closed_payment",
                payment_id=str(payment.id),
                status=payment.status.value,
                txn_id=txn_id,
            )
            return

        payment.last_callback = dict(obj)
        payment.paymob_txn_id = txn_id
        if payment.paymob_order_id is None:
            payment.paymob_order_id = _as_int(order_map.get("id"))
        source_data = obj.get("source_data")
        if isinstance(source_data, dict) and isinstance(source_data.get("type"), str):
            payment.method = source_data["type"]

        amount = _as_int(obj.get("amount_cents"))
        currency = obj.get("currency")
        if amount != payment.amount_minor or currency != payment.currency:
            payment.status = PaymentStatus.failed_mismatch
            payment.next_reconcile_at = None
            log.error(
                "paymob_amount_mismatch",
                payment_id=str(payment.id),
                txn_id=txn_id,
                expected_amount=payment.amount_minor,
                received_amount=amount,
                expected_currency=payment.currency,
                received_currency=str(currency)[:8],
                source=source,
            )
            return

        succeeded = (
            obj.get("success") is True
            and obj.get("pending") is False
            and not _is_true(obj.get("is_voided"))
            and not _is_true(obj.get("is_refunded"))
            and not _is_true(obj.get("error_occured"))
        )
        if succeeded:
            handler = _PAID_HANDLERS.get(payment.purpose)
            if handler is None:
                raise RuntimeError(f"no paid handler registered for {payment.purpose.value}")
            payment.status = PaymentStatus.paid
            payment.paid_at = self._now()
            payment.next_reconcile_at = None
            handler(self._session, payment, obj)
            log.info(
                "paymob_payment_paid",
                payment_id=str(payment.id),
                purpose=payment.purpose.value,
                txn_id=txn_id,
                source=source,
            )
        elif obj.get("pending") is True:
            payment.status = PaymentStatus.pending
        else:
            payment.status = PaymentStatus.failed
            payment.next_reconcile_at = None
            log.info("paymob_payment_failed", payment_id=str(payment.id), txn_id=txn_id, source=source)

    def _apply_post_payment_flags(
        self, payment: Payment, obj: Mapping[str, Any], *, txn_id: int
    ) -> None:
        """Mirror a refund or void on an already-paid payment (no grant changes here)."""
        if txn_id != payment.paymob_txn_id:
            log.warning("paymob_second_transaction_on_paid_payment", payment_id=str(payment.id), txn_id=txn_id)
            return
        payment.last_callback = dict(obj)
        if _is_true(obj.get("is_voided")):
            payment.status = PaymentStatus.voided
        elif _is_true(obj.get("is_refunded")):
            refunded = _as_int(obj.get("refunded_amount_cents")) or 0
            payment.status = (
                PaymentStatus.refunded
                if refunded >= payment.amount_minor
                else PaymentStatus.partially_refunded
            )
        else:
            return
        log.warning(
            "paymob_payment_reversed",
            payment_id=str(payment.id),
            status=payment.status.value,
            txn_id=txn_id,
        )

    def apply_token_callback(self, obj: Mapping[str, Any]) -> None:
        """Store or refresh the payer's saved card from a verified TOKEN callback (§5.5)."""
        token_id = _as_int(obj.get("id"))
        token = obj.get("token")
        if token_id is None or not isinstance(token, str) or not token:
            raise MalformedCallback("token callback lacks an id or a token")
        payload = {**dict(obj), "token": _REDACTED}
        dedupe_key = f"token:{token_id}:{obj.get('order_id')}"
        if not self._record_event(PaymobEventKind.token, dedupe_key, payload):
            log.info("paymob_duplicate_token", token_id=token_id)
            return
        order_id = _as_int(obj.get("order_id"))
        payment = (
            self._session.scalars(select(Payment).where(Payment.paymob_order_id == order_id)).one_or_none()
            if order_id is not None
            else None
        )
        if payment is None:
            log.warning("paymob_token_unknown_order", order_id=str(obj.get("order_id"))[:32])
            return
        if self._cipher is None:
            log.warning("paymob_token_not_stored_no_key", payment_id=str(payment.id))
            return
        fingerprint = self._cipher.fingerprint(token)
        masked_pan = str(obj.get("masked_pan") or "")
        brand = obj.get("card_subtype") if isinstance(obj.get("card_subtype"), str) else None
        card = self._session.scalars(
            select(SavedCard).where(
                SavedCard.user_id == payment.payer_user_id,
                SavedCard.token_fingerprint == fingerprint,
            )
        ).one_or_none()
        if card is None:
            self._session.add(
                SavedCard(
                    user_id=payment.payer_user_id,
                    token=self._cipher.encrypt(token),
                    token_fingerprint=fingerprint,
                    masked_pan=masked_pan,
                    brand=brand,
                    paymob_token_id=token_id,
                )
            )
        else:
            card.masked_pan = masked_pan
            card.brand = brand
            card.paymob_token_id = token_id
            card.is_active = True
        log.info("paymob_card_saved", payment_id=str(payment.id), user_id=str(payment.payer_user_id))

    def card_token(self, card: SavedCard) -> str:
        """The decrypted token for a merchant-initiated charge (Phase 06)."""
        if self._cipher is None:
            raise BillingError("card token key is not configured")
        return self._cipher.decrypt(card.token)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_billing_callbacks.py tests/test_billing_checkout.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 5: Pre-commit and commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/billing_repo.py tests/test_billing_callbacks.py
git commit -S -m "feat(billing): apply verified transaction and card-token callbacks exactly once" -- lemely/db/billing_repo.py tests/test_billing_callbacks.py
```

---

### Task 8: Reconcile missed callbacks and run it on the sweeper

**Files:**
- Modify: `lemely/db/billing_repo.py` (constants and `reconcile_pending`)
- Create: `lemely/web/billing_jobs.py`
- Create: `lemely/web/deps_billing.py`
- Modify: `lemely/web/scheduled_notifications.py` (`Sweeper.billing_reconcile` field and job)
- Modify: `lemely/web/deps.py` (`get_sweeper` and `reset_singletons`)
- Test: `tests/test_billing_reconcile.py`

**Interfaces:**
- Consumes: Tasks 6 and 7 (`BillingService._apply_transaction`, `FakePaymobClient.inquiry_response`).
- Produces:
  - `BillingService.reconcile_pending(*, now: datetime, limit: int = 20) -> int`, which commits per payment.
  - `lemely.web.billing_jobs.reconcile_pending_payments(sessionmaker, client, settings, *, now) -> int`.
  - `lemely.web.deps_billing`: `get_paymob_client() -> PaymobClient` (lru-cached), `get_billing_sessionmaker() -> sessionmaker[Session]`, `get_billing_reconcile_job() -> Callable[[datetime], int] | None` (None when `checkout_configured` is False), `reset_billing_singletons() -> None`.
  - `Sweeper.billing_reconcile: Callable[[datetime], int] | None = None`, run as job name `"billing.reconcile_pending"`.

- [ ] **Step 1: Write the failing reconcile test**

Create `tests/test_billing_reconcile.py`:

```python
"""Reconciliation of missed callbacks by transaction inquiry (spec §5.10, §6)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import sqlalchemy as sa

from lemely.db.announcement_repo import AnnouncementService
from lemely.db.billing_repo import BillingService
from lemely.db.class_repo import ClassService
from lemely.db.models.billing import Payment, PaymentStatus, PaymobEvent
from lemely.db.models.usage import UsageGrant
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.io.paymob.client import PaymobError
from lemely.runtime.config import NotificationsSettings
from lemely.web.billing_jobs import reconcile_pending_payments
from lemely.web.push import RecordingPushTransport
from lemely.web.scheduled_notifications import Sweeper
from tests.paymob_fixtures import (
    FIXED_NOW,
    PAYMOB_SETTINGS,
    FakePaymobClient,
    seed_pack,
    seed_payment,
    seed_user,
    transaction_obj,
)

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker


def _due_payment(sm: sessionmaker[Session], *, age: timedelta, **kwargs: object) -> uuid.UUID:
    payer = seed_user(sm)
    pack = seed_pack(sm)
    created = FIXED_NOW - age
    return seed_payment(sm, payer=payer, beneficiary=payer, pack_id=pack, created_at=created, **kwargs)  # type: ignore[arg-type]


def _reconcile(sm: sessionmaker[Session], client: FakePaymobClient, now: datetime = FIXED_NOW) -> int:
    with sm() as session:
        return BillingService(session, client, PAYMOB_SETTINGS, now=lambda: now).reconcile_pending(now=now)


def _payment(sm: sessionmaker[Session], pid: uuid.UUID) -> Payment:
    with sm() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        return payment


def _grant_count(sm: sessionmaker[Session], pid: uuid.UUID) -> int:
    with sm() as session:
        return len(session.scalars(sa.select(UsageGrant).where(UsageGrant.payment_id == pid)).all())


def test_a_payment_younger_than_fifteen_minutes_is_left_alone(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=10))
    client = FakePaymobClient()
    assert _reconcile(sm, client) == 0
    assert client.inquiries == []
    assert _payment(sm, pid).status is PaymentStatus.created


def test_a_missed_success_callback_is_found_by_inquiry_and_granted(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20))
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(merchant_order_id=str(pid))
    assert _reconcile(sm, client) == 1
    assert client.inquiries == [str(pid)]
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.paid
    assert payment.next_reconcile_at is None
    assert _grant_count(sm, pid) == 1


def test_the_late_real_callback_after_inquiry_is_a_duplicate(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20))
    obj = transaction_obj(merchant_order_id=str(pid))
    client = FakePaymobClient()
    client.inquiry_response = obj
    _reconcile(sm, client)
    with sm.begin() as session:
        BillingService(session, client, PAYMOB_SETTINGS).apply_transaction_callback(obj)
    assert _grant_count(sm, pid) == 1
    with sm() as session:
        assert len(session.scalars(sa.select(PaymobEvent)).all()) == 1


def test_no_transaction_yet_backs_off_15m_then_30m(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20))
    client = FakePaymobClient()
    client.inquiry_response = None
    _reconcile(sm, client)
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.created
    assert payment.reconcile_attempts == 1
    assert payment.next_reconcile_at == FIXED_NOW + timedelta(minutes=15)
    later = FIXED_NOW + timedelta(minutes=15)
    _reconcile(sm, client, now=later)
    payment = _payment(sm, pid)
    assert payment.reconcile_attempts == 2
    assert payment.next_reconcile_at == later + timedelta(minutes=30)


def test_backoff_is_capped_at_four_hours(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(hours=1))
    with sm.begin() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        payment.reconcile_attempts = 9
    client = FakePaymobClient()
    _reconcile(sm, client)
    assert _payment(sm, pid).next_reconcile_at == FIXED_NOW + timedelta(hours=4)


def test_after_24_hours_without_a_transaction_it_is_failed(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(hours=24, minutes=1))
    client = FakePaymobClient()
    client.inquiry_response = None
    _reconcile(sm, client)
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.failed
    assert payment.next_reconcile_at is None


def test_a_still_pending_transaction_keeps_being_checked(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20))
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(merchant_order_id=str(pid), success=False, pending=True)
    _reconcile(sm, client)
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.pending
    assert payment.next_reconcile_at == FIXED_NOW + timedelta(minutes=15)


def test_an_inquiry_failure_reschedules_and_never_fails_the_payment(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(hours=30))
    client = FakePaymobClient()
    client.inquiry_response = PaymobError("Paymob POST ... timed out", timeout=True)
    assert _reconcile(sm, client) == 1
    payment = _payment(sm, pid)
    assert payment.status is PaymentStatus.created
    assert payment.reconcile_attempts == 1


def test_closed_payments_are_never_inquired(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _due_payment(sm, age=timedelta(hours=1), status=PaymentStatus.paid)
    _due_payment(sm, age=timedelta(hours=1), status=PaymentStatus.failed)
    client = FakePaymobClient()
    assert _reconcile(sm, client) == 0
    assert client.inquiries == []


def test_the_job_function_opens_its_own_session(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    pid = _due_payment(sm, age=timedelta(minutes=20))
    client = FakePaymobClient()
    client.inquiry_response = transaction_obj(merchant_order_id=str(pid))
    assert reconcile_pending_payments(sm, client, PAYMOB_SETTINGS, now=FIXED_NOW) == 1
    assert _payment(sm, pid).status is PaymentStatus.paid


def _sweeper(sm: sessionmaker[Session], **kwargs: object) -> Sweeper:
    return Sweeper(
        sessionmaker=sm,
        announcements=AnnouncementService(sm, ClassService(sm)),
        notifications=NotificationService(sm, NotificationPreferencesService(sm)),
        transport=RecordingPushTransport(),
        settings=NotificationsSettings(),
        now=lambda: FIXED_NOW,
        **kwargs,  # type: ignore[arg-type]
    )


def test_the_sweeper_runs_billing_reconcile_pending_when_wired(migrated_sessionmaker: sessionmaker[Session]) -> None:
    seen: list[datetime] = []

    def job(now: datetime) -> int:
        seen.append(now)
        return 3

    results = _sweeper(migrated_sessionmaker, billing_reconcile=job).sweep_once()
    assert results["billing.reconcile_pending"] == 3
    assert seen == [FIXED_NOW]


def test_the_sweeper_leaves_billing_out_when_paymob_is_unconfigured(migrated_sessionmaker: sessionmaker[Session]) -> None:
    assert "billing.reconcile_pending" not in _sweeper(migrated_sessionmaker).sweep_once()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_billing_reconcile.py -v --no-cov`
Expected: collection error, `ModuleNotFoundError: No module named 'lemely.web.billing_jobs'`.

- [ ] **Step 3: Implement `reconcile_pending`**

In `lemely/db/billing_repo.py`:

(a) Directly below `RECONCILE_AFTER`, add:

```python
RECONCILE_GIVE_UP_AFTER: Final = timedelta(hours=24)
RECONCILE_MAX_BACKOFF: Final = timedelta(hours=4)
RECONCILE_BATCH: Final = 20
```

(b) Append these methods to `class BillingService`, after `card_token`:

```python
    # -- reconciliation (spec §5.10) -------------------------------------------

    def reconcile_pending(self, *, now: datetime, limit: int = RECONCILE_BATCH) -> int:
        """Inquire every open payment that is due; commit after each. Returns how many.

        ``FOR UPDATE SKIP LOCKED`` lets two replicas run this at once without
        inquiring the same payment twice. A payment still open after the inquiry
        is pushed back on a doubling schedule (15m, 30m, 1h, 2h, 4h, 4h...) until it
        is 24 hours old, then marked ``failed``. An inquiry error only reschedules:
        a Paymob outage must never fail a payment the customer may have paid.
        """
        handled = 0
        for _ in range(limit):
            payment = self._session.scalars(
                select(Payment)
                .where(Payment.status.in_(_OPEN), Payment.next_reconcile_at <= now)
                .order_by(Payment.next_reconcile_at, Payment.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            ).first()
            if payment is None:
                break
            self._reconcile_one(payment, now=now)
            self._session.commit()
            handled += 1
        return handled

    def _reconcile_one(self, payment: Payment, *, now: datetime) -> None:
        try:
            obj = self._client.inquire_by_order_ref(payment.special_reference)
        except PaymobError as exc:
            log.warning(
                "paymob_inquiry_failed",
                payment_id=str(payment.id),
                status_code=exc.status_code,
                timeout=exc.timeout,
            )
            self._schedule_next(payment, now=now)
            return
        if obj is not None and _as_int(obj.get("id")) is not None:
            self._apply_transaction(obj, source="inquiry", payment=payment)
        if payment.status not in _OPEN:
            payment.next_reconcile_at = None
            return
        if now - payment.created_at >= RECONCILE_GIVE_UP_AFTER:
            payment.status = PaymentStatus.failed
            payment.next_reconcile_at = None
            log.info("paymob_payment_abandoned", payment_id=str(payment.id))
            return
        self._schedule_next(payment, now=now)

    def _schedule_next(self, payment: Payment, *, now: datetime) -> None:
        payment.reconcile_attempts += 1
        delay = min(RECONCILE_AFTER * (2 ** (payment.reconcile_attempts - 1)), RECONCILE_MAX_BACKOFF)
        payment.next_reconcile_at = now + delay
```

Note: in `_apply_transaction`, when `payment` is passed in (reconcile), the payment row is already locked by the reconcile select, and `_payment_for_reference` is skipped.

- [ ] **Step 4: Implement the job module**

Create `lemely/web/billing_jobs.py`:

```python
"""Billing sweeper jobs (billing spec §3 "Jobs", §5.10).

``billing.reconcile_pending`` inquires Paymob for payments whose callback never
came (about 2% of transactions; abandoned 3DS sends none). Idempotency comes
from row state: ``FOR UPDATE SKIP LOCKED`` on each payment, the unique
``paymob_events.dedupe_key``, and status transitions that only move forward. A
second replica or a re-run after a crash therefore never double-grants.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.db.billing_repo import BillingService

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings


def reconcile_pending_payments(
    sessionmaker: sessionmaker[Session],
    client: PaymobClient,
    settings: PaymobSettings,
    *,
    now: datetime,
) -> int:
    """One pass of ``billing.reconcile_pending``; returns the payments inquired."""
    with sessionmaker() as session:
        return BillingService(session, client, settings, now=lambda: now).reconcile_pending(now=now)


__all__ = ["reconcile_pending_payments"]
```

Create `lemely/web/deps_billing.py`:

```python
"""Dependencies shared by the billing and Paymob webhook routers (billing spec §3).

Process-wide, lazily built singletons, the ``lru_cache`` pattern of
``lemely.web.deps``; tests override them through ``app.dependency_overrides``.
``deps.reset_singletons`` calls :func:`reset_billing_singletons`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from lemely.db.session import get_sessionmaker
from lemely.io.paymob.client import PaymobClient
from lemely.web.billing_jobs import reconcile_pending_payments
from lemely.web.deps import get_settings

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker


@lru_cache(maxsize=1)
def get_paymob_client() -> PaymobClient:
    """The process-wide Paymob client (it caches the one-hour auth token)."""
    return PaymobClient(get_settings().paymob)


def get_billing_sessionmaker() -> sessionmaker[Session]:
    """The process sessionmaker, as a dependency tests can point at a throwaway DB."""
    return get_sessionmaker(get_settings())


def get_billing_reconcile_job() -> Callable[[datetime], int] | None:
    """The ``billing.reconcile_pending`` job, or ``None`` when Paymob is unconfigured."""
    settings = get_settings().paymob
    if not settings.checkout_configured:
        return None

    def job(now: datetime) -> int:
        return reconcile_pending_payments(
            get_billing_sessionmaker(), get_paymob_client(), settings, now=now
        )

    return job


def reset_billing_singletons() -> None:
    """Clear this module's cached providers (``deps.reset_singletons`` does not know them)."""
    get_paymob_client.cache_clear()


__all__ = [
    "get_billing_reconcile_job",
    "get_billing_sessionmaker",
    "get_paymob_client",
    "reset_billing_singletons",
]
```

- [ ] **Step 5: Wire the sweeper**

In `lemely/web/scheduled_notifications.py`, in `class Sweeper`, add this field after `email_daily_cap: int = 60`:

```python
    #: ``billing.reconcile_pending`` (billing spec §5.10), given only when Paymob is
    #: configured, the same optional-collaborator pattern as ``email_provider``.
    billing_reconcile: Callable[[datetime], int] | None = None
```

In `Sweeper.sweep_once`, directly before `return run_jobs(jobs)`, add:

```python
        billing_reconcile = self.billing_reconcile
        if billing_reconcile is not None:
            jobs.append(("billing.reconcile_pending", lambda: billing_reconcile(moment)))
```

In `lemely/web/deps.py`, in `get_sweeper`, add a local import as the function's first statement:

```python
    from lemely.web.deps_billing import get_billing_reconcile_job
```

and add this keyword argument to the `Sweeper(...)` call, after `email_daily_cap=settings.tutoring.email_daily_cap,`:

```python
        billing_reconcile=get_billing_reconcile_job(),
```

In `reset_singletons`, after the last two lines (`from lemely.web.deps_tutoring import reset_tutoring_singletons` / `reset_tutoring_singletons()`), append:

```python
    from lemely.web.deps_billing import reset_billing_singletons

    reset_billing_singletons()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_billing_reconcile.py tests/test_billing_callbacks.py tests/test_scheduled_notifications.py tests/test_web_app.py tests/architecture/ -v --no-cov`
Expected: all PASS. The existing sweeper tests still see exactly their old job sets, because they build a `Sweeper` without `billing_reconcile`.

- [ ] **Step 7: Pre-commit and commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/billing_repo.py lemely/web/billing_jobs.py lemely/web/deps_billing.py lemely/web/scheduled_notifications.py lemely/web/deps.py tests/test_billing_reconcile.py
git commit -S -m "feat(billing): reconcile missed Paymob callbacks by inquiry on the sweeper" -- lemely/db/billing_repo.py lemely/web/billing_jobs.py lemely/web/deps_billing.py lemely/web/scheduled_notifications.py lemely/web/deps.py tests/test_billing_reconcile.py
```

---

### Task 9: `/api/billing` router (catalogue, pack checkout, payment status, receipts, saved cards)

**Files:**
- Create: `lemely/web/schemas_billing.py`
- Create: `lemely/web/routers/billing.py`
- Modify: `lemely/db/billing_repo.py` (add `saved_cards_for`)
- Modify: `lemely/web/deps_billing.py` (checkout limiter)
- Modify: `lemely/web/app.py` (import and `include_router`)
- Modify: `tests/test_authz_matrix_complete.py` (five entries; `TUTORING_PARTY` heading count 1 -> 6)
- Test: `tests/test_web_billing.py`

**Interfaces:**
- Consumes:
  - From Task 6: `BillingService.create_pack_checkout`, `CheckoutUnavailable`, `UnknownCreditPack`, `active_catalogue`, `payment_for_viewer`, `receipts_for`, `describe_payment`, `is_linked_parent`.
  - From Task 7: the `SavedCard` import in `billing_repo`.
  - From Task 8: `get_paymob_client`, `get_billing_sessionmaker`.
  - `require_role`, `AuthContext`, `get_settings` from `lemely.web.deps`.
  - `SlidingWindowLimiter`.
  - From Task 2: `TokenCipher` (tests only, to seed a sealed card).
- Produces:
  - Route `GET /api/billing/catalogue` returns `CatalogueDTO`.
  - Route `POST /api/billing/checkout/pack` takes `PackCheckoutRequest{creditPackId, beneficiaryId?}` and returns 201 `CheckoutDTO{paymentId, checkoutUrl}`.
  - Route `GET /api/billing/payments/{payment_id}` returns `PaymentStatusDTO`.
  - Route `GET /api/billing/receipts` returns `ReceiptListDTO`.
  - Route `GET /api/billing/cards` (index R3) returns `SavedCardList{cards: [SavedCardView{cardId, maskedPan, brand}]}`: the caller's own active saved cards, masked only, newest first. This is the shape Phase 08 types as `SavedCardList`; `brand` is `""` when Paymob sent none.
  - `billing_repo.saved_cards_for(session, user_id: uuid.UUID) -> list[SavedCard]`.
  - All five routes are guarded by `require_role(student, parent, teacher)`.
  - `deps_billing.get_checkout_limiter() -> SlidingWindowLimiter` allows 5 per user per 60 s.

- [ ] **Step 1: Write the failing router test**

Create `tests/test_web_billing.py`:

```python
"""/api/billing: catalogue, pack checkout, payment status, receipts, IDOR (spec §5.5, §7)."""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.db.models.billing import Payment, PaymentStatus, PlanAudience, PlanTier, SavedCard
from lemely.db.models.enums import Role
from lemely.io.paymob.client import PaymobError
from lemely.runtime.config import PaymobSettings, Settings
from lemely.runtime.token_cipher import TokenCipher
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_settings
from lemely.web.deps_billing import get_billing_sessionmaker, get_checkout_limiter, get_paymob_client
from lemely.web.ratelimit import SlidingWindowLimiter
from tests.paymob_fixtures import (
    FIXED_NOW,
    PAYMOB_SETTINGS,
    TEST_CARD_TOKEN_KEY,
    FakePaymobClient,
    link_parent,
    seed_pack,
    seed_payment,
    seed_user,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def paymob() -> FakePaymobClient:
    return FakePaymobClient()


@pytest.fixture
def client(migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient) -> Iterator[TestClient]:
    settings = Settings().model_copy(update={"paymob": PAYMOB_SETTINGS})
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_billing_sessionmaker] = lambda: migrated_sessionmaker
    app.dependency_overrides[get_paymob_client] = lambda: paymob
    app.dependency_overrides[get_checkout_limiter] = lambda: SlidingWindowLimiter(
        limit=100, window_seconds=60, clock=time.monotonic
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


def _tier(sm: sessionmaker[Session], code: str, audience: PlanAudience, *, active: bool = True) -> None:
    with sm.begin() as session:
        session.add(
            PlanTier(code=code, name=code, price_minor=9900, audience=audience, is_active=active, allowance_units=5000)
        )


# -- catalogue ----------------------------------------------------------------


def test_catalogue_shows_the_callers_audience_and_active_packs_only(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    _tier(sm, "student_monthly", PlanAudience.student)
    _tier(sm, "teacher_monthly", PlanAudience.teacher)
    _tier(sm, "student_retired", PlanAudience.student, active=False)
    seed_pack(sm, code="pack_100", name="100 credits")
    seed_pack(sm, code="pack_old", is_active=False)

    _as(client, seed_user(sm), Role.student)
    body = client.get("/api/billing/catalogue").json()
    assert [t["code"] for t in body["planTiers"]] == ["student_monthly"]
    assert [p["code"] for p in body["creditPacks"]] == ["pack_100"]
    assert body["creditPacks"][0]["credits"] == 100
    assert "allowanceUnits" not in body["planTiers"][0]  # allowances stay hidden (§2.1)

    _as(client, seed_user(sm, Role.parent), Role.parent)
    assert [t["code"] for t in client.get("/api/billing/catalogue").json()["planTiers"]] == ["student_monthly"]

    _as(client, seed_user(sm, Role.teacher), Role.teacher)
    assert [t["code"] for t in client.get("/api/billing/catalogue").json()["planTiers"]] == ["teacher_monthly"]


# -- pack checkout --------------------------------------------------------------


def test_a_student_buys_a_pack_for_themselves(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient
) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    pack = seed_pack(sm, price_minor=10000)
    _as(client, student, Role.student)
    response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(pack)})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["checkoutUrl"].startswith("https://eg.checkout.paymob.com/?publicKey=egy_pk_test_public")
    assert "egy_sk_test_secret" not in response.text
    with sm() as session:
        payment = session.get(Payment, uuid.UUID(body["paymentId"]))
        assert payment is not None
        assert payment.payer_user_id == payment.beneficiary_user_id == student
        assert payment.amount_minor == 10000
    assert paymob.intentions[0]["amount"] == 10000


def test_the_client_cannot_set_the_price(client: TestClient, migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _as(client, seed_user(sm), Role.student)
    pack = seed_pack(sm)
    response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(pack), "priceMinor": 1})
    assert response.status_code == 422


def test_a_student_cannot_buy_for_someone_else(client: TestClient, migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _as(client, seed_user(sm), Role.student)
    other = seed_user(sm)
    pack = seed_pack(sm)
    response = client.post(
        "/api/billing/checkout/pack", json={"creditPackId": str(pack), "beneficiaryId": str(other)}
    )
    assert response.status_code == 403
    with sm() as session:
        assert session.scalars(sa.select(Payment)).all() == []


def test_a_parent_buys_for_a_linked_child(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    child = seed_user(sm)
    link_parent(sm, parent_id=parent, child_id=child)
    pack = seed_pack(sm)
    _as(client, parent, Role.parent)
    response = client.post(
        "/api/billing/checkout/pack", json={"creditPackId": str(pack), "beneficiaryId": str(child)}
    )
    assert response.status_code == 201, response.text
    with sm() as session:
        payment = session.get(Payment, uuid.UUID(response.json()["paymentId"]))
        assert payment is not None
        assert (payment.payer_user_id, payment.beneficiary_user_id) == (parent, child)


def test_a_parent_cannot_buy_for_an_unlinked_student(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    _as(client, seed_user(sm, Role.parent), Role.parent)
    stranger = seed_user(sm)
    pack = seed_pack(sm)
    for beneficiary in (stranger, uuid.uuid4()):
        response = client.post(
            "/api/billing/checkout/pack", json={"creditPackId": str(pack), "beneficiaryId": str(beneficiary)}
        )
        assert response.status_code == 403  # same answer whether or not the user exists


def test_a_parent_must_name_the_child(client: TestClient, migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _as(client, seed_user(sm, Role.parent), Role.parent)
    response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(seed_pack(sm))})
    assert response.status_code == 422


def test_unknown_and_inactive_packs_are_404(client: TestClient, migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _as(client, seed_user(sm), Role.student)
    for pack in (uuid.uuid4(), seed_pack(sm, is_active=False)):
        response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(pack)})
        assert response.status_code == 404


def test_paymob_failure_is_503_with_a_friendly_message(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session], paymob: FakePaymobClient
) -> None:
    sm = migrated_sessionmaker
    _as(client, seed_user(sm), Role.student)
    paymob.intention_response = PaymobError("boom", status_code=502)
    response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(seed_pack(sm))})
    assert response.status_code == 503
    assert "try again" in response.json()["detail"]
    with sm() as session:
        assert session.scalars(sa.select(Payment.status)).one() is PaymentStatus.failed


def test_unconfigured_paymob_is_503(client: TestClient, migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    bare = Settings().model_copy(update={"paymob": PaymobSettings()})
    client.app.dependency_overrides[get_settings] = lambda: bare  # type: ignore[union-attr]
    _as(client, seed_user(sm), Role.student)
    response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(seed_pack(sm))})
    assert response.status_code == 503


def test_checkout_is_rate_limited_per_user(client: TestClient, migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=lambda: 0.0)
    client.app.dependency_overrides[get_checkout_limiter] = lambda: limiter  # type: ignore[union-attr]
    _as(client, seed_user(sm), Role.student)
    pack = seed_pack(sm)
    codes = [client.post("/api/billing/checkout/pack", json={"creditPackId": str(pack)}).status_code for _ in range(3)]
    assert codes == [201, 201, 429]
    response = client.post("/api/billing/checkout/pack", json={"creditPackId": str(pack)})
    assert int(response.headers["Retry-After"]) >= 1


# -- payment status -------------------------------------------------------------


def test_payment_status_is_visible_to_payer_and_beneficiary_only(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    child = seed_user(sm)
    pack = seed_pack(sm, name="100 credits")
    pid = seed_payment(sm, payer=parent, beneficiary=child, pack_id=pack, status=PaymentStatus.paid, paid_at=FIXED_NOW)
    for user, role in ((parent, Role.parent), (child, Role.student)):
        _as(client, user, role)
        body = client.get(f"/api/billing/payments/{pid}").json()
        assert body["status"] == "paid"
        assert body["description"] == "100 credits"
        assert body["amountMinor"] == 10000
    _as(client, seed_user(sm), Role.student)
    assert client.get(f"/api/billing/payments/{pid}").status_code == 404
    assert client.get(f"/api/billing/payments/{uuid.uuid4()}").status_code == 404
    assert client.get("/api/billing/payments/not-a-uuid").status_code == 422


# -- receipts -------------------------------------------------------------------


def test_receipts_list_only_payments_the_caller_paid(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    child = seed_user(sm)
    pack = seed_pack(sm)
    paid = seed_payment(sm, payer=parent, beneficiary=child, pack_id=pack, status=PaymentStatus.paid, paid_at=FIXED_NOW)
    seed_payment(sm, payer=parent, beneficiary=child, pack_id=pack, status=PaymentStatus.created)
    seed_payment(sm, payer=parent, beneficiary=child, pack_id=pack, status=PaymentStatus.failed)

    _as(client, parent, Role.parent)
    receipts = client.get("/api/billing/receipts").json()["receipts"]
    assert [r["paymentId"] for r in receipts] == [str(paid)]
    assert receipts[0]["beneficiaryId"] == str(child)

    _as(client, child, Role.student)  # the beneficiary is not the payer: no receipts
    assert client.get("/api/billing/receipts").json()["receipts"] == []


# -- saved cards (index R3) -------------------------------------------------------


def _card(
    sm: sessionmaker[Session], user_id: uuid.UUID, *, token: str, pan: str, active: bool = True
) -> uuid.UUID:
    cipher = TokenCipher(TEST_CARD_TOKEN_KEY)
    card_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            SavedCard(
                id=card_id,
                user_id=user_id,
                token=cipher.encrypt(token),
                token_fingerprint=cipher.fingerprint(token),
                masked_pan=pan,
                brand="MasterCard",
                is_active=active,
            )
        )
    return card_id


def test_cards_list_only_the_callers_active_cards_masked(
    client: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    parent = seed_user(sm, Role.parent)
    other = seed_user(sm, Role.parent)
    mine = _card(sm, parent, token="tok-parent-secret", pan="xxxx-xxxx-xxxx-2346")
    _card(sm, parent, token="tok-old", pan="xxxx-xxxx-xxxx-1111", active=False)
    _card(sm, other, token="tok-other-secret", pan="xxxx-xxxx-xxxx-9999")

    _as(client, parent, Role.parent)
    response = client.get("/api/billing/cards")
    assert response.status_code == 200
    assert response.json() == {
        "cards": [{"cardId": str(mine), "maskedPan": "xxxx-xxxx-xxxx-2346", "brand": "MasterCard"}]
    }
    assert "tok-" not in response.text  # neither plaintext nor ciphertext leaves the server
    assert "v1:" not in response.text

    _as(client, seed_user(sm), Role.student)  # IDOR: nobody else sees them
    assert client.get("/api/billing/cards").json() == {"cards": []}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_web_billing.py -v --no-cov`
Expected: collection error, `ImportError: cannot import name 'get_checkout_limiter' from 'lemely.web.deps_billing'`.

- [ ] **Step 3: Add the checkout limiter**

In `lemely/web/deps_billing.py`:

(a) Add these imports with the others:

```python
import time

from lemely.web.ratelimit import SlidingWindowLimiter
```

(b) Add this after `get_billing_sessionmaker`:

```python
#: Checkout creation (spec §7): 5 per user per minute. A real buyer needs one; a
#: retry after a declined card needs a second. Each checkout also costs a Paymob
#: intention, so this bounds what one account can make Paymob do.
_CHECKOUT_LIMIT = 5
_CHECKOUT_WINDOW_SECONDS = 60.0


@lru_cache(maxsize=1)
def get_checkout_limiter() -> SlidingWindowLimiter:
    """Per-user limiter for ``POST /api/billing/checkout/*`` (keyed by user id)."""
    return SlidingWindowLimiter(
        limit=_CHECKOUT_LIMIT, window_seconds=_CHECKOUT_WINDOW_SECONDS, clock=time.monotonic
    )
```

(c) In `reset_billing_singletons`, add `get_checkout_limiter.cache_clear()`, and add `"get_checkout_limiter"` to `__all__`.

(d) In `lemely/db/billing_repo.py`, add this read query after `receipts_for`, and add `"saved_cards_for"` to `__all__`. `SavedCard` is already imported since Task 7.

```python
def saved_cards_for(session: Session, user_id: uuid.UUID) -> list[SavedCard]:
    """The user's own active saved cards, newest first (index R3; masked fields only leave)."""
    return list(
        session.scalars(
            select(SavedCard)
            .where(SavedCard.user_id == user_id, SavedCard.is_active.is_(True))
            .order_by(SavedCard.created_at.desc(), SavedCard.id)
        ).all()
    )
```

- [ ] **Step 4: Write the DTOs**

Create `lemely/web/schemas_billing.py`:

```python
"""Billing API DTOs (camelCase wire format; billing spec §5.5, §2.5).

Allowance sizes are deliberately absent from the catalogue: users see a usage
meter, never the unit count behind it (spec §2.1).
"""

from __future__ import annotations

import uuid  # noqa: TC003 - pydantic reads the type at runtime
from datetime import datetime  # noqa: TC003 - pydantic reads the type at runtime
from typing import Any

from pydantic import Field

from lemely.web.schemas import ApiModel


class PlanTierDTO(ApiModel):
    planTierId: str
    code: str
    name: str
    priceMinor: int
    currency: str
    interval: str | None = None
    audience: str
    includedSeats: int
    extraSeatPriceMinor: int
    features: dict[str, Any] = Field(default_factory=dict)


class CreditPackDTO(ApiModel):
    creditPackId: str
    code: str
    name: str
    credits: int
    priceMinor: int
    currency: str


class CatalogueDTO(ApiModel):
    """Response for ``GET /api/billing/catalogue``."""

    planTiers: list[PlanTierDTO] = Field(default_factory=list)
    creditPacks: list[CreditPackDTO] = Field(default_factory=list)


class PackCheckoutRequest(ApiModel):
    """Body for ``POST /api/billing/checkout/pack``; the price is never client-sent."""

    creditPackId: uuid.UUID
    beneficiaryId: uuid.UUID | None = None


class CheckoutDTO(ApiModel):
    paymentId: str
    checkoutUrl: str


class PaymentStatusDTO(ApiModel):
    """Response for ``GET /api/billing/payments/{id}`` (the return page polls it)."""

    paymentId: str
    status: str
    purpose: str
    amountMinor: int
    currency: str
    description: str
    paidAt: datetime | None = None


class ReceiptDTO(ApiModel):
    paymentId: str
    purpose: str
    description: str
    amountMinor: int
    currency: str
    status: str
    paidAt: datetime
    beneficiaryId: str


class ReceiptListDTO(ApiModel):
    """Response for ``GET /api/billing/receipts``: money the caller paid (§2.5)."""

    receipts: list[ReceiptDTO] = Field(default_factory=list)


class SavedCardView(ApiModel):
    """One saved card, masked only; the token never leaves the server (spec §7)."""

    cardId: str
    maskedPan: str
    brand: str


class SavedCardList(ApiModel):
    """Response for ``GET /api/billing/cards`` (index R3; Phase 08's ``SavedCardList``)."""

    cards: list[SavedCardView] = Field(default_factory=list)
```

- [ ] **Step 5: Write the router**

Create `lemely/web/routers/billing.py`:

```python
"""Billing endpoints: catalogue, pack checkout, payment status, receipts (billing spec §5.5, §7).

**Authz.** Students, parents and teachers only (``require_role``). Every
object-level check keys on ``auth.user_id``:

* checkout: a student or teacher buys only for themselves; a parent only for a
  child linked by ``parent_child_links``. An unlinked or non-existent child is
  the same 403, so the route is no user-existence oracle;
* payment status: payer or beneficiary, else 404 (same answer as a missing id);
* receipts: payments the caller *paid for*; a child never sees a parent's
  receipts, only the plan and balance they were bought.

The price is computed on the server from ``credit_packs``; the request body
forbids extra fields, so a client-sent price is a 422.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, sessionmaker  # noqa: TC002 - FastAPI reads the type at runtime

from lemely.db.billing_repo import (
    BillingService,
    CheckoutUnavailable,
    UnknownCreditPack,
    active_catalogue,
    describe_payment,
    is_linked_parent,
    payment_for_viewer,
    receipts_for,
    saved_cards_for,
)
from lemely.db.models.billing import PlanAudience
from lemely.db.models.enums import Role
from lemely.io.paymob.client import PaymobClient
from lemely.runtime.config import Settings
from lemely.web.deps import AuthContext, get_settings, require_role
from lemely.web.deps_billing import get_billing_sessionmaker, get_checkout_limiter, get_paymob_client
from lemely.web.ratelimit import SlidingWindowLimiter
from lemely.web.schemas_billing import (
    CatalogueDTO,
    CheckoutDTO,
    CreditPackDTO,
    PackCheckoutRequest,
    PaymentStatusDTO,
    PlanTierDTO,
    ReceiptDTO,
    ReceiptListDTO,
    SavedCardList,
    SavedCardView,
)

require_billing_party: Final = require_role(Role.student, Role.parent, Role.teacher)

router = APIRouter(prefix="/api/billing")

_UNAVAILABLE = "Payments are temporarily unavailable. Please try again in a few minutes."


def _beneficiary(
    session: Session, auth: AuthContext, payer: uuid.UUID, requested: uuid.UUID | None
) -> uuid.UUID:
    if auth.role == Role.parent.value:
        if requested is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "beneficiaryId is required for a parent"
            )
        if not is_linked_parent(session, payer, requested):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only buy for a linked child")
        return requested
    if requested is not None and requested != payer:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only buy for yourself")
    return payer


@router.get("/catalogue", response_model=CatalogueDTO)
def get_catalogue(
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    sm: Annotated[sessionmaker[Session], Depends(get_billing_sessionmaker)],
) -> CatalogueDTO:
    """Active plan tiers for the caller's audience, and every active credit pack."""
    audience = PlanAudience.teacher if auth.role == Role.teacher.value else PlanAudience.student
    with sm() as session:
        tiers, packs = active_catalogue(session, audience=audience)
        return CatalogueDTO(
            planTiers=[
                PlanTierDTO(
                    planTierId=str(t.id),
                    code=t.code,
                    name=t.name,
                    priceMinor=t.price_minor,
                    currency=t.currency,
                    interval=t.interval.value if t.interval is not None else None,
                    audience=t.audience.value,
                    includedSeats=t.included_seats,
                    extraSeatPriceMinor=t.extra_seat_price_minor,
                    features=dict(t.features),
                )
                for t in tiers
            ],
            creditPacks=[
                CreditPackDTO(
                    creditPackId=str(p.id),
                    code=p.code,
                    name=p.name,
                    credits=p.units,
                    priceMinor=p.price_minor,
                    currency=p.currency,
                )
                for p in packs
            ],
        )


@router.post("/checkout/pack", response_model=CheckoutDTO, status_code=status.HTTP_201_CREATED)
def checkout_pack(
    body: PackCheckoutRequest,
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    sm: Annotated[sessionmaker[Session], Depends(get_billing_sessionmaker)],
    client: Annotated[PaymobClient, Depends(get_paymob_client)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_checkout_limiter)],
) -> CheckoutDTO:
    """Create a one-off credit-pack checkout and return the Unified Checkout URL."""
    if not limiter.allow(auth.user_id):
        retry = limiter.retry_after(auth.user_id)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many checkout attempts; retry in {retry}s.",
            headers={"Retry-After": str(retry)},
        )
    payer = uuid.UUID(auth.user_id)
    with sm() as session:
        beneficiary = _beneficiary(session, auth, payer, body.beneficiaryId)
        service = BillingService(session, client, settings.paymob)
        try:
            result = service.create_pack_checkout(
                payer_user_id=payer,
                beneficiary_user_id=beneficiary,
                credit_pack_id=body.creditPackId,
            )
        except UnknownCreditPack as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown credit pack") from exc
        except CheckoutUnavailable as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _UNAVAILABLE) from exc
    return CheckoutDTO(paymentId=str(result.payment_id), checkoutUrl=result.checkout_url)


@router.get("/payments/{payment_id}", response_model=PaymentStatusDTO)
def get_payment(
    payment_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    sm: Annotated[sessionmaker[Session], Depends(get_billing_sessionmaker)],
) -> PaymentStatusDTO:
    """Status of one payment for the return page; payer or beneficiary only."""
    with sm() as session:
        payment = payment_for_viewer(
            session, payment_id=payment_id, user_id=uuid.UUID(auth.user_id)
        )
        if payment is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown payment")
        return PaymentStatusDTO(
            paymentId=str(payment.id),
            status=payment.status.value,
            purpose=payment.purpose.value,
            amountMinor=payment.amount_minor,
            currency=payment.currency,
            description=describe_payment(session, payment),
            paidAt=payment.paid_at,
        )


@router.get("/receipts", response_model=ReceiptListDTO)
def list_receipts(
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    sm: Annotated[sessionmaker[Session], Depends(get_billing_sessionmaker)],
) -> ReceiptListDTO:
    """Every payment the caller paid for, newest first (spec §2.5)."""
    with sm() as session:
        receipts = []
        for payment in receipts_for(session, uuid.UUID(auth.user_id)):
            assert payment.paid_at is not None  # receipts_for filters on it  # noqa: S101
            receipts.append(
                ReceiptDTO(
                    paymentId=str(payment.id),
                    purpose=payment.purpose.value,
                    description=describe_payment(session, payment),
                    amountMinor=payment.amount_minor,
                    currency=payment.currency,
                    status=payment.status.value,
                    paidAt=payment.paid_at,
                    beneficiaryId=str(payment.beneficiary_user_id),
                )
            )
        return ReceiptListDTO(receipts=receipts)


@router.get("/cards", response_model=SavedCardList)
def list_saved_cards(
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    sm: Annotated[sessionmaker[Session], Depends(get_billing_sessionmaker)],
) -> SavedCardList:
    """The caller's own active saved cards, masked only (index R3, spec §7)."""
    with sm() as session:
        return SavedCardList(
            cards=[
                SavedCardView(cardId=str(card.id), maskedPan=card.masked_pan, brand=card.brand or "")
                for card in saved_cards_for(session, uuid.UUID(auth.user_id))
            ]
        )
```

FastAPI resolves every parameter annotation at runtime, including `sessionmaker[Session]`, so `Session`, `sessionmaker`, `PaymobClient`, `Settings` and `SlidingWindowLimiter` must stay top-level imports. Do not let a ruff autofix move them under `TYPE_CHECKING`; the `noqa: TC002` follows the pattern `lemely/web/deps_tutoring.py` uses for `Decimal`.

- [ ] **Step 6: Register the router**

In `lemely/web/app.py`, add `billing,` to the `from lemely.web.routers import (...)` list in alphabetical position, between `auth,` and `classes,`. Then add this line after `app.include_router(admin_tutoring_reports.router)`:

```python
    app.include_router(billing.router)
```

- [ ] **Step 7: Declare the routes in the authz matrix**

In `tests/test_authz_matrix_complete.py`, replace:

```python
    # ── TUTORING_PARTY (1) ────────────────────
    # Tutoring R1 (SPEC §c.1): target visibility (O12, O19) is object-level.
    ("POST", "/api/tutoring/reports"): TUTORING_PARTY,
```

with:

```python
    # ── TUTORING_PARTY (6) ────────────────────
    # Tutoring R1 (SPEC §c.1): target visibility (O12, O19) is object-level.
    ("POST", "/api/tutoring/reports"): TUTORING_PARTY,
    # Billing (spec 2026-11-02 §5.5, §7): the same three roles buy and pay.
    # Role half only. Object-level rules: a parent buys only for a linked child,
    # a payment is visible to its payer or beneficiary, receipts are the
    # caller's own payments (tests/test_web_billing.py IDOR cases).
    ("GET", "/api/billing/catalogue"): TUTORING_PARTY,
    ("POST", "/api/billing/checkout/pack"): TUTORING_PARTY,
    ("GET", "/api/billing/payments/{payment_id}"): TUTORING_PARTY,
    ("GET", "/api/billing/receipts"): TUTORING_PARTY,
    # Index R3: the caller's own saved cards, masked only.
    ("GET", "/api/billing/cards"): TUTORING_PARTY,
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_web_billing.py tests/test_authz_matrix_complete.py tests/test_web_app.py tests/architecture/ -v --no-cov`
Expected: all PASS, including `test_every_route_is_declared`, `test_declared_guard_matches_the_wired_guard` and `test_the_section_counts_in_this_file_match_what_it_registers`.

- [ ] **Step 9: Pre-commit and commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/billing_repo.py lemely/web/schemas_billing.py lemely/web/routers/billing.py lemely/web/deps_billing.py lemely/web/app.py tests/test_authz_matrix_complete.py tests/test_web_billing.py
git commit -S -m "feat(billing): add catalogue, pack checkout, payment status, receipts and saved-card routes" -- lemely/db/billing_repo.py lemely/web/schemas_billing.py lemely/web/routers/billing.py lemely/web/deps_billing.py lemely/web/app.py tests/test_authz_matrix_complete.py tests/test_web_billing.py
```

---

### Task 10: `/api/webhooks/paymob/transaction` route

**Files:**
- Create: `lemely/web/routers/paymob_webhooks.py`
- Modify: `lemely/web/app.py` (import and `include_router`)
- Modify: `tests/test_authz_matrix_complete.py` (one PUBLIC entry; PUBLIC heading 16 -> 17; `len(ROUTES) - 16` -> `- 17`)
- Test: `tests/test_web_paymob_webhooks.py`

**Interfaces:**
- Consumes:
  - From Task 3: `verify_transaction_hmac`, `verify_token_hmac`.
  - From Task 7: `BillingService.apply_transaction_callback`, `apply_token_callback`, `MalformedCallback`.
  - From Task 8: `get_billing_sessionmaker`, `get_paymob_client`.
  - From `tests/paymob_fixtures.py`: `sign_transaction`, `sign_token`, `transaction_callback`, `token_callback`.
- Produces: the route `POST /api/webhooks/paymob/transaction?hmac=<hex>` (PUBLIC). It takes a body of `{"type": "TRANSACTION" | "TOKEN", "obj": {...}}` and responds as follows:
  - 200 `{"status": "ok"}` after commit.
  - 200 `{"status": "ignored"}` for other types.
  - 401 on a HMAC mismatch or a missing `hmac`.
  - 400 when the body is malformed.
  - 503 when no HMAC secret is configured.

- [ ] **Step 1: Write the failing webhook test**

Create `tests/test_web_paymob_webhooks.py`:

```python
"""POST /api/webhooks/paymob/transaction end to end (spec §5.1 step 4, §5.5, §6, §9 router)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.db.models.billing import Payment, PaymentStatus, PaymobEvent, SavedCard
from lemely.db.models.usage import UsageGrant
from lemely.runtime.config import PaymobSettings, Settings
from lemely.web import create_app
from lemely.web.deps import get_settings
from lemely.web.deps_billing import get_billing_sessionmaker, get_paymob_client
from tests.paymob_fixtures import (
    PAYMOB_SETTINGS,
    FakePaymobClient,
    seed_pack,
    seed_payment,
    seed_user,
    sign_token,
    sign_transaction,
    token_callback,
    token_obj,
    transaction_callback,
    transaction_obj,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator
    from typing import Any

    from sqlalchemy.orm import Session, sessionmaker

URL = "/api/webhooks/paymob/transaction"


@pytest.fixture
def client(migrated_sessionmaker: sessionmaker[Session]) -> Iterator[TestClient]:
    settings = Settings().model_copy(update={"paymob": PAYMOB_SETTINGS})
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_billing_sessionmaker] = lambda: migrated_sessionmaker
    app.dependency_overrides[get_paymob_client] = lambda: FakePaymobClient()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _payment(sm: sessionmaker[Session]) -> uuid.UUID:
    payer = seed_user(sm)
    pack = seed_pack(sm)
    return seed_payment(sm, payer=payer, beneficiary=payer, pack_id=pack, paymob_order_id=265715202)


def _post(client: TestClient, body: dict[str, Any], hmac: str | None) -> Any:
    params = {"hmac": hmac} if hmac is not None else {}
    return client.post(URL, params=params, json=body)


def _status(sm: sessionmaker[Session], pid: uuid.UUID) -> PaymentStatus:
    with sm() as session:
        payment = session.get(Payment, pid)
        assert payment is not None
        return payment.status


def _count(sm: sessionmaker[Session], model: type[Any]) -> int:
    with sm() as session:
        return len(session.scalars(sa.select(model)).all())


def test_a_signed_success_callback_pays_and_grants(client: TestClient, migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    pid = _payment(sm)
    obj = transaction_obj(merchant_order_id=str(pid))
    response = _post(client, transaction_callback(obj), sign_transaction(obj))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert _status(sm, pid) is PaymentStatus.paid
    with sm() as session:
        (grant,) = session.scalars(sa.select(UsageGrant).where(UsageGrant.payment_id == pid)).all()
    assert grant.units == 100


def test_a_forged_signature_is_401_and_changes_nothing(client: TestClient, migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    pid = _payment(sm)
    obj = transaction_obj(merchant_order_id=str(pid))
    forged = sign_transaction(obj, secret="attacker-guess")
    assert _post(client, transaction_callback(obj), forged).status_code == 401
    assert _post(client, transaction_callback(obj), None).status_code == 401
    tampered = {**obj, "amount_cents": 1}
    assert _post(client, transaction_callback(tampered), sign_transaction(obj)).status_code == 401
    assert _status(sm, pid) is PaymentStatus.created
    assert _count(sm, PaymobEvent) == 0
    assert _count(sm, UsageGrant) == 0


def test_a_duplicate_delivery_is_200_and_grants_once(client: TestClient, migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    pid = _payment(sm)
    obj = transaction_obj(merchant_order_id=str(pid))
    for _ in range(3):
        assert _post(client, transaction_callback(obj), sign_transaction(obj)).status_code == 200
    assert _count(sm, UsageGrant) == 1
    assert _count(sm, PaymobEvent) == 1


def test_an_amount_mismatch_is_200_failed_mismatch_no_grant(client: TestClient, migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    pid = _payment(sm)
    obj = transaction_obj(merchant_order_id=str(pid), amount_cents=100)
    assert _post(client, transaction_callback(obj), sign_transaction(obj)).status_code == 200
    assert _status(sm, pid) is PaymentStatus.failed_mismatch
    assert _count(sm, UsageGrant) == 0


def test_an_unknown_reference_is_200_so_paymob_stops_retrying(client: TestClient, migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    obj = transaction_obj(merchant_order_id="no-such-payment")
    assert _post(client, transaction_callback(obj), sign_transaction(obj)).status_code == 200
    assert _count(sm, PaymobEvent) == 1


def test_a_signed_token_callback_saves_the_card(client: TestClient, migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _payment(sm)
    obj = token_obj(token="tok-live-1")
    assert _post(client, token_callback(obj), sign_token(obj)).status_code == 200
    with sm() as session:
        (card,) = session.scalars(sa.select(SavedCard)).all()
    assert "tok-live-1" not in card.token


def test_a_token_callback_signed_as_a_transaction_is_401(client: TestClient, migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    _payment(sm)
    obj = token_obj()
    assert _post(client, token_callback(obj), sign_transaction(obj)).status_code == 401
    assert _count(sm, SavedCard) == 0


def test_other_callback_types_are_acknowledged_and_ignored(client: TestClient, migrated_sessionmaker: sessionmaker[Session]) -> None:
    body = {"type": "DELIVERY_STATUS", "obj": {"order_id": 1}}
    response = _post(client, body, "anything")
    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
    assert _count(migrated_sessionmaker, PaymobEvent) == 0


@pytest.mark.parametrize("body", [{"type": "TRANSACTION"}, {"type": "TRANSACTION", "obj": "x"}])
def test_a_body_without_an_obj_is_400(client: TestClient, body: dict[str, Any]) -> None:
    assert _post(client, body, "abc").status_code == 400


def test_a_signed_callback_missing_its_id_is_400(client: TestClient) -> None:
    obj = transaction_obj()
    del obj["id"]
    assert _post(client, transaction_callback(obj), sign_transaction(obj)).status_code == 400


def test_unconfigured_hmac_secret_is_503(client: TestClient) -> None:
    bare = Settings().model_copy(update={"paymob": PaymobSettings()})
    client.app.dependency_overrides[get_settings] = lambda: bare  # type: ignore[union-attr]
    obj = transaction_obj()
    assert _post(client, transaction_callback(obj), sign_transaction(obj)).status_code == 503


def test_a_mismatch_is_logged_at_error_level(client: TestClient) -> None:
    from structlog.testing import capture_logs

    obj = transaction_obj()
    with capture_logs() as logs:
        _post(client, transaction_callback(obj), "0" * 128)
    assert any(e["event"] == "paymob_hmac_mismatch" and e["log_level"] == "error" for e in logs)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_web_paymob_webhooks.py -v --no-cov`
Expected: FAIL. Every request returns 404 because the route does not exist (for example `assert 404 == 200`).

- [ ] **Step 3: Write the router**

Create `lemely/web/routers/paymob_webhooks.py`:

```python
"""Paymob callbacks (billing spec §5.1 step 4, §5.5, §6; research 02 §1-§2).

``POST /api/webhooks/paymob/transaction?hmac=…`` receives both callback types
Paymob sends to an intention's ``notification_url``: ``"type": "TRANSACTION"``
(the Transaction Processed callback) and ``"type": "TOKEN"`` (a saved card). The
HMAC is in the query string for both. Order of operations:

1. No HMAC secret configured -> 503 (Paymob retries once we are configured).
2. HMAC mismatch or missing -> 401, logged at error level; nothing is stored.
3. Verified -> one ``sessionmaker.begin()`` transaction applies it; the 200 is
   sent only after that commits. Duplicates and unknown references are 200
   no-ops inside :class:`BillingService`, so Paymob stops retrying them.

Any other ``type`` (Paymob also has delivery-status callbacks) is acknowledged
with 200 and ignored: no state changes, so no verification is needed.

PUBLIC by necessity: Paymob holds no Lemely token. Authenticity is the HMAC
alone (Paymob publishes no source IPs). Not rate-limited: a limiter keyed by IP
would throttle Paymob itself.
"""

from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, sessionmaker  # noqa: TC002 - FastAPI reads the type at runtime

from lemely.db.billing_repo import BillingService, MalformedCallback
from lemely.io.paymob.client import PaymobClient
from lemely.io.paymob.hmac import verify_token_hmac, verify_transaction_hmac
from lemely.runtime.config import Settings
from lemely.web.deps import get_settings
from lemely.web.deps_billing import get_billing_sessionmaker, get_paymob_client

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/webhooks/paymob")

_VERIFIERS = {"TRANSACTION": verify_transaction_hmac, "TOKEN": verify_token_hmac}


@router.post("/transaction")
def paymob_transaction_callback(
    body: Annotated[dict[str, Any], Body()],
    settings: Annotated[Settings, Depends(get_settings)],
    sm: Annotated[sessionmaker[Session], Depends(get_billing_sessionmaker)],
    client: Annotated[PaymobClient, Depends(get_paymob_client)],
    hmac: Annotated[str | None, Query()] = None,
) -> dict[str, str]:
    """Verify and apply a Paymob transaction or card-token callback."""
    paymob = settings.paymob
    if paymob.hmac_secret is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Paymob webhooks are not configured")
    kind = body.get("type")
    verifier = _VERIFIERS.get(kind) if isinstance(kind, str) else None
    if verifier is None:
        log.info("paymob_callback_ignored", callback_type=str(kind)[:40])
        return {"status": "ignored"}
    obj = body.get("obj")
    if not isinstance(obj, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Callback has no obj")
    if not verifier(obj, hmac or "", paymob.hmac_secret.get_secret_value()):
        log.error(
            "paymob_hmac_mismatch",
            callback_type=kind,
            obj_id=str(obj.get("id"))[:40],
            hmac_present=bool(hmac),
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "HMAC verification failed")
    try:
        with sm.begin() as session:
            service = BillingService(session, client, paymob)
            if kind == "TRANSACTION":
                service.apply_transaction_callback(obj)
            else:
                service.apply_token_callback(obj)
    except MalformedCallback as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"status": "ok"}
```

As in Task 9, the `Session`/`sessionmaker`, `PaymobClient` and `Settings` imports stay top-level, because FastAPI resolves those parameter annotations at runtime.

- [ ] **Step 4: Register the router**

In `lemely/web/app.py`, add `paymob_webhooks,` to the `from lemely.web.routers import (...)` list between `parent_tutor_access,` and `placement,`. Then add this line after `app.include_router(billing.router)`:

```python
    app.include_router(paymob_webhooks.router)
```

- [ ] **Step 5: Declare the route in the authz matrix**

In `tests/test_authz_matrix_complete.py`:

(a) Replace `    # ── PUBLIC (16) ────────────────────` with `    # ── PUBLIC (17) ────────────────────`.

(b) Directly after the line `    ("GET", "/api/public/tutoring-areas"): PUBLIC,`, insert:

```python
    # Billing spec 2026-11-02 §5.1/§6: Paymob's server-to-server callbacks hold
    # no Lemely token; the HMAC in the query string is the only authenticity
    # check (401 on mismatch, inside the handler). tests/test_web_paymob_webhooks.py.
    ("POST", "/api/webhooks/paymob/transaction"): PUBLIC,
```

(c) In `test_the_sweeps_actually_cover_the_surface`, replace:

```python
    # card, P3 areas) + the landing page contact form.
    assert len(_NON_PUBLIC) == len(ROUTES) - 16
```

with:

```python
    # card, P3 areas) + the landing page contact form + the Paymob webhook.
    assert len(_NON_PUBLIC) == len(ROUTES) - 17
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_web_paymob_webhooks.py tests/test_web_billing.py tests/test_authz_matrix_complete.py tests/test_web_app.py tests/architecture/ -v --no-cov`
Expected: all PASS.

- [ ] **Step 7: Phase-end sweep of every touched test file**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_paymob_settings.py tests/test_deploy_paymob_env.py tests/test_token_cipher.py tests/test_paymob_hmac.py tests/test_paymob_client.py tests/test_migration_billing_payments.py tests/test_billing_checkout.py tests/test_billing_callbacks.py tests/test_billing_reconcile.py tests/test_web_billing.py tests/test_web_paymob_webhooks.py tests/test_authz_matrix_complete.py tests/test_db_schema.py tests/test_scheduled_notifications.py tests/test_settings_example_drift.py tests/test_deploy_evidence_bucket.py tests/test_web_platform_admin.py tests/test_seat_repo.py tests/test_web_app.py tests/architecture/ -v --no-cov`
Expected: all PASS.

- [ ] **Step 8: Pre-commit and commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/web/routers/paymob_webhooks.py lemely/web/app.py tests/test_authz_matrix_complete.py tests/test_web_paymob_webhooks.py
git commit -S -m "feat(paymob): receive HMAC-verified transaction and card-token webhooks" -- lemely/web/routers/paymob_webhooks.py lemely/web/app.py tests/test_authz_matrix_complete.py tests/test_web_paymob_webhooks.py
```

After this commit, run `graphify update .` (AST-only, no API cost) to keep the knowledge graph current, as `CLAUDE.md` requires after code changes. Do not commit `graphify-out/` unless the branch already tracks it.

---

## Spec coverage (self-review)

| Spec item | Task |
|---|---|
| §3 `PaymobClient`: every method in the index contract, auth token cached under 1 h | 4 |
| §3 HMAC: transaction (20 fields), token (8 fields), subscription, constant-time, `None` -> `""`, booleans | 3 |
| §3 `PaymobSettings`, GitHub secrets -> Cloud Run env | 1 |
| §4.1 `plan_tiers` columns, `credit_packs` | 5 |
| §4.2 `payments`, `paymob_events`, `saved_cards` (token encrypted) | 5, 2, 7 |
| §4.3 `subscriptions` columns, status labels, one live per beneficiary | 5 |
| §4.5 FK `usage_grants.payment_id` | 5 |
| §5.5 credit pack checkout (one-off intention), 12-month visible grant, debt repaid first (by `issue_grant`), payer = linked parent | 6, 7, 9 |
| §5.5 card-token callback stores or refreshes `saved_cards` | 7, 10 |
| §5.1 step 4 verify -> load by `merchant_order_id` -> amount/currency -> state flags -> one transaction -> 200 after commit | 7, 10 |
| §5.1 step 5 return page polls `GET /billing/payments/{id}` | 9 |
| §5.10 reconcile created/pending > 15 min by inquiry, backoff, 24 h -> failed | 8 |
| §6 HMAC 401 + alert log; duplicate 200; unknown ref 200; mismatch -> `failed_mismatch`, no grant, alert; insert before call; inquiry before any retry; outage -> 503 | 6, 7, 8, 9, 10 |
| §7 secrets server-only; token encrypted; parent only for linked child; payer-only receipts; IDOR tests; checkout rate limit | 1, 2, 9 |
| Index R3 `GET /api/billing/cards` (masked, own cards, IDOR-tested); R8 one-live index; R10 lineage-only migration test; R11 zero-price packs allowed, never sold | 9, 5, 5, 5/6 |
| §2.5 receipts = payments the payer paid | 9 |
| §9 HMAC worked example, `None` handling, wallet-shaped `source_data`; subscription HMAC; webhook fixtures; checkout IDOR; duplicate webhook; mismatch | 3, 7, 9, 10 |

Left to later phases (by the index): subscription checkout and webhooks (05), merchant charges and the `pay_with_token` use (06), refunds and clawback from the admin UI (07), and the return page and receipts UI (08).
