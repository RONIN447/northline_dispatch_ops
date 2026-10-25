"""Deterministic guardrails for generated dispatch briefings."""

from dataclasses import dataclass
from typing import List, Set, Tuple

from briefing.schema import Briefing, RiskyCheckpoint
from evals.checks import (
    evaluate_checks,
    expected_data_gaps,
    expected_risky_checkpoints,
    validate_briefing,
)
from routing.risk_levels import RISK_LEVELS


@dataclass(frozen=True)
class Intervention:
    rule: str
    detail: str


class BriefingValidationError(RuntimeError):
    """Raised if validator corrections cannot satisfy the shared safety checks."""


def enforce(plan: dict, briefing: Briefing) -> Tuple[Briefing, List[Intervention], bool]:
    """Return a corrected briefing, structured interventions, and fallback status."""
    final = briefing.model_copy(deep=True)
    interventions = []
    fallback_used = False

    recommended_route_id = plan["recommendedRouteId"]
    if final.recommended_route_id != recommended_route_id:
        interventions.append(
            Intervention(
                rule="canonical_recommended_route",
                detail="Changed recommended route to {}.".format(recommended_route_id),
            )
        )
        final.recommended_route_id = recommended_route_id

    canonical_gaps = expected_data_gaps(plan)
    if final.data_gaps != canonical_gaps:
        interventions.append(
            Intervention(
                rule="restore_data_gaps",
                detail="Replaced briefing data gaps with the plan's canonical missing-weather list.",
            )
        )
        final.data_gaps = canonical_gaps

    expected_risks = expected_risky_checkpoints(plan)
    plan_risks = {
        (route_id, checkpoint_index): level
        for route_id, checkpoint_index, level in expected_risks
    }
    seen: Set[Tuple[str, int]] = set()
    corrected_risks = []
    for checkpoint in final.risky_checkpoints:
        key = (checkpoint.route_id, checkpoint.checkpoint_index)
        plan_level = plan_risks.get(key)
        if plan_level is None:
            interventions.append(
                Intervention(
                    rule="remove_unexpected_risky_checkpoint",
                    detail="Removed {} checkpoint {} from the risky list.".format(*key),
                )
            )
            continue
        if key in seen:
            interventions.append(
                Intervention(
                    rule="remove_duplicate_risky_checkpoint",
                    detail="Removed duplicate {} checkpoint {}.".format(*key),
                )
            )
            continue
        seen.add(key)
        if checkpoint.level != plan_level:
            if RISK_LEVELS.index(checkpoint.level) < RISK_LEVELS.index(plan_level):
                rule = "restore_downgraded_risk"
                detail = "Restored {} checkpoint {} from {} to {}.".format(
                    checkpoint.route_id,
                    checkpoint.checkpoint_index,
                    checkpoint.level,
                    plan_level,
                )
            else:
                rule = "match_engine_risk"
                detail = "Changed {} checkpoint {} from {} to {}.".format(
                    checkpoint.route_id,
                    checkpoint.checkpoint_index,
                    checkpoint.level,
                    plan_level,
                )
            interventions.append(Intervention(rule=rule, detail=detail))
        corrected_risks.append(
            RiskyCheckpoint(
                route_id=checkpoint.route_id,
                checkpoint_index=checkpoint.checkpoint_index,
                level=plan_level,
            )
        )

    for route_id, checkpoint_index, level in expected_risks:
        key = (route_id, checkpoint_index)
        if key not in seen:
            corrected_risks.append(
                RiskyCheckpoint(
                    route_id=route_id,
                    checkpoint_index=checkpoint_index,
                    level=level,
                )
            )
            seen.add(key)
            interventions.append(
                Intervention(
                    rule="add_required_risky_checkpoint",
                    detail="Added {} checkpoint {} at {} risk.".format(
                        route_id, checkpoint_index, level
                    ),
                )
            )
    final.risky_checkpoints = corrected_risks

    grounding_errors = validate_briefing(final, plan)
    if any(
        error in grounding_errors
        for error in (
            "unsupported_number",
            "unsupported_route_id",
            "unsupported_place_name",
            "false_safe_claim",
        )
    ):
        final = _template_briefing(plan)
        fallback_used = True
        interventions.append(
            Intervention(
                rule="fallback_template",
                detail="Replaced ungrounded summary/actions with a deterministic plan-based template.",
            )
        )

    remaining_errors = validate_briefing(final, plan)
    failed_checks = [
        check
        for check, passed in evaluate_checks(final, plan).items()
        if not passed
    ]
    if remaining_errors or failed_checks:
        raise BriefingValidationError(
            "Briefing validator could not satisfy shared checks: {}".format(
                ", ".join(remaining_errors + failed_checks)
            )
        )
    return final, interventions, fallback_used


def _template_briefing(plan: dict) -> Briefing:
    recommended_route_id = plan["recommendedRouteId"]
    route = next(
        route for route in plan["routes"] if route["id"] == recommended_route_id
    )
    risky_checkpoints = [
        RiskyCheckpoint(
            route_id=route_id,
            checkpoint_index=checkpoint_index,
            level=level,
        )
        for route_id, checkpoint_index, level in expected_risky_checkpoints(plan)
    ]
    data_gaps = expected_data_gaps(plan)
    actions = ["Review checkpoint conditions before dispatch."]
    if data_gaps:
        actions.append("Review the listed forecast data gaps before dispatch.")
    return Briefing(
        recommended_route_id=recommended_route_id,
        summary=(
            "Recommended route: {} ({} mi, {} hr); severe exposure {} mi, "
            "high-risk exposure {} mi, no-travel exposure {} mi."
        ).format(
            recommended_route_id,
            route["distanceMiles"],
            route["durationHours"],
            route["severeMiles"],
            route["highMiles"],
            route["noTravelMiles"],
        ),
        risky_checkpoints=risky_checkpoints,
        data_gaps=data_gaps,
        dispatcher_actions=actions,
    )
