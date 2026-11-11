"""FastAPI route handlers for metrics, structured logs, and trace span ingestion and overview."""

from datetime import datetime
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import PaginatedResponse
from app.schemas.telemetry import (
    LogBatchIngestRequest,
    LogBatchIngestResponse,
    MetricBatchIngestRequest,
    MetricBatchIngestResponse,
    MetricSampleResponse,
    SpanBatchIngestRequest,
    SpanBatchIngestResponse,
    TelemetryOverviewResponse,
)
from app.services.anomaly.service import ServiceNotFoundError
from app.services.telemetry.logs_service import LogsService
from app.services.telemetry.metrics_service import (
    MetricsService,
    TelemetryProjectNotFoundError,
)
from app.services.telemetry.traces_service import TracesService

router = APIRouter(prefix="/telemetry", tags=["Telemetry"])


@router.post(
    "/metrics",
    response_model=MetricBatchIngestResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest batch of application metric samples and evaluate anomalies",
)
def ingest_metrics(
    payload: MetricBatchIngestRequest,
    db: Session = Depends(get_db),
) -> MetricBatchIngestResponse:
    """Persist raw application metrics and forward eligible metrics to AnomalyService."""
    service = MetricsService(db)
    try:
        return service.ingest_batch(payload)
    except TelemetryProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ServiceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get(
    "/metrics",
    response_model=PaginatedResponse[MetricSampleResponse],
    summary="Query persisted application metric samples",
)
def list_metrics(
    project_id: Optional[UUID] = Query(None, description="Filter by Project UUID"),
    service: Optional[str] = Query(None, description="Filter by service slug, identifier, or UUID"),
    metric_name: Optional[str] = Query(None, description="Filter by metric name"),
    endpoint: Optional[str] = Query(None, description="Filter by HTTP endpoint or operation"),
    trace_id: Optional[str] = Query(None, description="Filter by trace_id"),
    start_time: Optional[datetime] = Query(None, description="Start UTC timestamp"),
    end_time: Optional[datetime] = Query(None, description="End UTC timestamp"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MetricSampleResponse]:
    svc = MetricsService(db)
    items, total = svc.query_metrics(
        project_id=project_id,
        service_identifier=service,
        metric_name=metric_name,
        endpoint=endpoint,
        trace_id=trace_id,
        start_time=start_time,
        end_time=end_time,
        skip=offset,
        limit=limit,
    )
    page = (offset // limit) + 1
    total_pages = max(1, (total + limit - 1) // limit)
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=limit,
        total_pages=total_pages,
    )


@router.get(
    "/overview",
    response_model=TelemetryOverviewResponse,
    summary="Get time-bucketed telemetry overview computed from persisted metrics",
)
def get_telemetry_overview(
    range_str: str = Query("15m", alias="range", description="Time range: 15m, 1h, or 24h"),
    project_id: Optional[UUID] = Query(None, description="Optional Project UUID"),
    db: Session = Depends(get_db),
) -> TelemetryOverviewResponse:
    svc = MetricsService(db)
    return svc.get_telemetry_overview(time_range=range_str, project_id=project_id)


@router.post(
    "/logs",
    response_model=LogBatchIngestResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest batch of structured application logs with secret redaction",
)
def ingest_logs(
    payload: LogBatchIngestRequest,
    db: Session = Depends(get_db),
) -> LogBatchIngestResponse:
    svc = LogsService(db)
    try:
        return svc.ingest_batch(payload)
    except TelemetryProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ServiceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.post(
    "/spans",
    response_model=SpanBatchIngestResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest batch of distributed trace spans",
)
def ingest_spans(
    payload: SpanBatchIngestRequest,
    db: Session = Depends(get_db),
) -> SpanBatchIngestResponse:
    svc = TracesService(db)
    try:
        return svc.ingest_batch(payload)
    except TelemetryProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ServiceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

