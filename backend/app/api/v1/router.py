from fastapi import APIRouter
from app.api.v1.health import router as health_router
from app.api.v1.projects import router as projects_router
from app.api.v1.services import router as services_router
from app.api.v1.incidents import router as incidents_router
from app.api.v1.evidence import router as evidence_router
from app.api.v1.investigations import router as investigations_router

api_v1_router = APIRouter()

api_v1_router.include_router(health_router)
api_v1_router.include_router(projects_router)
api_v1_router.include_router(services_router)
api_v1_router.include_router(incidents_router)
api_v1_router.include_router(evidence_router)
api_v1_router.include_router(investigations_router)

