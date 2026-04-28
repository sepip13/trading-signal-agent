"""Run once to create all tables in Postgres."""
from app.db.session import Base, engine
from app.models import signal  # noqa: F401 — registers model with Base

Base.metadata.create_all(bind=engine)
print("✓ Tables created.")
