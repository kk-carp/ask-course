"""Keep uploads pending until an explicit human publication."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("supersedes_id", sa.String(36), nullable=True))
    op.create_table(
        "document_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_document_reviews_document_id", "document_reviews", ["document_id"])
    op.create_index("ux_documents_pending_hash", "documents", ["space_id", "content_hash"], unique=True,
                    postgresql_where=sa.text("status = 'pending' AND content_hash IS NOT NULL"),
                    sqlite_where=sa.text("status = 'pending' AND content_hash IS NOT NULL"))
    # Existing ready records retain their availability; no automatic human approval is invented.


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT 1 FROM document_reviews LIMIT 1")) is not None or connection.scalar(
        sa.text("SELECT 1 FROM documents WHERE status = 'pending' LIMIT 1")
    ) is not None:
        raise RuntimeError("Cannot discard document review data; retain 0004 or restore a compatible backup")
    op.drop_index("ux_documents_pending_hash", table_name="documents")
    op.drop_table("document_reviews")
    op.drop_column("documents", "supersedes_id")
