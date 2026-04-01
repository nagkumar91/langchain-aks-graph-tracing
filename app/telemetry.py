from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger(__name__)


@dataclass
class TelemetryConfig:
    service_name: str
    resource_attributes: dict[str, str]
    sampler_name: str
    sampler_arg: str
    exporter_enabled: bool
    callback_enabled: bool
    auto_instrumented: bool
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


def initialize_tracing() -> TelemetryConfig:
    """Set up Azure Monitor export and enable auto-instrumentation.

    When ``enable_auto_tracing()`` is available (PR #381), the tracer is
    auto-injected into every ``BaseCallbackManager`` — no manual callbacks
    needed.  Falls back to manual callback creation if auto-instrumentation
    is unavailable.
    """
    global _INITIALIZED, _CONFIG
    if _INITIALIZED and _CONFIG is not None:
        return _CONFIG

    raw_sampler = os.getenv("OTEL_TRACES_SAMPLER", "")
    normalized_sampler = SAMPLER_ALIASES.get(raw_sampler.lower())
    if normalized_sampler:
        os.environ["OTEL_TRACES_SAMPLER"] = normalized_sampler

    service_name = os.getenv("OTEL_SERVICE_NAME", "zava-travel-agent")
    sampler_name = os.getenv("OTEL_TRACES_SAMPLER", "parentbased_trace_id_ratio")
    sampler_arg = os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0")
    attrs = _resource_attributes()
    attrs["service.name"] = service_name

    connection_string = os.getenv("APPLICATION_INSIGHTS_CONNECTION_STRING")
    exporter_enabled = bool(connection_string)

    # configure_azure_monitor MUST be called before enable_auto_tracing so
    # the TracerProvider / exporter pipeline is already wired up.
    if connection_string:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=connection_string,
            enable_live_metrics=True,
        )
        LOGGER.info("configure_azure_monitor() completed — FastAPI, HTTP, and trace export active.")
    else:
        LOGGER.warning(
            "APPLICATION_INSIGHTS_CONNECTION_STRING is not set; telemetry exporter is disabled."
        )

    # Try auto-instrumentation first (PR #381 / future release).
    auto_instrumented = False
    callback_enabled = False
    try:
        from langchain_azure_ai.callbacks.tracers import enable_auto_tracing

        enable_auto_tracing(
            enable_content_recording=_parse_bool(
                os.getenv("OTEL_RECORD_CONTENT"), default=True
            ),
            provider_name="azure_openai",
            agent_id="zava-travel-agent",
            trace_all_langgraph_nodes=True,
            message_keys=["messages"],
            auto_configure_azure_monitor=False,
        )
        auto_instrumented = True
        callback_enabled = True
        LOGGER.info("enable_auto_tracing() active — callbacks injected automatically.")
    except ImportError:
        LOGGER.info(
            "enable_auto_tracing() not available; falling back to manual callbacks."
        )
        try:
            from langchain_azure_ai.callbacks.tracers.inference_tracing import (  # noqa: F401
                AzureAIOpenTelemetryTracer,
            )
            callback_enabled = True
        except ImportError:
            pass

    _CONFIG = TelemetryConfig(
        service_name=service_name,
        resource_attributes=attrs,
        sampler_name=sampler_name,
        sampler_arg=sampler_arg,
        exporter_enabled=exporter_enabled,
        callback_enabled=callback_enabled,
        auto_instrumented=auto_instrumented,
        default_record_content=_parse_bool(os.getenv("OTEL_RECORD_CONTENT"), default=True),
    )
    _INITIALIZED = True
    return _CONFIG


def create_langchain_callbacks(record_content: bool) -> list[Any]:
    """Return manual callbacks only when auto-instrumentation is not active."""
    config = initialize_tracing()
    if config.auto_instrumented:
        return []

    try:
        from langchain_azure_ai.callbacks.tracers.inference_tracing import (
            AzureAIOpenTelemetryTracer,
        )
    except ImportError:
        LOGGER.warning("langchain_azure_ai not installed; tracing callbacks disabled.")
        return []

    connection_string = os.getenv("APPLICATION_INSIGHTS_CONNECTION_STRING")

    tracer = AzureAIOpenTelemetryTracer(
        connection_string=connection_string,
        enable_content_recording=record_content,
        provider_name="azure_openai",
        name=os.getenv("OTEL_SERVICE_NAME", "zava-travel-agent"),
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
        "auto_instrumented": config.auto_instrumented,
        "default_record_content": config.default_record_content,
    }
