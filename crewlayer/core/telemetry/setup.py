"""OpenTelemetry bootstrap.

Call setup_telemetry(app) once at process startup. When OTEL_ENABLED=false
the function returns None immediately and all manually-created spans are no-ops
via the default ProxyTracerProvider — zero overhead.
"""
from __future__ import annotations

from typing import Any

from crewlayer.core.config import settings


def setup_telemetry(app: Any = None) -> Any:
    """Configure TracerProvider with OTLP gRPC exporter and auto-instrument the stack.

    Returns the TracerProvider, or None when OTEL_ENABLED=false.
    """
    if not settings.OTEL_ENABLED:
        return None

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource({SERVICE_NAME: settings.OTEL_SERVICE_NAME})
    provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(
        endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        insecure=True,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    SQLAlchemyInstrumentor().instrument()
    RedisInstrumentor().instrument()

    if app is not None:
        FastAPIInstrumentor.instrument_app(app)

    return provider
