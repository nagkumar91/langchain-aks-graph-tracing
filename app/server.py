from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status
from opentelemetry import trace
from opentelemetry.propagate import extract
from opentelemetry.trace import SpanKind, Status, StatusCode

from app.graph import build_graph
from app.model import build_chat_model, model_debug_config
from app.retriever import OfflineRetriever
from app.schemas import (
    InvokeRequest,
    InvokeResponse,
    Message,
    OutputDebug,
    OutputPayload,
    TelemetryPayload,
)
from app.telemetry import create_langchain_callbacks, effective_telemetry_config, initialize_tracing

LOGGER = logging.getLogger("agent_server")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


class AgentRuntime:
    def __init__(self, llm: Any | None = None, retriever: OfflineRetriever | None = None) -> None:
        self.startup_error: str | None = None
        self.telemetry_config = initialize_tracing()
        self.llm = None
        self.retriever = retriever or OfflineRetriever()
        self.graph = None
        try:
            self.llm = llm or build_chat_model()
            self.graph = build_graph(
                llm=self.llm,
                retriever=self.retriever,
                callbacks_factory=create_langchain_callbacks,
            )
        except Exception as exc:  # noqa: BLE001
            self.startup_error = str(exc)
            LOGGER.exception("Runtime initialization failed: %s", exc)

    @property
    def is_ready(self) -> bool:
        return self.graph is not None and self.startup_error is None


def _record_content(runtime: AgentRuntime, requested: bool | None) -> bool:
    if requested is None:
        return runtime.telemetry_config.default_record_content
    return requested


def create_app(llm: Any | None = None, retriever: OfflineRetriever | None = None) -> FastAPI:
    runtime = AgentRuntime(llm=llm, retriever=retriever)
    app = FastAPI(title="Zava Travel Agent", version="0.1.0")
    app.state.runtime = runtime
    tracer = trace.get_tracer(__name__)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(response: Response) -> dict[str, str]:
        if not runtime.is_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "not_ready", "reason": runtime.startup_error or "graph not initialized"}
        return {"status": "ready"}

    @app.get("/version")
    def version() -> dict[str, str]:
        return {
            "git_sha": os.getenv("BUILD_SHA", "dev"),
            "image_tag": os.getenv("IMAGE_TAG", "dev"),
            "build_id": os.getenv("BUILD_ID", "local"),
        }

    @app.get("/debug/telemetry")
    def debug_telemetry() -> dict[str, Any]:
        return {
            "telemetry": effective_telemetry_config(),
            "model": model_debug_config(),
            "runtime_ready": runtime.is_ready,
        }

    @app.post("/invoke", response_model=InvokeResponse)
    async def invoke(payload: InvokeRequest, request: Request) -> InvokeResponse:
        if not runtime.is_ready:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Service not ready: {runtime.startup_error or 'graph unavailable'}",
            )

        request_id = payload.request_id or request.headers.get("x-request-id") or str(uuid.uuid4())
        conversation_id = payload.conversation_id or str(uuid.uuid4())
        record_content = _record_content(runtime, payload.options.record_content)
        metadata = {
            "request_id": request_id,
            "user_id": payload.user_id,
            "conversation_id": conversation_id,
            "record_content": record_content,
            "force_goto_path": payload.options.force_goto_path,
        }
        initial_state = {
            "thread": {"messages": [message.model_dump() for message in payload.input.messages]},
            "constraints": payload.constraints.model_dump(),
            "metadata": metadata,
        }

        headers = {key.lower(): value for key, value in request.headers.items()}
        incoming_context = extract(headers)
        with tracer.start_as_current_span(
            "invoke_agent", context=incoming_context, kind=SpanKind.SERVER
        ) as span:
            span.set_attribute("gen_ai.operation.name", "invoke_agent")
            span.set_attribute("gen_ai.provider.name", "azure_openai")
            span.set_attribute("app.agent.name", "zava-travel-agent")
            span.set_attribute("biz.request_id", request_id)
            if payload.user_id:
                span.set_attribute("app.user_id", payload.user_id)
                span.set_attribute("enduser.id", payload.user_id)
            try:
                result = runtime.graph.invoke(initial_state)
            except Exception as exc:  # noqa: BLE001
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Workflow invocation failed: {exc}",
                ) from exc

            tool_outputs = result.get("tool_outputs", {})
            weather_summary = (
                tool_outputs.get("weather", {}).get("summary", "No weather data available.")
            )
            cost_estimate = tool_outputs.get("cost", {}).get("estimate_usd", 0.0)
            flights = tool_outputs.get("flights", {})
            hotels = tool_outputs.get("hotels", {})
            flight_summary = (
                f"{flights.get('airline', 'N/A')} {flights.get('travel_class', '')} "
                f"${flights.get('total_price_usd', 0)} for {flights.get('travelers', 0)} travelers"
            ) if flights else "No flight data available."
            hotel_summary = (
                f"{hotels.get('hotel_name', 'N/A')} ({hotels.get('tier', '')}) "
                f"${hotels.get('total_price_usd', 0)} for {hotels.get('nights', 0)} nights"
            ) if hotels else "No hotel data available."
            final_message = result.get("final_answer", "No response generated.")
            trace_ctx = span.get_span_context()
            return InvokeResponse(
                request_id=request_id,
                conversation_id=conversation_id,
                output=OutputPayload(
                    messages=[Message(role="assistant", content=final_message)],
                    plan=result.get("draft_plan", {}),
                    debug=OutputDebug(
                        route_taken=str(result.get("route", "normal")),
                        cost_estimate_usd=float(cost_estimate),
                        weather_summary=str(weather_summary),
                        flight_summary=flight_summary,
                        hotel_summary=hotel_summary,
                    ),
                ),
                telemetry=TelemetryPayload(
                    trace_id=f"{trace_ctx.trace_id:032x}" if trace_ctx else None,
                    span_id=f"{trace_ctx.span_id:016x}" if trace_ctx else None,
                ),
            )

    return app


app = create_app()
