"""在自行创建的临时 PostgreSQL 容器内演练停用、联合备份还原和迁移回滚保护。"""

import argparse
import hashlib
import json
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend import db
from backend.models import (
    Chunk,
    Conversation,
    Document,
    DocumentReview,
    Message,
    PilotControl,
    Space,
    User,
)
from backend.scripts.emergency_stop import stop_pilot
from backend.services.pilot_service import eligible, pilot_percent

ROOT = Path(__file__).resolve().parents[1]


def verify(condition: bool) -> None:
    if not condition:
        raise RuntimeError("Recovery verification failed")


def docker(*args) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, check=False, timeout=120)
    if result.returncode:
        # Docker errors may include credentials/config: preserve a safe step label only.
        raise RuntimeError(f"Docker step failed: {args[0]}")
    return result.stdout.strip()


def fingerprint(engine) -> dict:
    """Compare every application table's full contents without printing those contents."""
    with engine.connect() as connection:
        tables = connection.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).all()
        result = {}
        for table in tables:
            quoted = engine.dialect.identifier_preparer.quote(table)
            rows = connection.scalars(text(f"SELECT row_to_json(t)::text FROM {quoted} AS t")).all()
            digest = hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()
            result[table] = {"rows": len(rows), "sha256": digest}
        return result


def run_drill(output: Path) -> dict:
    started = time.monotonic()
    owner = uuid4().hex
    container = None
    engines = []
    report = {"scope": "isolated_synthetic_database_and_files", "production_tested": False,
              "image_rollback_tested": False, "checks": {}}
    try:
        container = docker("run", "-d", "--label", f"agent.recovery-drill={owner}",
                           "-e", f"POSTGRES_PASSWORD={secrets.token_hex(20)}", "-e", "POSTGRES_DB=agent_drill",
                           "-p", "127.0.0.1::5432", "pgvector/pgvector:pg16")
        details = json.loads(docker("inspect", container))[0]
        password = next(value.split("=", 1)[1] for value in details["Config"]["Env"] if value.startswith("POSTGRES_PASSWORD="))
        port = int(details["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"])
        deadline = time.monotonic() + 45
        while True:
            result = subprocess.run(["docker", "exec", container, "pg_isready", "-U", "postgres", "-d", "agent_drill"], capture_output=True, timeout=5, check=False)
            if result.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Temporary PostgreSQL readiness timed out")
            time.sleep(.5)
        url = URL.create("postgresql+psycopg", username="postgres", password=password,
                         host="127.0.0.1", port=port, database="agent_drill")
        source = create_engine(url)
        engines.append(source)
        config = Config(str(ROOT / "alembic.ini"))
        with source.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with tempfile.TemporaryDirectory(prefix="agent-recovery-") as temporary:
            work = Path(temporary)
            original = work / "release-data"
            original.mkdir()
            (original / "course.txt").write_text("Synthetic public robot syllabus", encoding="utf-8")
            with Session(source) as session:
                session.add(Space(id="drill", name="Synthetic"))
                session.add(User(id="drill-user", username="drill-user", password_hash="not-a-login", role="admin"))
                session.flush()
                session.add(Document(id="drill-document", space_id="drill", title="Synthetic syllabus", course_id="43",
                                     file_path="course.txt", status="ready"))
                session.add(Conversation(id="drill-conversation", user_id="drill-user"))
                session.flush()
                session.add(Chunk(document_id="drill-document", space_id="drill", chunk_index=0,
                                  content="Synthetic public robot syllabus", embedding=[1.0] + [0.0]*1023))
                session.add(DocumentReview(document_id="drill-document", actor_id="drill-user", action="publish",
                                           note="Synthetic human review record"))
                session.add(Message(conversation_id="drill-conversation", role="user", content="Synthetic consultation"))
                session.add(PilotControl(id=1, percent=5))
                session.commit()
            original_engine, original_factory = db.engine, db.SessionLocal
            db.engine, db.SessionLocal = source, sessionmaker(source)
            try:
                stop_pilot()
            finally:
                db.engine, db.SessionLocal = original_engine, original_factory
            with Session(source) as session:
                verify(pilot_percent(session) == 0)
                verify(not eligible("43", "synthetic-visitor", session))
            report["checks"]["emergency_stop"] = True
            before = fingerprint(source)
            docker("exec", container, "pg_dump", "-U", "postgres", "-d", "agent_drill", "-Fc", "-f", "/tmp/drill.dump")
            docker("cp", f"{container}:/tmp/drill.dump", str(work / "drill.dump"))
            archive = shutil.make_archive(str(work / "release-data"), "zip", original)
            restored_files = work / "restored-data"
            shutil.unpack_archive(archive, restored_files)
            verify(hashlib.sha256((original / "course.txt").read_bytes()).digest() == hashlib.sha256((restored_files / "course.txt").read_bytes()).digest())
            report["checks"]["file_archive_restore"] = True
            docker("exec", container, "createdb", "-U", "postgres", "agent_drill_restore")
            # Restore from the exported copy, not a separate fresh dump.
            docker("cp", str(work / "drill.dump"), f"{container}:/tmp/restore.dump")
            docker("exec", container, "pg_restore", "-U", "postgres", "-d", "agent_drill_restore", "--exit-on-error", "/tmp/restore.dump")
            restored = create_engine(url.set(database="agent_drill_restore"))
            engines.append(restored)
            verify(fingerprint(restored) == before)
            report["checks"]["all_tables_rows_and_content_match"] = True
            with Session(restored) as session:
                verify(pilot_percent(session) == 0)
                verify(session.scalar(select(Chunk.content)) == (restored_files / "course.txt").read_text())
                verify(session.get(Conversation, "drill-conversation").messages[0].content == "Synthetic consultation")
                verify(session.scalar(select(DocumentReview.action)) == "publish")
            report["checks"]["restored_records_and_stop_state"] = True
            with restored.begin() as connection:
                config.attributes["connection"] = connection
                try:
                    command.downgrade(config, "0003")
                except RuntimeError as exc:
                    if "Cannot discard" not in str(exc):
                        raise
                else:
                    raise AssertionError("Unsafe downgrade was accepted")
            verify(fingerprint(restored) == before)
            report["checks"]["unsafe_schema_rollback_refused_without_data_loss"] = True
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["failure_type"] = type(exc).__name__
        raise
    finally:
        for engine in engines:
            engine.dispose()
        if container:
            details = json.loads(docker("inspect", container))[0]
            if details["Config"]["Labels"].get("agent.recovery-drill") != owner:
                raise RuntimeError("Refusing to remove a container not owned by this drill")
            docker("rm", "-f", "-v", container)
            report["temporary_container_removed"] = True
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/operations/recovery-drill.json")
    args = parser.parse_args()
    try:
        report = run_drill(Path(args.output))
    except (RuntimeError, AssertionError, OSError, SQLAlchemyError, subprocess.SubprocessError, ValueError):
        print("恢复演练失败；详细步骤状态已保存到指定报告，未使用当前配置数据库。", file=sys.stderr)
        return 1
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
