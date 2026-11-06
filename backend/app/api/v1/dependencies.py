"""FastAPI endpoints for service dependency topology and graph management."""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.project_repository import ProjectRepository
from app.repositories.service_dependency_repository import (
    DependencyCycleError,
    InvalidDependencyError,
    ServiceDependencyRepository,
)
from app.schemas.service_dependency import (
    ProjectDependencyGraph,
    ServiceDependencyCreate,
    ServiceDependencyResponse,
)

router = APIRouter(prefix="/dependencies", tags=["Service Dependencies"])


@router.get(
    "",
    response_model=List[ServiceDependencyResponse],
    summary="List directed service dependencies for a project",
)
def list_dependencies(
    project_id: UUID = Query(..., description="Project UUID to list dependencies for"),
    db: Session = Depends(get_db),
) -> List[ServiceDependencyResponse]:
    """Retrieve all directed dependency edges defined within the specified project."""
    proj_repo = ProjectRepository(db)
    if not proj_repo.get_by_id(project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' was not found.",
        )

    dep_repo = ServiceDependencyRepository(db)
    deps = dep_repo.list_by_project(project_id)
    return [ServiceDependencyResponse.model_validate(d) for d in deps]


@router.get(
    "/graph",
    response_model=ProjectDependencyGraph,
    summary="Retrieve complete project DAG dependency topology",
)
def get_dependency_graph(
    project_id: UUID = Query(..., description="Project UUID"),
    db: Session = Depends(get_db),
) -> ProjectDependencyGraph:
    """Retrieve complete directed acyclic graph (DAG) including nodes, edges, and forward/reverse adjacency maps."""
    proj_repo = ProjectRepository(db)
    if not proj_repo.get_by_id(project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' was not found.",
        )

    dep_repo = ServiceDependencyRepository(db)
    return dep_repo.get_graph(project_id)


@router.post(
    "",
    response_model=ServiceDependencyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a directed dependency edge between two services in a project",
)
def create_dependency(
    payload: ServiceDependencyCreate,
    project_id: UUID = Query(..., description="Project UUID"),
    db: Session = Depends(get_db),
) -> ServiceDependencyResponse:
    """Register a directed dependency: source_service_id calls target_service_id.
    
    Guarantees:
    - Verifies both services exist within the project boundary.
    - Prevents self-dependencies.
    - Enforces DAG constraint by detecting and rejecting cycles before insertion.
    - Idempotently returns existing edge if duplicate submitted.
    """
    dep_repo = ServiceDependencyRepository(db)
    try:
        dep = dep_repo.create(
            project_id=project_id,
            source_service_id=payload.source_service_id,
            target_service_id=payload.target_service_id,
            dependency_type=payload.dependency_type.value,
            description=payload.description,
        )
        return ServiceDependencyResponse.model_validate(dep)
    except InvalidDependencyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except DependencyCycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )


@router.delete(
    "/{dependency_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a service dependency edge",
)
def delete_dependency(
    dependency_id: UUID,
    db: Session = Depends(get_db),
) -> None:
    """Delete a service dependency edge by ID."""
    dep_repo = ServiceDependencyRepository(db)
    dep = dep_repo.get_by_id(dependency_id)
    if not dep:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service dependency '{dependency_id}' was not found.",
        )
    dep_repo.delete(dep)

