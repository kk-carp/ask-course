from dataclasses import replace

import httpx
import pytest

from backend.errors import ServiceUnavailableError
from backend.services import purchase_service
from backend.services.approved_courses import ApprovedCourse

COURSE = ApprovedCourse("99", "测试课程", "测试人群", "测试基础", ("目标",), ("目标",), False, "none", 2,
                        "https://www.arborseek.com/course/99", "https://www.arborseek.com/course/99")


def test_purchase_requires_current_enrollment_and_reachable_page(monkeypatch):
    calls = []
    monkeypatch.setattr(purchase_service, "live_course", lambda cid, **kwargs: (calls.append(kwargs) or {"id": cid, "can_join": 1}, "now"))
    monkeypatch.setattr(httpx.Client, "get", lambda *_a, **_k: httpx.Response(200))
    assert purchase_service.validate_purchase_destination(COURSE) == COURSE.purchase_url
    assert calls == [{"force_refresh": True}]


@pytest.mark.parametrize("can_join", [0, None])
def test_stopped_course_cannot_be_purchased(monkeypatch, can_join):
    monkeypatch.setattr(purchase_service, "live_course", lambda *_a, **_k: ({"can_join": can_join}, "now"))
    with pytest.raises(ValueError, match="不可报名"):
        purchase_service.validate_purchase_destination(COURSE)


def test_wrong_course_or_domain_cannot_be_purchased():
    for url in ("https://www.arborseek.com/course/43", "https://invalid.test/course/99"):
        with pytest.raises(ValueError):
            purchase_service.validate_purchase_destination(replace(COURSE, purchase_url=url))


def test_broken_page_and_service_failure_are_distinct(monkeypatch):
    monkeypatch.setattr(purchase_service, "live_course", lambda *_a, **_k: ({"can_join": 1}, "now"))
    monkeypatch.setattr(httpx.Client, "get", lambda *_a, **_k: httpx.Response(404))
    with pytest.raises(ValueError, match="暂不可用"):
        purchase_service.validate_purchase_destination(COURSE)
    monkeypatch.setattr(purchase_service, "live_course", lambda *_a, **_k: None)
    with pytest.raises(ServiceUnavailableError):
        purchase_service.validate_purchase_destination(COURSE)
