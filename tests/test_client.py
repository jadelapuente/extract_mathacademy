from __future__ import annotations

from datetime import datetime, timezone

import pytest

from extract_mathacademy.mathacademy.client import (
    ExpiredSessionError,
    InvalidResponseError,
    MathAcademyClient,
    fetch_html,
    fetch_previous_tasks,
)


class FakeResponse:
    def __init__(self, *, url, text="", json_data=None, json_error=None):
        self.url = url
        self.text = text
        self._json_data = json_data
        self._json_error = json_error
        self.raise_for_status_called = False

    def raise_for_status(self):
        self.raise_for_status_called = True

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._json_data


def test_fetch_html_uses_supplied_cookies_and_returns_text(monkeypatch):
    calls = []
    response = FakeResponse(url="https://mathacademy.com/topics/285", text="<html/>")

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return response

    monkeypatch.setattr("requests.get", fake_get)

    html = MathAcademyClient(cookies=["session"]).fetch_html(
        "https://mathacademy.com/topics/285"
    )

    assert html == "<html/>"
    assert response.raise_for_status_called
    assert calls == [
        (("https://mathacademy.com/topics/285",), {
            "cookies": ["session"],
            "headers": {"User-Agent": "Mozilla/5.0"},
            "allow_redirects": True,
            "timeout": 30,
        })
    ]


def test_fetch_previous_tasks_builds_cursor_url_and_returns_list(monkeypatch):
    calls = []
    response = FakeResponse(
        url="https://mathacademy.com/api/previous-tasks/cursor",
        text="[]",
        json_data=[{"id": 1}],
    )

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return response

    monkeypatch.setattr("requests.get", fake_get)

    tasks = MathAcademyClient(cookies=["session"]).fetch_previous_tasks(
        datetime(2026, 8, 2, 7, tzinfo=timezone.utc)
    )

    assert tasks == [{"id": 1}]
    assert response.raise_for_status_called
    assert calls[0][0][0] == (
        "https://mathacademy.com/api/previous-tasks/"
        "2026-08-02T07%3A00%3A00Z"
    )
    assert calls[0][1]["cookies"] == ["session"]
    assert calls[0][1]["headers"] == {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }


def test_fetch_json_builds_api_url_and_returns_json(monkeypatch):
    calls = []
    response = FakeResponse(
        url="https://mathacademy.com/api/courses/113/content",
        text="{}",
        json_data={"result": True},
    )

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return response

    monkeypatch.setattr("requests.get", fake_get)

    data = MathAcademyClient(cookies=["session"]).fetch_json(
        "/api/courses/113/content"
    )

    assert data == {"result": True}
    assert response.raise_for_status_called
    assert calls == [
        (("https://mathacademy.com/api/courses/113/content",), {
            "cookies": ["session"],
            "headers": {
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            },
            "allow_redirects": True,
            "timeout": 30,
        })
    ]


def test_fetch_json_rejects_session_expired_response(monkeypatch):
    monkeypatch.setattr(
        "requests.get",
        lambda *a, **kw: FakeResponse(
            url="https://mathacademy.com/api/courses/113/content",
            text='{"sessionExpired":true}',
            json_data={"sessionExpired": True},
        ),
    )

    with pytest.raises(ExpiredSessionError, match="session has expired"):
        MathAcademyClient(cookies=["session"]).fetch_json(
            "/api/courses/113/content"
        )


def test_client_fetch_html_rejects_login_redirect(monkeypatch):
    monkeypatch.setattr(
        "requests.get",
        lambda *a, **kw: FakeResponse(
            url="https://mathacademy.com/login",
            text="<input type=\"password\">",
        ),
    )

    with pytest.raises(ExpiredSessionError, match="session looks expired"):
        MathAcademyClient(cookies=["session"]).fetch_html(
            "https://mathacademy.com/topics/285"
        )


def test_client_fetch_previous_tasks_rejects_non_json(monkeypatch):
    monkeypatch.setattr(
        "requests.get",
        lambda *a, **kw: FakeResponse(
            url="https://mathacademy.com/api/previous-tasks/cursor",
            text="not json",
            json_error=ValueError("bad json"),
        ),
    )

    with pytest.raises(InvalidResponseError, match="did not return JSON"):
        MathAcademyClient(cookies=["session"]).fetch_previous_tasks(
            datetime(2026, 8, 2, 7, tzinfo=timezone.utc)
        )


def test_client_fetch_previous_tasks_rejects_non_list_response(monkeypatch):
    monkeypatch.setattr(
        "requests.get",
        lambda *a, **kw: FakeResponse(
            url="https://mathacademy.com/api/previous-tasks/cursor",
            text="{}",
            json_data={"id": 1},
        ),
    )

    with pytest.raises(InvalidResponseError, match="Unexpected Math Academy"):
        MathAcademyClient(cookies=["session"]).fetch_previous_tasks(
            datetime(2026, 8, 2, 7, tzinfo=timezone.utc)
        )


def test_fetch_html_wrapper_preserves_system_exit_behavior(monkeypatch):
    monkeypatch.setattr(
        "requests.get",
        lambda *a, **kw: FakeResponse(
            url="https://mathacademy.com/login",
            text="<input type=\"password\">",
        ),
    )

    with pytest.raises(SystemExit, match="session looks expired"):
        fetch_html("https://mathacademy.com/topics/285", cookies=["session"])


def test_fetch_previous_tasks_wrapper_preserves_system_exit_behavior(monkeypatch):
    monkeypatch.setattr(
        "requests.get",
        lambda *a, **kw: FakeResponse(
            url="https://mathacademy.com/api/previous-tasks/cursor",
            text="{}",
            json_data={"id": 1},
        ),
    )

    with pytest.raises(SystemExit, match="Unexpected Math Academy"):
        fetch_previous_tasks(
            datetime(2026, 8, 2, 7, tzinfo=timezone.utc),
            cookies=["session"],
        )
