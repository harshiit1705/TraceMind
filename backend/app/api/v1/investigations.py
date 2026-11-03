from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.investigation import InvestigationDetailResponse
from app.services.incident_service import IncidentService

router = APIRouter(prefix="/investigations", tags=["Investigations"])


@router.get(
    "/{investigation_id}",
    response_model=InvestigationDetailResponse,
    summary="Get root-cause investigation details, findings, and remediation recommendations",
)
def get_investigation(
    investigation_id: str,
    db: Session = Depends(get_db),
) -> InvestigationDetailResponse:
    """Retrieve full details of an automated incident investigation, including findings, evidence links, and recommendations."""
    service = IncidentService(db)
    try:
        inv_uuid = UUID(investigation_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' was not found.",
        )

    investigation = service.get_investigation(inv_uuid)
    if not investigation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Investigation '{investigation_id}' was not found.",
        )
    return investigation
