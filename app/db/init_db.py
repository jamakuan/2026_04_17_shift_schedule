from sqlalchemy import select

from app.core.config import settings
from app.db.base import Base
from app.db.models import AppMetadata
from app.db.session import SessionLocal, engine
from app.services.schedule_service import bootstrap_defaults


def initialize_database() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        marker = session.scalar(
            select(AppMetadata).where(AppMetadata.key == "schema_version")
        )

        if marker is None:
            session.add(AppMetadata(key="schema_version", value="0.1.0"))
        bootstrap_defaults(session)
