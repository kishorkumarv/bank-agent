"""OpenTelemetry SDK bootstrap.

Configures tracing (and optionally metrics) for two modes:

* **Local** (default): ``ConsoleSpanExporter`` — traces go to stdout.
* **Cloud Run** (``TRACE_TO_CLOUD=true``): ``CloudTraceSpanExporter`` +
  ``CloudMonitoringMetricsExporter`` — traces go to Cloud Trace, custom
  metrics (token counts, cost) go to Cloud Monitoring.
"""

from __future__ import annotations

import logging

from .config import TRACE_TO_CLOUD

logger = logging.getLogger("bank_agent.observability.otel")

_INITIALISED = False


def init_otel() -> None:
    """Idempotent OTEL SDK initialisation.

    Call once at import time via :func:`setup_observability`.
    """
    global _INITIALISED
    if _INITIALISED:
        return
    _INITIALISED = True

    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
    except ImportError:
        logger.warning("opentelemetry-sdk not installed — OTEL tracing disabled")
        return

    resource = Resource.create({"service.name": "bank-agent"})
    provider = TracerProvider(resource=resource)

    if TRACE_TO_CLOUD:
        # ---------- Cloud exporters ----------
        try:
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

            cloud_exporter = CloudTraceSpanExporter()
            provider.add_span_processor(BatchSpanProcessor(cloud_exporter))
            logger.info("OTEL: Cloud Trace exporter registered")
        except Exception:
            logger.exception("Failed to initialise Cloud Trace exporter")

        try:
            from opentelemetry.exporter.cloud_monitoring import (
                CloudMonitoringMetricsExporter,
            )
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

            metric_reader = PeriodicExportingMetricReader(
                CloudMonitoringMetricsExporter(), export_interval_millis=60_000
            )
            meter_provider = MeterProvider(
                resource=resource, metric_readers=[metric_reader]
            )
            from opentelemetry import metrics as otel_metrics

            otel_metrics.set_meter_provider(meter_provider)
            logger.info("OTEL: Cloud Monitoring metrics exporter registered")
        except Exception:
            logger.exception("Failed to initialise Cloud Monitoring exporter")
    else:
        # ---------- Local / stdout ----------
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        logger.info("OTEL: Console exporter registered (local mode)")

    otel_trace.set_tracer_provider(provider)
