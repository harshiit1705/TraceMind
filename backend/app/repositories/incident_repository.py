from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.incident import Incident
from app.models.incident_event import IncidentEvent


class IncidentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_list(
        self,
        project_id: Optional[UUID] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[Incident], int]:
        query = self.db.query(Incident)
        if project_id:
            query = query.filter(Incident.project_id == project_id)
        if status:
            query = query.filter(Incident.status == status)
        if severity:
            query = query.filter(Incident.severity == severity)

        total = query.count()
        items = query.order_by(Incident.started_at.desc()).offset(skip).limit(limit).all()
        return items, total

    def get_by_id(self, incident_id: UUID) -> Optional[Incident]:
        return self.db.query(Incident).filter(Incident.id == incident_id).first()

    def get_by_number(self, incident_number: str) -> Optional[Incident]:
        return self.db.query(Incident).filter(Incident.incident_number.ilike(incident_number)).first()

    def get_events(self, incident_id: UUID) -> List[IncidentEvent]:
        return self.db.query(IncidentEvent).filter(IncidentEvent.incident_id == incident_id).order_by(IncidentEvent.timestamp.asc()).all()

    def create(self, incident: Incident) -> Incident:
        self.db.add(incident)
        self.db.commit()
        self.db.refresh(incident)
        return incident

    def add_event(self, event: IncidentEvent) -> IncidentEvent:
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

