"""Tests for lemely doctor / lemely version subcommands."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from click.testing import CliRunner

from lemely.app.cli import cli


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        snapshot = {
            k: v for k, v in os.environ.items() if k.startswith("LEMELY_") or k == "GEMINI_API_KEY"
        }

        def restore() -> None:
            for k in list(os.environ):
                if k.startswith("LEMELY_") or k == "GEMINI_API_KEY":
                    del os.environ[k]
            os.environ.update(snapshot)

        self.addCleanup(restore)
        for k in list(os.environ):
            if k.startswith("LEMELY_") or k == "GEMINI_API_KEY":
                del os.environ[k]

    def test_doctor_fails_without_gemini_api_key(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={"LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources")},
            )
        self.assertEqual(result.exit_code, 3, msg=result.output)
        payload = json.loads(result.output)
        self.assertFalse(payload["all_passed"])
        self.assertIn("gemini_api_key", json.dumps(payload))

    def test_doctor_succeeds_with_valid_env(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                    "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                },
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertTrue(payload["all_passed"])

    def _run_doctor_with_env(self, tmp: str) -> object:
        return self.runner.invoke(
            cli,
            ["--json", "doctor"],  # no --no-network: exercises the live ping
            env={
                "GEMINI_API_KEY": "test-key",
                "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
            },
        )

    def test_doctor_live_ping_reports_reachable(self) -> None:
        from unittest.mock import patch

        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            with patch("lemely.io.gemini.GeminiClient.check_reachable", return_value=None):
                result = self._run_doctor_with_env(tmp)
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertTrue(payload["all_passed"])
        reach = next(c for c in payload["checks"] if c["name"] == "gemini_reachable")
        self.assertTrue(reach["ok"])

    def test_doctor_live_ping_reports_unreachable(self) -> None:
        from unittest.mock import patch

        from lemely.runtime.errors import ExternalServiceError

        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            with patch(
                "lemely.io.gemini.GeminiClient.check_reachable",
                side_effect=ExternalServiceError("Gemini API not reachable: boom"),
            ):
                result = self._run_doctor_with_env(tmp)
        self.assertEqual(result.exit_code, 3, msg=result.output)
        payload = json.loads(result.output)
        self.assertFalse(payload["all_passed"])
        reach = next(c for c in payload["checks"] if c["name"] == "gemini_reachable")
        self.assertFalse(reach["ok"])
        self.assertIn("not reachable", str(reach["detail"]))

    def test_doctor_reports_push_unavailable_without_keys_and_does_not_fail_for_it(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                    "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                },
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        push = next(c for c in payload["checks"] if c["name"] == "push_transport")
        self.assertFalse(push["ok"])
        self.assertIn("push-keygen", push["detail"])
        self.assertTrue(payload["all_passed"])

    def test_doctor_reports_push_available_with_a_generated_pair(self) -> None:
        from lemely.runtime.vapid import generate_vapid_keypair

        pair = generate_vapid_keypair()
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                    "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                    "LEMELY_PUSH__VAPID_PUBLIC_KEY": pair.public_key,
                    "LEMELY_PUSH__VAPID_PRIVATE_KEY": pair.private_key,
                    "LEMELY_PUSH__VAPID_SUBJECT": "mailto:ops@example.test",
                },
            )
        payload = json.loads(result.output)
        push = next(c for c in payload["checks"] if c["name"] == "push_transport")
        self.assertTrue(push["ok"], msg=push)


class DoctorRemovedConfigKeysTests(unittest.TestCase):
    """F4 acceptance (5): ``lemely doctor`` warns, but does not fail, when a
    ``lemely.toml`` still sets a key F4 removed."""

    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_doctor_warns_on_stale_integrity_key_without_failing(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            toml_path = Path(tmp) / "lemely.toml"
            toml_path.write_text("[integrity]\nai_detection_enabled = true\n")
            result = self.runner.invoke(
                cli,
                ["--json", "--config", str(toml_path), "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                    "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                },
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        # Advisory: reported unhealthy but does not flip all_passed.
        self.assertTrue(payload["all_passed"], msg=result.output)
        check = next(c for c in payload["checks"] if c["name"] == "no_removed_config_keys")
        self.assertFalse(check["ok"])
        self.assertIn("integrity.ai_detection_enabled", check["detail"])

    def test_doctor_reports_no_removed_keys_on_a_clean_toml(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            toml_path = Path(tmp) / "lemely.toml"
            toml_path.write_text("[integrity]\nplagiarism_enabled = true\n")
            result = self.runner.invoke(
                cli,
                ["--json", "--config", str(toml_path), "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                    "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                },
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        check = next(c for c in payload["checks"] if c["name"] == "no_removed_config_keys")
        self.assertTrue(check["ok"])

    def test_doctor_warns_when_promo_pricing_window_is_within_30_days_of_expiry(self) -> None:
        """US-026: `lemely doctor` warns, but does not fail, when the 3.8/3.7/
        3.6-flash promotional pricing window (see FLASH_3X_PROMO_END_DATE in
        lemely.io.gemini) is within 30 days of lapsing to the real rate."""
        from datetime import timedelta
        from unittest.mock import patch

        from lemely.io.gemini import FLASH_3X_PROMO_END_DATE

        near_expiry = FLASH_3X_PROMO_END_DATE - timedelta(days=10)
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            with patch("lemely.io.gemini._today", return_value=near_expiry):
                result = self.runner.invoke(
                    cli,
                    ["--json", "doctor", "--no-network"],
                    env={
                        "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                        "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                        "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                        "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                    },
                )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertTrue(payload["all_passed"], msg=result.output)
        check = next(c for c in payload["checks"] if c["name"] == "gemini_promo_pricing_window")
        self.assertFalse(check["ok"], msg=check)
        self.assertIn("in 10 day(s)", check["detail"])
        self.assertIn(str(FLASH_3X_PROMO_END_DATE), check["detail"])

    def test_doctor_does_not_warn_when_promo_pricing_window_is_not_near_expiry(self) -> None:
        from datetime import timedelta
        from unittest.mock import patch

        from lemely.io.gemini import FLASH_3X_PROMO_END_DATE

        far_from_expiry = FLASH_3X_PROMO_END_DATE - timedelta(days=90)
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            with patch("lemely.io.gemini._today", return_value=far_from_expiry):
                result = self.runner.invoke(
                    cli,
                    ["--json", "doctor", "--no-network"],
                    env={
                        "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                        "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                        "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                        "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                    },
                )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        check = next(c for c in payload["checks"] if c["name"] == "gemini_promo_pricing_window")
        self.assertTrue(check["ok"], msg=check)

    def test_doctor_warns_on_a_pricing_override_that_bypasses_the_promo_gate(self) -> None:
        """Review finding 3: a `lemely.toml` `[gemini.pricing]` override pinned
        on a promo model bypasses `FLASH_3X_PROMO_END_DATE` entirely — that is
        pre-existing, intentional override-wins behaviour, but the advisory
        must name the override rather than claim a post-promo rate it never
        checked. Frozen well past expiry so a bug that fell through to the
        date branch would say something false ("...post-promo rate...")."""
        from datetime import timedelta
        from unittest.mock import patch

        from lemely.io.gemini import FLASH_3X_PROMO_END_DATE

        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            toml_path = Path(tmp) / "lemely.toml"
            toml_path.write_text('[gemini.pricing]\n"gemini-3.8-flash" = [0.00075, 0.00375]\n')
            with patch(
                "lemely.io.gemini._today",
                return_value=FLASH_3X_PROMO_END_DATE + timedelta(days=365),
            ):
                result = self.runner.invoke(
                    cli,
                    ["--json", "--config", str(toml_path), "doctor", "--no-network"],
                    env={
                        "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                        "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                        "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                        "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                    },
                )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertTrue(payload["all_passed"], msg=result.output)
        check = next(c for c in payload["checks"] if c["name"] == "gemini_promo_pricing_window")
        self.assertFalse(check["ok"], msg=check)
        self.assertIn("gemini-3.8-flash", check["detail"])
        self.assertIn("pins a fixed price", check["detail"])
        self.assertNotIn("post-promo rate", check["detail"])

    def test_doctor_warns_on_a_stale_key_set_as_an_env_var_without_failing(self) -> None:
        """Review finding F-6: the same warning, without a crash, however the
        removed key was supplied — a bare TOML file (no removed key of its
        own) with the key set as an env var instead."""
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            toml_path = Path(tmp) / "lemely.toml"
            toml_path.write_text("[integrity]\nplagiarism_enabled = true\n")
            result = self.runner.invoke(
                cli,
                ["--json", "--config", str(toml_path), "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                    "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                    "LEMELY_INTEGRITY__AI_DETECTION_ENABLED": "true",
                },
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertTrue(payload["all_passed"], msg=result.output)
        check = next(c for c in payload["checks"] if c["name"] == "no_removed_config_keys")
        self.assertFalse(check["ok"])
        self.assertIn("integrity.ai_detection_enabled", check["detail"])


class US034FallbackPricingVisibilityTests(unittest.TestCase):
    """US-034: `lemely doctor` must name any configured model resolving
    through the unrecognised-model pricing fallback, and must NOT name any of
    the three real configured models (none of which hits the fallback
    today)."""

    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_doctor_names_a_nonexistent_configured_model_as_hitting_the_fallback(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                    "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                    "LEMELY_GEMINI__EXTRACTION_MODEL": "totally-fake-model-does-not-exist",
                },
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        # Advisory: reported unhealthy but does not flip all_passed.
        self.assertTrue(payload["all_passed"], msg=result.output)
        check = next(c for c in payload["checks"] if c["name"] == "gemini_fallback_pricing")
        self.assertFalse(check["ok"], msg=check)
        self.assertIn("totally-fake-model-does-not-exist", check["detail"])
        self.assertIn("extraction", check["detail"])

    def test_doctor_does_not_name_any_real_configured_model_as_hitting_the_fallback(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                    "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                },
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertTrue(payload["all_passed"], msg=result.output)
        check = next(c for c in payload["checks"] if c["name"] == "gemini_fallback_pricing")
        self.assertTrue(check["ok"], msg=check)
        for real_model in ("gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"):
            self.assertNotIn(real_model, check["detail"])


class DoctorTestsEnvLeakTests(unittest.TestCase):
    """Regression test for #121: DoctorTests.setUp must not leak env deletions."""

    def test_doctor_tests_setup_does_not_leak_env_deletions(self) -> None:
        """Both var shapes ``setUp`` deletes must survive it.

        Each is asserted against a **synthetic sentinel this test plants
        itself**, never against whatever ambient value happens to be present.
        That is deliberate, and it is the difference between an oracle and a
        coin flip: an earlier version checked ``GEMINI_API_KEY`` only
        ``if original_gemini_key is not None``, which a partial-restore
        regression could silently switch off. ``DoctorTests``' own earlier
        tests run first in the same session, so a ``restore()`` that dropped
        ``GEMINI_API_KEY`` specifically would delete the ambient key *before*
        this test captured it — leaving ``original_gemini_key`` already
        ``None``, skipping the assertion, and passing. The bug would have
        disabled the check meant to catch it. Planting the value removes the
        run-order dependency, and makes the check work identically in CI
        (which exports no key) and locally (which does).
        """
        originals = {k: os.environ.get(k) for k in ("LEMELY_LEAK_CANARY", "GEMINI_API_KEY")}
        os.environ["LEMELY_LEAK_CANARY"] = "canary-value"
        os.environ["GEMINI_API_KEY"] = "leak-sentinel-not-a-real-key"
        try:
            suite = unittest.TestLoader().loadTestsFromTestCase(DoctorTests)
            with open(os.devnull, "w") as devnull:
                result = unittest.TextTestRunner(stream=devnull).run(suite)
            self.assertTrue(result.wasSuccessful(), msg=str(result.errors + result.failures))

            # Unconditional: value, not just presence, so a restore that puts
            # the key back with the wrong value is caught too.
            self.assertEqual(
                os.environ.get("LEMELY_LEAK_CANARY"),
                "canary-value",
                msg="DoctorTests.setUp leaked a LEMELY_* deletion past the class",
            )
            self.assertEqual(
                os.environ.get("GEMINI_API_KEY"),
                "leak-sentinel-not-a-real-key",
                msg="DoctorTests.setUp failed to restore GEMINI_API_KEY",
            )
        finally:
            # Restore BOTH, not just the canary: on failure the leak is by
            # definition still live, and leaving GEMINI_API_KEY deleted would
            # reproduce #120's contamination for the rest of the session.
            for key, value in originals.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class VersionTests(unittest.TestCase):
    def test_version_subcommand_prints_known_keys(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "version"])
        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.output)
        self.assertIn("lemely", payload)
        self.assertIn("python", payload)


if __name__ == "__main__":
    unittest.main()
