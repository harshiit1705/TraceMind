"""FastAPI route handlers for telemetry anomaly evaluation."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.anomaly import (
    AnomalyEvaluationRequest,
    AnomalyEvaluationResponse,
)
from app.services.anomaly.detector import OutOfOrderMeasurementError
from app.services.anomaly.service import (
    AnomalyService,
    ServiceNotFoundError,
)

router = APIRouter(prefix="/anomalies", tags=["Anomalies"])


@router.post(
    "/evaluate",
    response_model=AnomalyEvaluationResponse,
    status_code=status.HTTP_200_OK,
    summary="Evaluate telemetry measurement for anomalies against service-scoped baseline",
)
def evaluate_anomaly(
    payload: AnomalyEvaluationRequest,
    db: Session = Depends(get_db),
) -> AnomalyEvaluationResponse:
    """Evaluate a single telemetry measurement against historical statistical baselines.

    - Resolves the service within the specified project boundary.
    - Guarantees complete baseline isolation per project, service, and metric.
    - Enforces warmup accumulation and prevents anomalous contamination.
    """
    service = AnomalyService(db)
    try:
        return service.evaluate_measurement(payload)
    except ServiceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except OutOfOrderMeasurementError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

