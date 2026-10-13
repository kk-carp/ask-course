"""Configure a new empty index; never reinterpret existing vectors."""
from alembic import op
from sqlalchemy import text
from backend.config import settings

revision = "0005"
down_revision = "0004"
branch_labels = depends_on = None

def upgrade():
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    current = conn.execute(text("SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid='chunks'::regclass AND attname='embedding'")).scalar_one()
    target = f"vector({settings.embedding_dim})"
    if current == target:
        return
    if conn.execute(text("SELECT EXISTS(SELECT 1 FROM chunks)")).scalar():
        raise RuntimeError("向量维度变化需要独立空库并重新入库，禁止修改已有索引")
    op.execute(f"ALTER TABLE chunks ALTER COLUMN embedding TYPE {target}")

def downgrade():
    conn = op.get_bind()
    if conn.dialect.name != "postgresql": return
    if conn.execute(text("SELECT EXISTS(SELECT 1 FROM chunks)")).scalar():
        raise RuntimeError("存在向量时禁止降级维度")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1024)")
