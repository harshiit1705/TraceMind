from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.service import Service


class ServiceRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_project(self, project_id: UUID, status: Optional[str] = None, tier: Optional[int] = None) -> List[Service]:
        query = self.db.query(Service).filter(Service.project_id == project_id)
        if status:
            query = query.filter(Service.status == status)
        if tier is not None:
            query = query.filter(Service.tier == tier)
        return query.order_by(Service.tier.asc(), Service.name.asc()).all()

    def get_all(self, status: Optional[str] = None, tier: Optional[int] = None) -> List[Service]:
        query = self.db.query(Service)
        if status:
            query = query.filter(Service.status == status)
        if tier is not None:
            query = query.filter(Service.tier == tier)
        return query.order_by(Service.tier.asc(), Service.name.asc()).all()

    def get_by_id(self, service_id: UUID) -> Optional[Service]:
        return self.db.query(Service).filter(Service.id == service_id).first()

    def get_by_identifier(self, identifier: str) -> Optional[Service]:
        return self.db.query(Service).filter(Service.identifier == identifier).first()

    def create(self, service: Service) -> Service:
        self.db.add(service)
        self.db.commit()
        self.db.refresh(service)
        return service

