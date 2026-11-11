"""FastAPI route handlers for querying distributed traces and span waterfalls."""

from datetime import datetime
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.telemetry import TraceListResponse, TraceSummaryResponse
from app.services.telemetry.traces_service import TracesService

router = APIRouter(prefix="/traces", tags=["Traces"])


@router.get(
    "",
    response_model=TraceListResponse,
    summary="List distributed traces with service, status, duration, and time filtering",
)
def list_traces(
    project_id: Optional[UUID] = Query(None, description="Filter by Project UUID"),
    service: Optional[str] = Query(None, description="Filter by participating service slug, name, identifier, or UUID"),
    trace_status: Optional[str] = Query(None, alias="status", description="Filter by span status (ok or error)"),
    min_duration_ms: Optional[float] = Query(None, ge=0.0, description="Minimum span duration threshold in ms"),
    trace_id: Optional[str] = Query(None, description="Prefix or exact trace_id filter"),
    start_time: Optional[datetime] = Query(None, description="Start UTC timestamp"),
    end_time: Optional[datetime] = Query(None, description="End UTC timestamp"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> TraceListResponse:
    svc = TracesService(db)
    return svc.list_traces(
        project_id=project_id,
        service_identifier=service,
        status=trace_status,
        min_duration_ms=min_duration_ms,
        trace_id_prefix=trace_id,
        start_time=start_time,
        end_time=end_time,
        skip=offset,
        limit=limit,
    )


@router.get(
    "/{trace_id}",
    response_model=TraceSummaryResponse,
    summary="Retrieve full trace and parent-child span waterfall by trace_id",
)
def get_trace_detail(
    trace_id: str,
    project_id: Optional[UUID] = Query(None, description="Optional Project UUID filter"),
    db: Session = Depends(get_db),
) -> TraceSummaryResponse:
    svc = TracesService(db)
    trace = svc.get_trace_detail(trace_id=trace_id, project_id=project_id)
    if not trace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace '{trace_id}' was not found.",
        )
    return trace

