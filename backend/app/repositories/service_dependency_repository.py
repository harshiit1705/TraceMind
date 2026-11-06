"""Repository for managing directed service dependencies and DAG topology."""

from collections import deque
from typing import Dict, List, Optional, Set
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.service import Service
from app.models.service_dependency import ServiceDependency
from app.schemas.service_dependency import (
    ProjectDependencyGraph,
    ServiceDependencyEdge,
    ServiceDependencyNode,
)


class DependencyCycleError(ValueError):
    """Raised when adding a dependency edge would introduce a directed cycle into the topology."""
    pass


class InvalidDependencyError(ValueError):
    """Raised when dependency endpoints violate domain rules (self-dependency, missing service, cross-project)."""
    pass


class ServiceDependencyRepository:
    """Handles persistence and graph traversal for project-scoped service dependencies."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, dependency_id: UUID) -> Optional[ServiceDependency]:
        return self.db.query(ServiceDependency).filter(ServiceDependency.id == dependency_id).first()

    def get_by_endpoints(
        self,
        project_id: UUID,
        source_service_id: UUID,
        target_service_id: UUID,
    ) -> Optional[ServiceDependency]:
        return (
            self.db.query(ServiceDependency)
            .filter(
                ServiceDependency.project_id == project_id,
                ServiceDependency.source_service_id == source_service_id,
                ServiceDependency.target_service_id == target_service_id,
            )
            .first()
        )

    def list_by_project(self, project_id: UUID) -> List[ServiceDependency]:
        return (
            self.db.query(ServiceDependency)
            .filter(ServiceDependency.project_id == project_id)
            .order_by(ServiceDependency.created_at.asc())
            .all()
        )

    def list_upstream_dependencies(
        self,
        project_id: UUID,
        service_id: UUID,
    ) -> List[ServiceDependency]:
        """Callees that service_id calls (upstream dependencies)."""
        return (
            self.db.query(ServiceDependency)
            .filter(
                ServiceDependency.project_id == project_id,
                ServiceDependency.source_service_id == service_id,
            )
            .all()
        )

    def list_downstream_dependents(
        self,
        project_id: UUID,
        service_id: UUID,
    ) -> List[ServiceDependency]:
        """Callers that depend on service_id (downstream callers)."""
        return (
            self.db.query(ServiceDependency)
            .filter(
                ServiceDependency.project_id == project_id,
                ServiceDependency.target_service_id == service_id,
            )
            .all()
        )

    def has_path(
        self,
        project_id: UUID,
        start_service_id: UUID,
        target_service_id: UUID,
    ) -> bool:
        """Determines whether a directed path exists from start_service_id to target_service_id."""
        if start_service_id == target_service_id:
            return True

        # Load edges for this project
        edges = self.list_by_project(project_id)
        adj: Dict[UUID, List[UUID]] = {}
        for edge in edges:
            adj.setdefault(edge.source_service_id, []).append(edge.target_service_id)

        # BFS traversal
        visited: Set[UUID] = set([start_service_id])
        queue: deque[UUID] = deque([start_service_id])

        while queue:
            curr = queue.popleft()
            for neighbor in adj.get(curr, []):
                if neighbor == target_service_id:
                    return True
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        return False

    def shortest_path_distance(
        self,
        project_id: UUID,
        start_service_id: UUID,
        target_service_id: UUID,
    ) -> Optional[int]:
        """Compute the hop distance from start_service_id to target_service_id in directed graph."""
        if start_service_id == target_service_id:
            return 0

        edges = self.list_by_project(project_id)
        adj: Dict[UUID, List[UUID]] = {}
        for edge in edges:
            adj.setdefault(edge.source_service_id, []).append(edge.target_service_id)

        visited: Set[UUID] = set([start_service_id])
        queue: deque[tuple[UUID, int]] = deque([(start_service_id, 0)])

        while queue:
            curr, dist = queue.popleft()
            for neighbor in adj.get(curr, []):
                if neighbor == target_service_id:
                    return dist + 1
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, dist + 1))

        return None

    def create(
        self,
        project_id: UUID,
        source_service_id: UUID,
        target_service_id: UUID,
        dependency_type: str = "sync",
        description: Optional[str] = None,
    ) -> ServiceDependency:
        """Create and persist a validated directed dependency edge.
        
        Validations:
        - Prevents self-dependency (source == target).
        - Validates that both services exist in the specified project.
        - Prevents duplicate edges.
        - Prevents dependency cycles (DAG validation).
        """
        # 1. Self-dependency check
        if source_service_id == target_service_id:
            raise InvalidDependencyError(
                f"Self-dependencies are forbidden: service '{source_service_id}' cannot depend on itself."
            )

        # 2. Service existence and project boundary check
        source_svc = (
            self.db.query(Service)
            .filter(Service.id == source_service_id, Service.project_id == project_id)
            .first()
        )
        if not source_svc:
            raise InvalidDependencyError(
                f"Source service '{source_service_id}' does not exist in project '{project_id}'."
            )

        target_svc = (
            self.db.query(Service)
            .filter(Service.id == target_service_id, Service.project_id == project_id)
            .first()
        )
        if not target_svc:
            raise InvalidDependencyError(
                f"Target service '{target_service_id}' does not exist in project '{project_id}'."
            )

        # 3. Duplicate edge check
        existing = self.get_by_endpoints(project_id, source_service_id, target_service_id)
        if existing:
            return existing

        # 4. DAG Cycle Detection:
        # Adding (source -> target) creates a cycle if there is already a path from target to source
        if self.has_path(project_id, start_service_id=target_service_id, target_service_id=source_service_id):
            raise DependencyCycleError(
                f"Adding dependency from '{source_svc.name}' to '{target_svc.name}' "
                f"would create a cyclic dependency graph."
            )

        # 5. Persist edge
        dep = ServiceDependency(
            project_id=project_id,
            source_service_id=source_service_id,
            target_service_id=target_service_id,
            dependency_type=dependency_type,
            description=description,
        )
        self.db.add(dep)
        self.db.commit()
        self.db.refresh(dep)
        return dep

    def delete(self, dependency: ServiceDependency) -> None:
        self.db.delete(dependency)
        self.db.commit()

    def get_graph(self, project_id: UUID) -> ProjectDependencyGraph:
        """Construct the complete ProjectDependencyGraph for the project."""
        services = (
            self.db.query(Service)
            .filter(Service.project_id == project_id)
            .order_by(Service.name.asc())
            .all()
        )
        edges = self.list_by_project(project_id)

        nodes: List[ServiceDependencyNode] = [
            ServiceDependencyNode(
                id=s.id,
                slug=s.slug,
                name=s.name,
                identifier=s.identifier,
                tier=s.tier,
                status=s.status,
            )
            for s in services
        ]

        edge_list: List[ServiceDependencyEdge] = [
            ServiceDependencyEdge(
                id=e.id,
                source_service_id=e.source_service_id,
                target_service_id=e.target_service_id,
                dependency_type=e.dependency_type,
                description=e.description,
            )
            for e in edges
        ]

        adjacency: Dict[str, List[str]] = {str(s.id): [] for s in services}
        reverse_adjacency: Dict[str, List[str]] = {str(s.id): [] for s in services}

        for e in edges:
            src_str = str(e.source_service_id)
            tgt_str = str(e.target_service_id)
            adjacency.setdefault(src_str, []).append(tgt_str)
            reverse_adjacency.setdefault(tgt_str, []).append(src_str)

        return ProjectDependencyGraph(
            project_id=project_id,
            nodes=nodes,
            edges=edge_list,
            adjacency=adjacency,
            reverse_adjacency=reverse_adjacency,
        )

