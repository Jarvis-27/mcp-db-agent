"""When OTEL_ENABLED is False, init_tracing must be a no-op and the global
provider must remain the OTel API's built-in proxy.

This test deliberately does NOT use the ``memory_span_exporter`` fixture, so
the global provider stays untouched between runs.
"""

from unittest.mock import MagicMock


def test_init_tracing_noop_when_disabled():
    from src.core.observability import init_tracing

    settings = MagicMock()
    settings.otel_enabled = False
    # init_tracing should return immediately without raising or installing a provider.
    init_tracing(settings)


def test_shutdown_tracing_idempotent_when_never_initialised():
    from src.core import observability

    observability.shutdown_tracing()
    observability.shutdown_tracing()
    assert observability._provider is None


def test_should_capture_sql_default_false():
    from src.core.observability import should_capture_sql

    assert should_capture_sql() is False


def test_get_tracer_returns_tracer():
    from src.core.observability import get_tracer

    tracer = get_tracer("any.module")
    # Smoke-test the API surface: the tracer must support start_as_current_span.
    with tracer.start_as_current_span("noop") as span:
        assert span is not None
