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

    def get_by_correlation_group_id(self, correlation_group_id: UUID) -> Optional[Incident]:
        return self.db.query(Incident).filter(Incident.correlation_group_id == correlation_group_id).first()

    def generate_next_incident_number(self) -> str:
        rows = self.db.query(Incident.incident_number).all()
        max_num = 0
        for (num_str,) in rows:
            if num_str and num_str.upper().startswith("INC-"):
                digits = num_str[4:]
                if digits.isdigit():
                    max_num = max(max_num, int(digits))
        next_num = max(max_num + 1, 8493)
        return f"INC-{next_num}"

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

