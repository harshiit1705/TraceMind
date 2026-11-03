from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.evidence import EvidenceListResponse
from app.services.incident_service import IncidentService

router = APIRouter(prefix="/incidents", tags=["Evidence"])


@router.get(
    "/{incident_id}/evidence",
    response_model=EvidenceListResponse,
    summary="Get correlated telemetry evidence for an incident",
)
def get_incident_evidence(
    incident_id: str,
    db: Session = Depends(get_db),
) -> EvidenceListResponse:
    """Retrieve correlated multi-modal telemetry evidence (metrics, logs, traces, topology) for an incident."""
    service = IncidentService(db)
    evidence_bundle = service.get_evidence(incident_id)
    if not evidence_bundle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' was not found.",
        )
    return evidence_bundle

