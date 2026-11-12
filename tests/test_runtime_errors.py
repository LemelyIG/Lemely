"""Tests for lemely.runtime.errors exception hierarchy."""

from __future__ import annotations

import unittest

from lemely.runtime import errors


class ExitCodeTests(unittest.TestCase):
    def test_base_lemely_error_has_exit_code_1(self) -> None:
        self.assertEqual(errors.LemelyError.exit_code, 1)

    def test_subclass_exit_codes_are_distinct_and_documented(self) -> None:
        expected = {
            errors.UsageError: 2,
            errors.ConfigError: 3,
            errors.InputError: 4,
            errors.NotFoundError: 5,
            errors.ParseError: 6,
            errors.ExternalServiceError: 7,
        }
        for cls, code in expected.items():
            with self.subTest(cls=cls.__name__):
                self.assertTrue(issubclass(cls, errors.LemelyError))
                self.assertEqual(cls.exit_code, code)

    def test_partial_failure_error_shares_base_exit_code(self) -> None:
        self.assertEqual(errors.PartialFailureError.exit_code, 1)
        self.assertTrue(issubclass(errors.PartialFailureError, errors.LemelyError))

    def test_cost_ceiling_error_has_its_own_exit_code_distinct_from_external_service_error(
        self,
    ) -> None:
        """I1 review round 4, SHOULD-FIX D: CostCeilingError used to inherit
        ExternalServiceError's exit code 7 unchanged, so a retry wrapper or
        CI job keyed on "exit 7 -> retry" could not tell a genuinely
        retryable transient failure (a 503) apart from a budget-ceiling
        breach, which is a stop signal for the whole run. It must keep
        being a subclass (so existing ``except ExternalServiceError`` call
        sites and assertRaisesRegex(ExternalServiceError, ...) tests keep
        working) but must not share the exit code."""
        self.assertTrue(issubclass(errors.CostCeilingError, errors.ExternalServiceError))
        self.assertNotEqual(
            errors.CostCeilingError.exit_code, errors.ExternalServiceError.exit_code
        )
        self.assertEqual(errors.CostCeilingError.exit_code, 10)

    def test_instances_carry_message(self) -> None:
        err = errors.ConfigError("missing api key")
        self.assertEqual(str(err), "missing api key")
        self.assertEqual(err.exit_code, 3)


if __name__ == "__main__":
    unittest.main()
