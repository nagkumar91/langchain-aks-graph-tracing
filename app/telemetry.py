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

    service_name = os.getenv("OTEL_SERVICE_NAME", "zava-travel-agent")
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

    callback_enabled = _load_tracer_class() is not None
    _CONFIG = TelemetryConfig(
        service_name=service_name,
        resource_attributes=attrs,
        sampler_name=sampler_name,
        sampler_arg=sampler_arg,
        exporter_enabled=exporter_enabled,
        callback_enabled=callback_enabled,
        default_record_content=_parse_bool(os.getenv("OTEL_RECORD_CONTENT"), default=True),
    )
    _INITIALIZED = True
    return _CONFIG


def _load_tracer_class() -> type | None:
    try:
        from langchain_azure_ai.callbacks.tracers.inference_tracing import (
            AzureAIOpenTelemetryTracer,
        )

        return AzureAIOpenTelemetryTracer
    except Exception:
        return None


def create_langchain_callbacks(record_content: bool) -> list[Any]:
    tracer_cls = _load_tracer_class()
    if tracer_cls is None:
        return []

    for kwargs in (
        {
            "enable_content_recording": record_content,
            "name": os.getenv("OTEL_SERVICE_NAME", "zava-travel-agent"),
        },
        {"record_content": record_content, "name": os.getenv("OTEL_SERVICE_NAME", "zava")},
        {"enable_content_recording": record_content},
        {"record_content": record_content},
        {},
    ):
        try:
            return [tracer_cls(**kwargs)]
        except TypeError:
            continue
    return []


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
