"""Tests for raw/final evaluation and report generation."""

import json
import os
import unittest
from io import StringIO
from unittest.mock import patch

import django
from django.core.management import call_command
from django.core.management.base import CommandError

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
django.setup()

from briefing.providers import MockProvider
from briefing.schema import Briefing
from briefing.service import BriefingMetadata
from evals.checks import evaluate_checks
from evals.runner import (
    CHECK_NAMES,
    load_thresholds,
    quality_gate_failures,
    run_evaluations,
    write_report,
)
from evals.scenarios import load_scenarios


class EvaluationRunnerTests(unittest.TestCase):
    def test_runner_records_raw_final_pass_rates_interventions_and_fallbacks(self):
        scenario = next(
            scenario
            for scenario in load_scenarios()
            if scenario["category"] == "severe_or_no_travel"
        )

        def generate(plan):
            response = MockProvider("faulty_number").generate("", json.dumps(plan))
            return (
                Briefing.model_validate_json(response.text),
                BriefingMetadata(
                    provider="mock",
                    model="rule-based",
                    prompt_version="v1",
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=0,
                    retry_count=0,
                ),
            )

        report, results = run_evaluations([scenario], generate)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["raw_checks"]["numbers_grounded"])
        self.assertTrue(all(results[0]["final_checks"].values()))
        self.assertTrue(results[0]["fallback_used"])
        self.assertIn("fallback_template", results[0]["interventions"])
        self.assertIn("Raw pass rate", report)
        self.assertIn("Final pass rate", report)
        self.assertIn("Provider: mock", report)
        self.assertIn("Model: rule-based", report)
        self.assertIn("Prompt version: v1", report)
        self.assertIn("Pass rates by scenario category", report)
        self.assertIn("| severe | 1 |", report)
        self.assertIn("fallback_template", report)
        self.assertEqual(
            len(CHECK_NAMES),
            len(
                evaluate_checks(
                    Briefing.model_validate_json(
                        MockProvider("normal")
                        .generate("", json.dumps(scenario["plan"]))
                        .text
                    ),
                    scenario["plan"],
                )
            ),
        )

    def test_report_is_written_to_requested_location(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "reports" / "latest.md"
            write_report("# report\n", path)
            self.assertEqual(path.read_text(encoding="utf-8"), "# report\n")

    def test_configured_thresholds_are_all_safety_checks_at_100_percent(self):
        thresholds = load_thresholds()
        self.assertEqual(set(thresholds), set(CHECK_NAMES))
        self.assertTrue(all(value == 1.0 for value in thresholds.values()))

    def test_quality_gate_reports_threshold_misses(self):
        checks = {name: True for name in CHECK_NAMES}
        checks["no_false_safe"] = False
        failures = quality_gate_failures(
            [{"final_checks": checks}],
            {"route_matches_engine": 1.0, "no_false_safe": 1.0},
        )
        self.assertEqual(
            failures,
            ["no_false_safe: final pass rate 0.0% is below required 100.0%"],
        )

    def test_management_command_exits_with_error_when_gate_fails(self):
        report_results = [
            {"final_checks": {name: True for name in CHECK_NAMES}}
        ]
        with patch(
            "briefing.management.commands.run_evals.run_evaluations",
            return_value=("# report", report_results),
        ), patch(
            "briefing.management.commands.run_evals.quality_gate_failures",
            return_value=["no_false_safe: threshold missed"],
        ), patch(
            "briefing.management.commands.run_evals.render_quality_gate",
            return_value="\n# gate\n",
        ), patch("briefing.management.commands.run_evals.write_report"):
            with self.assertRaises(CommandError):
                call_command("run_evals", "--gate", stdout=StringIO())
