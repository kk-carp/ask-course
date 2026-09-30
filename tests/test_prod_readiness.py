import pytest

from backend import config


def _prod_settings(**overrides):
    values = {
        "app_env": "prod",
        "secret_key": "a-real-secret-for-production",
        "demo_password": "a-real-internal-password",
        "course_content_validation_mode": "strict",
        "handoff_enabled": True,
        "handoff_fallback_contact": "https://work.weixin.qq.com/ca/real-contact-id",
    }
    values.update(overrides)
    return config.Settings(**values)


def test_safe_prod_settings_pass(monkeypatch) -> None:
    monkeypatch.setattr(config, "settings", _prod_settings())

    config.assert_safe_for_environment()


def test_prod_requires_strict_course_content(monkeypatch) -> None:
    monkeypatch.setattr(
        config,
        "settings",
        _prod_settings(course_content_validation_mode="warn"),
    )

    with pytest.raises(RuntimeError, match="COURSE_CONTENT_VALIDATION_MODE=strict"):
        config.assert_safe_for_environment()


def test_prod_requires_real_fallback_contact(monkeypatch) -> None:
    monkeypatch.setattr(
        config,
        "settings",
        _prod_settings(handoff_fallback_contact="placeholder://wecom/fallback"),
    )

    with pytest.raises(RuntimeError, match="HANDOFF_FALLBACK_CONTACT"):
        config.assert_safe_for_environment()
