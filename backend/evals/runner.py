"""Run raw and validator-corrected briefings against the golden scenarios."""

from collections import Counter
from pathlib import Path

from briefing.validator import enforce
from evals.checks import evaluate_checks
from evals.scenarios import load_scenarios

CHECK_NAMES = (
    "route_matches_engine",
    "severe_coverage",
    "no_risk_downgrade",
    "no_false_safe",
    "numbers_grounded",
    "route_ids_grounded",
    "place_names_grounded",
)
REPORT_PATH = Path(__file__).resolve().parent / "reports" / "latest.md"
THRESHOLDS_PATH = Path(__file__).resolve().parent / "thresholds.yaml"


def run_evaluations(scenarios=None, generate=None):
    """Evaluate every scenario and return report text plus structured results."""
    if scenarios is None:
        scenarios = load_scenarios()
    if generate is None:
        from briefing.service import generate_briefing

        generate = generate_briefing

    results = []
    intervention_counts = Counter()
    fallback_count = 0
    for scenario in scenarios:
        plan = scenario["plan"]
        raw, metadata = generate(plan)
        raw_checks = evaluate_checks(raw, plan)
        final, interventions, fallback_used = enforce(plan, raw)
        final_checks = evaluate_checks(final, plan)
        intervention_counts.update(item.rule for item in interventions)
        fallback_count += int(fallback_used)
        results.append(
            {
                "id": scenario["id"],
                "provider": metadata.provider,
                "raw_checks": raw_checks,
                "final_checks": final_checks,
                "interventions": [item.rule for item in interventions],
                "fallback_used": fallback_used,
            }
        )

    report = render_report(results, intervention_counts, fallback_count)
    return report, results


def render_report(results, intervention_counts, fallback_count):
    """Render aggregate raw/final pass rates and correction counts as Markdown."""
    total = len(results)
    lines = [
        "# Briefing evaluation report",
        "",
        "Scenarios: {} | Raw briefings: {} | Validator-corrected briefings: {}".format(
            total, total, total
        ),
        "",
        "| Check | Raw pass rate | Final pass rate |",
        "| --- | ---: | ---: |",
    ]
    for check in CHECK_NAMES:
        raw_passes = sum(result["raw_checks"][check] for result in results)
        final_passes = sum(result["final_checks"][check] for result in results)
        lines.append(
            "| {} | {}/{} ({:.1f}%) | {}/{} ({:.1f}%) |".format(
                check,
                raw_passes,
                total,
                _percentage(raw_passes, total),
                final_passes,
                total,
                _percentage(final_passes, total),
            )
        )

    lines.extend(
        [
            "",
            "## Validator interventions",
            "",
            "Fallback template used: {}/{} scenarios.".format(fallback_count, total),
        ]
    )
    if intervention_counts:
        lines.extend(["", "| Rule | Count |", "| --- | ---: |"])
        for rule, count in sorted(intervention_counts.items()):
            lines.append("| {} | {} |".format(rule, count))
    else:
        lines.extend(["", "No validator interventions were required."])
    lines.extend(
        [
            "",
            "## Scenario results",
            "",
            "| Scenario | Provider | Raw checks passed | Final checks passed | Interventions | Fallback |",
            "| --- | --- | ---: | ---: | --- | --- |",
        ]
    )
    for result in results:
        raw_passes = sum(result["raw_checks"].values())
        final_passes = sum(result["final_checks"].values())
        lines.append(
            "| {} | {} | {}/{} | {}/{} | {} | {} |".format(
                result["id"],
                result["provider"],
                raw_passes,
                len(CHECK_NAMES),
                final_passes,
                len(CHECK_NAMES),
                ", ".join(result["interventions"]) or "-",
                "yes" if result["fallback_used"] else "no",
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_report(report, path=REPORT_PATH):
    """Persist a completed report, creating the report directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")


def load_thresholds(path=THRESHOLDS_PATH):
    """Load and validate configured minimum final-output pass rates."""
    import yaml

    with path.open(encoding="utf-8") as threshold_file:
        config = yaml.safe_load(threshold_file)
    if not isinstance(config, dict) or not isinstance(
        config.get("final_pass_rates"), dict
    ):
        raise ValueError("Thresholds must define a final_pass_rates mapping.")
    thresholds = config["final_pass_rates"]
    unknown = set(thresholds) - set(CHECK_NAMES)
    if unknown:
        raise ValueError("Unknown evaluation checks in thresholds: {}".format(
            ", ".join(sorted(unknown))
        ))
    missing = set(CHECK_NAMES) - set(thresholds)
    if missing:
        raise ValueError("Missing evaluation thresholds: {}".format(
            ", ".join(sorted(missing))
        ))
    for check, threshold in thresholds.items():
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise ValueError("Threshold for {} must be a number.".format(check))
        if not 0 <= threshold <= 1:
            raise ValueError("Threshold for {} must be between 0 and 1.".format(check))
    return thresholds


def quality_gate_failures(results, thresholds=None):
    """Return final pass-rate threshold violations for the requested checks."""
    if thresholds is None:
        thresholds = load_thresholds()
    total = len(results)
    failures = []
    for check, minimum in thresholds.items():
        passed = sum(result["final_checks"][check] for result in results)
        rate = passed / total if total else 0.0
        if rate < minimum:
            failures.append(
                "{}: final pass rate {:.1%} is below required {:.1%}".format(
                    check, rate, minimum
                )
            )
    return failures


def render_quality_gate(results, thresholds=None):
    """Render final pass rates against the configured CI thresholds."""
    if thresholds is None:
        thresholds = load_thresholds()
    total = len(results)
    lines = ["", "## Final-output quality gate", ""]
    lines.extend(
        [
            "| Check | Final pass rate | Required | Result |",
            "| --- | ---: | ---: | --- |",
        ]
    )
    for check, minimum in thresholds.items():
        passed = sum(result["final_checks"][check] for result in results)
        rate = passed / total if total else 0.0
        result = "PASS" if rate >= minimum else "FAIL"
        lines.append(
            "| {} | {:.1%} | {:.1%} | {} |".format(
                check, rate, minimum, result
            )
        )
    return "\n".join(lines) + "\n"


def _percentage(passes, total):
    return 100.0 * passes / total if total else 0.0
