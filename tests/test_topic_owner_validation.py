import pytest

from backend.services.topic_owner_service import (
    TopicOwnerError,
    is_usable_contact,
    match_owner_for_question,
    validate_topic_owner_fields,
)


def test_real_https_contact_is_usable() -> None:
    assert is_usable_contact("https://work.weixin.qq.com/ca/real-contact-id")


@pytest.mark.parametrize(
    "contact",
    [
        "",
        "placeholder://wecom/course",
        "https://example.com/contact",
        "https://work.weixin.qq.com/ca/replace-with-real-contact",
        "javascript:alert(1)",
    ],
)
def test_placeholder_or_unsafe_contact_is_rejected(contact: str) -> None:
    assert not is_usable_contact(contact)


def test_course_id_must_match_public_contract() -> None:
    with pytest.raises(TopicOwnerError):
        validate_topic_owner_fields(
            topic_key="四足 课程",
            topic_name="四足机器人巡检",
            name="售前 A",
            contact="https://work.weixin.qq.com/ca/real-contact-id",
        )


def test_placeholder_owner_cannot_mask_real_owner() -> None:
    class Owner:
        def __init__(self, key: str, keywords: str, contact: str) -> None:
            self.topic_key = key
            self.topic_name = key
            self.keywords = keywords
            self.owner_name = key
            self.contact = contact

    class Rows:
        def all(self):
            return [
                Owner(
                    "placeholder-course",
                    "四足机器人巡检",
                    "placeholder://wecom/course",
                ),
                Owner(
                    "real-course",
                    "四足",
                    "https://work.weixin.qq.com/ca/real-contact-id",
                ),
            ]

    class Session:
        def scalars(self, _statement):
            return Rows()

    result = match_owner_for_question(Session(), "我想了解四足机器人巡检")

    assert result.configured is True
    assert result.topic_key == "real-course"
