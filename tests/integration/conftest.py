"""Real PostgreSQL tests use an isolated schema, never application tables."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend import db
from backend.config import settings


@pytest.fixture
def postgres_store(monkeypatch):
    url = os.environ.get("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set TEST_POSTGRES_URL to run PostgreSQL integration tests")
    admin = create_engine(url, pool_pre_ping=True)
    if admin.dialect.name != "postgresql":
        admin.dispose()
        pytest.fail("TEST_POSTGRES_URL must use PostgreSQL")
    schema = "test_agent_" + uuid4().hex
    with admin.begin() as connection:
        # public resolves pgvector's type. Refuse existing public tables so
        # Alembic's checkfirst cannot adopt application tables via search_path.
        if connection.scalar(text(
            "SELECT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public')"
        )):
            admin.dispose()
            pytest.fail("TEST_POSTGRES_URL requires a dedicated database with no public tables")
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema},public -clock_timeout=5000 -cstatement_timeout=15000"},
        pool_pre_ping=True,
    )
    factory = sessionmaker(engine, autoflush=False)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", factory)
    monkeypatch.setattr(settings, "data_retention_days", 0)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        db.init_db()
        yield factory, engine, config
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
