from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON, ParentBased, TraceIdRatioBased

LOGGER = logging.getLogger(__name__)


@dataclass
class TelemetryConfig:
    service_name: str
    resource_attributes: dict[str, str]
    sampler_name: str
    sampler_arg: str
    exporter_enabled: bool
    callback_enabled: bool
    default_record_content: bool


_INITIALIZED = False
_CONFIG: TelemetryConfig | None = None

SAMPLER_ALIASES = {
    "traceidratio": "trace_id_ratio",
    "parentbased_traceidratio": "parentbased_trace_id_ratio",
}


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resource_attributes() -> dict[str, str]:
    raw = os.getenv("OTEL_RESOURCE_ATTRIBUTES", "")
    attrs: dict[str, str] = {}
    if not raw:
        return attrs
    for token in raw.split(","):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        key = key.strip()
        if key:
            attrs[key] = value.strip()
    return attrs


def _sampler_from_env() -> tuple[Any, str, str]:
    sampler_name = os.getenv("OTEL_TRACES_SAMPLER", "parentbased_trace_id_ratio").lower()
    sampler_arg = os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0")
    sampler_name = SAMPLER_ALIASES.get(sampler_name, sampler_name)
    ratio = float(sampler_arg)
    if sampler_name == "always_on":
        return ALWAYS_ON, sampler_name, sampler_arg
    if sampler_name == "always_off":
        return ALWAYS_OFF, sampler_name, sampler_arg
    if sampler_name in {"traceidratio", "trace_id_ratio"}:
        return TraceIdRatioBased(ratio), sampler_name, sampler_arg
    return ParentBased(TraceIdRatioBased(ratio)), sampler_name, sampler_arg


def initialize_tracing() -> TelemetryConfig:
    global _INITIALIZED, _CONFIG
    if _INITIALIZED and _CONFIG is not None:
        return _CONFIG

    raw_sampler = os.getenv("OTEL_TRACES_SAMPLER", "")
    normalized_sampler = SAMPLER_ALIASES.get(raw_sampler.lower())
    if normalized_sampler:
        os.environ["OTEL_TRACES_SAMPLER"] = normalized_sampler

    service_name = os.getenv("OTEL_SERVICE_NAME", "langgraph-workflow-agent")
    attrs = _resource_attributes()
    attrs["service.name"] = service_name
    sampler, sampler_name, sampler_arg = _sampler_from_env()
    provider = TracerProvider(resource=Resource.create(attrs), sampler=sampler)

    connection_string = os.getenv("APPLICATION_INSIGHTS_CONNECTION_STRING")
    exporter_enabled = bool(connection_string)
    if connection_string:
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

        exporter = AzureMonitorTraceExporter(connection_string=connection_string)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        LOGGER.warning(
            "APPLICATION_INSIGHTS_CONNECTION_STRING is not set; telemetry exporter is disabled."
        )
    trace.set_tracer_provider(provider)

    # Instrument FastAPI/ASGI so inbound HTTP requests produce server spans
    # that carry the incoming traceparent as the root of the trace.
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument(tracer_provider=provider)
    except ImportError:
        LOGGER.warning("opentelemetry-instrumentation-fastapi not installed; HTTP spans disabled.")
    except Exception:
        LOGGER.debug("FastAPI instrumentor already active or failed.", exc_info=True)

    try:
        from langchain_azure_ai.callbacks.tracers.inference_tracing import (  # noqa: F401
            AzureAIOpenTelemetryTracer,
        )
        callback_enabled = True
    except ImportError:
        callback_enabled = False
    _CONFIG = TelemetryConfig(
        service_name=service_name,
        resource_attributes=attrs,
        sampler_name=sampler_name,
        sampler_arg=sampler_arg,
        exporter_enabled=exporter_enabled,
        callback_enabled=callback_enabled,
        default_record_content=_parse_bool(os.getenv("OTEL_RECORD_CONTENT"), default=False),
    )
    _INITIALIZED = True
    return _CONFIG


def create_langchain_callbacks(record_content: bool) -> list[Any]:
    try:
        from langchain_azure_ai.callbacks.tracers.inference_tracing import (
            AzureAIOpenTelemetryTracer,
        )
    except ImportError:
        LOGGER.warning("langchain_azure_ai not installed; tracing callbacks disabled.")
        return []

    # The tracer uses whatever global TracerProvider is set.  A connection
    # string is only needed when NO provider exists yet (the tracer would
    # call configure_azure_monitor to create one).  When our initialize_tracing()
    # has already registered a provider, the tracer piggybacks on it.
    connection_string = os.getenv("APPLICATION_INSIGHTS_CONNECTION_STRING")

    tracer = AzureAIOpenTelemetryTracer(
        connection_string=connection_string,
        enable_content_recording=record_content,
        provider_name="azure_openai",
        name=os.getenv("OTEL_SERVICE_NAME", "langgraph-workflow-agent"),
        trace_all_langgraph_nodes=True,
    )
    return [tracer]


def effective_telemetry_config() -> dict[str, Any]:
    config = initialize_tracing()
    return {
        "service_name": config.service_name,
        "resource_attributes": config.resource_attributes,
        "sampler_name": config.sampler_name,
        "sampler_arg": config.sampler_arg,
        "exporter_enabled": config.exporter_enabled,
        "callback_enabled": config.callback_enabled,
        "default_record_content": config.default_record_content,
    }
