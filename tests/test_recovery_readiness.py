"""The drill must reach PostgreSQL through its published port before migrating."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from scripts import recovery_drill as drill


@pytest.mark.parametrize("ready_after", [2, None])
def test_drill_waits_for_host_connection_before_migration(monkeypatch, tmp_path, capsys, ready_after):
    state = {"clock": 0.0, "attempts": 0, "ready": False, "migrated": False, "removed": False}
    password = "synthetic-test-password-do-not-log"

    def fake_docker(*args):
        if args[0] == "run":
            state["owner"] = args[args.index("--label") + 1].split("=", 1)[1]
            return "synthetic-container"
        if args[0] == "inspect":
            return json.dumps([{
                "Config": {"Env": [f"POSTGRES_PASSWORD={password}"],
                           "Labels": {"agent.recovery-drill": state["owner"]}},
                "NetworkSettings": {"Ports": {"5432/tcp": [{"HostPort": "54321"}]}},
            }])
        if args[0] == "rm":
            state["removed"] = True
            return ""
        raise AssertionError(args[0])

    class MigrationReached(Exception):
        pass

    class Engine:
        @contextmanager
        def connect(self):
            state["attempts"] += 1
            if ready_after is None or state["attempts"] <= ready_after:
                raise OperationalError(None, None, Exception(password))

            def execute(query):
                assert str(query) == "SELECT 1"
                state["ready"] = True

            yield SimpleNamespace(execute=execute)

        def begin(self):
            assert state["ready"], "Migration started before the published PostgreSQL port was ready"
            state["migrated"] = True
            raise MigrationReached()

        def dispose(self):
            pass

    def create_engine(url, **kwargs):
        assert url.host == "127.0.0.1" and url.port == 54321
        assert kwargs["connect_args"]["connect_timeout"] == 2
        return Engine()

    def sleep(seconds):
        state["clock"] += seconds

    monkeypatch.setattr(drill, "docker", fake_docker)
    # The old socket probe reports ready even while the published port rejects connections.
    monkeypatch.setattr(drill.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
    monkeypatch.setattr(drill, "create_engine", create_engine)
    monkeypatch.setattr(drill.time, "monotonic", lambda: state["clock"])
    monkeypatch.setattr(drill.time, "sleep", sleep)
    output = tmp_path / "report.json"
    if ready_after is None:
        with pytest.raises(RuntimeError, match="readiness timed out"):
            drill.run_drill(output)
        assert not state["migrated"]
        assert 45 <= state["clock"] <= 46
    else:
        with pytest.raises(MigrationReached):
            drill.run_drill(output)
        assert state["attempts"] == ready_after + 1
    assert state["removed"]
    assert password not in output.read_text()
    diagnostic = capsys.readouterr().err
    assert password not in diagnostic
    expected_step = "postgres_readiness" if ready_after is None else "schema_upgrade"
    assert expected_step in diagnostic
