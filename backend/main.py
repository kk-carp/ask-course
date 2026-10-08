"""FastAPI 入口：启动时建库、加载 BGE-M3 与 reranker，挂载 P0 路由。

P0 改动（相对 FDE 源）：
1. 只挂载售前需要的路由（问答/文档入库/课程—售前映射/账号/会话/健康/指标）；
   已移除学院答疑专用模块；
2. 启动不再初始化课外语义搜索等 FDE 旁路。
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from backend.config import assert_safe_for_environment, session_https_only, settings
from backend.db import init_db
from backend.infra.embed import load_model
from backend.infra.origin_guard import OriginGuardMiddleware
from backend.infra.request_context import RequestIdMiddleware
from backend.infra.rerank import load_reranker
from backend.routes import (
    ask,
    auth,
    consultations,
    conversations,
    documents,
    health,
    metrics,
    topic_owners,
    widget_history,
)
from backend.spa import register_frontend

_log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """启动时初始化数据库与向量模型，避免请求阶段重复冷启动。"""
    started = time.perf_counter()

    def _step(name: str) -> None:
        _log.info("startup [%s] ...", name)

    def _done(name: str, t0: float) -> None:
        _log.info("startup [%s] done (%.1fs)", name, time.perf_counter() - t0)

    assert_safe_for_environment()

    t0 = time.perf_counter()
    _step("1/3 init_db")
    init_db()
    _done("1/3 init_db", t0)

    t0 = time.perf_counter()
    _step(f"2/3 load embed model ({settings.embed_model})")
    load_model()
    _done("2/3 load embed model", t0)

    t0 = time.perf_counter()
    if settings.retrieve_use_rerank:
        _step(f"3/3 load reranker ({settings.rerank_model})")
    else:
        _step("3/3 load reranker (skipped)")
    load_reranker()
    _done("3/3 load reranker", t0)

    _log.info("startup complete (%.1fs total)", time.perf_counter() - started)
    async def cleanup():
        from backend.db import purge_expired_on_startup
        while True:
            await asyncio.sleep(300)
            await run_in_threadpool(purge_expired_on_startup)

    task = asyncio.create_task(cleanup())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="天树探界 · 售前 Agent 助手（P0 独立部署）",
    description="课程知识库问答、多轮问诊推荐、购买页引导与人工承接。",
    lifespan=lifespan,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie=settings.session_cookie_name,
    same_site="lax",
    https_only=session_https_only(),
    max_age=60 * 60 * 24 * 7,
)
# 后添加的更靠外：Origin 校验包住 Session；RequestId 最外层，403 也带编号。
app.add_middleware(OriginGuardMiddleware)
app.add_middleware(RequestIdMiddleware)

app.include_router(health.router)
app.include_router(metrics.router)
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(ask.router)
app.include_router(conversations.router)
app.include_router(consultations.router)
app.include_router(widget_history.router)
app.include_router(topic_owners.router)

register_frontend(app)
