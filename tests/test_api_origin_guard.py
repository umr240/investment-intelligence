"""Another website must not drive the local API (architecture audit, finding 1).

CORS hides a cross-site response but still lets the request run, so a page could
spend tokens, pass `confirm=true` to a dangerous skill, or (by <img>) hit a GET
that writes, such as /valuation.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import app

# Missing `message` fails validation (422) inside the route: past the guard, no handler runs.
_ROUTE = "/dive/LULU/chat"


def _client() -> TestClient:
    return TestClient(app, base_url="http://127.0.0.1:8000")


def _post(origin: str | None) -> int:
    headers = {"Origin": origin} if origin else {}
    return _client().post(_ROUTE, headers=headers).status_code


def test_cross_site_post_is_refused() -> None:
    assert _post("https://evil.example") == 403
    assert _post("null") == 403  # sandboxed iframe / no-referrer form
    delete = _client().delete("/scheduler/jobs/x", headers={"Origin": "https://evil.example"})
    assert delete.status_code == 403


def test_the_ui_swagger_and_non_browser_clients_still_pass() -> None:
    assert _post("http://localhost:5173") == 422
    assert _post("http://127.0.0.1:8000") == 422  # /docs is same-origin
    local = TestClient(app, base_url="http://localhost:8000")
    assert local.post(_ROUTE, headers={"Origin": "http://localhost:8000"}).status_code == 422
    assert _post(None) == 422  # curl, the CLI


def test_a_cross_site_get_without_origin_is_refused() -> None:
    def get(**headers: str) -> int:
        return _client().get("/", headers=headers).status_code

    assert get(**{"Sec-Fetch-Site": "cross-site"}) == 403  # <img src=...> on another site
    assert get(**{"Sec-Fetch-Site": "same-site"}) == 403  # ... or on another local port
    assert get(**{"Sec-Fetch-Site": "cross-site", "Origin": "http://localhost:5173"}) == 200
    assert get(**{"Sec-Fetch-Site": "none"}) == 200  # typed into the address bar


def test_a_rebound_host_name_is_refused() -> None:
    client = TestClient(app, base_url="http://attacker.example:8000")
    assert client.get("/").status_code == 400
