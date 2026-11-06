"""Tests for lemely doctor / lemely version subcommands."""

from __future__ import annotations

import contextlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from click.testing import CliRunner

from lemely.app.cli import cli
from lemely.runtime.config import Settings

#: Settings that put every task tag and the binder on Gemini, for the tests of the Gemini path.
_ALL_GEMINI: dict[str, str | None] = {
    "LEMELY_GEMINI__MODEL": "gemini-2.5-flash",
    "LEMELY_GEMINI__MARK_SCHEME_MODEL": "gemini-2.5-flash",
    "LEMELY_GEMINI__EXTRACTION_MODEL": "gemini-3.5-flash-lite",
    "LEMELY_GEMINI__CORRECTION_MODEL": "gemini-3.1-flash-lite",
    "LEMELY_GEMINI__GENERATION_MODEL": "gemini-3.5-flash-lite",
    "LEMELY_GEMINI__SCAN_METADATA_MODEL": "gemini-3.5-flash-lite",
    "LEMELY_GEMINI__ADJUDICATION_MODEL": "gemini-3.8-flash",
    "LEMELY_BINDING__READ_MODEL": "gemini-3.8-flash",
    "LEMELY_BINDING__RETRY_MODEL": "gemini-3.8-flash",
}


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        keys = ("GEMINI_API_KEY", "ANTHROPIC_API_KEY")
        snapshot = {k: v for k, v in os.environ.items() if k.startswith("LEMELY_") or k in keys}

        def restore() -> None:
            for k in list(os.environ):
                if k.startswith("LEMELY_") or k in keys:
                    del os.environ[k]
            os.environ.update(snapshot)

        self.addCleanup(restore)
        for k in list(os.environ):
            if k.startswith("LEMELY_") or k in keys:
                del os.environ[k]
        # Every default task tag is claude- since sub-project C, so a healthy install has
        # an Anthropic key; the tests that need it absent say so (ANTHROPIC_API_KEY=None).
        os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key-not-validated"

    def test_doctor_fails_without_gemini_api_key(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    **_ALL_GEMINI,
                },
            )
        self.assertEqual(result.exit_code, 3, msg=result.output)
        payload = json.loads(result.output)
        self.assertFalse(payload["all_passed"])
        check = next(c for c in payload["checks"] if c["name"] == "gemini_api_key")
        self.assertFalse(check["ok"])

    def _doctor_env(self, tmp: str, **extra: str | None) -> dict[str, str | None]:
        (Path(tmp) / "Sources").mkdir()
        (Path(tmp) / "outputs").mkdir()
        return {
            "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
            "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
            "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
            "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
            "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
            **extra,
        }

    def test_doctor_lists_the_price_table_and_fails_an_unpriced_claude_tag(self) -> None:
        with TemporaryDirectory() as tmp:
            env = self._doctor_env(
                tmp,
                LEMELY_GEMINI__CORRECTION_MODEL="claude-nonexistent-9",
                ANTHROPIC_API_KEY="test-key",
            )
            result = self.runner.invoke(cli, ["--json", "doctor", "--no-network"], env=env)
        payload = json.loads(result.output)
        checks = {c["name"]: c for c in payload["checks"]}
        self.assertIn(
            "correction=anthropic:claude-nonexistent-9", checks["llm_price_table"]["detail"]
        )
        self.assertFalse(checks["claude_price_rows"]["ok"])
        self.assertFalse(payload["all_passed"])

    def test_doctor_price_rows_pass_on_defaults(self) -> None:
        with TemporaryDirectory() as tmp:
            result = self.runner.invoke(
                cli, ["--json", "doctor", "--no-network"], env=self._doctor_env(tmp)
            )
        checks = {c["name"]: c for c in json.loads(result.output)["checks"]}
        self.assertTrue(checks["claude_price_rows"]["ok"])
        self.assertTrue(checks["llm_price_table"]["ok"])

    def test_doctor_fails_when_a_claude_model_is_configured_without_an_anthropic_key(self) -> None:
        with TemporaryDirectory() as tmp:
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env=self._doctor_env(
                    tmp,
                    ANTHROPIC_API_KEY=None,
                    LEMELY_GEMINI__CORRECTION_MODEL="claude-haiku-5-5",
                ),
            )
        self.assertEqual(result.exit_code, 3, msg=result.output)
        payload = json.loads(result.output)
        self.assertFalse(payload["all_passed"])
        check = next(c for c in payload["checks"] if c["name"] == "anthropic_api_key")
        self.assertFalse(check["ok"])
        self.assertIn("correction=claude-haiku-5-5", check["detail"])

    def test_doctor_fails_when_the_second_read_is_on_claude_without_an_anthropic_key(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env=self._doctor_env(
                    tmp,
                    ANTHROPIC_API_KEY=None,
                    LEMELY_BINDING__SECOND_READ_MODEL="claude-haiku-5-5",
                ),
            )
        self.assertEqual(result.exit_code, 3, msg=result.output)
        payload = json.loads(result.output)
        check = next(c for c in payload["checks"] if c["name"] == "anthropic_api_key")
        self.assertFalse(check["ok"])
        self.assertIn("binding_second_read=claude-haiku-5-5", check["detail"])
        table = next(c for c in payload["checks"] if c["name"] == "gemini_model_table")
        self.assertIn("binding_second_read=claude-haiku-5-5", table["detail"])

    def _workspace_check(self, **env: str) -> dict[str, object] | None:
        with TemporaryDirectory() as tmp:
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env=self._doctor_env(tmp, ANTHROPIC_API_KEY="sk-ant-test", **env),
            )
        payload = json.loads(result.output)
        return next((c for c in payload["checks"] if c["name"] == "claude_files_workspace"), None)

    def test_doctor_names_only_image_carrying_claude_calls_as_uploading(self) -> None:
        check = self._workspace_check(
            LEMELY_GEMINI__CORRECTION_MODEL="claude-haiku-5-5",
            LEMELY_GEMINI__EXTRACTION_MODEL="claude-haiku-5-5",
            LEMELY_BINDING__SECOND_READ_MODEL="claude-haiku-5-5",
        )
        assert check is not None
        self.assertTrue(check["ok"])
        detail = str(check["detail"])
        self.assertIn("extraction", detail)
        self.assertIn("binding_second_read", detail)
        self.assertNotIn("correction", detail)
        self.assertIn("dedicated Lemely workspace", detail)

    def test_doctor_skips_the_workspace_check_when_no_image_call_is_on_claude(self) -> None:
        self.assertIsNone(
            self._workspace_check(
                **{**_ALL_GEMINI, "LEMELY_GEMINI__CORRECTION_MODEL": "claude-haiku-5-5"}
            )
        )

    def test_doctor_says_inline_when_the_files_api_is_off(self) -> None:
        check = self._workspace_check(
            LEMELY_GEMINI__EXTRACTION_MODEL="claude-haiku-5-5",
            LEMELY_GEMINI__CLAUDE_FILES_API="false",
        )
        assert check is not None
        self.assertIn("sent inline", str(check["detail"]))

    def test_doctor_shows_escalation_as_off_and_the_binder_retry(self) -> None:
        with TemporaryDirectory() as tmp:
            result = self.runner.invoke(
                cli, ["--json", "doctor", "--no-network"], env=self._doctor_env(tmp)
            )
        payload = json.loads(result.output)
        table = next(c for c in payload["checks"] if c["name"] == "gemini_model_table")["detail"]
        self.assertIn("escalation=(off)", table)
        self.assertIn("binding_retry=claude-sonnet-5-5", table)

    def test_doctor_needs_an_anthropic_key_under_default_settings(self) -> None:
        """Sub-project C: every default task tag is a claude- model."""
        with TemporaryDirectory() as tmp:
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env=self._doctor_env(tmp, ANTHROPIC_API_KEY=None),
            )
        self.assertEqual(result.exit_code, 3, msg=result.output)
        payload = json.loads(result.output)
        check = next(c for c in payload["checks"] if c["name"] == "anthropic_api_key")
        self.assertFalse(check["ok"])

    def test_doctor_does_not_need_an_anthropic_key_when_every_tag_is_on_gemini(self) -> None:
        with TemporaryDirectory() as tmp:
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env=self._doctor_env(tmp, ANTHROPIC_API_KEY=None, **_ALL_GEMINI),
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        check = next(c for c in payload["checks"] if c["name"] == "anthropic_api_key")
        self.assertTrue(check["ok"])

    def test_doctor_passes_the_gemini_key_check_with_no_key_when_every_tag_is_claude(self) -> None:
        with TemporaryDirectory() as tmp:
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env=self._doctor_env(
                    tmp, GEMINI_API_KEY=None, LEMELY_GEMINI__MARK_SCHEME_MODEL="claude-haiku-5-5"
                ),
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        check = next(c for c in payload["checks"] if c["name"] == "gemini_api_key")
        self.assertTrue(check["ok"])

    def test_doctor_lists_mark_scheme_under_the_gemini_key_by_default(self) -> None:
        """Mark-scheme parsing stays on Gemini, so a default install needs the Gemini key."""
        with TemporaryDirectory() as tmp:
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env=self._doctor_env(tmp, GEMINI_API_KEY=None),
            )
        self.assertEqual(result.exit_code, 3, msg=result.output)
        payload = json.loads(result.output)
        check = next(c for c in payload["checks"] if c["name"] == "gemini_api_key")
        self.assertFalse(check["ok"])
        self.assertEqual(check["detail"].count("="), 1)
        self.assertIn("mark_scheme=gemini-2.5-flash", check["detail"])

    def test_doctor_fails_the_gemini_key_check_for_one_gemini_tag_and_no_key(self) -> None:
        with TemporaryDirectory() as tmp:
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env=self._doctor_env(
                    tmp,
                    GEMINI_API_KEY=None,
                    LEMELY_GEMINI__SCAN_METADATA_MODEL="gemini-3.5-flash-lite",
                ),
            )
        self.assertEqual(result.exit_code, 3, msg=result.output)
        payload = json.loads(result.output)
        check = next(c for c in payload["checks"] if c["name"] == "gemini_api_key")
        self.assertFalse(check["ok"])
        self.assertIn("scan_metadata=gemini-3.5-flash-lite", check["detail"])
        self.assertNotIn("extraction=", check["detail"])

    def test_doctor_succeeds_with_valid_env(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
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
                "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
                # One Gemini tag, so the live Gemini ping is the check under test.
                "LEMELY_GEMINI__EXTRACTION_MODEL": "gemini-3.5-flash-lite",
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
                    "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
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
                    "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
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

    # -- The tutor evidence bucket (review finding 5). Before this line the
    # doctor probed uploads and avatars only, so a deploy whose bootstrap was
    # never re-run looked healthy while every evidence upload answered 503.

    def _evidence_check(
        self, args: list[str], **extra: str | None
    ) -> tuple[dict[str, object], dict[str, object], Path]:
        """Run the doctor; return its payload, the evidence check and the output dir."""
        from unittest.mock import patch

        with TemporaryDirectory() as tmp:
            # ADC is never consulted for real: the gcs storage line asks for it even
            # with --no-network, and a developer machine may or may not have it.
            with (
                patch("google.auth.default", return_value=(None, "proj-1234")),
                patch("lemely.io.gemini.GeminiClient.check_reachable", return_value=None),
            ):
                result = self.runner.invoke(
                    cli, ["--json", "doctor", *args], env=self._doctor_env(tmp, **extra)
                )
            self.assertEqual(result.exit_code, 0, msg=result.output)
            payload = json.loads(result.output)
            outputs = Path(tmp) / "outputs"
            check = next(c for c in payload["checks"] if c["name"] == "tutor_evidence_storage")
            directory_exists = (outputs / "storage" / "lemely-tutor-evidence").is_dir()
        return payload, {**check, "directory_exists": directory_exists}, outputs

    def test_doctor_reports_the_local_evidence_directory(self) -> None:
        payload, check, outputs = self._evidence_check(["--no-network"])
        self.assertTrue(check["ok"], msg=check)
        self.assertEqual(check["detail"], str(outputs / "storage" / "lemely-tutor-evidence"))
        self.assertTrue(check["directory_exists"])
        self.assertTrue(payload["all_passed"])

    def test_doctor_reports_a_gcs_evidence_bucket_without_a_project_number(self) -> None:
        """Fail closed, and say which setting is missing; advisory, like the storage line."""
        payload, check, _ = self._evidence_check(
            ["--no-network"],
            LEMELY_STORAGE__BACKEND="gcs",
            LEMELY_STORAGE__TUTOR_EVIDENCE_BUCKET="proj-1234-tutor-evidence-staging",
        )
        self.assertFalse(check["ok"], msg=check)
        self.assertIn("LEMELY_STORAGE__GCS_PROJECT_NUMBER", str(check["detail"]))
        self.assertTrue(payload["all_passed"])

    def test_doctor_reports_the_placeholder_evidence_bucket_under_gcs(self) -> None:
        _, check, _ = self._evidence_check(
            ["--no-network"],
            LEMELY_STORAGE__BACKEND="gcs",
            LEMELY_STORAGE__GCS_PROJECT_NUMBER="123456789012",
        )
        self.assertFalse(check["ok"], msg=check)
        self.assertIn("LEMELY_STORAGE__TUTOR_EVIDENCE_BUCKET", str(check["detail"]))
        self.assertFalse(check["directory_exists"])

    def test_doctor_does_not_probe_the_evidence_bucket_with_no_network(self) -> None:
        _, check, _ = self._evidence_check(
            ["--no-network"],
            LEMELY_STORAGE__BACKEND="gcs",
            LEMELY_STORAGE__TUTOR_EVIDENCE_BUCKET="proj-1234-tutor-evidence-staging",
            LEMELY_STORAGE__GCS_PROJECT_NUMBER="123456789012",
        )
        self.assertTrue(check["ok"], msg=check)
        self.assertIn("gcs://proj-1234-tutor-evidence-staging", str(check["detail"]))
        self.assertIn("not probed", str(check["detail"]))

    def test_doctor_probes_the_evidence_bucket_owner_over_the_network(self) -> None:
        """The probe reports the privacy-and-owner result, not merely that the bucket answers."""
        from unittest.mock import MagicMock, patch

        from google.cloud import storage

        def _metadata(owner: str) -> storage.Bucket:
            bucket = storage.Bucket(MagicMock(), name="proj-1234-tutor-evidence-staging")
            bucket._set_properties(
                {
                    "projectNumber": owner,
                    "iamConfiguration": {
                        "publicAccessPrevention": "enforced",
                        "uniformBucketLevelAccess": {"enabled": True},
                    },
                }
            )
            return bucket

        env = {
            "LEMELY_STORAGE__BACKEND": "gcs",
            "LEMELY_STORAGE__TUTOR_EVIDENCE_BUCKET": "proj-1234-tutor-evidence-staging",
            "LEMELY_STORAGE__GCS_PROJECT_NUMBER": "123456789012",
        }
        for owner, ok in (("123456789012", True), ("987654321098", False)):
            client = MagicMock()
            client.get_bucket.return_value = _metadata(owner)
            with patch("google.cloud.storage.Client", return_value=client):
                payload, check, _ = self._evidence_check([], **env)
            self.assertIs(check["ok"], ok, msg=check)
            client.get_bucket.assert_any_call("proj-1234-tutor-evidence-staging", timeout=30.0)
            self.assertTrue(payload["all_passed"])
        self.assertIn("belongs to project number 987654321098", str(check["detail"]))

    def test_doctor_warns_on_a_stale_key_in_dot_env_without_failing(self) -> None:
        """Spec 2026-09-26 §11 (#6): a removed key left in `.env` is reported
        the way a TOML one is (advisory, exit 0), instead of crashing
        load_settings before doctor can run at all.

        Fix round 1: the suite's own ``tests/conftest.py::_disable_dotenv_file``
        fixture sets ``Settings.model_config["env_file"] = None`` for every
        test, so it must be re-enabled here for the ``load_settings`` call
        inside ``doctor_cmd`` to actually read this test's ``.env`` -- without
        that, the crash-avoidance claim above would be true only because the
        removed key is never read in the first place, not because the fix
        (``_RemovedKeysDotEnvSource``) works.
        """
        original_env_file = Settings.model_config.get("env_file")
        Settings.model_config["env_file"] = ".env"
        try:
            with TemporaryDirectory() as tmp:
                (Path(tmp) / "Sources").mkdir()
                (Path(tmp) / "outputs").mkdir()
                toml_path = Path(tmp) / "lemely.toml"
                toml_path.write_text("[integrity]\nplagiarism_enabled = true\n")
                (Path(tmp) / ".env").write_text("LEMELY_INTEGRITY__AI_DETECTION_ENABLED=true\n")
                with contextlib.chdir(tmp):
                    result = self.runner.invoke(
                        cli,
                        ["--json", "--config", str(toml_path), "doctor", "--no-network"],
                        env={
                            "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                            "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
                            "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                            "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                            "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                        },
                    )
        finally:
            Settings.model_config["env_file"] = original_env_file
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertTrue(payload["all_passed"], msg=result.output)
        check = next(c for c in payload["checks"] if c["name"] == "no_removed_config_keys")
        self.assertFalse(check["ok"])
        self.assertIn("integrity.ai_detection_enabled", check["detail"])


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
                    "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
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
                    "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
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
        """US-026: `lemely doctor` warns, but does not fail, when the 3.8/
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
                        "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
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
                        "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
                        "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                        "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                        "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                    },
                )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        check = next(c for c in payload["checks"] if c["name"] == "gemini_promo_pricing_window")
        self.assertTrue(check["ok"], msg=check)

    def test_doctor_warns_on_an_unparseable_cost_ledger_without_failing(self) -> None:
        """US-035: a present-but-corrupt gemini_spend.json is advisory, never
        fatal (fail-open, per ruling) — but `doctor` must name it."""
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            outputs = Path(tmp) / "outputs"
            outputs.mkdir()
            (outputs / "gemini_spend.json").write_text("{ not valid json", encoding="utf-8")
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    "LEMELY_PATHS__OUTPUT_DIR": str(outputs),
                    "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                },
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["all_passed"], msg=result.output)
        check = next(c for c in payload["checks"] if c["name"] == "gemini_cost_ledger")
        self.assertFalse(check["ok"], msg=check)
        self.assertIn("gemini_spend.json", check["detail"])

    def test_doctor_does_not_warn_on_an_absent_cost_ledger(self) -> None:
        """Absent is the legitimate first-run state, not corruption."""
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            outputs = Path(tmp) / "outputs"
            outputs.mkdir()
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    "LEMELY_PATHS__OUTPUT_DIR": str(outputs),
                    "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                },
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.stdout)
        check = next(c for c in payload["checks"] if c["name"] == "gemini_cost_ledger")
        self.assertTrue(check["ok"], msg=check)

    def test_doctor_does_not_warn_on_a_healthy_cost_ledger(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            outputs = Path(tmp) / "outputs"
            outputs.mkdir()
            from lemely.io.cost_ledger import CostLedger

            CostLedger(outputs / "gemini_spend.json").add(1.0, thresholds=[])
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    "LEMELY_PATHS__OUTPUT_DIR": str(outputs),
                    "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                },
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.stdout)
        check = next(c for c in payload["checks"] if c["name"] == "gemini_cost_ledger")
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
                        "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
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
                    "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
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
                    "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
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
                    "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
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


class DoctorBindingTests(unittest.TestCase):
    """`lemely doctor` shows how answers are bound and what that costs."""

    def setUp(self) -> None:
        self.runner = CliRunner()

    def _doctor(self, **extra_env: str) -> dict[str, dict[str, object]]:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "Sources").mkdir()
            (Path(tmp) / "outputs").mkdir()
            result = self.runner.invoke(
                cli,
                ["--json", "doctor", "--no-network"],
                env={
                    "GEMINI_API_KEY": "test-key-not-validated-with-no-network",
                    "ANTHROPIC_API_KEY": "test-anthropic-key-not-validated",
                    "LEMELY_PATHS__SOURCES_DIR": str(Path(tmp) / "Sources"),
                    "LEMELY_PATHS__OUTPUT_DIR": str(Path(tmp) / "outputs"),
                    "LEMELY_PATHS__CACHE_DIR": str(Path(tmp) / "cache"),
                    **extra_env,
                },
            )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertTrue(payload["all_passed"], msg=result.output)
        return {check["name"]: check for check in payload["checks"]}

    def test_doctor_shows_the_binder_its_model_and_both_reads(self) -> None:
        checks = self._doctor()
        self.assertIn("binding_read=claude-haiku-5-5", checks["gemini_model_table"]["detail"])
        binding = checks["binding"]
        self.assertTrue(binding["ok"], msg=binding)
        # Both reads think "low" since cost-ladder B1; the table names the second read's
        # tag, so that is a choice and not a warning, and the advisory says what makes
        # the second read independent.
        for expected in (
            "binder=label",
            "gate=enforce",
            "both reads on claude-haiku-5-5 think low",
            "b1-second-read-low/verdict.json",
            "own task tag and cache key",
        ):
            self.assertIn(expected, binding["detail"])

    def test_doctor_reports_a_cross_model_second_read(self) -> None:
        # The first read is pinned to Gemini: the default read model is claude-haiku-5-5 now,
        # which would make the second read the same model rather than a cross-model one.
        checks = self._doctor(
            LEMELY_BINDING__READ_MODEL="gemini-3.8-flash",
            LEMELY_BINDING__SECOND_READ_MODEL="claude-haiku-5-5",
            ANTHROPIC_API_KEY="test-key-not-validated-with-no-network",
        )
        binding = checks["binding"]
        self.assertTrue(binding["ok"], msg=binding)
        for expected in (
            "first on gemini-3.8-flash (thinking low)",
            "second on claude-haiku-5-5 (thinking low)",
            "two reads per extraction",
        ):
            self.assertIn(expected, binding["detail"])
        self.assertNotIn("b1-second-read-low", binding["detail"])

    def test_doctor_reports_on_trigger_mode_when_both_reads_think_alike(self) -> None:
        always = self._doctor()["binding"]["detail"]
        self.assertIn("two reads per extraction", always)
        on_trigger = self._doctor(LEMELY_BINDING__SECOND_READ_MODE="on_trigger")["binding"]
        self.assertTrue(on_trigger["ok"], msg=on_trigger)
        self.assertIn("think low", on_trigger["detail"])
        self.assertIn("only when the first gives a reason for it", on_trigger["detail"])
        self.assertNotIn("two reads per extraction", on_trigger["detail"])

    def test_doctor_warns_when_the_second_read_is_the_first_one_again(self) -> None:
        # A [gemini.thinking_level_for] table replaces the defaults, so one written
        # before the binder existed leaves `binding_second_read` out: both reads then
        # resolve to the same thinking level on the same model.
        checks = self._doctor(LEMELY_GEMINI__THINKING_LEVEL_FOR='{"extraction": "minimal"}')
        binding = checks["binding"]
        self.assertFalse(binding["ok"], msg=binding)
        self.assertIn("binding_second_read", binding["detail"])
        self.assertIn("same", binding["detail"])

    def test_doctor_advises_the_budget_table_for_a_read_model_that_ignores_levels(self) -> None:
        # A 2.5 model reads [gemini.thinking_budget_for], not thinking_level_for: both
        # reads resolve to the same budget, and the level table would change nothing.
        checks = self._doctor(LEMELY_BINDING__READ_MODEL="gemini-2.5-flash")
        binding = checks["binding"]
        self.assertFalse(binding["ok"], msg=binding)
        self.assertIn("thinking_budget_for", binding["detail"])
        self.assertNotIn("thinking_level_for", binding["detail"])

    def test_doctor_prices_the_binder_model(self) -> None:
        checks = self._doctor(LEMELY_BINDING__READ_MODEL="totally-fake-model-does-not-exist")
        pricing = checks["gemini_fallback_pricing"]
        self.assertFalse(pricing["ok"], msg=pricing)
        self.assertIn("binding_read=totally-fake-model-does-not-exist", pricing["detail"])

    def test_doctor_shows_the_legacy_binder_and_its_retry_model(self) -> None:
        checks = self._doctor(LEMELY_BINDING__BINDER="legacy")
        self.assertIn("binding_retry=claude-sonnet-5-5", checks["gemini_model_table"]["detail"])
        self.assertNotIn("binding_read=", checks["gemini_model_table"]["detail"])
        self.assertIn("binder=legacy", checks["binding"]["detail"])

        ungated = self._doctor(LEMELY_BINDING__BINDER="legacy", LEMELY_BINDING__GATE="off")
        self.assertNotIn("binding_", ungated["gemini_model_table"]["detail"])
        self.assertIn("gate=off", ungated["binding"]["detail"])


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
