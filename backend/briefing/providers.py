"""Rule-based and API-backed providers for dispatch briefings."""

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Optional, Protocol

from routing.risk_levels import HIGH, NO_TRAVEL, RISK_LEVELS, RISK_SCORES, SEVERE

from briefing.schema import Briefing, RiskyCheckpoint

PROVIDER_TIMEOUT_SECONDS = 20.0
GUNICORN_TIMEOUT_SECONDS = 45


@dataclass
class ProviderResponse:
    text: str
    tokens: int
    latency_ms: float
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


class ProviderRequestError(RuntimeError):
    """Raised when a hosted provider request fails."""


class ProviderConfigurationError(RuntimeError):
    """Raised when a production deployment has not selected a provider."""


class Provider(Protocol):
    def generate(self, system: str, user: str) -> ProviderResponse:
        ...


class MockProvider:
    def __init__(self, mode: Optional[str] = None):
        self.mode = (mode or os.getenv("MOCK_MODE", "normal")).lower()
        if self.mode not in {
            "normal",
            "faulty",
            "faulty_route",
            "faulty_missing_checkpoint",
            "faulty_number",
            "faulty_downgrade",
            "faulty_no_gap",
            "faulty_place",
            "faulty_route_id",
            "faulty_safe",
        }:
            raise ValueError(
                "MOCK_MODE must be 'normal', 'faulty', 'faulty_route', "
                "'faulty_missing_checkpoint', 'faulty_number', "
                "'faulty_downgrade', 'faulty_no_gap', 'faulty_place', "
                "'faulty_route_id', or 'faulty_safe'."
            )

    def generate(self, system: str, user: str) -> ProviderResponse:
        started = time.perf_counter()
        try:
            match = re.search(
                r"(?s)^.*?BEGIN_UNTRUSTED_ROUTE_PLAN_DATA\n(.*?)\n"
                r"END_UNTRUSTED_ROUTE_PLAN_DATA.*$",
                user,
            )
            request_data = json.loads(match.group(1) if match else user)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("Mock provider input must be a JSON route plan.") from error
        route_plan = request_data.get("plan", request_data)
        briefing = self._build_briefing(route_plan)
        if self.mode in {"faulty", "faulty_route"}:
            self._make_faulty_route(briefing, route_plan)
        if self.mode in {"faulty", "faulty_missing_checkpoint"}:
            self._make_faulty_missing_checkpoint(briefing)
        if self.mode in {"faulty", "faulty_number"}:
            self._make_faulty_number(briefing)
        if self.mode == "faulty_downgrade":
            briefing = self._make_faulty_downgrade(briefing)
        elif self.mode == "faulty_no_gap":
            briefing.data_gaps = []
        elif self.mode == "faulty_place":
            briefing.dispatcher_actions.append("Reroute through Phoenix.")
        elif self.mode == "faulty_route_id":
            briefing.dispatcher_actions.append("Route route-999 is faster.")
        elif self.mode == "faulty_safe":
            briefing.dispatcher_actions.append("This route is safe to travel.")
        text = briefing.model_dump_json()
        return ProviderResponse(
            text=text,
            tokens=len(system.split()) + len(user.split()) + len(text.split()),
            latency_ms=(time.perf_counter() - started) * 1000,
            input_tokens=len(system.split()) + len(user.split()),
            output_tokens=len(text.split()),
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
    def _make_faulty_route(briefing: Briefing, route_plan: dict) -> None:
        route_ids = [route["id"] for route in route_plan["routes"]]
        wrong_route = next(
            (route_id for route_id in route_ids if route_id != briefing.recommended_route_id),
            "unknown-route",
        )
        briefing.recommended_route_id = wrong_route

    @staticmethod
    def _make_faulty_missing_checkpoint(briefing: Briefing) -> None:
        target_risk = SEVERE
        if not any(item.level == SEVERE for item in briefing.risky_checkpoints):
            target_risk = NO_TRAVEL
        briefing.risky_checkpoints = [
            item for item in briefing.risky_checkpoints if item.level != target_risk
        ]

    @staticmethod
    def _make_faulty_number(briefing: Briefing) -> None:
        briefing.summary += " Estimated delay: 999 hours."

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
        self._api_error_type = anthropic.APIError
        self._client = anthropic.Anthropic(
            api_key=api_key,
            timeout=PROVIDER_TIMEOUT_SECONDS,
            max_retries=0,
        )

    def generate(self, system: str, user: str) -> ProviderResponse:
        started = time.perf_counter()
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1200,
                temperature=0,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except self._api_error_type as error:
            raise ProviderRequestError("Anthropic briefing request failed.") from error
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        return ProviderResponse(
            text,
            input_tokens + output_tokens,
            (time.perf_counter() - started) * 1000,
            input_tokens,
            output_tokens,
        )


class OpenAIProvider:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for the OpenAI provider.")
        self._model = model or os.getenv("OPENAI_MODEL")
        if not self._model:
            raise ValueError("OPENAI_MODEL is required for the OpenAI provider.")
        try:
            from openai import APIError, OpenAI
        except ImportError as error:
            raise RuntimeError("Install the openai package to use this provider.") from error
        self._api_error_type = APIError
        self._client = OpenAI(
            api_key=api_key,
            timeout=PROVIDER_TIMEOUT_SECONDS,
            max_retries=0,
        )

    def generate(self, system: str, user: str) -> ProviderResponse:
        started = time.perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=1200,
            )
        except self._api_error_type as error:
            raise ProviderRequestError("OpenAI briefing request failed.") from error
        text = response.choices[0].message.content or ""
        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0
        return ProviderResponse(
            text,
            input_tokens + output_tokens,
            (time.perf_counter() - started) * 1000,
            input_tokens,
            output_tokens,
        )


def get_provider(name: Optional[str] = None) -> Provider:
    configured_name = name or os.getenv("LLM_PROVIDER")
    if not configured_name and (
        os.getenv("RENDER", "").lower() == "true"
        or os.getenv("DEBUG", "True").lower() not in {"1", "true", "yes", "on"}
    ):
        raise ProviderConfigurationError(
            "LLM_PROVIDER must be configured in production."
        )
    provider_name = (configured_name or "mock").strip().lower()
    if provider_name == "mock":
        return MockProvider()
    if provider_name == "anthropic":
        return AnthropicProvider()
    if provider_name == "openai":
        return OpenAIProvider()
    raise ValueError("LLM_PROVIDER must be 'mock', 'anthropic', or 'openai'.")
