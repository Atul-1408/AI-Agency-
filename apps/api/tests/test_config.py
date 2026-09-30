"""
Tests for Phase 1 configuration.
Verifies Settings loads correctly and provides expected defaults.
"""
from __future__ import annotations

import pytest


def test_settings_load():
    """Settings should load without raising errors."""
    from core.config import settings
    assert settings is not None


def test_settings_defaults():
    """Verify Phase 1 defaults are correct."""
    from core.config import settings
    assert settings.APP_ENV == "test"
    assert settings.JWT_ALGORITHM == "HS256"
    assert settings.JWT_EXPIRE_MINUTES == 1440
    assert settings.NEMOTRON_ENABLED is False
    assert settings.MAX_EMAILS_PER_DAY == 50


def test_is_production_false_in_test():
    from core.config import settings
    assert settings.is_production is False


def test_ai_disabled_by_default():
    """AI must be disabled by default — no accidental live API calls."""
    from core.config import settings
    assert settings.NEMOTRON_ENABLED is False


def test_app_secret_not_default():
    """APP_SECRET must be overridden (tests set it via env)."""
    from core.config import settings
    assert settings.APP_SECRET != "CHANGE_ME", (
        "APP_SECRET must be overridden from the default in test/prod environments"
    )
