import re
from types import SimpleNamespace
import pytest
from secret_request.crypto import new_key, public_jwk
from .worker_backend import backend, Client, State

@pytest.fixture(scope="session")
def key():
    return new_key()

@pytest.fixture(scope="session")
def worker_url():
    with backend() as base:
        yield base

@pytest.fixture
def system(worker_url):
    with Client(base_url=worker_url, trust_env=False, timeout=15) as client:
        client.post('/__test/reset',json={}).raise_for_status()
        app = SimpleNamespace(state=State(client))
        yield client, app, {}, None


def auth(token):
    return {"Authorization": "Bearer " + token}


def request(client, tokens, key, **extra):
    response = client.post('/api/requests', json={"name":"测试凭据", "purpose":"仅用于测试", "public_key":public_jwk(key), **extra})
    assert response.status_code == 201, 'Worker create failed'
    result = response.json()
    result['submit_token'] = result['input_url'].split('#', 1)[1]
    assert re.fullmatch(r'[A-Za-z0-9_-]{22}', result['submit_token'])
    return result
