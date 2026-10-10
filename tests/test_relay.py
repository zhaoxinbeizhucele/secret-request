from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from secret_request.crypto import public_jwk
from secret_request.relay import Settings, create_app
from fastapi.testclient import TestClient
from .conftest import auth, request
from .test_crypto import encrypt

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


def test_restart_loses_inflight_requests(system, key):
    client, app, tokens, now = system
    created = request(client, tokens, key)
    fresh = create_app(Settings('http://testserver', allow_local_http=True))
    with TestClient(fresh) as restarted:
        assert restarted.get('/api/requests/'+created['id']+'/status', headers=auth(created['receive_token'])).status_code == 404
