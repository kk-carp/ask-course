"""Adopt the pre-Alembic schema without dropping existing records."""

from alembic import op

from migrations.baseline_schema import Base

revision = "0001"
down_revision = None
branch_labels = depends_on = None


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(connection, checkfirst=True)
    # Historical installations may predate these additive columns.
    if connection.dialect.name == "postgresql":
        for sql in (
            "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS path VARCHAR(512)",
            "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS content_tsv tsvector",
            "ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)",
            "ALTER TABLE documents ADD COLUMN IF NOT EXISTS course_id VARCHAR(32)",
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS context_summary TEXT",
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS summary_message_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE visitor_consultations ADD COLUMN IF NOT EXISTS history_json TEXT NOT NULL DEFAULT '[]'",
        ):
            op.execute(sql)


def downgrade():
    raise RuntimeError(
        "Baseline adoption cannot be undone by deleting existing business tables"
    )
