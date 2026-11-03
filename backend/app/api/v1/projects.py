from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.project import ProjectResponse
from app.schemas.service import ServiceResponse
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("", response_model=List[ProjectResponse], summary="List all projects")
def list_projects(db: Session = Depends(get_db)) -> List[ProjectResponse]:
    """Retrieve all projects for the active tenant."""
    service = ProjectService(db)
    return service.list_projects()


@router.get(
    "/{project_id}/services",
    response_model=List[ServiceResponse],
    summary="List services by project",
)
def list_project_services(
    project_id: UUID, db: Session = Depends(get_db)
) -> List[ServiceResponse]:
    """Retrieve all microservices belonging to a specific project."""
    service = ProjectService(db)
    # verify project exists
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID '{project_id}' was not found.",
        )
    return service.list_services(project_id=project_id)

