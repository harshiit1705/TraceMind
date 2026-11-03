from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.common import ServiceHealthStatus
from app.schemas.service import ServiceResponse
from app.services.project_service import ProjectService

router = APIRouter(prefix="/services", tags=["Services"])


@router.get("", response_model=List[ServiceResponse], summary="List all services with optional filters")
def list_services(
    project_id: Optional[UUID] = Query(None, description="Filter by Project UUID"),
    status: Optional[ServiceHealthStatus] = Query(None, description="Filter by health status"),
    tier: Optional[int] = Query(None, description="Filter by tier (0, 1, 2)"),
    db: Session = Depends(get_db),
) -> List[ServiceResponse]:
    """Retrieve microservice registry records with optional status, tier, and project filters."""
    service = ProjectService(db)
    return service.list_services(
        project_id=project_id,
        status=status.value if status else None,
        tier=tier,
    )

