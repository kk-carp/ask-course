"""管理员只读运行指标：当前进程累计。"""

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select
from datetime import datetime, timedelta, timezone
from backend import db
from backend.models import FunnelEvent

from backend.infra.metrics import snapshot, latency_snapshot
from backend.schemas import MetricsResponse
from backend.services.auth_service import can_manage_documents, load_auth_context

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(request: Request) -> MetricsResponse:
    context = load_auth_context(request)
    if context is None:
        raise HTTPException(status_code=401, detail="未登录")
    if not can_manage_documents(context.user):
        raise HTTPException(status_code=403, detail="仅管理员可查看运行概况")
    data = snapshot()
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    funnel: dict[str, int] = {}
    if db.SessionLocal is not None:
        try:
            with db.SessionLocal() as session:
                funnel = dict(session.execute(select(FunnelEvent.event_name, func.count()).where(FunnelEvent.created_at >= cutoff).group_by(FunnelEvent.event_name)).all())
        except Exception:
            # 老库尚未完成新表初始化时，保留原有运行指标。
            pass
    return MetricsResponse(
        ask_total=data.ask_total,
        ask_hit=data.ask_hit,
        ask_miss=data.ask_miss,
        ask_error_502=data.ask_error_502,
        ask_error_503=data.ask_error_503,
        ask_429=data.ask_429,
        llm_calls=data.llm_calls,
        prompt_tokens_total=data.prompt_tokens_total,
        completion_tokens_total=data.completion_tokens_total,
        funnel_events_30d=funnel,
        latency_ms=latency_snapshot(),
    )


@router.get("/metrics/funnel")
def get_funnel_metrics(request: Request) -> dict:
    context = load_auth_context(request)
    if context is None:
        raise HTTPException(status_code=401, detail="未登录")
    if not can_manage_documents(context.user):
        raise HTTPException(status_code=403, detail="仅管理员可查看运行概况")
    if db.SessionLocal is None:
        raise HTTPException(status_code=503, detail="数据库不可用")
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    with db.SessionLocal() as session:
        rows = session.execute(select(
            func.date(FunnelEvent.created_at), FunnelEvent.course_id,
            FunnelEvent.event_name, func.count(),
        ).where(FunnelEvent.created_at >= cutoff).group_by(
            func.date(FunnelEvent.created_at), FunnelEvent.course_id, FunnelEvent.event_name,
        )).all()
    return {"days": 7, "events": [
        {"day": str(day), "course_id": course_id, "event_name": event_name, "count": count}
        for day, course_id, event_name, count in rows
    ]}
