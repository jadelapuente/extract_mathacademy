from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

MA_DOMAIN = "mathacademy.com"
MA_BASE_URL = f"https://{MA_DOMAIN}"
USER_AGENT = "Mozilla/5.0"


class MathAcademyError(Exception):
    """Base class for recoverable Math Academy client failures."""


class MissingSessionError(MathAcademyError):
    """No usable Math Academy session cookie was found in local browsers."""


class ExpiredSessionError(MathAcademyError):
    """The supplied Math Academy session was redirected to login."""


class InvalidResponseError(MathAcademyError):
    """Math Academy returned an unexpected response shape."""


def load_session_cookies():
    """Read the Math Academy `session` cookie from a local browser profile."""
    import browser_cookie3 as bc3

    for name in ("chrome", "brave", "edge", "firefox", "safari"):
        try:
            cj = getattr(bc3, name)(domain_name=MA_DOMAIN)
        except Exception:                           # locked DB, no profile, etc.
            continue
        if any(c.name == "session" for c in cj):
            return cj
    raise MissingSessionError(
        "Could not find a Math Academy session in any browser. "
        "Log in at https://mathacademy.com, then run this again."
    )


def session_cookies():
    try:
        return load_session_cookies()
    except MathAcademyError as exc:
        raise SystemExit(str(exc)) from exc


def _iso_z(dt: datetime) -> str:
    """Render an aware datetime as the UTC ISO form Math Academy accepts."""
    return dt.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def _raise_if_login_page(response) -> None:
    if "/login" in response.url or 'type="password"' in response.text.lower():
        raise ExpiredSessionError(
            f"Got redirected to {response.url} -- your Math Academy session "
            "looks expired. Re-open mathacademy.com in your browser to refresh "
            "it."
        )


class MathAcademyClient:
    """Authenticated HTTP access to Math Academy pages and task APIs."""

    def __init__(self, cookies=None, base_url: str = MA_BASE_URL):
        self.cookies = cookies if cookies is not None else load_session_cookies()
        self.base_url = base_url.rstrip("/")

    def fetch_html(self, url: str) -> str:
        import requests

        response = requests.get(
            url,
            cookies=self.cookies,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
            timeout=30,
        )
        _raise_if_login_page(response)
        response.raise_for_status()
        return response.text

    def fetch_json(self, path_or_url: str) -> dict[str, Any] | list[Any]:
        """Fetch a Math Academy JSON API endpoint using the current session."""
        import requests

        url = (
            path_or_url
            if path_or_url.startswith(("http://", "https://"))
            else f"{self.base_url}/{path_or_url.lstrip('/')}"
        )
        response = requests.get(
            url,
            cookies=self.cookies,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            allow_redirects=True,
            timeout=30,
        )
        _raise_if_login_page(response)
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as exc:
            raise InvalidResponseError(
                "Math Academy did not return JSON. Your session may be expired."
            ) from exc
        if isinstance(data, dict) and data.get("sessionExpired") is True:
            raise ExpiredSessionError(
                "Math Academy reported that your session has expired. "
                "Re-open mathacademy.com in your browser to refresh it."
            )
        return data

    def fetch_previous_tasks(self, before: datetime) -> list[dict[str, Any]]:
        """Fetch completed tasks older than `before`.

        This mirrors Math Academy's dashboard pagination endpoint. The server
        also accepts a misspelled `minumum` query parameter, but the default
        pagination was more reliable in live probing.
        """
        import requests

        url = f"{self.base_url}/api/previous-tasks/{quote(_iso_z(before), safe='')}"
        response = requests.get(
            url,
            cookies=self.cookies,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            allow_redirects=True,
            timeout=30,
        )
        _raise_if_login_page(response)
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as exc:
            raise InvalidResponseError(
                "Math Academy did not return JSON for completed tasks. "
                "Your session may be expired."
            ) from exc
        if not isinstance(data, list):
            raise InvalidResponseError(
                "Unexpected Math Academy completed-task response."
            )
        return data


def _exit_for_client_error(fn):
    try:
        return fn()
    except MathAcademyError as exc:
        raise SystemExit(str(exc)) from exc


def fetch_html(url: str, cookies=None) -> str:
    return _exit_for_client_error(
        lambda: MathAcademyClient(cookies=cookies).fetch_html(url)
    )


def fetch_previous_tasks(before: datetime, cookies=None) -> list[dict[str, Any]]:
    return _exit_for_client_error(
        lambda: MathAcademyClient(cookies=cookies).fetch_previous_tasks(before)
    )
