from backend.schemas import OwnerInfo
from backend.services.course_qr_service import lookup_official_presale, parse_presale_qr
from backend.services.handoff_service import resolve_handoff


QR = "https://publicqn.arborseek.com/tstj/images/1785143748273.png"


def test_parse_presale_qr_reads_image_url() -> None:
    parsed = parse_presale_qr(
        {
            "data": {
                "course": {
                    "id": 40,
                    "title": "WorkBuddy AI 助手实战课程",
                    "pre_sale_service_qrcode": QR,
                    "full_description": "<div><img src='body.png'></div>",
                }
            }
        }
    )
    assert parsed == ("WorkBuddy AI 助手实战课程", QR)


def test_parse_presale_qr_ignores_missing_field() -> None:
    assert parse_presale_qr({"data": {"course": {"title": "无码课程"}}}) is None
    assert parse_presale_qr({"data": {}}) is None


def test_slug_course_id_does_not_call_official_api(monkeypatch) -> None:
    def fail_get(*_args, **_kwargs):
        raise AssertionError("slug course id must not call the official API")

    monkeypatch.setattr("backend.services.course_qr_service.httpx.Client.get", fail_get)
    assert lookup_official_presale("quadruped-inspection") is None


def test_handoff_uses_official_qr_before_local_mapping(monkeypatch) -> None:
    owner = OwnerInfo(
        configured=True,
        topic_key="40",
        topic_name="WorkBuddy AI 助手实战课程",
        name="课程顾问",
        contact=QR,
    )
    monkeypatch.setattr(
        "backend.services.handoff_service.lookup_official_presale",
        lambda course_id: owner if course_id == "40" else None,
    )

    result = resolve_handoff(question="这门课怎么退款？", course_id="40", session=object())

    assert result.route == "course_api"
    assert result.owner.contact == QR
    assert result.owner.topic_name == "WorkBuddy AI 助手实战课程"


def test_course_handoff_does_not_route_to_another_courses_keyword(monkeypatch) -> None:
    import backend.services.handoff_service as service

    wrong_owner = OwnerInfo(configured=True, topic_key="99", contact=QR)
    monkeypatch.setattr(service, "lookup_official_presale", lambda _id: None)
    monkeypatch.setattr(service, "_match_by_course_id", lambda _session, _id: OwnerInfo(configured=False))
    monkeypatch.setattr(service, "_match_by_keyword", lambda _session, _question: wrong_owner)
    monkeypatch.setattr(service, "_fallback_owner", lambda: OwnerInfo(configured=False))

    result = resolve_handoff(question="99 课程怎么样", course_id="43", session=object())

    assert result.route == "fallback"
    assert result.owner.configured is False
