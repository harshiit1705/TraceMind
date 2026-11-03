from typing import Optional
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.investigation import Investigation


class InvestigationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, investigation_id: UUID) -> Optional[Investigation]:
        return self.db.query(Investigation).filter(Investigation.id == investigation_id).first()

    def get_by_incident_id(self, incident_id: UUID) -> Optional[Investigation]:
        return self.db.query(Investigation).filter(Investigation.incident_id == incident_id).first()

    def create(self, investigation: Investigation) -> Investigation:
        self.db.add(investigation)
        self.db.commit()
        self.db.refresh(investigation)
        return investigation

