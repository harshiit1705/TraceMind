"""Pydantic v2 schemas for service dependency and topology representations."""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class DependencyType(str, Enum):
    SYNC = "sync"           # Synchronous RPC / HTTP / gRPC call
    ASYNC = "async"         # Asynchronous messaging / Kafka / SQS / RabbitMQ
    DATABASE = "database"   # Database storage / Aurora / Postgres / DynamoDB
    CACHE = "cache"         # In-memory caching / Redis / Memcached
    THIRD_PARTY = "third_party"  # External API / SaaS gateway


class ServiceDependencyCreate(BaseModel):
    """Schema for creating a directed dependency between two services."""
    source_service_id: UUID = Field(
        ...,
        description="ID of the caller / dependent service (downstream).",
    )
    target_service_id: UUID = Field(
        ...,
        description="ID of the callee / dependency service (upstream).",
    )
    dependency_type: DependencyType = Field(
        default=DependencyType.SYNC,
        description="Type of interaction between caller and callee.",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional human-readable notes about the interface or protocol.",
    )


class ServiceDependencyResponse(BaseModel):
    """Schema representing an established dependency edge."""
    id: UUID
    project_id: UUID
    source_service_id: UUID
    target_service_id: UUID
    dependency_type: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ServiceDependencyNode(BaseModel):
    """Node in the project dependency topology."""
    id: UUID
    slug: str
    name: str
    identifier: str
    tier: int
    status: str


class ServiceDependencyEdge(BaseModel):
    """Edge in the project dependency topology."""
    id: UUID
    source_service_id: UUID  # Caller / downstream
    target_service_id: UUID  # Dependency / upstream
    dependency_type: str
    description: Optional[str] = None


class ProjectDependencyGraph(BaseModel):
    """Complete directed acyclic graph (DAG) representation for a project's microservices."""
    project_id: UUID
    nodes: List[ServiceDependencyNode]
    edges: List[ServiceDependencyEdge]
    # Adjacency: caller -> list of upstream dependencies it calls
    adjacency: Dict[str, List[str]]
    # Reverse adjacency: dependency -> list of downstream services that call it
    reverse_adjacency: Dict[str, List[str]]

