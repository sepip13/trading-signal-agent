"""Run once to create all tables in Postgres."""
from app.db.session import Base, engine
import app.models  # noqa: F401 — registers all models with Base

Base.metadata.create_all(bind=engine)
print("✓ Tables created.")
