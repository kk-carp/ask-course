"""登录 / 登出 / 当前用户：Session Cookie；允许空间由服务端按成员计算。"""

from fastapi import APIRouter, HTTPException, Request

from backend.domain.membership import get_allowed_spaces_for_user
from backend.errors import ServiceUnavailableError
from backend.infra.rate_limit import RATE_LIMIT_DETAIL, allow_login, client_ip
from backend.schemas import LoginRequest, MeResponse
from backend.services.auth_service import (
    AuthUser,
    authenticate,
    can_manage_documents,
    clear_session,
    load_auth_context,
    set_session_user,
)

router = APIRouter(tags=["auth"])


def _to_me_response(user: AuthUser) -> MeResponse:
    return MeResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        allowed_spaces=get_allowed_spaces_for_user(user.id),
        can_manage_documents=can_manage_documents(user),
    )


@router.post("/login", response_model=MeResponse)
async def login(payload: LoginRequest, request: Request) -> MeResponse:
    if not allow_login(payload.username, client_ip(request)):
        raise HTTPException(status_code=429, detail=RATE_LIMIT_DETAIL)
    try:
        user = authenticate(payload.username, payload.password)
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    set_session_user(request, user.id)
    try:
        return _to_me_response(user)
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/logout")
async def logout(request: Request) -> dict[str, bool]:
    clear_session(request)
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
async def me(request: Request) -> MeResponse:
    try:
        context = load_auth_context(request)
        if context is None:
            raise HTTPException(status_code=401, detail="未登录")
        return _to_me_response(context.user)
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
