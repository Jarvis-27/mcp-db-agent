"""Pytest fixtures shared across the test suite."""

import pytest


@pytest.fixture
def memory_span_exporter():
    """Install an in-memory OTel exporter for the duration of one test.

    The OTel API's ``set_tracer_provider`` is once-per-process, so we patch the
    private ``_TRACER_PROVIDER`` directly to allow re-entry between tests. The
    previously installed provider is restored on teardown, along with any
    module-level ``_tracer`` references that were cached against the proxy.
    """
    import opentelemetry.trace as otrace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    old_provider = otrace._TRACER_PROVIDER  # type: ignore[attr-defined]
    otrace._TRACER_PROVIDER = provider  # type: ignore[attr-defined]

    # Modules cache ``_tracer = get_tracer(__name__)`` at import time. Replace
    # those cached references with tracers backed by the new provider so spans
    # land in our exporter; restore on teardown.
    import src.core.schema_inspector as si
    import src.core.self_corrector as sc
    import src.core.sql_executor as se
    import src.core.sql_generator as sg
    import src.server as server

    saved = (si._tracer, sc._tracer, se._tracer, sg._tracer, server._tracer)
    si._tracer = provider.get_tracer("src.core.schema_inspector")
    sc._tracer = provider.get_tracer("src.core.self_corrector")
    se._tracer = provider.get_tracer("src.core.sql_executor")
    sg._tracer = provider.get_tracer("src.core.sql_generator")
    server._tracer = provider.get_tracer("src.server")

    try:
        yield exporter
    finally:
        si._tracer, sc._tracer, se._tracer, sg._tracer, server._tracer = saved
        otrace._TRACER_PROVIDER = old_provider  # type: ignore[attr-defined]
