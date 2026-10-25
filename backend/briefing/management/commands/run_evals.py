"""Run the golden briefing evaluation suite."""

from django.core.management.base import BaseCommand, CommandError

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

    def handle(self, *args, **options):
        try:
            report, results = run_evaluations()
            failures = quality_gate_failures(results)
            report += render_quality_gate(results)
            write_report(report)
        except Exception as error:
            raise CommandError(
                "Briefing evaluation failed ({}): {}".format(
                    type(error).__name__, error
                )
            ) from error
        self.stdout.write(
            self.style.SUCCESS(
                "Evaluated {} scenarios; report written to {}.".format(
                    len(results), REPORT_PATH
                )
            )
        )
        if options["gate"] and failures:
            raise CommandError(
                "Evaluation quality gate failed: {}".format("; ".join(failures))
            )
        if options["gate"]:
            self.stdout.write(self.style.SUCCESS("Evaluation quality gate passed."))
