from fastapi import APIRouter
from app.api.v1.health import router as health_router
from app.api.v1.projects import router as projects_router
from app.api.v1.services import router as services_router
from app.api.v1.incidents import router as incidents_router
from app.api.v1.evidence import router as evidence_router
from app.api.v1.investigations import router as investigations_router
from app.api.v1.anomalies import router as anomalies_router
from app.api.v1.dependencies import router as dependencies_router
from app.api.v1.correlations import router as correlations_router
from app.api.v1.telemetry import router as telemetry_router
from app.api.v1.logs import router as logs_router
from app.api.v1.traces import router as traces_router
from app.api.v1.remediations import router as remediations_router
from app.api.v1.verifications import router as verifications_router

api_v1_router = APIRouter()

api_v1_router.include_router(health_router)
api_v1_router.include_router(projects_router)
api_v1_router.include_router(services_router)
api_v1_router.include_router(dependencies_router)
api_v1_router.include_router(incidents_router)
api_v1_router.include_router(evidence_router)
api_v1_router.include_router(investigations_router)
api_v1_router.include_router(anomalies_router)
api_v1_router.include_router(correlations_router)
api_v1_router.include_router(telemetry_router)
api_v1_router.include_router(logs_router)
api_v1_router.include_router(traces_router)
api_v1_router.include_router(remediations_router)
api_v1_router.include_router(verifications_router)

