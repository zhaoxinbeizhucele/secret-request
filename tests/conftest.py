import re
import secrets
import pytest
from fastapi.testclient import TestClient
from secret_request.crypto import new_key, public_jwk
from secret_request.relay import Settings, create_app

@pytest.fixture(scope="session")
def key():
    return new_key()

@pytest.fixture
def system(key):
    tokens = {name: secrets.token_urlsafe(32) for name in ("agent", "other", "reviewer")}
    now = [100.0]
    app = create_app(Settings("http://testserver", allow_local_http=True), clock=lambda: now[0])
    with TestClient(app) as client:
        yield client, app, tokens, now

def auth(token):
    return {"Authorization": "Bearer " + token}

def request(client, tokens, key, **extra):
    short_link = extra.pop("short_link", False)
    payload = {"name": "测试凭据", "purpose": "仅用于测试", "public_key": public_jwk(key), **extra}
    headers = {"X-Secret-Request-Link": "short"} if short_link else None
    response = client.post("/api/requests", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    result = response.json()
    link, fragment = result["input_url"].split("#", 1)
    result["submit_token"] = fragment
    if short_link:
        assert link.endswith("/i") and re.fullmatch(r"[A-Za-z0-9_-]{22}", fragment)
    else:
        assert link.endswith("/input/" + result["id"]) and re.fullmatch(r"[A-Za-z0-9_-]{43}", fragment)
    return result
