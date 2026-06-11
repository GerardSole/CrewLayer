from opentelemetry import trace as _trace


def get_tracer(name: str) -> _trace.Tracer:
    """Return a tracer bound to *name* from the current global TracerProvider."""
    return _trace.get_tracer(name)
