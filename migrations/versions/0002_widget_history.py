"""Owned website sessions and durable, idempotent turn records."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = depends_on = None


def upgrade():
    for column in (
        sa.Column("title", sa.String(40), nullable=False, server_default="新咨询"),
        sa.Column(
            "custom_title", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "widget_session", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creation_key", sa.String(36), nullable=True),
    ):
        op.add_column("visitor_consultations", column)
    op.execute("UPDATE visitor_consultations SET last_activity_at = updated_at")
    op.create_index(
        "uq_widget_creation_key", "visitor_consultations", ["creation_key"], unique=True
    )
    existing = sa.inspect(op.get_bind())
    if existing.has_table("visitor_turns"):
        # A legacy hot-reload process can create new tables via create_all before
        # this release is migrated. Adopt only an exact compatible schema.
        columns = {
            column["name"]: column for column in existing.get_columns("visitor_turns")
        }
        expected = {
            "id",
            "conversation_id",
            "request_id",
            "question",
            "response_json",
            "created_at",
        }
        unique = {
            tuple(item["column_names"])
            for item in existing.get_unique_constraints("visitor_turns")
        }
        foreign = existing.get_foreign_keys("visitor_turns")
        compatible = (
            set(columns) == expected
            and all(
                not columns[key]["nullable"] for key in expected - {"response_json"}
            )
            and existing.get_pk_constraint("visitor_turns")["constrained_columns"]
            == ["id"]
            and ("conversation_id", "request_id") in unique
            and any(
                item["constrained_columns"] == ["conversation_id"]
                and item["referred_table"] == "visitor_consultations"
                and item["options"].get("ondelete") == "CASCADE"
                for item in foreign
            )
            and all(
                isinstance(columns[key]["type"], sa.String)
                and columns[key]["type"].length == 36
                for key in ("id", "conversation_id", "request_id")
            )
            and all(
                isinstance(columns[key]["type"], sa.Text)
                for key in ("question", "response_json")
            )
            and isinstance(columns["created_at"]["type"], sa.DateTime)
        )
        if not compatible:
            raise RuntimeError(
                "Existing visitor_turns schema is incompatible; inspect it before migration"
            )
    else:
        op.create_table(
            "visitor_turns",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "conversation_id",
                sa.String(36),
                sa.ForeignKey("visitor_consultations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("request_id", sa.String(36), nullable=False),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("response_json", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "conversation_id", "request_id", name="uq_visitor_turn_request"
            ),
        )
    if "ix_visitor_turns_conversation_id" not in {
        item["name"] for item in sa.inspect(op.get_bind()).get_indexes("visitor_turns")
    }:
        op.create_index(
            "ix_visitor_turns_conversation_id", "visitor_turns", ["conversation_id"]
        )


def downgrade():
    op.drop_table("visitor_turns")
    op.drop_index("uq_widget_creation_key", table_name="visitor_consultations")
    for name in (
        "creation_key",
        "deleted_at",
        "last_activity_at",
        "widget_session",
        "custom_title",
        "title",
    ):
        op.drop_column("visitor_consultations", name)
