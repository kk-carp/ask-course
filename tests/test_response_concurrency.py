import asyncio
import threading
import time

import httpx

from backend.main import app
from backend.routes import ask
from backend.schemas import AskResponse
from backend.services.ask_orchestrator import AskIdentity


def test_slow_model_turn_does_not_block_health(monkeypatch):
    started = threading.Event()
    monkeypatch.setattr(ask, "_prepare_request", lambda *_a: AskIdentity(["courses"], None, None, "test"))
    monkeypatch.setattr("backend.routes.health.db.init_engine", lambda: (_ for _ in ()).throw(RuntimeError("test database offline")))

    def slow(*_a):
        started.set()
        time.sleep(0.3)
        return AskResponse(answer="测试回答")

    monkeypatch.setattr(ask, "run_ask_turn", slow)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            pending = asyncio.create_task(client.post("/ask", json={"question": "test"}))
            while not started.is_set():
                await asyncio.sleep(0.005)
            before = time.perf_counter()
            response = await client.get("/health")
            assert response.status_code == 200
            assert time.perf_counter() - before < 0.2
            assert not pending.done()
            assert (await pending).status_code == 200
    asyncio.run(scenario())
