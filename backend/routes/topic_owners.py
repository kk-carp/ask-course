"""内部主题负责人 HTTP：管理员维护关键词与联系方式；无匹配则明确未配置。"""

from fastapi import APIRouter, HTTPException, Request

from backend.errors import ServiceUnavailableError
from backend.schemas import TopicOwnerResponse, TopicOwnerUpsertRequest
from backend.services.auth_service import can_manage_documents, load_auth_context
from backend.services.topic_owner_service import (
    TopicOwnerError,
    list_topic_owners,
    upsert_topic_owner,
)

router = APIRouter(tags=["topic_owners"])


def _require_manager(request: Request):
    context = load_auth_context(request)
    if context is None:
        raise HTTPException(status_code=401, detail="未登录")
    if not can_manage_documents(context.user):
        raise HTTPException(status_code=403, detail="无主题负责人管理权限")
    return context.user


@router.get("/topic_owners", response_model=list[TopicOwnerResponse])
async def get_topic_owners(request: Request) -> list[TopicOwnerResponse]:
    """列出主题负责人；仅管理员。"""
    _require_manager(request)
    try:
        return list_topic_owners()
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.put("/topic_owners", response_model=TopicOwnerResponse)
async def put_topic_owner(
    payload: TopicOwnerUpsertRequest,
    request: Request,
) -> TopicOwnerResponse:
    """新增或更新一条主题负责人；联系方式只来自本表，不经模型生成。"""
    _require_manager(request)
    try:
        return upsert_topic_owner(
            topic_key=payload.topic_key,
            topic_name=payload.topic_name,
            keywords=payload.keywords,
            name=payload.name,
            contact=payload.contact,
        )
    except TopicOwnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
