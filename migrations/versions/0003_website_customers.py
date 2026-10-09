"""Separate website customers and enforce exclusive consultation ownership."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "website_customers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("external_user_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "external_user_id", name="uq_website_customer_identity"),
        sa.CheckConstraint("length(trim(provider)) > 0", name="ck_website_customer_provider"),
        sa.CheckConstraint("length(trim(external_user_id)) > 0", name="ck_website_customer_external_id"),
    )
    with op.batch_alter_table("visitor_consultations") as batch:
        batch.add_column(sa.Column("customer_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("source_visitor_id", sa.String(32), nullable=True))
        batch.alter_column("visitor_id", existing_type=sa.String(32), nullable=True)
        batch.create_foreign_key(
            "fk_consultation_customer", "website_customers", ["customer_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_check_constraint(
            "ck_consultation_one_owner",
            "(visitor_id IS NOT NULL AND customer_id IS NULL) OR "
            "(visitor_id IS NULL AND customer_id IS NOT NULL)",
        )
        batch.create_index("ix_consultations_customer_activity", ["customer_id", "last_activity_at", "id"])
    # Preserve ownership, messages and activity timestamps for all existing guests.
    op.execute("UPDATE visitor_consultations SET source_visitor_id = visitor_id")


def downgrade():
    connection = op.get_bind()
    # Old code cannot represent customer ownership. Refuse data-losing rollback.
    if (
        connection.scalar(sa.text("SELECT 1 FROM website_customers LIMIT 1")) is not None
        or connection.scalar(sa.text(
            "SELECT 1 FROM visitor_consultations WHERE customer_id IS NOT NULL LIMIT 1"
        )) is not None
    ):
        raise RuntimeError("Cannot downgrade website customer data; restore a compatible backup or keep revision 0003")
    with op.batch_alter_table("visitor_consultations") as batch:
        batch.drop_index("ix_consultations_customer_activity")
        batch.drop_constraint("ck_consultation_one_owner", type_="check")
        batch.drop_constraint("fk_consultation_customer", type_="foreignkey")
        batch.drop_column("source_visitor_id")
        batch.drop_column("customer_id")
        batch.alter_column("visitor_id", existing_type=sa.String(32), nullable=False)
    op.drop_table("website_customers")
