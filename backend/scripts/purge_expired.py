"""手动清理过期会话：python -m backend.scripts.purge_expired"""

from datetime import datetime, timezone

from backend.config import settings
from backend import db
from backend.services.retention_service import purge_expired


def main() -> None:
    db.init_engine()
    if db.SessionLocal is None:
        raise RuntimeError("数据库会话未初始化")
    with db.SessionLocal() as session:
        result = purge_expired(
            session,
            now=datetime.now(timezone.utc),
            retention_days=settings.data_retention_days,
        )
        session.commit()
    print(
        f"已清理过期数据：会话 {result.conversations} 条"
        f"（保留 {settings.data_retention_days} 天）。"
    )


if __name__ == "__main__":
    main()
