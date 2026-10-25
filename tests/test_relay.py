import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
from urllib.parse import urlsplit
import pytest
from secret_request.crypto import decrypt, public_jwk
from secret_request.relay import Settings, create_app
from fastapi.testclient import TestClient
from .conftest import auth, request
from .test_crypto import encrypt


def nbytes(token):
    return len(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))


def accepted_by_deployed_clients(base, created):
    """The link check shipped clients still run. Short links must not pass it."""
    rid, url = created["id"], created["input_url"]
    target, origin = urlsplit(url), urlsplit(base)
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{24}", rid)
        and (target.scheme, target.hostname, target.port) == (origin.scheme, origin.hostname, origin.port)
        and not target.username and not target.password and not target.query
        and target.path == "/input/" + rid
        and re.fullmatch(r"[A-Za-z0-9_-]{43}", target.fragment))

def test_happy_path_single_delivery_no_plaintext(system, key):
    client, app, tokens, now = system
    result = request(client, tokens, key)
    rid = result["id"]
    envelope = encrypt(key, rid, "FAKE-秘密-with-spaces  ")
    assert client.post(f"/api/requests/{rid}/submit", json=envelope, headers=auth(result["submit_token"])).status_code == 200
    assert "FAKE-秘密" not in repr(app.state.entries)
    assert result["submit_token"] not in repr(app.state.entries)
    assert result["receive_token"] not in repr(app.state.entries)
    consumed = client.post(f"/api/requests/{rid}/consume", json={}, headers=auth(result["receive_token"]))
    assert consumed.json()["envelope"] == envelope
    assert app.state.entries[rid].envelope is None
    assert client.post(f"/api/requests/{rid}/consume", json={}, headers=auth(result["receive_token"])).status_code == 409

@pytest.mark.parametrize("role", ["agent", "other", "reviewer", "missing"])
def test_role_tokens_cannot_read_or_submit_request(system, key, role):
    client, app, tokens, now = system
    result = request(client, tokens, key)
    headers = auth(tokens.get(role, ""))
    rid = result["id"]
    assert client.get(f"/api/requests/{rid}", headers=headers).status_code == 404
    assert client.get(f"/api/requests/{rid}/status", headers=headers).status_code == 404
    assert client.post(f"/api/requests/{rid}/submit", json=encrypt(key, rid, "fake"), headers=headers).status_code == 404

def test_capabilities_are_distinct(system, key):
    client, app, tokens, now = system
    result = request(client, tokens, key)
    rid = result["id"]
    assert client.get(f"/api/requests/{rid}", headers=auth(result["receive_token"])).status_code == 404
    assert client.get(f"/api/requests/{rid}/status", headers=auth(result["submit_token"])).status_code == 404
    assert client.get("/api/pending", headers=auth(tokens["agent"])).status_code == 404
    assert client.post("/api/requests", json={"name":"a","purpose":"b","public_key":public_jwk(key)}).status_code == 201

@pytest.mark.parametrize("terminal", ["decline", "cancel"])
def test_terminal_states_fail_closed(system, key, terminal):
    client, app, tokens, now = system
    result = request(client, tokens, key)
    rid = result["id"]
    token = result["submit_token" if terminal == "decline" else "receive_token"]
    assert client.post(f"/api/requests/{rid}/{terminal}", json={}, headers=auth(token)).status_code == 200
    assert client.post(f"/api/requests/{rid}/submit", json=encrypt(key, rid, "fake"), headers=auth(result["submit_token"])).status_code == 409
    assert client.post(f"/api/requests/{rid}/consume", json={}, headers=auth(result["receive_token"])).status_code == 409

@pytest.mark.parametrize("submitted", [True, False])
def test_expiry_clears_ciphertext_and_later_purges(system, key, submitted):
    client, app, tokens, now = system
    result = request(client, tokens, key, ttl_seconds=10)
    rid = result["id"]
    if submitted: client.post(f"/api/requests/{rid}/submit", json=encrypt(key, rid, "fake"), headers=auth(result["submit_token"]))
    now[0] += 10
    assert client.get(f"/api/requests/{rid}/status", headers=auth(result["receive_token"])).json()["state"] == "expired"
    assert app.state.entries[rid].envelope is None
    assert client.post(f"/api/requests/{rid}/consume", json={}, headers=auth(result["receive_token"])).status_code == 409
    now[0] += 600
    assert client.get(f"/api/requests/{rid}", headers=auth(result["submit_token"])).status_code == 404

def test_concurrent_submission_and_consumption(system, key):
    client, app, tokens, now = system
    result = request(client, tokens, key)
    rid = result["id"]
    envelope = encrypt(key, rid, "fake")
    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda _: client.post(f"/api/requests/{rid}/submit", json=envelope, headers=auth(result["submit_token"])).status_code, range(8)))
    assert codes.count(200) == 1 and codes.count(409) == 7
    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda _: client.post(f"/api/requests/{rid}/consume", json={}, headers=auth(result["receive_token"])).status_code, range(8)))
    assert codes.count(200) == 1 and codes.count(409) == 7

@pytest.mark.parametrize("payload", [{"name":" "}, {"purpose":" "}, {"name":"line\n"}, {"ttl_seconds":True}, {"ttl_seconds":9}, {"ttl_seconds":1801}, {"owner":"forged"}, {"public_key":{"kty":"RSA"}}])
def test_bad_creation_input_is_sanitized(system, key, payload):
    client, app, tokens, now = system
    response = client.post("/api/requests", json={"name":"fake","purpose":"test","public_key":public_jwk(key), **payload}, headers=auth(tokens["agent"]))
    assert response.status_code == 422
    assert "input" not in response.text or "invalid" in response.text
    assert len(app.state.entries) == 0

def test_origin_content_type_size_and_security_headers(system):
    client, app, tokens, now = system
    assert client.post("/api/requests", json={}, headers={**auth(tokens["agent"]), "Origin":"https://evil.test"}).status_code == 403
    assert client.post("/api/requests", content="not-json").status_code == 415
    assert client.post("/api/requests", content=b"x"*100001, headers={"Content-Type":"application/json"}).status_code == 413
    assert client.post("/api/requests", content="{", headers={"Content-Type":"application/json"}).status_code == 422
    response = client.get("/")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert client.get("/assets/nonexistent").status_code == 404
    assert client.get("/docs").status_code == 404


def test_per_request_capabilities_cannot_cross_requests(system, key):
    client, app, tokens, now = system
    first, second = request(client, tokens, key), request(client, tokens, key)
    for role, path in [("submit_token", ""), ("receive_token", "/status")]:
        assert client.get('/api/requests/' + second['id'] + path, headers=auth(first[role])).status_code == 404
    for path in ('/api/pending', '/api/history', '/requests', '/assets/requests.js'):
        assert client.get(path, headers=auth(tokens['agent'])).status_code == 404
    assert client.post('/api/review-sessions', headers=auth(tokens['agent']), json={}).status_code == 404


def test_anonymous_source_quota_rate_limit_and_no_ip_disclosure(key):
    settings = Settings('http://testserver', max_requests_per_ip=1,
                        requests_per_minute=1, allow_local_http=True)
    now = [0.0]
    app = create_app(settings, clock=lambda: now[0])
    with TestClient(app, client=('192.0.2.1', 1000)) as client:
        other = TestClient(app, client=('192.0.2.2', 1000))
        payload = {'name': 'fake', 'purpose': 'test', 'public_key': public_jwk(key), 'ttl_seconds': 10}
        first = client.post('/api/requests', json=payload).json()
        details = client.get('/api/requests/'+first['id'], headers=auth(first['input_url'].split('#')[1])).json()
        assert 'device' not in details and '192.0.2.1' not in json.dumps(details)
        assert '192.0.2.1' not in repr(app.state.entries)
        assert client.post('/api/requests', json=payload, headers={'X-Forwarded-For':'192.0.2.9'}).status_code == 429
        assert other.post('/api/requests', json=payload).status_code == 201
        client.post('/api/requests/'+first['id']+'/cancel', json={}, headers=auth(first['receive_token']))
        assert client.post('/api/requests', json=payload).status_code == 429
        now[0] = 60
        assert client.post('/api/requests', json=payload).status_code == 201
        other.close()


def test_global_rate_limit_across_anonymous_sources(key):
    now = [0.0]
    app = create_app(Settings('http://testserver', global_requests_per_minute=1,
                             allow_local_http=True), clock=lambda: now[0])
    with TestClient(app, client=('192.0.2.1', 1000)) as first:
        other = TestClient(app, client=('192.0.2.2', 1000))
        payload = {'name':'fake','purpose':'test','public_key':public_jwk(key)}
        assert first.post('/api/requests', json=payload).status_code == 201
        assert other.post('/api/requests', json=payload).status_code == 429
        now[0] = 60
        assert other.post('/api/requests', json=payload).status_code == 201
        other.close()


@pytest.mark.parametrize('url', ['http://example.test', 'https://u:p@example.test', 'https://example.test/path', 'https://example.test/#x'])
def test_invalid_service_url(url):
    with pytest.raises(ValueError):
        Settings(url)


def test_health_reports_anonymous_protocol(system):
    assert system[0].get('/health').json() == {'status':'ok','version':'0.3.0','access':'anonymous'}


def test_published_input_link_lengths():
    assert len("https://secret-request.eicai.cc/input/" + "a" * 24 + "#" + "b" * 43) == 106
    assert len("https://secret-request.eicai.cc/i#" + "c" * 22) == 56
    assert len("https://sr.eicai.cc/#" + "c" * 22) == 43


def test_default_link_matches_deployed_clients(system, key):
    client, app, tokens, now = system
    result = request(client, tokens, key)
    base = "http://testserver"
    assert accepted_by_deployed_clients(base, result)
    assert nbytes(result["id"]) == 18 and nbytes(result["submit_token"]) == 32 and nbytes(result["receive_token"]) == 32
    hashed = hashlib.sha256(result["submit_token"].encode()).hexdigest()
    assert app.state.submit_index[hashed] == result["id"]
    assert result["submit_token"] not in repr(app.state.submit_index)
    details = client.get("/api/input", headers=auth(result["submit_token"])).json()
    assert details["id"] == result["id"] and "receive_token" not in details and result["submit_token"] not in json.dumps(details)
    page = client.get("/input/" + result["id"])
    assert page.status_code == 200 and page.headers["referrer-policy"] == "no-referrer"
    assert page.text == client.get("/i").text


def test_short_link_is_opt_in_and_looked_up_by_hash(system, key):
    client, app, tokens, now = system
    payload = {"name": "测试凭据", "purpose": "仅用于测试", "public_key": public_jwk(key)}
    for value in ("Short", "short ", " short", "legacy", "short,short", ""):
        created = client.post("/api/requests", json=payload, headers={"X-Secret-Request-Link": value})
        assert created.status_code == 201
        body = created.json()
        assert accepted_by_deployed_clients("http://testserver", body)
        client.post(f"/api/requests/{body['id']}/cancel", json={}, headers=auth(body["receive_token"]))
    result = request(client, tokens, key, short_link=True)
    parts = urlsplit(result["input_url"])
    assert parts.path == "/i" and parts.query == "" and parts.fragment == result["submit_token"]
    assert result["id"] not in result["input_url"].split("#", 1)[1]
    assert not accepted_by_deployed_clients("http://testserver", result)
    assert nbytes(result["submit_token"]) == 16 and nbytes(result["receive_token"]) == 32 and nbytes(result["id"]) == 18
    lowered = client.post("/api/requests", json=payload, headers={"x-secret-request-link": "short"})
    assert lowered.status_code == 201 and urlsplit(lowered.json()["input_url"]).path == "/i"
    client.post(f"/api/requests/{lowered.json()['id']}/cancel", json={}, headers=auth(lowered.json()["receive_token"]))
    hashed = hashlib.sha256(result["submit_token"].encode()).hexdigest()
    assert app.state.submit_index[hashed] == result["id"]
    assert result["submit_token"] not in repr(app.state.entries) and result["submit_token"] not in repr(app.state.submit_index)
    details = client.get("/api/input", headers=auth(result["submit_token"]))
    assert details.status_code == 200
    body = details.json()
    assert set(body) == {"id", "name", "purpose", "expires_at", "remaining_seconds", "state", "public_key", "agent", "fields", "created_at"}
    assert body["id"] == result["id"] and body["public_key"]["kty"] == "RSA"
    wrong = "b" * 24 if result["id"] == "a" * 24 else "a" * 24
    assert client.get("/api/requests/" + wrong, headers=auth(result["submit_token"])).status_code == 404
    envelope = encrypt(key, body["id"], "FAKE-秘密")
    assert client.post(f"/api/requests/{body['id']}/submit", json=envelope, headers=auth(result["submit_token"])).status_code == 200
    consumed = client.post(f"/api/requests/{result['id']}/consume", json={}, headers=auth(result["receive_token"]))
    assert decrypt(key, result["id"], consumed.json()["envelope"]) == "FAKE-秘密"
    assert "FAKE-秘密" not in repr(app.state.entries)


def test_short_link_one_time_use_and_expiry(system, key):
    client, app, tokens, now = system
    result = request(client, tokens, key, short_link=True, ttl_seconds=10)
    rid, submit, receive = result["id"], result["submit_token"], result["receive_token"]
    envelope = encrypt(key, rid, "FAKE-ONCE")
    assert client.post(f"/api/requests/{rid}/submit", json=envelope, headers=auth(submit)).status_code == 200
    assert "FAKE-ONCE" not in repr(app.state.entries) and submit not in repr(app.state.submit_index)
    assert client.post(f"/api/requests/{rid}/submit", json=envelope, headers=auth(submit)).status_code == 409
    assert client.get("/api/input", headers=auth(submit)).json()["state"] == "submitted"
    assert client.post(f"/api/requests/{rid}/consume", json={}, headers=auth(receive)).status_code == 200
    assert client.post(f"/api/requests/{rid}/consume", json={}, headers=auth(receive)).status_code == 409
    expiring = request(client, tokens, key, short_link=True, ttl_seconds=10)
    exp_headers = auth(expiring["submit_token"])
    assert client.post(f"/api/requests/{expiring['id']}/submit", json=encrypt(key, expiring["id"], "FAKE-EXPIRE"), headers=exp_headers).status_code == 200
    now[0] += 10
    assert client.get("/api/input", headers=exp_headers).json()["state"] == "expired"
    assert app.state.entries[expiring["id"]].envelope is None
    assert client.post(f"/api/requests/{expiring['id']}/submit", json=encrypt(key, expiring["id"], "FAKE-EXPIRE"), headers=exp_headers).status_code == 409
    assert client.post(f"/api/requests/{expiring['id']}/consume", json={}, headers=auth(expiring["receive_token"])).status_code == 409
    now[0] += 600
    hashed = hashlib.sha256(expiring["submit_token"].encode()).hexdigest()
    assert client.get("/api/input", headers=exp_headers).status_code == 404
    assert client.get(f"/api/requests/{expiring['id']}", headers=exp_headers).status_code == 404
    assert hashed not in app.state.submit_index and expiring["id"] not in app.state.entries


def test_short_link_capabilities_stay_separated(system, key):
    client, app, tokens, now = system
    result = request(client, tokens, key, short_link=True)
    other = request(client, tokens, key, short_link=True)
    rid, submit = result["id"], result["submit_token"]
    assert client.get("/api/input", headers=auth(result["receive_token"])).status_code == 404
    assert client.get("/api/input", headers=auth(other["submit_token"])).json()["id"] == other["id"]
    assert client.get(f"/api/requests/{rid}", headers=auth(other["submit_token"])).status_code == 404
    assert client.get(f"/api/requests/{other['id']}", headers=auth(submit)).status_code == 404
    assert client.post(f"/api/requests/{rid}/cancel", json={}, headers=auth(submit)).status_code == 404
    assert client.post(f"/api/requests/{rid}/consume", json={}, headers=auth(submit)).status_code == 404
    assert client.get(f"/api/requests/{rid}/status", headers=auth(submit)).status_code == 404
    assert client.post(f"/api/requests/{rid}/submit", json=encrypt(key, rid, "x"), headers=auth(result["receive_token"])).status_code == 404
    assert client.post(f"/api/requests/{rid}/decline", json={}, headers=auth(submit)).status_code == 200
    assert client.post(f"/api/requests/{rid}/decline", json={}, headers=auth(submit)).status_code == 409
    assert client.post(f"/api/requests/{rid}/submit", json=encrypt(key, rid, "x"), headers=auth(submit)).status_code == 409
    assert client.get("/api/input", headers=auth(submit)).json()["state"] == "declined"
    assert client.post(f"/api/requests/{other['id']}/cancel", json={}, headers=auth(other["receive_token"])).status_code == 200
    assert client.post(f"/api/requests/{other['id']}/submit", json=encrypt(key, other["id"], "x"), headers=auth(other["submit_token"])).status_code == 409
    assert client.get("/api/input", headers=auth(other["submit_token"])).json()["state"] == "cancelled"


def test_malformed_tokens_never_resolve(system, key):
    client, app, tokens, now = system
    result = request(client, tokens, key, short_link=True)
    envelope = encrypt(key, result["id"], "nope")
    samples = ["", "x" * 21, "x" * 23, "x" * 42, "x" * 44, "x" * 10000, "bad token",
               "+" * 43, "a" * 21 + "/", "a" * 42 + "=", "a" * 22 + "\n", "a" * 22]
    for token in samples:
        headers = {"Authorization": "Bearer " + token}
        assert client.get("/api/input", headers=headers).status_code == 404
        assert client.get(f"/api/requests/{result['id']}", headers=headers).status_code == 404
        assert client.post(f"/api/requests/{result['id']}/submit", json=envelope, headers=headers).status_code == 404
        assert client.get(f"/api/requests/{result['id']}/status", headers=headers).status_code == 404
    assert client.get("/api/input").status_code == 404
    assert client.get("/api/input", headers={"Authorization": "Bearer"}).status_code == 404
    assert client.get("/api/input", headers={"Authorization": result["submit_token"]}).status_code == 404
    assert client.get("/api/input", headers=auth(result["submit_token"])).json()["state"] == "pending"


def test_input_page_is_served_for_short_and_legacy_paths(system):
    client, app, tokens, now = system
    short = client.get("/i")
    legacy = client.get("/input/" + "a" * 24)
    assert short.status_code == legacy.status_code == 200
    assert short.text == legacy.text and 'id="secret"' in short.text
    assert short.headers["cache-control"] == "no-store" and short.headers["referrer-policy"] == "no-referrer"
    assert "/api/input" in client.get("/assets/app.js").text
    assert "current.id" in client.get("/assets/app.js").text
    assert "location.replace('/i'" in client.get("/assets/home.js").text
    assert 'id="fields"' not in client.get("/").text


def test_restart_loses_inflight_requests(system, key):
    client, app, tokens, now = system
    created = request(client, tokens, key)
    fresh = create_app(Settings('http://testserver', allow_local_http=True))
    with TestClient(fresh) as restarted:
        assert restarted.get('/api/requests/'+created['id']+'/status', headers=auth(created['receive_token'])).status_code == 404
