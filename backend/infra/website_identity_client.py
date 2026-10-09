"""Read-only /miniapp/me verification; never log or persist credentials/profile."""

import httpx
from httpx import Client
from fastapi import HTTPException

from backend.config import settings

IDENTITY_URL = "https://arboradmin.saikr.com/miniapp/me"


def lookup_member(authorization: str) -> str:
    # Fixed destination and redirects disabled: a response cannot forward a
    # customer's Bearer credential to another host. No cookies or staff auth.
    try:
        with Client(timeout=settings.website_identity_timeout_seconds,
                    follow_redirects=False) as client:
            response = client.post(IDENTITY_URL, headers={
                "Accept": "application/json", "Authorization": authorization,
                # The observed website request sends both headers. Derive the
                # second from the same validated input; never forward an
                # independently supplied browser token header.
                "token": authorization.split(" ", 1)[1],
            })
    except httpx.HTTPError:
        raise HTTPException(503, "官网身份验证暂不可用，请稍后重试") from None
    if response.status_code == 401:
        raise HTTPException(401, "官网身份已失效，请重新登录")
    # Unknown business failures, WAF/403, throttling, redirects and server errors
    # cannot establish identity. Do not guess undocumented business error codes.
    if response.status_code != 200 or len(response.content) > 65536:
        raise HTTPException(503, "官网身份验证暂不可用，请稍后重试")
    try:
        payload = response.json()
    except ValueError:
        raise HTTPException(503, "官网身份验证响应无效，请稍后重试") from None
    member = payload.get("data") if isinstance(payload, dict) else None
    member_id = member.get("id") if isinstance(member, dict) else None
    if (not isinstance(payload, dict) or payload.get("success") is not True
            or type(member_id) is not int or member_id <= 0 or len(str(member_id)) > 128):
        raise HTTPException(503, "官网身份验证响应无效，请稍后重试")
    # Ignore nickname, role, phone, balances and all other personal fields.
    return str(member_id)
