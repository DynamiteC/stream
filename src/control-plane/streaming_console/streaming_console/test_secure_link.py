"""Unit tests for nginx secure_link token generation.

``secure_link.py`` is imported by path so these tests run without a Frappe
install (the module itself has no Frappe dependency).
"""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "secure_link", Path(__file__).resolve().parent / "secure_link.py"
)
secure_link = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(secure_link)


# Golden vector, independently computed for the nginx config
#   secure_link_md5 "$secure_link_expires REPLACE_WITH_SECRET_KEY";
# i.e. base64url(md5(b"1000 testsecret")) with padding stripped.
GOLDEN_EXPIRES = 1000
GOLDEN_SECRET = "testsecret"
GOLDEN_TOKEN = "gEK-_NZKBkhIzAlt7-VMbQ"


def test_generate_token_matches_nginx_format():
    assert secure_link.generate_token(GOLDEN_EXPIRES, secret=GOLDEN_SECRET) == GOLDEN_TOKEN


def test_token_is_urlsafe_unpadded_22_chars():
    token = secure_link.generate_token(1234567890, secret="abc")
    assert len(token) == 22  # 16-byte md5 -> 22 base64 chars, no padding
    assert "=" not in token
    assert "+" not in token and "/" not in token


def test_token_is_deterministic():
    a = secure_link.generate_token(42, secret="s")
    b = secure_link.generate_token(42, secret="s")
    assert a == b


def test_token_changes_with_expires():
    assert secure_link.generate_token(1, secret="s") != secure_link.generate_token(
        2, secret="s"
    )


def test_token_changes_with_secret():
    assert secure_link.generate_token(1, secret="a") != secure_link.generate_token(
        1, secret="b"
    )


def test_sign_returns_future_expiry_and_matching_token():
    token, expires = secure_link.sign(ttl_seconds=3600, secret="s", now=1000)
    assert expires == 4600
    assert token == secure_link.generate_token(4600, secret="s")


def test_sign_uses_secret_from_env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "from-env")
    token, expires = secure_link.sign(ttl_seconds=10, now=100)
    assert token == secure_link.generate_token(expires, secret="from-env")


def test_get_secret_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    assert secure_link.get_secret() == secure_link.DEFAULT_SECRET


def test_append_token_adds_query_when_none():
    url = secure_link.append_token("https://cdn/live/x.m3u8", "TOK", 123)
    assert url == "https://cdn/live/x.m3u8?token=TOK&expires=123"


def test_append_token_uses_ampersand_when_query_present():
    url = secure_link.append_token("https://cdn/live/x.m3u8?a=1", "TOK", 123)
    assert url == "https://cdn/live/x.m3u8?a=1&token=TOK&expires=123"


@pytest.mark.parametrize("ttl", [1, 60, 3600])
def test_sign_respects_ttl(ttl):
    _token, expires = secure_link.sign(ttl_seconds=ttl, now=0)
    assert expires == ttl
