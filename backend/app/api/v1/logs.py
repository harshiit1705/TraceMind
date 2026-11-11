"""FastAPI route handler for querying structured application logs."""

from datetime import datetime
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import PaginatedResponse
from app.schemas.telemetry import ApplicationLogResponse
from app.services.telemetry.logs_service import LogsService

router = APIRouter(prefix="/logs", tags=["Logs"])


@router.get(
    "",
    response_model=PaginatedResponse[ApplicationLogResponse],
    summary="Query persisted structured application logs with filtering and pagination",
)
def list_logs(
    project_id: Optional[UUID] = Query(None, description="Filter by Project UUID"),
    service: Optional[str] = Query(None, description="Filter by service slug, identifier, name, or UUID"),
    level: Optional[str] = Query(None, description="Filter by severity level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"),
    request_id: Optional[str] = Query(None, description="Filter by request ID"),
    trace_id: Optional[str] = Query(None, description="Filter by distributed trace ID"),
    search: Optional[str] = Query(None, description="Case-insensitive text search across message/exception/IDs"),
    start_time: Optional[datetime] = Query(None, description="Start UTC timestamp"),
    end_time: Optional[datetime] = Query(None, description="End UTC timestamp"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ApplicationLogResponse]:
    svc = LogsService(db)
    items, total = svc.query_logs(
        project_id=project_id,
        service_identifier=service,
        level=level,
        request_id=request_id,
        trace_id=trace_id,
        search=search,
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

