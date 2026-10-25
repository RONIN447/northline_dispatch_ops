"""Rule-based and API-backed providers for dispatch briefings."""

import json
import os
import time
from dataclasses import dataclass
from typing import Optional, Protocol

from routing.risk_levels import HIGH, NO_TRAVEL, RISK_LEVELS, RISK_SCORES, SEVERE

from briefing.schema import Briefing, RiskyCheckpoint

PROVIDER_TIMEOUT_SECONDS = 30.0


@dataclass
class ProviderResponse:
    text: str
    tokens: int
    latency_ms: float


class Provider(Protocol):
    def generate(self, system: str, user: str) -> ProviderResponse:
        ...


class MockProvider:
    def __init__(self, mode: Optional[str] = None):
        self.mode = (mode or os.getenv("MOCK_MODE", "normal")).lower()
        if self.mode not in {
            "normal",
            "faulty",
            "faulty_downgrade",
            "faulty_no_gap",
        }:
            raise ValueError(
                "MOCK_MODE must be 'normal', 'faulty', 'faulty_downgrade', "
                "or 'faulty_no_gap'."
            )

    def generate(self, system: str, user: str) -> ProviderResponse:
        del system
        started = time.perf_counter()
        try:
            request_data = json.loads(user)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("Mock provider input must be a JSON route plan.") from error
        route_plan = request_data.get("plan", request_data)
        briefing = self._build_briefing(route_plan)
        if self.mode == "faulty":
            briefing = self._make_faulty(briefing, route_plan)
        elif self.mode == "faulty_downgrade":
            briefing = self._make_faulty_downgrade(briefing)
        elif self.mode == "faulty_no_gap":
            briefing.data_gaps = []
        text = briefing.model_dump_json()
        return ProviderResponse(
            text=text,
            tokens=len(text.split()),
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    @staticmethod
    def _build_briefing(route_plan: dict) -> Briefing:
        recommended_route_id = route_plan["recommendedRouteId"]
        routes = route_plan["routes"]
        recommended_route = next(
            (route for route in routes if route["id"] == recommended_route_id), None
        )
        if recommended_route is None:
            raise ValueError("Route plan has no route matching recommendedRouteId.")

        risky_checkpoints = []
        data_gaps = []
        for route in routes:
            for index, checkpoint in enumerate(route["checkpoints"]):
                risk = checkpoint.get("risk")
                if risk not in RISK_SCORES:
                    raise ValueError("Route plan contains an unknown checkpoint risk.")
                if RISK_SCORES[risk] >= RISK_SCORES[HIGH]:
                    risky_checkpoints.append(
                        RiskyCheckpoint(
                            route_id=route["id"],
                            checkpoint_index=index,
                            level=risk,
                        )
                    )
                missing = [
                    field
                    for field in ("windMph", "rainInHr", "snowInHr")
                    if checkpoint.get(field) is None
                ]
                if missing:
                    data_gaps.append(
                        "{} checkpoint {} is missing {}.".format(
                            route["id"], index, ", ".join(missing)
                        )
                    )

        summary = (
            "Recommended route: {} ({} mi, {} hr); severe exposure {} mi, "
            "high-risk exposure {} mi, no-travel exposure {} mi."
        ).format(
            recommended_route_id,
            recommended_route["distanceMiles"],
            recommended_route["durationHours"],
            recommended_route["severeMiles"],
            recommended_route["highMiles"],
            recommended_route["noTravelMiles"],
        )
        recommended_risks = [item.level for item in risky_checkpoints
                             if item.route_id == recommended_route_id]
        if NO_TRAVEL in recommended_risks:
            actions = ["Hold dispatch until No Travel checkpoints have been reviewed."]
        elif SEVERE in recommended_risks:
            actions = ["Review Severe checkpoints and consider delaying or rerouting."]
        elif recommended_risks:
            actions = ["Brief the driver on elevated-risk checkpoints and monitor conditions."]
        else:
            actions = ["Proceed with the recommended route and monitor checkpoint forecasts."]

        return Briefing(
            recommended_route_id=recommended_route_id,
            summary=summary,
            risky_checkpoints=risky_checkpoints,
            data_gaps=data_gaps,
            dispatcher_actions=actions,
        )

    @staticmethod
    def _make_faulty(briefing: Briefing, route_plan: dict) -> Briefing:
        route_ids = [route["id"] for route in route_plan["routes"]]
        wrong_route = next(
            (route_id for route_id in route_ids if route_id != briefing.recommended_route_id),
            "unknown-route",
        )
        briefing.recommended_route_id = wrong_route

        target_risk = SEVERE
        if not any(item.level == SEVERE for item in briefing.risky_checkpoints):
            target_risk = NO_TRAVEL
        briefing.risky_checkpoints = [
            item for item in briefing.risky_checkpoints if item.level != target_risk
        ]
        briefing.summary += " Estimated delay: 999 hours."
        return briefing

    @staticmethod
    def _make_faulty_downgrade(briefing: Briefing) -> Briefing:
        for checkpoint in briefing.risky_checkpoints:
            risk_index = RISK_LEVELS.index(checkpoint.level)
            if risk_index > 0:
                checkpoint.level = RISK_LEVELS[risk_index - 1]
                return briefing
        raise ValueError(
            "MOCK_MODE=faulty_downgrade requires a route plan with a risky checkpoint."
        )


class AnthropicProvider:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for the Anthropic provider.")
        self._model = model or os.getenv("ANTHROPIC_MODEL")
        if not self._model:
            raise ValueError("ANTHROPIC_MODEL is required for the Anthropic provider.")
        try:
            import anthropic
        except ImportError as error:
            raise RuntimeError("Install the anthropic package to use this provider.") from error
        self._client = anthropic.Anthropic(
            api_key=api_key,
            timeout=PROVIDER_TIMEOUT_SECONDS,
        )

    def generate(self, system: str, user: str) -> ProviderResponse:
        started = time.perf_counter()
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1200,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        tokens = response.usage.input_tokens + response.usage.output_tokens
        return ProviderResponse(text, tokens, (time.perf_counter() - started) * 1000)


class OpenAIProvider:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for the OpenAI provider.")
        self._model = model or os.getenv("OPENAI_MODEL")
        if not self._model:
            raise ValueError("OPENAI_MODEL is required for the OpenAI provider.")
        try:
            from openai import OpenAI
        except ImportError as error:
            raise RuntimeError("Install the openai package to use this provider.") from error
        self._client = OpenAI(
            api_key=api_key,
            timeout=PROVIDER_TIMEOUT_SECONDS,
        )

    def generate(self, system: str, user: str) -> ProviderResponse:
        started = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        return ProviderResponse(text, tokens, (time.perf_counter() - started) * 1000)


def get_provider(name: Optional[str] = None) -> Provider:
    provider_name = (name or os.getenv("LLM_PROVIDER", "mock")).strip().lower()
    if provider_name == "mock":
        return MockProvider()
    if provider_name == "anthropic":
        return AnthropicProvider()
    if provider_name == "openai":
        return OpenAIProvider()
    raise ValueError("LLM_PROVIDER must be 'mock', 'anthropic', or 'openai'.")
