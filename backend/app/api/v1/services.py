from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.service import Service
from app.models.telemetry import ApplicationLog, MetricSample, TraceSpan
from app.schemas.common import ServiceHealthStatus
from app.schemas.service import ServiceResponse
from app.services.project_service import ProjectService
from app.services.telemetry.metrics_service import MetricsService

router = APIRouter(prefix="/services", tags=["Services"])


@router.get("", response_model=List[ServiceResponse], summary="List all services with optional filters")
def list_services(
    project_id: Optional[UUID] = Query(None, description="Filter by Project UUID"),
    status_filter: Optional[ServiceHealthStatus] = Query(None, alias="status", description="Filter by health status"),
    tier: Optional[int] = Query(None, description="Filter by tier (0, 1, 2)"),
    db: Session = Depends(get_db),
) -> List[ServiceResponse]:
    """Retrieve microservice registry records with optional status, tier, and project filters."""
    service = ProjectService(db)
    return service.list_services(
        project_id=project_id,
        status=status_filter.value if status_filter else None,
        tier=tier,
    )


@router.get("/stats", summary="Aggregate service health and telemetry volume stats")
def get_services_stats(
    project_id: Optional[UUID] = Query(None, description="Optional Project UUID filter"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Compute service fleet health counts and telemetry volume strictly from persisted database records."""
    svc_q = db.query(Service)
    metric_q = db.query(MetricSample)
    log_q = db.query(ApplicationLog)
    span_q = db.query(TraceSpan)
    if project_id:
        svc_q = svc_q.filter(Service.project_id == project_id)
        metric_q = metric_q.filter(MetricSample.project_id == project_id)
        log_q = log_q.filter(ApplicationLog.project_id == project_id)
        span_q = span_q.filter(TraceSpan.project_id == project_id)

    services = svc_q.all()
    healthy = sum(1 for s in services if (s.status or "").lower() == "healthy")
    degraded = sum(1 for s in services if (s.status or "").lower() == "degraded")
    unhealthy = sum(1 for s in services if (s.status or "").lower() == "unhealthy")

    metric_count = metric_q.count()
    log_count = log_q.count()
    span_count = span_q.count()

    # Compute telemetry sample ingestion rate strictly from persisted MetricSample timestamps (15m window),
    # never from seeded placeholder Service.request_rate_rps values.
    now_utc = datetime.now(timezone.utc)
    recent_cutoff = now_utc - timedelta(minutes=15)
    recent_metrics_q = metric_q.filter(MetricSample.timestamp >= recent_cutoff)
    recent_metric_count = recent_metrics_q.count()
    min_ts, max_ts = recent_metrics_q.with_entities(
        func.min(MetricSample.timestamp),
        func.max(MetricSample.timestamp),
    ).one()

    sample_ingestion_rate: Optional[float] = None
    if recent_metric_count >= 2 and min_ts is not None and max_ts is not None:
        min_aware = min_ts if min_ts.tzinfo else min_ts.replace(tzinfo=timezone.utc)
        max_aware = max_ts if max_ts.tzinfo else max_ts.replace(tzinfo=timezone.utc)
        elapsed_sec = (max_aware - min_aware).total_seconds()
        if elapsed_sec >= 1.0:
            sample_ingestion_rate = round(recent_metric_count / elapsed_sec, 2)

    if metric_count == 0:
        ingestion_label = "0.0 samples/s (0 metrics)"
    elif sample_ingestion_rate is not None:
        ingestion_label = f"{sample_ingestion_rate:.1f} samples/s ({metric_count} metrics)"
    else:
        ingestion_label = f"Insufficient window ({metric_count} metrics)"

    resolved_project_id = project_id
    if resolved_project_id is None and services:
        resolved_project_id = services[0].project_id

    app_rps: Optional[float] = None
    total_requests = 0
    request_rate_status = "no_traffic"
    if resolved_project_id is not None:
        ov = MetricsService(db).get_telemetry_overview(time_range="15m", project_id=resolved_project_id)
        total_requests = ov.totalRequests
        request_rate_status = ov.requestRateStatus
        if ov.throughputAvailable and ov.currentThroughputRps is not None:
            app_rps = ov.currentThroughputRps

    return {
        "totalServices": len(services),
        "healthyCount": healthy,
        "degradedCount": degraded,
        "unhealthyCount": unhealthy,
        "ingestionBandwidth": ingestion_label,
        "sampleIngestionRatePerSec": sample_ingestion_rate,
        "totalMetricSamples": metric_count,
        "totalLogs": log_count,
        "totalSpans": span_count,
        "logPayloadDaily": f"{log_count} persisted logs · {span_count} spans",
        "applicationRequestRateRps": app_rps,
        "totalRequests": total_requests,
        "requestRateStatus": request_rate_status,
    }


@router.get("/{service_identifier}", response_model=ServiceResponse, summary="Get service by UUID, slug, or identifier")
def get_service_detail(
    service_identifier: str,
    db: Session = Depends(get_db),
) -> ServiceResponse:
    svc = None
    try:
        svc_uuid = UUID(service_identifier)
        svc = db.query(Service).filter(Service.id == svc_uuid).first()
    except ValueError:
        pass

    if not svc:
        svc = db.query(Service).filter(
            (Service.slug == service_identifier)
            | (Service.identifier == service_identifier)
            | (Service.name == service_identifier)
        ).first()

    if not svc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service '{service_identifier}' was not found.",
        )
    return ServiceResponse.model_validate(svc)

