"""Test helpers talk to workerd/SQLite. No Python service implementation."""
from contextlib import contextmanager
import json
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace
import httpx

ROOT = Path(__file__).resolve().parents[1]

@contextmanager
def backend():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(['node', str(ROOT/'scripts/worker_fixture.mjs'), str(port)],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdout.readline().strip() == b'ready', 'Worker fixture startup failed'
        yield f'http://127.0.0.1:{port}'
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=10)

class State:
    def __init__(self, client):
        self.client = client
    @property
    def entries(self):
        rows = self.client.get('/__test/inspect').json()['rows']
        return {r['id']: SimpleNamespace(**{**r, **json.loads(r['data'])}) for r in rows}

class Client(httpx.Client):
    pass

class BrowserBase(str):
    def __new__(cls, value):
        result = str.__new__(cls, value)
        result.fixtures = {}
        return result

def create_browser(base, multiple=True, purpose=''):
    from secret_request.crypto import new_key, public_jwk
    from .test_fields import FIELDS
    key = new_key()
    body = {'name':'浏览器测试凭据', 'purpose':purpose or '仅验证合成值', 'agent':'测试 Agent',
            'fields':FIELDS if multiple else None, 'public_key':public_jwk(key)}
    response = httpx.post(base+'/api/requests', json=body, trust_env=False)
    assert response.status_code == 201, 'Worker fixture create failed'
    result = response.json()
    base.fixtures[result['id']] = key, result['receive_token'], multiple
    return {'url':result['input_url'], 'id':result['id']}

def browser_state(base, rid):
    _, token, _ = base.fixtures[rid]
    return httpx.get(base+f'/api/requests/{rid}/status', headers={'Authorization':'Bearer '+token}, trust_env=False).json()

def check_browser(base, rid):
    from secret_request.crypto import decrypt
    key, token, multiple = base.fixtures[rid]
    response = httpx.post(base+f'/api/requests/{rid}/consume', json={}, headers={'Authorization':'Bearer '+token}, trust_env=False)
    assert response.status_code == 200, 'Worker fixture consume failed'
    value = decrypt(key, rid, response.json()['envelope'])
    expected = {'username':' FAKE-用户 ', 'password':'FAKE-ONLY-TEST', 'key':'line1\nline2\n'}
    assert json.loads(value) == expected if multiple else value in {'FAKE-ONLY-TEST', 'FAKE-ONLY-TEST\nsecond line'}
