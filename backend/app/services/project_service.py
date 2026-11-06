from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.organization import Organization
from app.models.project import Project
from app.models.service import Service
from app.repositories.project_repository import ProjectRepository
from app.repositories.service_repository import ServiceRepository
from app.schemas.project import ProjectResponse
from app.schemas.service import ServiceResponse


class ProjectService:
    def __init__(self, db: Session):
        self.db = db
        self.project_repo = ProjectRepository(db)
        self.service_repo = ServiceRepository(db)

    def ensure_default_seed(self) -> Project:
        """Seeds default organization, project, and services if database is currently empty."""
        existing_project = self.project_repo.get_by_slug("core-ecommerce")
        if existing_project:
            svcs = self.service_repo.get_by_project(existing_project.id)
            service_map = {s.slug: s for s in svcs}
            self._seed_dependencies(existing_project.id, service_map)
            return existing_project

        # 1. Organization
        org = Organization(
            slug="acme-cloud",
            name="Acme Cloud Infrastructure",
            tier="enterprise",
            settings_json={"retention_days": 30, "spikeguard": True}
        )
        self.db.add(org)
        self.db.commit()
        self.db.refresh(org)

        # 2. Project
        proj = Project(
            organization_id=org.id,
            slug="core-ecommerce",
            name="Core E-Commerce & Payments",
            environment="production",
            description="Mission-critical distributed payment settlement and checkout processing fleet."
        )
        self.db.add(proj)
        self.db.commit()
        self.db.refresh(proj)

        # 3. 10 Microservices matching frontend mock contract
        services_data = [
            {
                "name": "API Gateway",
                "slug": "api-gateway",
                "identifier": "svc:ingress-proxy-v2",
                "tier": 0,
                "owner_team": "Edge Infrastructure",
                "status": "degraded",
                "request_rate_rps": 42800.0,
                "error_rate_percent": 2.84,
                "p95_latency_ms": 180.0,
                "metadata_json": {
                    "last_deployment": "v2.14.2 (2 hours ago by @sarah)",
                    "availability_percent": 99.12,
                    "cpu_saturation_percent": 68,
                    "memory_usage_percent": 62,
                    "upstream_dependencies": ["Cloudflare CDN", "Route53 DNS"],
                    "downstream_dependencies": ["Order Service", "User Service", "Auth Service"]
                }
            },
            {
                "name": "Order Service",
                "slug": "order-service",
                "identifier": "svc:order-orchestration",
                "tier": 0,
                "owner_team": "Checkout Core",
                "status": "degraded",
                "request_rate_rps": 8920.0,
                "error_rate_percent": 4.12,
                "p95_latency_ms": 840.0,
                "metadata_json": {
                    "last_deployment": "v4.8.1 (1 day ago by @alex)",
                    "availability_percent": 97.40,
                    "cpu_saturation_percent": 88,
                    "memory_usage_percent": 84,
                    "upstream_dependencies": ["API Gateway"],
                    "downstream_dependencies": ["Payment Service", "PostgreSQL Primary (Aurora)", "Notification Service"]
                }
            },
            {
                "name": "Payment Service",
                "slug": "payment-service",
                "identifier": "svc:stripe-ledger-adapter",
                "tier": 0,
                "owner_team": "Payments Engine",
                "status": "degraded",
                "request_rate_rps": 3110.0,
                "error_rate_percent": 8.85,
                "p95_latency_ms": 1420.0,
                "metadata_json": {
                    "last_deployment": "v3.1.0 (3 days ago by @elena)",
                    "availability_percent": 94.80,
                    "cpu_saturation_percent": 94,
                    "memory_usage_percent": 89,
                    "upstream_dependencies": ["Order Service"],
                    "downstream_dependencies": ["PostgreSQL Primary (Aurora)", "Stripe Payment Gateway"]
                }
            },
            {
                "name": "User Service",
                "slug": "user-service",
                "identifier": "svc:accounts-core",
                "tier": 1,
                "owner_team": "Identity & Auth",
                "status": "healthy",
                "request_rate_rps": 12400.0,
                "error_rate_percent": 0.08,
                "p95_latency_ms": 34.0,
                "metadata_json": {
                    "last_deployment": "v1.19.4 (4 days ago by @david)",
                    "availability_percent": 99.98,
                    "cpu_saturation_percent": 42,
                    "memory_usage_percent": 51,
                    "upstream_dependencies": ["API Gateway"],
                    "downstream_dependencies": ["Redis User Cache", "PostgreSQL Replica"]
                }
            },
            {
                "name": "Notification Service",
                "slug": "notification-service",
                "identifier": "svc:push-email-worker",
                "tier": 2,
                "owner_team": "Communications",
                "status": "healthy",
                "request_rate_rps": 1840.0,
                "error_rate_percent": 0.01,
                "p95_latency_ms": 22.0,
                "metadata_json": {
                    "last_deployment": "v2.0.8 (6 days ago by @maria)",
                    "availability_percent": 99.99,
                    "cpu_saturation_percent": 28,
                    "memory_usage_percent": 38,
                    "upstream_dependencies": ["Order Service"],
                    "downstream_dependencies": ["SendGrid API", "APNS Gateway"]
                }
            },
            {
                "name": "PostgreSQL Primary (Aurora)",
                "slug": "postgres",
                "identifier": "db:aurora-cluster-leader-az1",
                "tier": 0,
                "owner_team": "Data Platform",
                "status": "unhealthy",
                "request_rate_rps": 18200.0,
                "error_rate_percent": 14.20,
                "p95_latency_ms": 2400.0,
                "metadata_json": {
                    "last_deployment": "Engine 15.4 (18 days ago by @sre-bot)",
                    "availability_percent": 88.50,
                    "cpu_saturation_percent": 98,
                    "memory_usage_percent": 96,
                    "upstream_dependencies": ["Order Service", "Payment Service"],
                    "downstream_dependencies": []
                }
            },
            {
                "name": "Inventory Service",
                "slug": "inventory-service",
                "identifier": "svc:stock-allocation-v1",
                "tier": 1,
                "owner_team": "Fulfillment Ops",
                "status": "healthy",
                "request_rate_rps": 5400.0,
                "error_rate_percent": 0.02,
                "p95_latency_ms": 45.0,
                "metadata_json": {
                    "last_deployment": "v3.2.1 (2 days ago by @chen)",
                    "availability_percent": 99.96
                }
            },
            {
                "name": "Search Indexer",
                "slug": "search-indexer",
                "identifier": "svc:es-catalog-sync",
                "tier": 2,
                "owner_team": "Search & Discovery",
                "status": "healthy",
                "request_rate_rps": 2100.0,
                "error_rate_percent": 0.15,
                "p95_latency_ms": 65.0,
                "metadata_json": {
                    "last_deployment": "v1.8.0 (5 days ago by @marcus)",
                    "availability_percent": 99.91
                }
            },
            {
                "name": "Auth Service",
                "slug": "auth-service",
                "identifier": "svc:oauth-jwt-issuer",
                "tier": 0,
                "owner_team": "Security Platform",
                "status": "healthy",
                "request_rate_rps": 15600.0,
                "error_rate_percent": 0.03,
                "p95_latency_ms": 12.0,
                "metadata_json": {
                    "last_deployment": "v5.0.2 (1 week ago by @hannah)",
                    "availability_percent": 99.99
                }
            },
            {
                "name": "Recommendation Engine",
                "slug": "recommendation-engine",
                "identifier": "svc:tensor-recs-online",
                "tier": 2,
                "owner_team": "Data Science & ML",
                "status": "healthy",
                "request_rate_rps": 940.0,
                "error_rate_percent": 0.20,
                "p95_latency_ms": 110.0,
                "metadata_json": {
                    "last_deployment": "v2.4.0-weights-q3 (2 days ago by @wei)",
                    "availability_percent": 99.85
                }
            }
        ]

        service_map = {}
        for s_data in services_data:
            svc = Service(project_id=proj.id, **s_data)
            self.db.add(svc)
            service_map[s_data["slug"]] = svc

        self.db.commit()
        for svc in service_map.values():
            self.db.refresh(svc)

        self._seed_dependencies(proj.id, service_map)
        return proj

    def _seed_dependencies(self, project_id: UUID, service_map: dict) -> None:
        from app.models.service_dependency import ServiceDependency
        from app.repositories.service_dependency_repository import ServiceDependencyRepository
        dep_repo = ServiceDependencyRepository(self.db)
        existing_deps = dep_repo.list_by_project(project_id)
        if existing_deps:
            return

        dep_edges = [
            ("api-gateway", "order-service", "sync", "Ingress proxy route to order orchestration"),
            ("api-gateway", "user-service", "sync", "Ingress proxy route to identity core"),
            ("api-gateway", "auth-service", "sync", "Token authentication and authorization check"),
            ("order-service", "payment-service", "sync", "Payment intent and token settlement"),
            ("order-service", "inventory-service", "sync", "Stock allocation and reservation"),
            ("order-service", "notification-service", "async", "Transactional email and push dispatch"),
            ("order-service", "postgres", "database", "Orders ledger and state machine persistence"),
            ("payment-service", "postgres", "database", "PCI ledger transaction audit records"),
            ("user-service", "postgres", "database", "User account profile storage"),
            ("inventory-service", "postgres", "database", "Warehouse catalog inventory counts"),
        ]
        for src_slug, tgt_slug, dep_type, desc in dep_edges:
            src = service_map.get(src_slug)
            tgt = service_map.get(tgt_slug)
            if src and tgt:
                dep = ServiceDependency(
                    project_id=project_id,
                    source_service_id=src.id,
                    target_service_id=tgt.id,
                    dependency_type=dep_type,
                    description=desc,
                )
                self.db.add(dep)
        self.db.commit()

    def list_projects(self, skip: int = 0, limit: int = 50) -> List[ProjectResponse]:
        self.ensure_default_seed()
        projects = self.project_repo.get_all(skip=skip, limit=limit)
        return [ProjectResponse.model_validate(p) for p in projects]

    def get_project(self, project_id: UUID) -> Optional[ProjectResponse]:
        return self.get_project_by_id(project_id)

    def get_project_by_id(self, project_id: UUID) -> Optional[ProjectResponse]:
        self.ensure_default_seed()
        project = self.project_repo.get_by_id(project_id)
        if not project:
            return None
        return ProjectResponse.model_validate(project)

    def list_services(
        self,
        project_id: Optional[UUID] = None,
        status: Optional[str] = None,
        tier: Optional[int] = None
    ) -> List[ServiceResponse]:
        self.ensure_default_seed()
        if project_id:
            services = self.service_repo.get_by_project(project_id, status=status, tier=tier)
        else:
            services = self.service_repo.get_all(status=status, tier=tier)
        return [ServiceResponse.model_validate(s) for s in services]

    def list_services_for_project(
        self,
        project_id: UUID,
        status: Optional[str] = None,
        tier: Optional[int] = None
    ) -> List[ServiceResponse]:
        return self.list_services(project_id=project_id, status=status, tier=tier)

