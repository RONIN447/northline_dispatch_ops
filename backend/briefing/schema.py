"""Pydantic schemas for validating weather-aware route plans."""

from typing import List, Optional

from pydantic import BaseModel, field_validator, model_validator

from routing.risk_levels import RISK_LEVELS


class BriefingLocation(BaseModel):
    label: str
    lat: float
    lon: float
    timezone: str


class BriefingCheckpoint(BaseModel):
    mile: float
    lat: float
    lon: float
    eta: str
    windMph: float
    rainInHr: float
    snowInHr: float
    temperatureF: Optional[float] = None
    forecastHour: Optional[str] = None
    risk: str

    @field_validator("risk")
    @classmethod
    def validate_risk(cls, value: str) -> str:
        if value not in RISK_LEVELS:
            raise ValueError(f"Risk must be one of: {', '.join(RISK_LEVELS)}")
        return value


class BriefingRoute(BaseModel):
    id: str
    distanceMiles: float
    durationHours: float
    arrival: str
    geometry: List[List[float]]
    checkpoints: List[BriefingCheckpoint]
    severeMiles: float
    highMiles: float
    noTravelMiles: float
    averageRisk: float
    summary: str
    recommended: bool


class BriefingRoutePlan(BaseModel):
    origin: BriefingLocation
    destination: BriefingLocation
    routes: List[BriefingRoute]
    recommendedRouteId: str
    forecastHours: int

    @model_validator(mode="after")
    def recommended_route_exists(self) -> "BriefingRoutePlan":
        if not any(route.id == self.recommendedRouteId for route in self.routes):
            raise ValueError("recommendedRouteId must match a route in routes")
        return self


class RiskyCheckpoint(BaseModel):
    route_id: str
    checkpoint_index: int
    level: str

    @field_validator("level")
    @classmethod
    def validate_level(cls, value: str) -> str:
        if value not in RISK_LEVELS:
            raise ValueError(f"Level must be one of: {', '.join(RISK_LEVELS)}")
        return value


class Briefing(BaseModel):
    recommended_route_id: str
    summary: str
    risky_checkpoints: List[RiskyCheckpoint]
    data_gaps: List[str]
    dispatcher_actions: List[str]
