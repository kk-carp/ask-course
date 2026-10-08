"""Use the application's configured database; never store credentials in ini."""

from alembic import context
from sqlalchemy import create_engine, pool

from backend.config import settings
from backend.models import Base


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=settings.database_url, target_metadata=Base.metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied = context.config.attributes.get("connection")
    if supplied is not None:
        run(supplied)
    else:
        engine = create_engine(settings.database_url, poolclass=pool.NullPool)
        with engine.connect() as connection:
            if connection.dialect.name == "postgresql":
                # Serialise release jobs across replicas for this database.
                connection.exec_driver_sql("SELECT pg_advisory_lock(82417621)")
                connection.commit()
            try:
                run(connection)
            finally:
                if connection.dialect.name == "postgresql":
                    connection.exec_driver_sql("SELECT pg_advisory_unlock(82417621)")
                    connection.commit()
