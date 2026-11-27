"""Tests for lemely.runtime.config Settings loading and validation."""

from __future__ import annotations

import os
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from lemely.runtime.config import load_settings


class _IsolatedEnv:
    """Fully isolate Settings inputs: clears LEMELY_* and unprefixed key env
    vars, AND chdirs into an empty temp dir so ``Settings(env_file=".env")``
    cannot pick up a developer's real repo-root ``.env`` during the test.
    """

    def __init__(self, **overrides: str) -> None:
        self.overrides = overrides
        self._snapshot: dict[str, str] = {}
        self._prev_cwd: str = ""
        self._tmp: TemporaryDirectory[str] | None = None

    # Env vars that feed Settings but do not carry the LEMELY_ prefix
    # (the google-genai SDK reads these directly; Settings aliases them too).
    _UNPREFIXED = ("GEMINI_API_KEY", "GOOGLE_API_KEY")

    def __enter__(self) -> _IsolatedEnv:
        self._snapshot = dict(os.environ)
        for key in list(os.environ):
            if key.startswith("LEMELY_") or key in self._UNPREFIXED:
                del os.environ[key]
        os.environ.update(self.overrides)
        self._prev_cwd = os.getcwd()
        self._tmp = TemporaryDirectory()
        os.chdir(self._tmp.name)
        return self

    def __exit__(self, *_: object) -> None:
        os.chdir(self._prev_cwd)
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None
        os.environ.clear()
        os.environ.update(self._snapshot)


class SettingsTests(unittest.TestCase):
    def test_notifications_defaults_match_the_spec(self) -> None:
        with _IsolatedEnv(), TemporaryDirectory() as tmp:
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertTrue(s.notifications.sweeper_enabled)
        self.assertEqual(s.notifications.sweep_poll_seconds, 60)
        self.assertEqual(s.notifications.streak_warning_hour, 19)
        self.assertEqual(s.notifications.study_plan_reminder_hour, 8)

    def test_notifications_hours_must_be_hours(self) -> None:
        from pydantic import ValidationError

        from lemely.runtime.config import NotificationsSettings

        with self.assertRaises(ValidationError):
            NotificationsSettings(streak_warning_hour=24)
        with self.assertRaises(ValidationError):
            NotificationsSettings(sweep_poll_seconds=0)

    def test_sweeper_can_be_disabled_from_the_environment(self) -> None:
        with _IsolatedEnv(), TemporaryDirectory() as tmp:
            os.environ["LEMELY_NOTIFICATIONS__SWEEPER_ENABLED"] = "0"
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertFalse(s.notifications.sweeper_enabled)

    def test_defaults_load_without_any_source(self) -> None:
        with _IsolatedEnv(), TemporaryDirectory() as tmp:
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertEqual(s.gradio.host, "127.0.0.1")
        self.assertEqual(s.gradio.port, 7860)
        self.assertEqual(s.logging.level, "INFO")
        self.assertEqual(s.logging.format, "auto")
        self.assertEqual(s.gemini.model, "claude-haiku-5-5")
        self.assertIsNone(s.gemini_api_key)

    def test_extra_forbid_rejects_unknown_keys_in_toml(self) -> None:
        with TemporaryDirectory() as tmp:
            toml = Path(tmp) / "lemely.toml"
            toml.write_text(
                textwrap.dedent("""
                [gradio]
                hsot = "0.0.0.0"
            """).strip()
            )
            with _IsolatedEnv(), self.assertRaises(ValidationError) as cm:
                load_settings(toml_path=toml, cwd=Path(tmp))
        self.assertIn("hsot", str(cm.exception))

    def test_env_overrides_toml(self) -> None:
        with TemporaryDirectory() as tmp:
            toml = Path(tmp) / "lemely.toml"
            toml.write_text("[gradio]\nport = 5000\n")
            with _IsolatedEnv(LEMELY_GRADIO__PORT="9000"):
                s = load_settings(toml_path=toml, cwd=Path(tmp))
        self.assertEqual(s.gradio.port, 9000)

    def test_secret_redaction_in_dump(self) -> None:
        with _IsolatedEnv(LEMELY_GEMINI_API_KEY="sk-secret-xyz"), TemporaryDirectory() as tmp:
            s = load_settings(toml_path=None, cwd=Path(tmp))
        # Guard: ensure the secret actually loaded, so the redaction assertion
        # below isn't trivially true on an unset field.
        self.assertIsNotNone(s.gemini_api_key)
        self.assertEqual(s.gemini_api_key.get_secret_value(), "sk-secret-xyz")
        dumped = s.model_dump(mode="json")
        self.assertNotIn("sk-secret-xyz", str(dumped))

    def test_unprefixed_gemini_api_key_populates_settings(self) -> None:
        # The env-mapping trap fix: an unprefixed GEMINI_API_KEY (what the
        # google-genai SDK reads) must reach settings.gemini_api_key so the web
        # portal's AI-feature gate sees the key, not just CLI/Gradio.
        with _IsolatedEnv(GEMINI_API_KEY="sk-unprefixed"), TemporaryDirectory() as tmp:
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertIsNotNone(s.gemini_api_key)
        assert s.gemini_api_key is not None
        self.assertEqual(s.gemini_api_key.get_secret_value(), "sk-unprefixed")

    def test_google_api_key_populates_settings(self) -> None:
        with _IsolatedEnv(GOOGLE_API_KEY="sk-google"), TemporaryDirectory() as tmp:
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertIsNotNone(s.gemini_api_key)
        assert s.gemini_api_key is not None
        self.assertEqual(s.gemini_api_key.get_secret_value(), "sk-google")

    def test_lemely_prefixed_key_wins_over_unprefixed(self) -> None:
        with (
            _IsolatedEnv(LEMELY_GEMINI_API_KEY="sk-lemely", GEMINI_API_KEY="sk-plain"),
            TemporaryDirectory() as tmp,
        ):
            s = load_settings(toml_path=None, cwd=Path(tmp))
        assert s.gemini_api_key is not None
        self.assertEqual(s.gemini_api_key.get_secret_value(), "sk-lemely")

    # ── Blank credentials read as unset (P6.10 / D6.8) ──────────────────────
    # `docker-compose.yml` forwards optional credentials as `${VAR:-}`, so on a
    # `make up` stack with nothing exported the variable is PRESENT and empty.
    # Before the fix that produced `SecretStr("")`, which is not None, so every
    # `is None` "not configured" check answered "configured" with nothing behind
    # it — /api/health claimed `apiKeyConfigured: true` on a stack that could not
    # mark a single paper. Observed on the real container, not hypothesised.

    def test_blank_gemini_api_key_reads_as_unset(self) -> None:
        with _IsolatedEnv(GEMINI_API_KEY=""), TemporaryDirectory() as tmp:
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertIsNone(s.gemini_api_key)

    def test_whitespace_only_gemini_api_key_reads_as_unset(self) -> None:
        with _IsolatedEnv(LEMELY_GEMINI_API_KEY="   "), TemporaryDirectory() as tmp:
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertIsNone(s.gemini_api_key)

    def test_blank_supabase_keys_read_as_unset(self) -> None:
        """So ``GoTrueClient._anon_key`` raises its explicit AuthError rather than
        sending an empty ``apikey`` header — which local Kong tolerates (it works!)
        and Supabase Cloud rejects with an unrelated-looking 401.
        """
        with (
            _IsolatedEnv(LEMELY_SUPABASE__ANON_KEY="", LEMELY_SUPABASE__SERVICE_ROLE_KEY=""),
            TemporaryDirectory() as tmp,
        ):
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertIsNone(s.supabase.anon_key)
        self.assertIsNone(s.supabase.service_role_key)

    def test_blank_vapid_credentials_read_as_unset(self) -> None:
        """Same mechanism, same file: a blank key would report the push transport
        available (D5.9 §4 gates availability on these being None) and then fail.
        """
        with (
            _IsolatedEnv(
                LEMELY_PUSH__VAPID_PUBLIC_KEY="",
                LEMELY_PUSH__VAPID_PRIVATE_KEY="",
                LEMELY_PUSH__VAPID_SUBJECT="",
            ),
            TemporaryDirectory() as tmp,
        ):
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertIsNone(s.push.vapid_public_key)
        self.assertIsNone(s.push.vapid_private_key)
        self.assertIsNone(s.push.vapid_subject)

    def test_a_real_credential_is_not_stripped_or_dropped(self) -> None:
        """The guard must only fire on blank input — an ordinary key is untouched,
        including one with incidental surrounding whitespace preserved verbatim.
        """
        with _IsolatedEnv(GEMINI_API_KEY=" sk-real "), TemporaryDirectory() as tmp:
            s = load_settings(toml_path=None, cwd=Path(tmp))
        assert s.gemini_api_key is not None
        self.assertEqual(s.gemini_api_key.get_secret_value(), " sk-real ")

    def test_email_app_base_url_rejects_an_origin_with_no_host(self) -> None:
        """The empty-host case is the one that reached a real inbox.

        ``app_base_url = ""`` joined onto ``/verify-email/<token>`` produces
        ``http:///verify-email/<token>``, which is syntactically a URL and
        completely unreachable. Failing at settings-load turns that into a
        startup error naming the value, instead of a broken link nobody sees
        until a recipient clicks it.
        """
        for bad in ("", "lemelyig.com", "https://", "/verify-email"):
            with (
                self.subTest(value=bad),
                TemporaryDirectory() as tmp,
                _IsolatedEnv(LEMELY_EMAIL__APP_BASE_URL=bad),
                self.assertRaises(ValidationError),
            ):
                load_settings(toml_path=None, cwd=Path(tmp))

    def test_email_app_base_url_accepts_a_real_origin_and_trims_a_trailing_slash(self) -> None:
        """A trailing slash must not survive into a doubled path separator."""
        with (
            _IsolatedEnv(LEMELY_EMAIL__APP_BASE_URL="https://staging.lemelyig.com/"),
            TemporaryDirectory() as tmp,
        ):
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertEqual(s.email.app_base_url, "https://staging.lemelyig.com")

    def test_email_app_base_url_defaults_to_the_production_site(self) -> None:
        with _IsolatedEnv(), TemporaryDirectory() as tmp:
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertEqual(s.email.app_base_url, "https://lemelyig.com")

    def test_storage_defaults_to_gcs_with_globally_unique_bucket_names(self) -> None:
        """GCS is the default provider, and the bucket defaults are GCS-shaped.

        The prefix is not cosmetic. GCS bucket names live in a single global
        namespace shared by every Google Cloud customer, so the old Supabase
        defaults (bare ``uploads``/``avatars``, which are per-project there)
        name buckets this project could never own — a default that can only
        fail. Pinned here because it is a deployment-visible contract that no
        other test would notice moving.
        """
        with _IsolatedEnv(), TemporaryDirectory() as tmp:
            s = load_settings(toml_path=None, cwd=Path(tmp))
        self.assertEqual(s.storage.backend, "local")
        self.assertEqual(s.storage.bucket, "lemely-uploads")
        self.assertEqual(s.storage.avatar_bucket, "lemely-avatars")

    def test_storage_rejects_an_empty_bucket_name(self) -> None:
        """An unset GitHub Actions variable renders as "" — fail at startup, not at upload.

        ``deploy.yml`` passes the bucket names through ``vars.``; a mistyped or
        missing one would otherwise boot a service that writes every object to
        bucket ``""`` and only discovers it at the first student upload.
        """
        with (
            _IsolatedEnv(LEMELY_STORAGE__BUCKET=""),
            TemporaryDirectory() as tmp,
            self.assertRaises(ValidationError) as cm,
        ):
            load_settings(toml_path=None, cwd=Path(tmp))
        self.assertIn("bucket", str(cm.exception))

    def test_toml_discovery_prefers_cwd_lemely_toml(self) -> None:
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp) / "cwd"
            cwd.mkdir()
            (cwd / "lemely.toml").write_text("[gradio]\nport = 4242\n")
            with _IsolatedEnv():
                s = load_settings(toml_path=None, cwd=cwd)
        self.assertEqual(s.gradio.port, 4242)

    def test_a_connection_pool_of_one_is_refused(self) -> None:
        """A sweep pass holds one connection for its advisory lock while its jobs use another,
        so a pool of size 1 with no overflow would starve every triggered pass at startup of
        the first job; refuse it at load time instead."""
        from lemely.runtime.config import DatabaseSettings

        with self.assertRaises(ValidationError) as cm:
            DatabaseSettings(pool_size=1, max_overflow=0)
        self.assertIn("at least 2", str(cm.exception))
        self.assertEqual(DatabaseSettings(pool_size=1, max_overflow=1).pool_size, 1)
        self.assertEqual(DatabaseSettings(pool_size=2, max_overflow=0).max_overflow, 0)
        with (
            _IsolatedEnv(LEMELY_DATABASE__POOL_SIZE="1", LEMELY_DATABASE__MAX_OVERFLOW="0"),
            self.assertRaises(ValidationError),
            TemporaryDirectory() as tmp,
        ):
            load_settings(toml_path=None, cwd=Path(tmp))

    def test_a_charge_started_at_the_end_of_the_budget_must_end_inside_the_sweep_lock(self) -> None:
        """The sweep never stops a claimed charge, so the budget plus one charge's worst case
        (two requests, each bounded by its four Paymob timeouts) must stay under the lock's
        240 s idle timeout less its 30 s margin. The old 20 s on every phase would not."""
        with TemporaryDirectory() as tmp:
            with _IsolatedEnv():
                defaults = load_settings(toml_path=None, cwd=Path(tmp))
            # 60 + 5 + 2 * (5 + 5 + 20 + 5) = 135
            self.assertEqual(defaults.notifications.sweep_pass_budget_seconds, 60)
            self.assertEqual(defaults.paymob.request_hard_seconds, 35)

            old_phases = {
                "LEMELY_PAYMOB__CONNECT_TIMEOUT_SECONDS": "20",
                "LEMELY_PAYMOB__WRITE_TIMEOUT_SECONDS": "20",
                "LEMELY_PAYMOB__POOL_TIMEOUT_SECONDS": "20",
            }
            with _IsolatedEnv(**old_phases), self.assertRaises(ValidationError) as cm:
                load_settings(toml_path=None, cwd=Path(tmp))
            self.assertIn("exceeds 210 s", str(cm.exception))

            # 140 + 5 + 2 * 32.5 = 210 sits exactly on the limit.
            edge = {
                "LEMELY_NOTIFICATIONS__SWEEP_PASS_BUDGET_SECONDS": "140",
                "LEMELY_PAYMOB__TIMEOUT_SECONDS": "17.5",
            }
            with _IsolatedEnv(**edge):
                load_settings(toml_path=None, cwd=Path(tmp))
            edge["LEMELY_NOTIFICATIONS__SWEEP_PASS_BUDGET_SECONDS"] = "141"
            with _IsolatedEnv(**edge), self.assertRaises(ValidationError):
                load_settings(toml_path=None, cwd=Path(tmp))


if __name__ == "__main__":
    unittest.main()
