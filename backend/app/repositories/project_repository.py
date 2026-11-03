from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.project import Project


class ProjectRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self, skip: int = 0, limit: int = 50) -> List[Project]:
        return self.db.query(Project).offset(skip).limit(limit).all()

    def count(self) -> int:
        return self.db.query(Project).count()

    def get_by_id(self, project_id: UUID) -> Optional[Project]:
        return self.db.query(Project).filter(Project.id == project_id).first()

    def get_by_slug(self, slug: str) -> Optional[Project]:
        return self.db.query(Project).filter(Project.slug == slug).first()

    def create(self, project: Project) -> Project:
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

