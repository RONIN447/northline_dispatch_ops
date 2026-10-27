"""Run the golden briefing evaluation suite."""

from django.core.management.base import BaseCommand, CommandError
from pathlib import Path

from evals.runner import (
    REPORT_PATH,
    quality_gate_failures,
    render_quality_gate,
    run_evaluations,
    write_report,
)


class Command(BaseCommand):
    help = "Evaluate raw and validator-corrected briefings on the golden scenarios."

    def add_arguments(self, parser):
        parser.add_argument(
            "--gate",
            action="store_true",
            help="Exit with an error if final pass rates miss configured thresholds.",
        )
        parser.add_argument(
            "--output",
            default=str(REPORT_PATH),
            help="Write the report to this path instead of evals/reports/latest.md.",
        )

    def handle(self, *args, **options):
        report_path = Path(options["output"])
        try:
            report, results = run_evaluations()
            failures = quality_gate_failures(results)
            report += render_quality_gate(results)
            write_report(report, report_path)
        except Exception as error:
            raise CommandError(
                "Briefing evaluation failed ({}): {}".format(
                    type(error).__name__, error
                )
            ) from error
        self.stdout.write(
            self.style.SUCCESS(
                "Evaluated {} scenarios; report written to {}.".format(
                    len(results), report_path.resolve()
                )
            )
        )
        if options["gate"] and failures:
            raise CommandError(
                "Evaluation quality gate failed: {}".format("; ".join(failures))
            )
        if options["gate"]:
            self.stdout.write(self.style.SUCCESS("Evaluation quality gate passed."))
