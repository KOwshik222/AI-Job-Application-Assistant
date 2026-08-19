"""Tests for guardrails service."""

import pytest

from app.config import get_settings
from app.services.guardrails import Guardrails


def test_valid_url_https():
    assert Guardrails.is_valid_url("https://careers.example.com/job/123") is True


def test_valid_url_http():
    assert Guardrails.is_valid_url("http://example.com/apply") is True


def test_invalid_url_ftp():
    assert Guardrails.is_valid_url("ftp://bad.com") is False


def test_invalid_url_garbage():
    assert Guardrails.is_valid_url("not-a-url") is False


def test_invalid_url_empty():
    assert Guardrails.is_valid_url("") is False


def test_invalid_url_no_host():
    assert Guardrails.is_valid_url("http://") is False


def test_match_threshold_default():
    settings = get_settings()
    assert settings.match_threshold == 75


def test_max_applications_per_day():
    settings = get_settings()
    assert settings.max_applications_per_day == 20


def test_same_company_cooldown():
    settings = get_settings()
    assert settings.same_company_cooldown_days == 30
