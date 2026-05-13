"""OpenTelemetry tracing setup (G16).

When ``OTEL_ENABLED=false`` (default), ``init_tracing`` is a no-op and
``get_tracer`` returns the OTel API's built-in ``NoOpTracer`` — manual
``start_as_current_span(...)`` blocks are then free no-ops, so call sites need
no ``if enabled:`` guards.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.sdk.resources import (
    DEPLOYMENT_ENVIRONMENT,
    SERVICE_NAME,
    SERVICE_VERSION,
    Resource,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

if TYPE_CHECKING:
    from opentelemetry.trace import Span, Tracer

    from src.config import Settings


_provider: TracerProvider | None = None


def init_tracing(settings: Settings) -> None:
    """Install the global TracerProvider when ``settings.otel_enabled`` is True.

    Idempotent — a second call replaces the previous provider so reload-style
    environments stay consistent.
    """
    global _provider

    if not settings.otel_enabled:
        return

    resource = Resource.create(
        {
            SERVICE_NAME: settings.otel_service_name,
            SERVICE_VERSION: "0.1.0",
            DEPLOYMENT_ENVIRONMENT: settings.environment,
        }
    )
    sampler = ParentBased(TraceIdRatioBased(settings.otel_sampler_ratio))
    provider = TracerProvider(resource=resource, sampler=sampler)

    exporter: SpanExporter
    if settings.otel_otlp_protocol == "http":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter as HTTPExporter,
        )

        exporter = HTTPExporter(endpoint=settings.otel_otlp_endpoint)
    else:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter as GRPCExporter,
        )

        exporter = GRPCExporter(
            endpoint=settings.otel_otlp_endpoint,
            insecure=settings.otel_otlp_insecure,
        )

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _provider = provider


def shutdown_tracing() -> None:
    """Flush the BatchSpanProcessor and shut down the provider. Idempotent."""
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None


def get_tracer(name: str = "mcp_db_agent") -> Tracer:
    return trace.get_tracer(name)


def add_request_id(span: Span) -> None:
    """Copy ``request_id_var`` (set by ``RequestIDMiddleware``) onto the span."""
    from src.middleware.request_id import request_id_var

    rid = request_id_var.get()
    if rid:
        span.set_attribute("request.id", rid)


def should_capture_sql() -> bool:
    """Return True when raw SQL may be recorded as a span attribute.

    Reads the ``settings`` singleton lazily to avoid a circular import.
    """
    from src.config import settings

    return settings.otel_capture_sql_text
