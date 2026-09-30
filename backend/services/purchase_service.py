"""点击购买时检查当前可报名状态和官网地址，订单登录由官网处理。"""

import httpx

from backend.config import settings
from backend.errors import ServiceUnavailableError
from backend.services.approved_courses import ApprovedCourse, valid_purchase_url
from backend.services.course_facts import live_course


def validate_purchase_destination(course: ApprovedCourse) -> str:
    if not valid_purchase_url(course.purchase_url, course.id):
        raise ValueError("课程购买地址不正确")
    current = live_course(course.id, force_refresh=True)
    if current is None:
        raise ServiceUnavailableError("暂时无法核实课程报名状态，请稍后重试")
    if current[0].get("can_join") != 1:
        raise ValueError("课程当前不可报名，请联系课程顾问")
    try:
        with httpx.Client(timeout=settings.course_detail_timeout_seconds, follow_redirects=False) as client:
            response = client.get(course.purchase_url)
        if response.status_code != 200:
            raise ValueError("官网课程页暂不可用，请稍后重试")
    except httpx.HTTPError as exc:
        raise ServiceUnavailableError("暂时无法打开官网课程页，请稍后重试") from exc
    return course.purchase_url
