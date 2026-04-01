from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["user", "assistant", "system", "tool"]
    content: str


class InvokeInput(BaseModel):
    messages: list[Message] = Field(default_factory=list)


class Constraints(BaseModel):
    budget_usd: float = 2000.0
    days: int = 5
    destination: str = "Paris"
    travelers: int = 2
    travel_style: str = "mid"
    dates: list[str] = Field(default_factory=list)


class InvokeOptions(BaseModel):
    record_content: bool | None = None
    force_goto_path: bool = False


class InvokeRequest(BaseModel):
    request_id: str | None = None
    user_id: str | None = None
    conversation_id: str | None = None
    input: InvokeInput
    constraints: Constraints = Field(default_factory=Constraints)
    options: InvokeOptions = Field(default_factory=InvokeOptions)


class OutputDebug(BaseModel):
    route_taken: str
    cost_estimate_usd: float
    weather_summary: str
    flight_summary: str
    hotel_summary: str


class OutputPayload(BaseModel):
    messages: list[Message]
    plan: dict[str, Any]
    debug: OutputDebug


class TelemetryPayload(BaseModel):
    trace_id: str | None = None
    span_id: str | None = None


class InvokeResponse(BaseModel):
    request_id: str
    conversation_id: str
    output: OutputPayload
    telemetry: TelemetryPayload
